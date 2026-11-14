# -*- coding: utf-8 -*-
"""What the N900 screen draws, in plain pycairo (works on Maemo and laptops).

Pure drawing: draw(cr, w, h, snap, local, t) paints one frame from the
agent's UI snapshot and the UI's own typing state. No GTK in here, so the
tests can render the screens to PNG files.

Look: deep dark industrial. Near-black, film grain and scanlines; raw
off-white condensed type; crossed-out words and tally marks;
Baselitz's upside-down words; Bacon's smeared flesh pink and a face that
won't hold its shape. Everything is drawn, so nothing has to be shipped.
"""

import math
import random

import cairo

from compat import text_type, string_types, to_text

FONT = 'Nokia Sans Cn'      # the N900's own condensed face; cairo falls back if missing
FONT_FALLBACK = 'Sans'

INK = (0.93, 0.90, 0.84)       # raw off-white
BONE = (0.91, 0.85, 0.66)      # crown yellow-bone
BLOOD = (0.70, 0.05, 0.04)
FLESH = (0.86, 0.47, 0.42)
BG = (0.035, 0.03, 0.028)

CONSENT_LINES = [
    'The camera, microphone and motion of this phone',
    'feed a performance made only for you.',
    'Nothing leaves this room.',
    'Everything is erased when you leave.',
]


def txt(v):
    """Unicode text for cairo on Python 2 and 3 (JSON strings may be non-ASCII)."""
    if isinstance(v, string_types):
        return to_text(v)
    return text_type(v)


def hex_rgb(s, default=FLESH):
    try:
        s = str(s).lstrip('#')
        if len(s) == 3:
            s = ''.join([c * 2 for c in s])
        return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)
    except Exception:
        return default


def font(cr, size, bold=True):
    cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL,
                        bold and cairo.FONT_WEIGHT_BOLD or cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(size)


def text_w(cr, s):
    return cr.text_extents(s)[4]


def fit(cr, s, max_w, size, bold=True):
    font(cr, size, bold)
    w = text_w(cr, s)
    if w > max_w and w > 0:
        size = size * max_w / w
        font(cr, size, bold)
    return size


def show(cr, s, x, y, rgb=INK, a=1.0):
    cr.set_source_rgba(rgb[0], rgb[1], rgb[2], a)
    cr.move_to(x, y)
    cr.show_text(s)


def jitter_line(cr, pts, rnd, amp, width, rgb, a=1.0):
    cr.set_source_rgba(rgb[0], rgb[1], rgb[2], a)
    cr.set_line_width(width)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    first = True
    for x, y in pts:
        x += rnd.uniform(-amp, amp)
        y += rnd.uniform(-amp, amp)
        if first:
            cr.move_to(x, y)
            first = False
        else:
            cr.line_to(x, y)
    cr.stroke()


def strike(cr, x, y, w, size, rnd, rgb=BLOOD, a=0.9, n=2):
    """Basquiat cross-out: rough strokes through a word (it stays legible)."""
    for k in range(n):
        yy = y - size * (0.28 + 0.12 * k)
        jitter_line(cr, [(x - 6, yy + rnd.uniform(-3, 3)), (x + w * 0.5, yy + rnd.uniform(-4, 4)),
                         (x + w + 6, yy + rnd.uniform(-3, 3))], rnd, 1.5, size * 0.09, rgb, a)


def tally(cr, x, y, s, rnd, rgb=BONE, a=1.0):
    """Four strokes and a slash: the room keeping count."""
    for i in range(4):
        xx = x + s * (0.12 + 0.22 * i)
        jitter_line(cr, [(xx, y), (xx + s * 0.04, y - s * 0.8)], rnd, s * 0.04, max(2.0, s * 0.07), rgb, a)
    jitter_line(cr, [(x, y - s * 0.15), (x + s, y - s * 0.65)], rnd, s * 0.04, max(2.0, s * 0.07), rgb, a)


