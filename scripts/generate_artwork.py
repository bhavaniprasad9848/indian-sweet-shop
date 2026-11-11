"""Generate the shop's SVG artwork: logo, mandala, and an illustration for every sample product.

Run:  python scripts/generate_artwork.py
Writes into app/static/images/. Uploaded photos (admin → product → image) replace these per product.
"""
import math
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "static", "images")
PROD = os.path.join(OUT, "products")


def svg(body, w=400, h=320, defs="", box="4 96 392 228"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box}" width="{w}" height="{int(w * 228 / 392)}">'
            f'<defs>{COMMON_DEFS}{defs}</defs>{body}</svg>')


COMMON_DEFS = """
<radialGradient id="brass" cx="50%" cy="40%" r="60%"><stop offset="0" stop-color="#FCE7A8"/><stop offset=".55" stop-color="#E2B544"/><stop offset="1" stop-color="#9C7414"/></radialGradient>
<radialGradient id="brassIn" cx="50%" cy="40%" r="60%"><stop offset="0" stop-color="#FFF4CF"/><stop offset="1" stop-color="#E9C665"/></radialGradient>
<linearGradient id="leaf" x1="0" x2="1"><stop offset="0" stop-color="#2E7D32"/><stop offset=".5" stop-color="#4CAF50"/><stop offset="1" stop-color="#2E7D32"/></linearGradient>
<radialGradient id="bowl" cx="50%" cy="20%" r="80%"><stop offset="0" stop-color="#C9662B"/><stop offset="1" stop-color="#6E2A12"/></radialGradient>
<filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="6" stdDeviation="6" flood-color="#5A2A10" flood-opacity=".28"/></filter>
<radialGradient id="shine" cx="35%" cy="30%" r="40%"><stop offset="0" stop-color="#fff" stop-opacity=".85"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
"""


def thali(cx=200, cy=210, rx=170, ry=62):
    return (f'<g filter="url(#soft)"><ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="url(#brass)"/>'
            f'<ellipse cx="{cx}" cy="{cy - 4}" rx="{rx - 18}" ry="{ry - 14}" fill="url(#brassIn)"/>'
            + "".join(f'<circle cx="{cx + (rx - 9) * math.cos(a):.1f}" cy="{cy + (ry - 4) * math.sin(a):.1f}" r="2.2" fill="#9C7414" opacity=".7"/>'
                      for a in [i * math.pi / 14 for i in range(28)]) + '</g>')


def banana_leaf(cx=200, cy=212):
    veins = "".join(f'<path d="M{x} {cy - 4} q 18 -40 34 -66" stroke="#A5D6A7" stroke-width="1.4" fill="none" opacity=".7"/>'
                    f'<path d="M{x} {cy + 4} q 18 40 34 64" stroke="#A5D6A7" stroke-width="1.4" fill="none" opacity=".7"/>'
                    for x in range(cx - 160, cx + 140, 26))
    return (f'<g filter="url(#soft)"><path d="M{cx - 190} {cy} C {cx - 120} {cy - 120}, {cx + 130} {cy - 118}, {cx + 192} {cy - 6} '
            f'C {cx + 130} {cy + 96}, {cx - 120} {cy + 104}, {cx - 190} {cy}Z" fill="url(#leaf)"/>'
            f'<path d="M{cx - 186} {cy} L{cx + 190} {cy - 6}" stroke="#C8E6C9" stroke-width="3"/>{veins}</g>')


def bowl(cx=200, cy=180, rx=135, liquid="#F4C27A", depth=95):
    return (f'<g filter="url(#soft)"><path d="M{cx - rx} {cy} Q {cx - rx + 10} {cy + depth} {cx} {cy + depth + 6} '
            f'Q {cx + rx - 10} {cy + depth} {cx + rx} {cy} Z" fill="url(#bowl)"/>'
            f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="34" fill="#8A3A18"/>'
            f'<ellipse cx="{cx}" cy="{cy + 3}" rx="{rx - 10}" ry="27" fill="{liquid}"/>'
            f'<path d="M{cx - rx + 18} {cy + 30} Q {cx} {cy + 70} {cx + rx - 18} {cy + 30}" stroke="#E3A15E" stroke-width="3" fill="none" opacity=".6"/></g>')


