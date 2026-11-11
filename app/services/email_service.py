"""Email delivery over SMTP, with a local outbox fallback when SMTP isn't configured.

Every message is recorded in EmailLogs whatever happens, so the admin can audit deliveries.
"""
import base64
import json
import os
import re
import smtplib
import urllib.error
import urllib.request
from email.utils import parseaddr
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid

from flask import current_app, render_template

from ..extensions import db
from ..models import EmailLog


def email_enabled():
    """True when real delivery is configured (Brevo API or SMTP)."""
    cfg = current_app.config
    return bool(cfg.get("BREVO_API_KEY") or cfg.get("MAIL_SERVER"))


def provider_label():
    cfg = current_app.config
    if cfg.get("BREVO_API_KEY"):
        return "Brevo email API"
    if cfg.get("MAIL_SERVER"):
        return f"SMTP ({cfg['MAIL_SERVER']})"
    return None


def _send_brevo(to, subject, html, text, attachments):
    cfg = current_app.config
    name, addr = parseaddr(cfg["MAIL_DEFAULT_SENDER"])
    payload = {"sender": {"email": addr, "name": name or cfg["STORE_NAME"]}, "to": [{"email": to}],
               "subject": subject, "htmlContent": html, "textContent": text}
    if attachments:
        payload["attachment"] = [{"name": fn, "content": base64.b64encode(data).decode()} for fn, data, _ in attachments]
    req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", data=json.dumps(payload).encode(),
                                 headers={"api-key": cfg["BREVO_API_KEY"], "content-type": "application/json",
                                          "accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Brevo {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def _html_to_text(html):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</(p|tr|h\d|div)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def send_email(to, subject, html, category, order_id=None, attachments=None):
    """Send an HTML email. attachments: list of (filename, bytes, mime 'type/subtype')."""
    cfg = current_app.config
    attachments = attachments or []
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["MAIL_DEFAULT_SENDER"]
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain="sweetshop.local")
    msg.set_content(_html_to_text(html))
    msg.add_alternative(html, subtype="html")
    for filename, data, mime in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    log = EmailLog(recipient=to, subject=subject, category=category, order_id=order_id, html_body=html,
                   attachment_name=", ".join(a[0] for a in attachments) or None)

    if cfg.get("BREVO_API_KEY"):
        try:
            _send_brevo(to, subject, html, _html_to_text(html), attachments)
            log.status = "sent"
        except Exception as exc:  # never break checkout over email
            current_app.logger.exception("Brevo send failed")
            log.status = "failed"
            log.error = str(exc)[:500]
    elif cfg["MAIL_SERVER"]:
        try:
            if cfg["MAIL_USE_SSL"]:
                server = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=20,
                                          context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=20)
                if cfg["MAIL_USE_TLS"]:
                    server.starttls(context=ssl.create_default_context())
            with server:
                if cfg["MAIL_USERNAME"]:
                    server.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
                server.send_message(msg)
            log.status = "sent"
        except Exception as exc:  # network/auth failures must never break checkout
            current_app.logger.exception("SMTP send failed")
            log.status = "failed"
            log.error = str(exc)[:500]
    else:
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
        safe = re.sub(r"[^A-Za-z0-9]+", "_", to)
        path = os.path.join(cfg["OUTBOX_DIR"], f"{stamp}_{category}_{safe}.eml")
        with open(path, "wb") as fh:
            fh.write(bytes(msg))
        log.status = "outbox"
        log.outbox_path = path

    db.session.add(log)
    db.session.commit()
    return log


# ----------------------------------------------------------------- typed emails
def send_otp_email(email, code, purpose_text, ttl_minutes, context=None):
    html = render_template("emails/otp.html", code=code, purpose_text=purpose_text,
                           ttl_minutes=ttl_minutes, context=context or {})
    return send_email(email, f"{code} is your verification code", html, "otp")


def send_order_confirmation(order):
    from .invoice_service import build_invoice_pdf
    pdf_bytes = build_invoice_pdf(order)
    html = render_template("emails/order_confirmation.html", order=order, invoice=order.invoice,
                           payment=order.successful_payment)
    return send_email(order.customer_email,
                      f"Order confirmed · {order.order_number} · Invoice {order.invoice.invoice_number}",
                      html, "order_confirmation", order_id=order.id,
                      attachments=[(f"Invoice-{order.invoice.invoice_number}.pdf", pdf_bytes, "application/pdf")])


def send_cancellation_email(order):
    from .invoice_service import build_credit_note_pdf
    canc = order.cancellation
    attachments = []
    if canc and canc.credit_note_number:
        attachments.append((f"CreditNote-{canc.credit_note_number}.pdf", build_credit_note_pdf(order), "application/pdf"))
    html = render_template("emails/cancellation.html", order=order, cancellation=canc,
                           refund=canc.refund if canc else None)
    return send_email(order.customer_email, f"Order {order.order_number} cancelled", html,
                      "cancellation", order_id=order.id, attachments=attachments)


def send_status_update(order):
    html = render_template("emails/status_update.html", order=order)
    return send_email(order.customer_email, f"Your order {order.order_number} is {order.status_label}",
                      html, "status", order_id=order.id)
