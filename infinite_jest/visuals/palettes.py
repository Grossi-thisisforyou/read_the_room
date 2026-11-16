"""Colour palettes. The five named palettes come from the contract; the extra
ones are the flat saturated painted grounds the visuals pick for themselves.

A palette is 5 colours ordered dark -> light:
  [0] deepest shadow, [1] ground shadow, [2] main accent / ground,
  [3] flesh / mid, [4] highlight / paper.
"""

def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


NAMED = {
    # contract palettes
    "meat":   ["#0b0b0b", "#3a0d0d", "#8c1c1c", "#d9826b", "#efe6dc"],
    "bruise": ["#050507", "#1d1630", "#4b2c5e", "#8a6a9c", "#d8d0c0"],
    "crown":  ["#0a0a0a", "#1a1a1a", "#e8c547", "#c0392b", "#f2f2f2"],
    "ash":    ["#000000", "#151515", "#3d3d3d", "#8a8a8a", "#e0e0e0"],
    "sodium": ["#050300", "#2b1600", "#a35200", "#ff8c1a", "#fff1d6"],
    # visuals' own: the flat saturated grounds of the triptychs
    "triptych": ["#120806", "#5a1e0e", "#d4622a", "#e3a08a", "#f3e7d3"],  # burnt orange
    "papal":    ["#07040a", "#2a1238", "#6b2f86", "#c98b8b", "#efe2d0"],  # violet
    "acid":     ["#050805", "#203014", "#6f8f2a", "#d9a48e", "#f0ead8"],  # sick green
    "concrete": ["#040404", "#1b1b1b", "#e4e2dc", "#b3261e", "#8f8f88"],  # grey-white wall, one red
    "rose":     ["#14070b", "#5e1630", "#cf4f78", "#e8a99a", "#f6e9dc"],  # deep pink
    "oxblood":  ["#0b0304", "#3a0a10", "#8a1a28", "#d08a78", "#efe2d2"],  # dried blood red
    "teal":     ["#030a0a", "#0f3534", "#1f7c74", "#d9a08c", "#efe7da"],  # cold green-blue
    "lilac":    ["#0a0710", "#3b2d55", "#8f7bbd", "#e0a898", "#f4ece2"],  # pale violet
    "putty":    ["#0a0806", "#3c342a", "#c9b8a0", "#9e2b25", "#f2ebe0"],  # warm grey wall
    "abyss":    ["#020308", "#0b123a", "#1d2a78", "#8f8aa8", "#d8d4e8"],  # deep ultramarine (void)
    "abyss_red": ["#060102", "#260508", "#561019", "#a07070", "#e8d8d0"],  # deep oxblood (void)
    "abyss_green": ["#010504", "#06231e", "#0f4a40", "#7f9a90", "#d4e2dc"],  # deep bottle green (void)
}

# The contract's "crown" palette (black, yellow, red, white) is drawn as a
# warm putty wall instead: that colour combination reads as a street tag.
ALIAS = {"crown": "putty"}

# Which ground each hook prefers when the engine does not send a palette.
HOOK_DEFAULT = {
    "flesh": "triptych",
    "scrawl": "concrete",
    "inverted": "acid",
    "mirror": "bruise",
    "void": "ash",
}


def get(name_or_colors):
    """Accept a name, a list of hex strings, or a contract palette dict."""
    cols = None
    if isinstance(name_or_colors, dict):
        name = name_or_colors.get("name", "")
        if name in ALIAS:
            cols = NAMED[ALIAS[name]]
        else:
            cols = name_or_colors.get("colors") or NAMED.get(name, None)
    elif isinstance(name_or_colors, str):
        cols = NAMED.get(ALIAS.get(name_or_colors, name_or_colors))
    elif isinstance(name_or_colors, (list, tuple)):
        cols = list(name_or_colors)
    if not cols:
        cols = NAMED["triptych"]
    cols = [hex2rgb(c) if isinstance(c, str) else tuple(c) for c in cols]
    while len(cols) < 5:  # pad short palettes by repeating the lightest
        cols.append(cols[-1])
    return cols[:5]


def pick_for(ocean, hook):
    """Choose a palette from the visitor's OCEAN scores when none is sent.
    High openness gets the stranger grounds, low agreeableness the harsher ones."""
    O = ocean.get("O", 0.5); A = ocean.get("A", 0.5); N = ocean.get("N", 0.5)
    E = ocean.get("E", 0.5); C = ocean.get("C", 0.5)
    if hook in ("scrawl",):
        return "concrete" if E > 0.4 else "putty"
    if hook == "void":
        return "abyss" if A >= 0.5 else ("abyss_red" if N > 0.5 else "abyss_green")
    if hook == "mirror":
        return "bruise" if E < 0.6 else "rose"
    if O > 0.66:
        if hook == "inverted":
            return "acid" if A < 0.5 else "teal"
        return "acid" if A < 0.5 else ("papal" if C < 0.5 else "lilac")
    if N > 0.62 and A < 0.5:
        return "meat"
    if N > 0.62:
        return "bruise"
    if E > 0.6:
        return "rose" if A > 0.6 else ("sodium" if C < 0.5 else "triptych")
    if N > 0.5 and hook == "flesh":
        return "oxblood"
    return HOOK_DEFAULT.get(hook, "triptych")


def shift(cols, hue_deg=0.0, sat=1.0, val=1.0):
    """The same palette nudged: hue rotated by hue_deg, saturation and value
    scaled. Used to make every visitor's ground a slightly different paint."""
    import colorsys
    out = []
    for c in cols:
        h, s, v = colorsys.rgb_to_hsv(*(x / 255.0 for x in c))
        h = (h + hue_deg / 360.0) % 1.0
        s = min(1.0, s * sat)
        v = min(1.0, v * val)
        out.append(tuple(int(round(x * 255)) for x in colorsys.hsv_to_rgb(h, s, v)))
    return out


def mix(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))