_GID = 0


def ball(x, y, r, c1, c2, texture=None, rng=None):
    global _GID
    _GID += 1
    gid = f"b{_GID}"
    s = (f'<defs><radialGradient id="{gid}" cx="38%" cy="32%" r="70%"><stop offset="0" stop-color="{c1}"/>'
         f'<stop offset="1" stop-color="{c2}"/></radialGradient></defs>'
         f'<circle cx="{x}" cy="{y}" r="{r}" fill="url(#{gid})"/>')
    if texture and rng:
        for _ in range(int(r * 2.2)):
            a, d = rng.random() * 6.28, rng.random() * r * .88
            s += f'<circle cx="{x + d * math.cos(a):.1f}" cy="{y + d * math.sin(a):.1f}" r="{rng.uniform(1.1, 2.4):.1f}" fill="{texture}" opacity=".55"/>'
    s += f'<ellipse cx="{x - r * .35:.1f}" cy="{y - r * .4:.1f}" rx="{r * .32:.1f}" ry="{r * .2:.1f}" fill="url(#shine)"/>'
    return s


def diamond(x, y, w, h, fill="#E9DCC3", edge="#C9B48E"):
    return (f'<path d="M{x} {y - h} L{x + w} {y} L{x} {y + h} L{x - w} {y}Z" fill="{fill}" stroke="{edge}" stroke-width="2"/>'
            f'<path d="M{x} {y - h + 5} L{x + w - 9} {y} L{x} {y + h - 5} L{x - w + 9} {y}Z" fill="#F7F1E5" opacity=".75"/>'
            f'<path d="M{x - w * .3} {y - h * .2} L{x + w * .1} {y - h * .55}" stroke="#fff" stroke-width="3" opacity=".8"/>')


def block(x, y, w, h, top, side, front, texture=None, rng=None, nuts=None):
    d = 14
    s = (f'<path d="M{x} {y} l{d} {-d} h{w} v{h} l{-d} {d}Z" fill="{side}"/>'
         f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{front}"/>'
         f'<path d="M{x} {y} l{d} {-d} h{w} l{-d} {d}Z" fill="{top}"/>')
    if texture and rng:
        for _ in range(int(w * h / 90)):
            s += f'<circle cx="{x + rng.random() * w:.1f}" cy="{y + rng.random() * h:.1f}" r="{rng.uniform(.8, 2.2):.1f}" fill="{texture}" opacity=".5"/>'
    if nuts:
        for i in range(3):
            s += f'<ellipse cx="{x + d / 2 + w * (i + 1) / 4:.1f}" cy="{y - d / 2:.1f}" rx="5" ry="2.4" fill="{nuts}" transform="rotate({-20 + i * 20} {x + d / 2 + w * (i + 1) / 4:.1f} {y - d / 2:.1f})"/>'
    return s


def spiral(cx, cy, turns=3.2, r=34, color="#F28C1E", width=8):
    pts = []
    for i in range(0, int(turns * 60)):
        t = i / 60 * 2 * math.pi
        rr = 4 + r * (i / (turns * 60))
        pts.append(f"{cx + rr * math.cos(t):.1f},{cy + rr * .78 * math.sin(t):.1f}")
    path = "M" + " L".join(pts)
    return (f'<path d="{path}" fill="none" stroke="#B4500A" stroke-width="{width + 3}" stroke-linecap="round"/>'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'
            f'<path d="{path}" fill="none" stroke="#FFD27A" stroke-width="2" stroke-linecap="round" opacity=".7" transform="translate(-1.5 -2)"/>')


def chutney(cx, cy, r=26, color="#5DA34A", rim="#C9C1B5"):
    return (f'<g filter="url(#soft)"><ellipse cx="{cx}" cy="{cy}" rx="{r}" ry="{r * .55}" fill="{rim}"/>'
            f'<ellipse cx="{cx}" cy="{cy - 1}" rx="{r - 5}" ry="{r * .55 - 4}" fill="{color}"/></g>')