def grain(cr, w, h, rnd, n=180, a=0.10):
    # two batched fills (dark and light specks) keep this cheap on the N900
    for v in (0.0, 1.0):
        cr.set_source_rgba(v, v, v, a)
        for i in range(n // 2):
            cr.rectangle(rnd.random() * w, rnd.random() * h, 1 + rnd.random() * 2, 1)
        cr.fill()


def scanlines(cr, w, h, t):
    cr.set_source_rgba(0, 0, 0, 0.28)
    off = int(t * 30) % 3
    y = off
    while y < h:
        cr.rectangle(0, y, w, 1)
        y += 3
    cr.fill()


def smear(cr, cx, cy, r, rgb, t, rnd, strength=1.0):
    """Bacon: a body that is mostly a wound, dragged sideways."""
    for i in range(9):
        dy = (i - 4.5) * r * 0.17
        drag = (math.sin(t * 0.9 + i * 0.7) * 0.5 + 0.5) * r * 1.4 * strength
        g = cairo.LinearGradient(cx - r, 0, cx + r + drag, 0)
        g.add_color_stop_rgba(0, rgb[0], rgb[1], rgb[2], 0.0)
        g.add_color_stop_rgba(0.35, rgb[0], rgb[1], rgb[2], 0.55)
        g.add_color_stop_rgba(1, rgb[0] * 0.4, rgb[1] * 0.2, rgb[2] * 0.2, 0.0)
        cr.set_source(g)
        cr.rectangle(cx - r, cy + dy, 2 * r + drag, r * 0.19 + rnd.uniform(0, r * 0.05))
        cr.fill()


def face(cr, cx, cy, r, t, loud, motion, rnd, rgb=FLESH):
    """A head that won't keep its shape. Loudness opens the mouth, motion tears it."""
    cr.save()
    cr.translate(cx, cy)
    tear = 0.15 + motion * 0.9
    cr.new_path()
    n = 28
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        rr = r * (1 + 0.10 * math.sin(a * 3 + t * 1.3) + tear * 0.25 * math.sin(a * 7 - t * 2.1)
                  + rnd.uniform(-0.03, 0.03))
        x = math.cos(a) * rr * (1 + tear * 0.4 * max(0, math.cos(a)))
        y = math.sin(a) * rr * 1.18
        if i == 0:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)
    cr.close_path()
    g = cairo.RadialGradient(-r * 0.2, -r * 0.3, r * 0.1, 0, 0, r * 1.3)
    g.add_color_stop_rgba(0, rgb[0], rgb[1], rgb[2], 0.85)
    g.add_color_stop_rgba(0.6, rgb[0] * 0.7, rgb[1] * 0.35, rgb[2] * 0.35, 0.7)
    g.add_color_stop_rgba(1, 0.1, 0.02, 0.02, 0.0)
    cr.set_source(g)
    cr.fill()
    # eyes: two dark smudges; one slides
    for sx in (-0.38, 0.32):
        cr.set_source_rgba(0.04, 0.02, 0.02, 0.9)
        cr.arc(r * sx + math.sin(t * 0.5) * r * 0.1 * tear, -r * 0.25, r * 0.12, 0, 2 * math.pi)
        cr.fill()
    # mouth: the scream opens with the room's loudness
    mo = r * (0.04 + loud * 0.45)
    cr.set_source_rgba(BLOOD[0] * 0.5, 0.0, 0.0, 0.95)
    cr.save()
    cr.translate(0, r * 0.45)
    cr.scale(r * 0.42, mo + 1)
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()
    cr.fill()
    cr.restore()


def upside_down(cr, s, x, y, size, rgb=INK, a=1.0):
    """Baselitz: the word hangs upside down, anchored at (x, y)."""
    cr.save()
    cr.translate(x, y)
    cr.rotate(math.pi)
    font(cr, size)
    show(cr, s, -text_w(cr, s), 0, rgb, a)
    cr.restore()


# --------------------------------------------------------------- screens --

def draw(cr, w, h, snap, local, t):
    beat_seed = int(t * 8)
    rnd = random.Random(beat_seed)
    cr.set_source_rgb(BG[0], BG[1], BG[2])
    cr.paint()
    if snap.get('optout'):
        draw_optout(cr, w, h, t, rnd)
    elif snap.get('screen') == 'live':
        draw_live(cr, w, h, snap, local, t, rnd)
    else:
        draw_consent(cr, w, h, snap, t, rnd)
    grain(cr, w, h, rnd)
    scanlines(cr, w, h, t)
    link_dot(cr, w, snap.get('link', 'none'), t)


def link_dot(cr, w, link, t):
    if link == 'ws':
        cr.set_source_rgba(INK[0], INK[1], INK[2], 0.35)
    elif link == 'udp':
        cr.set_source_rgba(BONE[0], BONE[1], BONE[2], 0.35 + 0.3 * (int(t * 2) % 2))
    else:
        cr.set_source_rgba(BLOOD[0], BLOOD[1], BLOOD[2], 0.4 + 0.5 * (int(t * 2) % 2))
    cr.arc(w - 10, 10, 3, 0, 2 * math.pi)
    cr.fill()


