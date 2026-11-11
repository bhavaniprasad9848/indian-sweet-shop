/* Storefront interactions: AJAX add-to-cart, qty steppers, OTP boxes, resend countdown, card preview. */
(function () {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;

  function toast(message, ok = true) {
    const area = document.getElementById('toastArea');
    if (!area) return;
    const el = document.createElement('div');
    el.className = `toast align-items-center border-0 text-white ${ok ? 'bg-success' : 'bg-danger'}`;
    el.style.background = ok ? '#7B1E2B' : '#B3261E';
    el.innerHTML = `<div class="d-flex"><div class="toast-body"><i class="bi ${ok ? 'bi-bag-check' : 'bi-exclamation-circle'}"></i> ${message}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    area.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 2800 });
    t.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
  }

  // AJAX add to cart
  document.querySelectorAll('form[data-ajax-cart]').forEach(form => {
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const btn = form.querySelector('button:not([type=button])');
      btn && (btn.disabled = true);
      try {
        const res = await fetch(form.action, {
          method: 'POST', body: new FormData(form),
          headers: { 'X-Requested-With': 'fetch', 'X-CSRFToken': csrf, 'Accept': 'application/json' },
        });
        const data = await res.json();
        if (res.status === 401 && data.login) { location.href = data.login; return; }
        toast(data.message || data.error, data.ok);
        if (data.ok) {
          const badge = document.querySelector('[data-cart-count]');
          if (badge) { badge.textContent = data.count; badge.hidden = false; badge.classList.remove('bump'); void badge.offsetWidth; badge.classList.add('bump'); }
        }
      } catch (err) { form.submit(); }
      finally { btn && (btn.disabled = false); }
    });
  });

  // Quantity steppers
  document.querySelectorAll('[data-stepper]').forEach(st => {
    const input = st.querySelector('input[type=number]');
    let timer;
    st.querySelectorAll('[data-step]').forEach(b => b.addEventListener('click', () => {
      const min = parseInt(input.min || '0', 10), max = parseInt(input.max || '99', 10);
      input.value = Math.max(min, Math.min(max, (parseInt(input.value, 10) || 0) + parseInt(b.dataset.step, 10)));
      if (st.hasAttribute('data-autosubmit')) { clearTimeout(timer); timer = setTimeout(() => st.submit(), 450); }
    }));
    if (st.hasAttribute('data-autosubmit')) input.addEventListener('change', () => st.submit());
  });

  // OTP boxes: auto-advance, backspace, paste
  document.querySelectorAll('[data-otp]').forEach(wrap => {
    const boxes = [...wrap.querySelectorAll('input')];
    boxes[0]?.focus();
    boxes.forEach((box, i) => {
      box.addEventListener('input', () => {
        box.value = box.value.replace(/\D/g, '').slice(-1);
        if (box.value && boxes[i + 1]) boxes[i + 1].focus();
        if (boxes.every(b => b.value)) box.form.requestSubmit?.();
      });
      box.addEventListener('keydown', e => { if (e.key === 'Backspace' && !box.value && boxes[i - 1]) boxes[i - 1].focus(); });
      box.addEventListener('paste', e => {
        const digits = (e.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, boxes.length);
        if (!digits) return;
        e.preventDefault();
        digits.split('').forEach((d, j) => boxes[j] && (boxes[j].value = d));
        (boxes[digits.length] || boxes[boxes.length - 1]).focus();
        if (digits.length === boxes.length) box.form.requestSubmit?.();
      });
    });
  });

  // Resend countdown
  document.querySelectorAll('[data-resend]').forEach(btn => {
    let wait = parseInt(btn.dataset.wait || '0', 10);
    const label = btn.textContent;
    const tick = () => {
      if (wait > 0) { btn.disabled = true; btn.textContent = `Resend code in ${wait}s`; wait--; setTimeout(tick, 1000); }
      else { btn.disabled = false; btn.textContent = label; }
    };
    tick();
  });

  // Password visibility + strength
  document.querySelectorAll('[data-toggle-pw]').forEach(b => b.addEventListener('click', () => {
    const inp = document.querySelector(b.dataset.togglePw);
    inp.type = inp.type === 'password' ? 'text' : 'password';
    b.querySelector('i').className = inp.type === 'password' ? 'bi bi-eye' : 'bi bi-eye-slash';
  }));
  document.querySelectorAll('[data-pw-meter]').forEach(inp => inp.addEventListener('input', () => {
    const v = inp.value; let s = 0;
    if (v.length >= 8) s++; if (/[A-Z]/.test(v) && /[a-z]/.test(v)) s++; if (/\d/.test(v)) s++; if (/[^A-Za-z0-9]/.test(v)) s++;
    const bar = document.querySelector('.pw-meter span');
    if (bar) { bar.style.width = `${s * 25}%`; bar.style.background = ['#B3261E', '#E8772E', '#D4A017', '#2F7D32', '#2F7D32'][s]; }
  }));

  // Checkout: toggle new-address block and billing
  const newAddr = document.getElementById('newAddress');
  document.querySelectorAll('input[name=address_id]').forEach(r => r.addEventListener('change', () => {
    newAddr?.classList.toggle('d-none', r.value !== '0' || !r.checked);
  }));
  document.querySelectorAll('[data-toggle-target]').forEach(cb => cb.addEventListener('change', () => {
    document.querySelector(cb.dataset.toggleTarget)?.classList.toggle('d-none', !cb.checked);
  }));

  // Card form live preview + formatting
  const num = document.querySelector('[data-card-number]');
  if (num) {
    num.addEventListener('input', () => {
      const d = num.value.replace(/\D/g, '').slice(0, 19);
      num.value = d.replace(/(.{4})/g, '$1 ').trim();
      document.querySelector('[data-cv-number]').textContent = (d.padEnd(16, '•')).replace(/(.{4})/g, '$1 ').trim();
    });
    document.querySelector('[data-card-name]')?.addEventListener('input', e => {
      document.querySelector('[data-cv-name]').textContent = e.target.value.toUpperCase() || 'CARDHOLDER';
    });
    document.querySelector('[data-card-exp]')?.addEventListener('input', e => {
      let v = e.target.value.replace(/\D/g, '').slice(0, 4);
      if (v.length > 2) v = v.slice(0, 2) + '/' + v.slice(2);
      e.target.value = v;
      document.querySelector('[data-cv-exp]').textContent = v || 'MM/YY';
    });
  }
  // Prevent double-submits on payment forms
  document.querySelectorAll('form[data-pay-form]').forEach(f => f.addEventListener('submit', () => {
    const b = f.querySelector('[data-pay-btn]');
    if (b) { b.disabled = true; b.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processing…'; }
  }));
})();