# ------------------------------------------------------------------ products
def p_gulab_jamun(rng):
    s = bowl(liquid="#E8A24A")
    for x, y, r in [(150, 178, 34), (222, 172, 36), (186, 196, 33), (262, 196, 30)]:
        s += ball(x, y, r, "#8B3A1A", "#3A1206")
    s += "".join(f'<circle cx="{x}" cy="{y}" r="2.4" fill="#2E7D32"/>' for x, y in [(160, 165), (232, 158), (196, 186)])
    return s


def p_rasgulla(rng):
    s = bowl(liquid="#FFF3D6")
    for x, y, r in [(146, 182, 33), (214, 174, 35), (182, 200, 32), (258, 196, 30)]:
        s += ball(x, y, r, "#FFFFFF", "#E9E1D2", texture="#D9CFBE", rng=rng)
    return s


def p_rasmalai(rng):
    s = bowl(liquid="#F7D58B")
    for x, y in [(150, 185), (212, 176), (262, 190), (190, 200)]:
        s += (f'<ellipse cx="{x}" cy="{y}" rx="34" ry="16" fill="#FFF7E6" stroke="#EBD9B6" stroke-width="2"/>'
              f'<ellipse cx="{x - 8}" cy="{y - 5}" rx="12" ry="4" fill="url(#shine)"/>')
    for _ in range(26):
        s += f'<rect x="{rng.uniform(110, 290):.0f}" y="{rng.uniform(165, 208):.0f}" width="5" height="2.2" fill="{rng.choice(["#7CB342", "#C0392B", "#E67E22"])}" rx="1" transform="rotate({rng.randint(0, 180)} 200 190)"/>'
    return s


def p_kaju_katli(rng):
    s = thali()
    for x, y in [(130, 196), (200, 186), (270, 196), (165, 222), (235, 222), (200, 160)]:
        s += diamond(x, y, 42, 26)
    return s


def p_mysore_pak(rng):
    s = thali()
    for x, y in [(110, 196), (178, 186), (246, 196), (150, 228), (218, 230)]:
        s += block(x, y - 30, 52, 36, "#F7C548", "#C98A12", "#E9A825", texture="#A86A06", rng=rng)
    return s


def p_motichoor_laddu(rng):
    s = thali()
    for x, y, r in [(140, 195, 38), (215, 186, 40), (268, 210, 34), (180, 222, 36)]:
        s += ball(x, y, r, "#FFB347", "#E0661B", texture="#FFE0A3", rng=rng)
    return s


def p_besan_laddu(rng):
    s = thali()
    for x, y, r in [(140, 196, 38), (215, 186, 40), (268, 210, 34), (180, 222, 36)]:
        s += ball(x, y, r, "#F6D27A", "#C99032", texture="#B07A25", rng=rng)
        s += f'<ellipse cx="{x}" cy="{y - r + 6}" rx="7" ry="3" fill="#F5EBD7" transform="rotate(-25 {x} {y - r + 6})"/>'
    return s


def p_jalebi(rng):
    s = thali()
    for cx, cy in [(140, 196), (215, 188), (270, 212), (182, 222)]:
        s += spiral(cx, cy, turns=2.6, r=32)
    return s


def p_peda(rng):
    s = thali()
    for x, y in [(130, 196), (200, 186), (270, 196), (165, 224), (235, 224)]:
        s += (f'<ellipse cx="{x}" cy="{y + 6}" rx="34" ry="15" fill="#B9874C"/>'
              f'<ellipse cx="{x}" cy="{y}" rx="34" ry="16" fill="#E6BF84"/>'
              f'<ellipse cx="{x}" cy="{y}" rx="13" ry="6" fill="#D4A86A"/>'
              f'<circle cx="{x}" cy="{y}" r="3.2" fill="#E8772E"/>')
    return s