def draw_consent(cr, w, h, snap, t, rnd):
    m = w * 0.05
    # Bacon smear bottom-left, breathing
    smear(cr, w * 0.2, h * 0.78, h * 0.32, FLESH, t, rnd, 0.6 + 0.4 * math.sin(t * 0.6))
    # Baselitz: the title hangs upside down top-left
    upside_down(cr, 'INFINITE JEST', m, h * 0.05, h * 0.075, INK, 0.75)
    # a tally, top right: the room keeps count
    tally(cr, w * 0.83, h * 0.17, h * 0.13, rnd)
    font(cr, h * 0.035, False)
    show(cr, u'DARK DATA', w * 0.80, h * 0.23, BONE, 0.8)
    # The headline. RECORDING is struck through and still legible.
    size = fit(cr, 'THIS ROOM IS', w * 0.62, h * 0.13)
    y = h * 0.33
    show(cr, 'THIS ROOM IS', m, y)
    y += size * 1.0
    size2 = fit(cr, 'RECORDING YOU', w * 0.88, h * 0.16)
    show(cr, 'RECORDING YOU', m, y)
    font(cr, size2)
    rec_w = text_w(cr, 'RECORDING')
    strike(cr, m, y + size2 * 0.05, rec_w, size2 * 0.6, rnd, BLOOD, 0.75, 1)
    # plain statement, no cleverness
    y += h * 0.10
    for line in CONSENT_LINES:
        fit(cr, line, w * 0.62, h * 0.045, False)
        show(cr, line, m, y, INK, 0.92)
        y += h * 0.058
    # enter
    blink = 0.55 + 0.45 * math.sin(t * 3.0)
    fit(cr, 'TOUCH TO ENTER', w * 0.3, h * 0.07)
    tw = text_w(cr, 'TOUCH TO ENTER')
    show(cr, 'TOUCH TO ENTER', w - m - tw, h * 0.92, BONE, blink)
    jitter_line(cr, [(w - m - tw - 50, h * 0.90), (w - m - tw - 12, h * 0.90),
                     (w - m - tw - 24, h * 0.87), (w - m - tw - 12, h * 0.90),
                     (w - m - tw - 24, h * 0.93)], rnd, 1.2, 3, BONE, blink)


def draw_optout(cr, w, h, t, rnd):
    """The visitor covered the eye for 3 s: nothing about them is read now."""
    s = 'YOU ARE NOT BEING READ'
    size = fit(cr, s, w * 0.86, h * 0.12)
    show(cr, s, (w - text_w(cr, s)) / 2, h * 0.5, INK, 0.9)
    fit(cr, 'the eye is closed until you leave', w * 0.6, h * 0.045, False)
    sub = 'the eye is closed until you leave'
    show(cr, sub, (w - text_w(cr, sub)) / 2, h * 0.62, INK, 0.5)
    # a closed eye: one heavy lid line
    jitter_line(cr, [(w * 0.42, h * 0.25), (w * 0.5, h * 0.28), (w * 0.58, h * 0.25)],
                rnd, 1.0, 5, BLOOD, 0.8)


def readout_lines(r, local):
    """The 'dark data' it is collecting, said back to the visitor."""
    out = []
    tilt = r.get('tilt')
    if tilt:
        out.append(u'YOU TILT %+.0f\xb0 / %+.0f\xb0' % (tilt.get('beta', 0), tilt.get('gamma', 0)))
    if 'held' in r:
        out.append(r['held'] and 'YOU ARE HOLDING ME' or 'YOU LEFT ME ON THE TABLE')
    a = r.get('audio')
    if a:
        out.append('VOICE %s   LEVEL %.2f' % (a.get('voiced') and 'YES' or 'NO', a.get('level', 0)))
    if 'motion' in r:
        out.append('MOVEMENT %.2f' % r['motion'])
    if 'light' in r:
        out.append('LIGHT %.2f' % r['light'])
    if r.get('proximity', {}).get('near'):
        out.append('TOO CLOSE')
    if local.get('backspaces'):
        out.append('HESITATIONS %d' % local['backspaces'])
    if 'presence' in r:
        out.append('CERTAINTY YOU ARE HERE %.0f%%' % (r['presence'] * 100))
    return out


