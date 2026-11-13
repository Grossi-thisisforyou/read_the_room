"""Colour palettes. The five named palettes come from docs/CONTRACT.md; the
extra ones are flat Bacon-style grounds the visuals pick for themselves.

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
}

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
        cols = name_or_colors.get("colors") or NAMED.get(name_or_colors.get("name", ""), None)
    elif isinstance(name_or_colors, str):
        cols = NAMED.get(name_or_colors)
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
        return "concrete" if E > 0.4 else "ash"
    if hook == "void":
        return "ash"
    if O > 0.66:
        return "acid" if A < 0.5 else "papal"
    if N > 0.62 and A < 0.5:
        return "meat"
    if N > 0.62:
        return "bruise"
    if E > 0.6:
        return "sodium" if C < 0.5 else "triptych"
    return HOOK_DEFAULT.get(hook, "triptych")