def p_soan_papdi(rng):
    s = thali()
    for x, y in [(118, 168), (186, 160), (254, 168), (152, 200), (220, 202)]:
        s += block(x, y, 54, 34, "#FFF0B8", "#D9B860", "#F3D987")
        s += "".join(f'<path d="M{x + 3} {y + 6 + i * 6} q 24 -4 48 0" stroke="#D2AE55" stroke-width="1.3" fill="none"/>' for i in range(5))
        s += f'<circle cx="{x + 30}" cy="{y - 7}" r="3" fill="#7CB342"/>'
    return s


def p_milk_cake(rng):
    s = thali()
    for x, y in [(112, 168), (186, 160), (258, 170), (150, 204), (224, 206)]:
        s += (f'<defs><linearGradient id="mc{x}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F5DDB0"/>'
              f'<stop offset=".5" stop-color="#B9733A"/><stop offset="1" stop-color="#F0D3A0"/></linearGradient></defs>')
        s += block(x, y, 52, 34, "#F3D7A6", "#9C5A26", f"url(#mc{x})", texture="#8A4B1E", rng=rng)
    return s


def p_badusha(rng):
    s = thali()
    for x, y in [(140, 196), (215, 186), (270, 212), (180, 224)]:
        s += (f'<ellipse cx="{x}" cy="{y + 6}" rx="38" ry="20" fill="#B0661C"/>'
              f'<ellipse cx="{x}" cy="{y}" rx="38" ry="21" fill="#E39A3B"/>'
              + "".join(f'<path d="M{x + 36 * math.cos(a):.1f} {y + 19 * math.sin(a):.1f} q {-6 * math.cos(a):.1f} {-4 * math.sin(a):.1f} {-14 * math.cos(a):.1f} {-8 * math.sin(a):.1f}" stroke="#A0581A" stroke-width="2" fill="none"/>' for a in [i * math.pi / 6 for i in range(12)])
              + f'<ellipse cx="{x}" cy="{y - 2}" rx="16" ry="8" fill="#F7C46A"/><ellipse cx="{x - 10}" cy="{y - 8}" rx="12" ry="4" fill="url(#shine)"/>')
    return s


def p_coconut_burfi(rng):
    s = thali()
    for x, y in [(112, 168), (186, 160), (258, 170), (150, 204), (224, 206)]:
        s += block(x, y, 52, 34, "#FFFFFF", "#E2D8CB", "#FAF5EC", texture="#E3D5C2", rng=rng)
        s += f'<rect x="{x}" y="{y + 22}" width="52" height="12" fill="#F7B6C5"/>'
    return s


def p_kalakand(rng):
    s = thali()
    for x, y in [(112, 168), (186, 160), (258, 170), (150, 204), (224, 206)]:
        s += block(x, y, 52, 34, "#FFF4DA", "#DCC48F", "#F6E6BF", texture="#D2B477", rng=rng, nuts="#7CB342")
    return s


def p_cham_cham(rng):
    s = thali()
    for x, y, c1, c2 in [(140, 194, "#FFC1CF", "#E8899E"), (215, 186, "#FFE6A8", "#E7B24B"), (270, 210, "#FFC1CF", "#E8899E"), (180, 224, "#FFE6A8", "#E7B24B")]:
        s += (f'<ellipse cx="{x}" cy="{y}" rx="40" ry="22" fill="{c2}"/><ellipse cx="{x}" cy="{y - 3}" rx="38" ry="19" fill="{c1}"/>')
        for _ in range(28):
            s += f'<rect x="{x + rng.uniform(-34, 34):.0f}" y="{y + rng.uniform(-18, 10):.0f}" width="4" height="1.6" fill="#fff" opacity=".9"/>'
        s += f'<ellipse cx="{x - 12}" cy="{y - 10}" rx="12" ry="4" fill="url(#shine)"/>'
    return s