def draw_live(cr, w, h, snap, local, t, rnd):
    st = snap.get('state') or {}
    r = snap.get('reading') or {}
    pal = st.get('palette') or {}
    colors = pal.get('colors') if isinstance(pal, dict) else pal
    cols = [hex_rgb(c) for c in (colors or [])] or [FLESH, BLOOD, BONE]
    inten = float(st.get('intensity', 0.4) or 0.4)
    tempo = float(st.get('tempo', 128) or 128)
    beat = (t * tempo / 60.0) % 1.0
    kick = math.exp(-beat * 7.0) * inten
    # background thump in the palette's first color
    c0 = cols[0]
    cr.set_source_rgba(c0[0], c0[1], c0[2], 0.06 + 0.22 * kick)
    cr.paint()
    loud = r.get('audio', {}).get('level', 0.0) or 0.0
    motion = r.get('motion', 0.0) or 0.0
    hook = st.get('hook') or ''
    # the face sits where the tilt pushes it
    tilt = r.get('tilt') or {}
    fx = w * 0.5 + (tilt.get('gamma', 0) or 0) * w * 0.006
    fy = h * 0.47 + (tilt.get('beta', 0) or 0) * h * 0.004
    if hook == 'void':
        cr.set_source_rgba(INK[0], INK[1], INK[2], 0.5 + 0.5 * kick)
        cr.rectangle(w * 0.2, h * 0.5, w * 0.6, 2)
        cr.fill()
    else:
        smear(cr, fx - h * 0.15, fy + h * 0.1, h * 0.3, cols[min(1, len(cols) - 1)], t, rnd, inten)
        face(cr, fx, fy, h * (0.2 + 0.05 * kick), t, loud, motion, rnd, cols[0])
        if hook in ('scrawl', 'inverted', ''):
            tally(cr, fx - h * 0.12, fy - h * 0.28, h * 0.24, rnd)
    # words the engine wants scrawled: some crossed out, some upside down
    words = st.get('words') or []
    wr = random.Random(len(words) * 7 + int(t / 3))
    for i, word in enumerate(words[:6]):
        word = txt(word).upper()[:28]
        size = h * wr.uniform(0.04, 0.07)
        x = wr.uniform(w * 0.03, w * 0.6)
        y = wr.uniform(h * 0.12, h * 0.6)
        if hook == 'inverted' or i % 3 == 2:
            upside_down(cr, word, x, y, size, BONE, 0.45)
        else:
            font(cr, size)
            show(cr, word, x, y, INK, 0.45)
            if i % 2:
                strike(cr, x, y, text_w(cr, word), size, wr, BLOOD, 0.6)
    # dark data readout, bottom left, small and relentless
    lines = readout_lines(r, local)
    font(cr, h * 0.032, False)
    y = h * 0.97 - len(lines) * h * 0.042
    for line in lines:
        show(cr, line, w * 0.03, y, INK, 0.55)
        y += h * 0.042
    # what the show says to this visitor
    text = txt(snap.get('text') or '')
    if text and not snap.get('prompt'):
        reveal = min(len(text), int((t - snap.get('text_t', t)) * 18) + 1)
        s = text[:max(0, reveal)].upper()
        size = fit(cr, s or ' ', w * 0.86, h * 0.12)
        tw = text_w(cr, s)
        show(cr, s, (w - tw) / 2, h * 0.2, INK, 0.95)
    prompt = snap.get('prompt')
    if prompt:
        draw_prompt(cr, w, h, prompt, t, rnd)
    # typing line (keyboard slid open)
    if local.get('typing') or r.get('slide'):
        buf = txt(local.get('buffer', ''))
        cur = (int(t * 2) % 2) and '_' or ' '
        size = fit(cr, '> ' + buf + cur, w * 0.9, h * 0.06)
        cr.set_source_rgba(0, 0, 0, 0.7)
        cr.rectangle(0, h * 0.84, w, h * 0.1)
        cr.fill()
        show(cr, '> ' + buf + cur, w * 0.04, h * 0.91, BONE, 1.0)


def draw_prompt(cr, w, h, prompt, t, rnd):
    cr.set_source_rgba(0, 0, 0, 0.55)
    cr.paint()
    ask = txt(prompt.get('ask', '')).upper()
    size = fit(cr, ask, w * 0.9, h * 0.1)
    show(cr, ask, (w - text_w(cr, ask)) / 2, h * 0.2)
    # torn vertical divider
    pts = []
    y = h * 0.3
    while y < h * 0.95:
        pts.append((w / 2, y))
        y += h * 0.05
    jitter_line(cr, pts, rnd, 4, 3, BLOOD, 0.8)
    opts = prompt.get('options') or ['', '']
    for i in range(2):
        s = txt(opts[i]).upper()
        cx = w * (0.25 + 0.5 * i)
        size = fit(cr, s, w * 0.4, h * 0.14)
        show(cr, s, cx - text_w(cr, s) / 2, h * 0.62, INK if i == 0 else BONE)
        font(cr, h * 0.035, False)
        hint = '[%d]' % (i + 1)
        show(cr, hint, cx - text_w(cr, hint) / 2, h * 0.75, INK, 0.4)