def p_samosa(rng):
    s = thali()
    for x, y, rot in [(140, 200, -8), (212, 186, 6), (262, 214, -4)]:
        s += (f'<g transform="rotate({rot} {x} {y})"><path d="M{x - 46} {y + 26} L{x} {y - 46} L{x + 46} {y + 26} Q{x} {y + 40} {x - 46} {y + 26}Z" fill="#C88A2E"/>'
              f'<path d="M{x - 40} {y + 20} L{x} {y - 38} L{x + 40} {y + 20} Q{x} {y + 30} {x - 40} {y + 20}Z" fill="#E6B04A"/>'
              + "".join(f'<circle cx="{x + rng.uniform(-28, 28):.0f}" cy="{y + rng.uniform(-10, 18):.0f}" r="1.6" fill="#B07A25"/>' for _ in range(16))
              + f'<path d="M{x - 10} {y - 18} L{x - 2} {y - 30}" stroke="#FFF1C4" stroke-width="3" opacity=".7"/></g>')
    s += chutney(300, 168, 24, "#5DA34A") + chutney(98, 168, 22, "#8B2E1A")
    return s


def p_kachori(rng):
    s = thali()
    for x, y in [(140, 196), (215, 186), (270, 212), (180, 224)]:
        s += (f'<ellipse cx="{x}" cy="{y + 8}" rx="40" ry="22" fill="#A8661F"/>'
              f'<ellipse cx="{x}" cy="{y}" rx="40" ry="26" fill="#D9963A"/>'
              f'<ellipse cx="{x}" cy="{y - 4}" rx="28" ry="15" fill="#E9B45A"/>'
              f'<path d="M{x - 10} {y - 8} q 10 6 20 0" stroke="#B26E22" stroke-width="2" fill="none"/>'
              f'<ellipse cx="{x - 14}" cy="{y - 12}" rx="12" ry="4" fill="url(#shine)"/>')
    return s


def p_veg_puff(rng):
    s = thali()
    for x, y in [(110, 170), (196, 160), (152, 206)]:
        s += (f'<rect x="{x}" y="{y}" width="84" height="44" rx="10" fill="#C98A33"/>'
              + "".join(f'<rect x="{x + 2}" y="{y + 4 + i * 7}" width="80" height="4" rx="2" fill="{["#F2C46D", "#E5AC4A"][i % 2]}"/>' for i in range(5))
              + f'<rect x="{x + 4}" y="{y - 4}" width="76" height="10" rx="5" fill="#F7D589"/>')
    return s


def p_paneer_tikka(rng):
    s = thali()
    for y, off in [(176, 0), (214, 18)]:
        s += f'<line x1="70" y1="{y + 10}" x2="330" y2="{y - 10}" stroke="#8D6E63" stroke-width="4" stroke-linecap="round"/>'
        x = 92 + off
        for i in range(5):
            yy = y + 8 - (x - 70) * 20 / 260
            if i % 2 == 0:
                s += (f'<rect x="{x - 18}" y="{yy - 18}" width="36" height="34" rx="5" fill="#F3A33C"/>'
                      f'<rect x="{x - 15}" y="{yy - 15}" width="30" height="12" rx="4" fill="#FCD9A0"/>'
                      f'<circle cx="{x + 8}" cy="{yy + 8}" r="4" fill="#7A2E12" opacity=".7"/>')
            else:
                s += (f'<path d="M{x - 14} {yy - 16} q 14 -6 28 0 v 30 q -14 6 -28 0Z" fill="{rng.choice(["#4CAF50", "#E53935"])}"/>'
                      f'<path d="M{x - 6} {yy - 14} q 4 14 0 28" stroke="#F8BBD0" stroke-width="5" fill="none"/>')
            x += 44
    s += chutney(330, 236, 22, "#5DA34A")
    return s


def p_masala_dosa(rng):
    s = banana_leaf()
    s += (f'<path d="M60 196 Q200 140 340 176 L332 208 Q200 182 70 226Z" fill="#C67B22"/>'
          f'<path d="M66 202 Q200 152 336 184 L330 200 Q200 174 72 218Z" fill="#E9A83E"/>'
          + "".join(f'<circle cx="{rng.uniform(90, 310):.0f}" cy="{rng.uniform(178, 205):.0f}" r="{rng.uniform(1.4, 3):.1f}" fill="#9B5A12" opacity=".6"/>' for _ in range(40)))
    s += chutney(110, 252, 24, "#F2F2E6") + chutney(170, 262, 24, "#D84315") + chutney(240, 258, 26, "#E9A15A")
    return s


def p_idli(rng):
    s = banana_leaf()
    for x, y in [(130, 190), (196, 180), (262, 192), (166, 222), (232, 224)]:
        s += (f'<ellipse cx="{x}" cy="{y + 8}" rx="36" ry="14" fill="#E9E3D6"/>'
              f'<path d="M{x - 36} {y + 8} Q{x} {y - 30} {x + 36} {y + 8}Z" fill="#FFFFFF"/>'
              f'<ellipse cx="{x - 10}" cy="{y - 6}" rx="12" ry="5" fill="url(#shine)"/>')
    s += chutney(316, 246, 28, "#E9A15A") + chutney(84, 246, 24, "#F2F2E6")
    return s


def p_vada(rng):
    s = banana_leaf()
    for x, y in [(140, 196), (215, 186), (270, 214), (178, 226)]:
        s += (f'<ellipse cx="{x}" cy="{y + 6}" rx="40" ry="24" fill="#8C4A12"/>'
              f'<ellipse cx="{x}" cy="{y}" rx="40" ry="24" fill="#C47A2C"/>'
              f'<ellipse cx="{x}" cy="{y}" rx="12" ry="7" fill="#5C2C08"/>'
              + "".join(f'<circle cx="{x + rng.uniform(-30, 30):.0f}" cy="{y + rng.uniform(-16, 16):.0f}" r="1.4" fill="#5C2C08"/>' for _ in range(10))
              + f'<ellipse cx="{x - 16}" cy="{y - 12}" rx="12" ry="4" fill="url(#shine)"/>')
    s += chutney(318, 172, 24, "#F2F2E6")
    return s


def p_biryani(rng):
    s = (f'<g filter="url(#soft)"><path d="M70 170 Q72 268 200 274 Q328 268 330 170Z" fill="#8D4A1F"/>'
         f'<ellipse cx="200" cy="170" rx="130" ry="36" fill="#6E3415"/>'
         f'<ellipse cx="200" cy="164" rx="118" ry="30" fill="#F4E3C1"/></g>')
    for _ in range(320):
        x, y = rng.uniform(92, 308), rng.uniform(140, 190)
        if ((x - 200) / 118) ** 2 + ((y - 164) / 30) ** 2 < 1:
            s += f'<ellipse cx="{x:.0f}" cy="{y:.0f}" rx="4.2" ry="1.4" fill="{rng.choice(["#FFF8E7", "#FFE0A3", "#F5B041", "#FFFFFF", "#FFFFFF"])}" transform="rotate({rng.randint(-40, 40)} {x:.0f} {y:.0f})"/>'
    for x, y in [(160, 150), (230, 162), (200, 140)]:
        s += f'<path d="M{x} {y} q 8 -12 16 0 q -8 8 -16 0Z" fill="#43A047"/>'
    s += '<rect x="56" y="198" width="22" height="10" rx="5" fill="#6E3415"/><rect x="322" y="198" width="22" height="10" rx="5" fill="#6E3415"/>'
    return s


def p_pav_bhaji(rng):
    s = thali()
    s += f'<g filter="url(#soft)"><ellipse cx="170" cy="200" rx="78" ry="34" fill="#C9C1B5"/><ellipse cx="170" cy="197" rx="68" ry="27" fill="#C2410C"/></g>'
    for _ in range(22):
        s += f'<circle cx="{rng.uniform(116, 224):.0f}" cy="{rng.uniform(182, 212):.0f}" r="{rng.uniform(1.5, 3.2):.1f}" fill="{rng.choice(["#E85D04", "#8E2C07", "#FFD166"])}"/>'
    s += '<rect x="150" y="186" width="22" height="8" rx="3" fill="#FFE8A3"/>'
    for _ in range(10):
        s += f'<path d="M{rng.uniform(130, 210):.0f} {rng.uniform(186, 205):.0f} l4 -4" stroke="#43A047" stroke-width="2"/>'
    for x, y in [(276, 176), (292, 218)]:
        s += (f'<rect x="{x - 40}" y="{y - 22}" width="80" height="44" rx="18" fill="#B9742C"/>'
              f'<rect x="{x - 36}" y="{y - 20}" width="72" height="34" rx="16" fill="#E9A85A"/>'
              f'<ellipse cx="{x - 10}" cy="{y - 10}" rx="16" ry="5" fill="#FFE39E" opacity=".8"/>')
    return s


def p_chole_bhature(rng):
    s = thali()
    s += ('<g filter="url(#soft)"><ellipse cx="148" cy="190" rx="92" ry="54" fill="#D9A04A"/>'
          '<ellipse cx="148" cy="182" rx="86" ry="48" fill="#F2C878"/>'
          '<ellipse cx="128" cy="168" rx="30" ry="12" fill="url(#shine)"/>'
          '<path d="M80 196 q 30 12 60 2 q 30 -10 70 4" stroke="#C88A2E" stroke-width="2" fill="none"/></g>')
    s += '<g filter="url(#soft)"><ellipse cx="282" cy="212" rx="56" ry="28" fill="#C9C1B5"/><ellipse cx="282" cy="209" rx="48" ry="22" fill="#7A3E12"/></g>'
    for _ in range(30):
        s += f'<circle cx="{rng.uniform(244, 320):.0f}" cy="{rng.uniform(196, 222):.0f}" r="3.4" fill="{rng.choice(["#C17A2C", "#A8611D", "#D9963A"])}"/>'
    s += '<path d="M262 200 l10 -6 M290 202 l8 4" stroke="#E53935" stroke-width="3"/><path d="M300 196 q6 -8 12 0" stroke="#43A047" stroke-width="3" fill="none"/>'
    return s


def p_poori(rng):
    s = thali()
    for x, y, r in [(132, 196, 46), (214, 182, 50), (270, 212, 40), (180, 226, 40)]:
        s += (f'<ellipse cx="{x}" cy="{y + 4}" rx="{r}" ry="{r * .55}" fill="#C7852F"/>'
              f'<ellipse cx="{x}" cy="{y - 2}" rx="{r - 3}" ry="{r * .5}" fill="#EDB75C"/>'
              f'<ellipse cx="{x - r * .3:.0f}" cy="{y - r * .25:.0f}" rx="{r * .35:.0f}" ry="{r * .14:.0f}" fill="url(#shine)"/>'
              + "".join(f'<circle cx="{x + rng.uniform(-r * .7, r * .7):.0f}" cy="{y + rng.uniform(-r * .3, r * .3):.0f}" r="2" fill="#B5701F" opacity=".6"/>' for _ in range(6)))
    return s


def p_parotta(rng):
    s = thali()
    for x, y in [(160, 200), (238, 190)]:
        s += f'<ellipse cx="{x}" cy="{y + 6}" rx="70" ry="38" fill="#C78A3A"/><ellipse cx="{x}" cy="{y}" rx="68" ry="36" fill="#EFC27A"/>'
        for k in range(5, 0, -1):
            s += f'<ellipse cx="{x}" cy="{y}" rx="{k * 12}" ry="{k * 6.4}" fill="none" stroke="#C9893A" stroke-width="2.2" opacity=".75"/>'
        for _ in range(14):
            s += f'<circle cx="{x + rng.uniform(-55, 55):.0f}" cy="{y + rng.uniform(-26, 26):.0f}" r="2.2" fill="#9B5A1A" opacity=".55"/>'
    s += chutney(318, 238, 22, "#E9A15A")
    return s


PRODUCTS = {
    "gulab-jamun": p_gulab_jamun, "rasgulla": p_rasgulla, "rasmalai": p_rasmalai, "kaju-katli": p_kaju_katli,
    "mysore-pak": p_mysore_pak, "motichoor-laddu": p_motichoor_laddu, "besan-laddu": p_besan_laddu,
    "jalebi": p_jalebi, "peda": p_peda, "soan-papdi": p_soan_papdi, "milk-cake": p_milk_cake,
    "badusha": p_badusha, "coconut-burfi": p_coconut_burfi, "kalakand": p_kalakand, "cham-cham": p_cham_cham,
    "samosa": p_samosa, "kachori": p_kachori, "veg-puff": p_veg_puff, "paneer-tikka": p_paneer_tikka,
    "masala-dosa": p_masala_dosa, "idli": p_idli, "vada": p_vada, "biryani": p_biryani, "pav-bhaji": p_pav_bhaji,
    "chole-bhature": p_chole_bhature, "poori": p_poori, "parotta": p_parotta,
}


# ------------------------------------------------------------------ brand assets
def logo():
    petals = "".join(
        f'<path d="M50 50 Q{50 + 30 * math.cos(a - .28):.1f} {50 + 30 * math.sin(a - .28):.1f} {50 + 40 * math.cos(a):.1f} {50 + 40 * math.sin(a):.1f} '
        f'Q{50 + 30 * math.cos(a + .28):.1f} {50 + 30 * math.sin(a + .28):.1f} 50 50Z" fill="#E8772E" opacity=".9"/>'
        for a in [i * math.pi / 6 for i in range(12)])
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<circle cx="50" cy="50" r="48" fill="#D4A017"/><circle cx="50" cy="50" r="44" fill="#7B1E2B"/>'
            f'{petals}<circle cx="50" cy="50" r="22" fill="#7B1E2B"/>'
            '<path d="M32 56 Q50 74 68 56Z" fill="#F3D27A"/>'
            '<path d="M50 30 C57 39 56 47 50 52 C44 47 43 39 50 30Z" fill="#FFE08A"/>'
            '<path d="M50 38 C53 43 53 47 50 50 C47 47 47 43 50 38Z" fill="#fff"/>'
            '<circle cx="50" cy="50" r="46" fill="none" stroke="#F3D27A" stroke-width="1.2" stroke-dasharray="2 3"/></svg>')


def mandala():
    parts = []
    for ring, (n, r, size) in enumerate([(8, 30, 16), (16, 60, 14), (24, 92, 12), (32, 124, 10)]):
        for i in range(n):
            a = i * 2 * math.pi / n
            x, y = 150 + r * math.cos(a), 150 + r * math.sin(a)
            deg = math.degrees(a) + 90
            parts.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{size / 2.4:.1f}" ry="{size:.1f}" transform="rotate({deg:.1f} {x:.1f} {y:.1f})"/>')
    circles = "".join(f'<circle cx="150" cy="150" r="{r}"/>' for r in (16, 45, 76, 108, 140))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300"><g fill="none" stroke="#F3D27A" stroke-width="2">'
            f'{circles}{"".join(parts)}</g></svg>')


def empty_thali():
    return svg(thali(200, 190, 170, 64) + '<text x="200" y="196" text-anchor="middle" font-family="Georgia" font-size="22" fill="#9C7414" opacity=".7">खाली थाली</text>')


def placeholder():
    rng = random.Random(1)
    return svg(thali() + ball(200, 186, 44, "#F6D27A", "#C99032", texture="#B07A25", rng=rng))


def main():
    os.makedirs(PROD, exist_ok=True)
    for slug, fn in PRODUCTS.items():
        rng = random.Random(slug)
        with open(os.path.join(PROD, f"{slug}.svg"), "w") as fh:
            fh.write(svg(fn(rng)))
    with open(os.path.join(PROD, "placeholder.svg"), "w") as fh:
        fh.write(placeholder())
    with open(os.path.join(OUT, "logo-mark.svg"), "w") as fh:
        fh.write(logo())
    with open(os.path.join(OUT, "mandala.svg"), "w") as fh:
        fh.write(mandala())
    with open(os.path.join(OUT, "empty-thali.svg"), "w") as fh:
        fh.write(empty_thali())
    print(f"Wrote {len(PRODUCTS)} product illustrations + brand assets to {OUT}")


if __name__ == "__main__":
    main()
