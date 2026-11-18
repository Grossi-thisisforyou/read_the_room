"""Scene variants: several compositions per hook, chosen per visitor and
rotated during long hook phases, so a long evening does not repeat itself.

A scene is plain data:
  name      for the control view / debugging
  ground    spec for ground.build_ground (kind, horizon, panels, shadow, light, busy)
  figs      figure instances, each a dict:
              cx, cy   centre in 0..1 of the frame
              h        height as a share of the frame height
              rot      degrees (counter-clockwise), 180 = upside down
              mirror   flip left/right
              crop     None (whole body), 'head', 'face', 'eyes', 'mouth'
              src      'live', or 'echo1'/'echo2'/'echo3' (the visitor a few
                       seconds ago, held in memory only for this visit), or
                       'bank' (a painted cutout figure from the overnight
                       library; 'fallback' names the source when there is none)
              smear    multiplier on the smear for this instance
              alpha    0..1
              paint    True: strokes and arc swipes are painted on this one
              shadow   True: a painted cast shadow behind it
              move     how much the phone's tilt moves it (0..1.5)
  props     painted furniture: kind 'dais' | 'plinth' | 'bench' | 'rug',
            x, y, w, h in 0..1 (centre x, top y, width, height)
  cage      None | 'box' | 'arch' | 'ring' | 'rail' | 'frame', with 'cage_fig'
  strokes   brush family weights for the paint on the figure
  swipes    how often arc swipes cross the face (per minute at full intensity)
  fade      how fast the paint on top fades (alpha steps per second)
  text      'free' | 'margins' | 'band' | 'line' : where words may go

Every builder takes (rng, oc) where rng is a random.Random seeded by the
visitor and the rotation count, and oc the OCEAN dict.
"""
import math


def _fig(**kw):
    d = dict(cx=0.5, cy=0.55, h=0.9, rot=0.0, mirror=False, crop=None, src="live",
             smear=1.0, alpha=1.0, paint=False, shadow=False, move=1.0, panel=None)
    d.update(kw)
    return d


def _scene(name, **kw):
    d = dict(name=name, ground=dict(kind="room", horizon=0.7), figs=[], props=[], cage=None, cage_fig=0,
             strokes=dict(loaded=1.0, wipe=0.6, scumble=0.4, knife=0.2, nervous=0.2),
             swipes=4.0, fade=40.0, text="free")
    d.update(kw)
    return d


# ---------------------------------------------------------------- flesh
def flesh_dais(rng, oc):
    x = rng.choice([0.5, 0.42, 0.58])
    return _scene("flesh/dais",
                  ground=dict(kind="room", horizon=rng.uniform(0.66, 0.74), shadow=(x, 0.86, 0.17, 0.05),
                              light=(x, 0.4, 0.55), busy=rng.uniform(0.3, 0.7)),
                  figs=[_fig(cx=x, cy=0.5, h=0.78, paint=True, shadow=True)],
                  props=[dict(kind="dais", x=x, y=0.8, w=0.42, h=0.13)],
                  cage=rng.choice(["box", "box", "arch", "ring"]))


def flesh_bench(rng, oc):
    side = rng.choice([-1, 1])
    return _scene("flesh/bench",
                  ground=dict(kind="room", horizon=rng.uniform(0.58, 0.66), shadow=(0.5, 0.86, 0.32, 0.06),
                              light=(0.5, 0.45, 0.6), busy=0.5),
                  # the visitor lies on the bed: turned on their side
                  figs=[_fig(cx=0.5, cy=0.6, h=0.46, rot=90 * side, paint=True, shadow=True, move=0.6)],
                  props=[dict(kind="bench", x=0.5, y=0.7, w=0.72, h=0.14)],
                  cage=rng.choice(["rail", "frame", None]), swipes=5.0,
                  strokes=dict(loaded=0.8, wipe=1.0, scumble=0.5, knife=0.2, nervous=0.3))


def flesh_triptych(rng, oc):
    # three panels, the visitor in three states: a moment ago, now, turned
    return _scene("flesh/triptych",
                  ground=dict(kind="room", horizon=0.72, panels=3, light=(0.5, 0.45, 0.9), busy=0.35),
                  figs=[_fig(cx=1 / 6, cy=0.52, h=0.62, src="bank", fallback="echo2", smear=1.8, alpha=0.9, panel=0, move=0.4),
                        _fig(cx=0.5, cy=0.5, h=0.74, paint=True, shadow=True, panel=1, move=0.5),
                        _fig(cx=5 / 6, cy=0.52, h=0.62, src="echo1", mirror=True, smear=1.3, panel=2, move=0.4,
                             rot=rng.choice([0, 0, 180]))],
                  props=[dict(kind="rug", x=1 / 6, y=0.8, w=0.22, h=0.07), dict(kind="dais", x=0.5, y=0.8, w=0.26, h=0.09),
                         dict(kind="rug", x=5 / 6, y=0.8, w=0.22, h=0.07)],
                  cage=None, swipes=3.0, text="margins")


def flesh_head(rng, oc):
    # a head in a box on a plinth
    return _scene("flesh/head",
                  ground=dict(kind="room", horizon=0.78, light=(0.5, 0.35, 0.5), busy=0.6),
                  figs=[_fig(cx=0.5, cy=0.42, h=0.62, crop="head", paint=True, shadow=True, smear=1.3)],
                  props=[dict(kind="plinth", x=0.5, y=0.7, w=0.3, h=0.3)],
                  cage="box", swipes=7.0,
                  strokes=dict(loaded=1.0, wipe=1.0, scumble=0.3, knife=0.3, nervous=0.3))


def flesh_corner(rng, oc):
    # off-centre figure, a long shadow and a bent rail, much empty field
    x = rng.choice([0.3, 0.7])
    return _scene("flesh/corner",
                  ground=dict(kind="room", horizon=0.68, shadow=(x + (0.12 if x < 0.5 else -0.12), 0.84, 0.24, 0.05),
                              light=(x, 0.4, 0.5), busy=0.4),
                  figs=[_fig(cx=x, cy=0.52, h=0.7, paint=True, shadow=True)],
                  props=[dict(kind="rug", x=x, y=0.79, w=0.3, h=0.08)],
                  cage="rail", cage_fig=0, swipes=4.0)


# ---------------------------------------------------------------- inverted
def inv_full(rng, oc):
    return _scene("inverted/full",
                  ground=dict(kind="room", horizon=rng.uniform(0.3, 0.38), light=(0.5, 0.55, 0.6), busy=0.8),
                  figs=[_fig(cx=0.5, cy=0.5, h=0.86, rot=180, paint=True, smear=1.2)],
                  props=[], cage=rng.choice([None, "frame"]),
                  strokes=dict(loaded=1.4, wipe=0.4, scumble=0.6, knife=0.8, nervous=0.3), swipes=2.0, fade=60.0)


def inv_bust(rng, oc):
    # head-down bust, huge, cut off by the frame
    return _scene("inverted/bust",
                  ground=dict(kind="field", light=(0.5, 0.5, 0.7), busy=0.9),
                  figs=[_fig(cx=0.5, cy=0.56, h=1.25, rot=180, crop="head", paint=True, smear=0.9)],
                  strokes=dict(loaded=1.4, wipe=0.3, scumble=0.8, knife=1.0, nervous=0.4), swipes=2.0, fade=55.0,
                  text="margins")


def inv_double(rng, oc):
    return _scene("inverted/double",
                  ground=dict(kind="room", horizon=0.36, light=(0.5, 0.5, 0.8), busy=0.7),
                  figs=[_fig(cx=0.3, cy=0.5, h=0.8, rot=180, paint=True),
                        _fig(cx=0.7, cy=0.52, h=0.74, rot=180, mirror=True, src="bank", fallback="echo1", smear=1.6, alpha=0.85)],
                  strokes=dict(loaded=1.2, wipe=0.5, scumble=0.7, knife=0.9, nervous=0.3), swipes=2.0, fade=55.0)


def inv_fall(rng, oc):
    a = rng.choice([150, 205, 160])
    return _scene("inverted/fall",
                  ground=dict(kind="field", light=(0.55, 0.45, 0.6), busy=0.7),
                  figs=[_fig(cx=0.52, cy=0.5, h=0.8, rot=a, paint=True, smear=1.4, shadow=True)],
                  strokes=dict(loaded=1.0, wipe=0.8, scumble=0.6, knife=0.7, nervous=0.5), swipes=3.0, fade=60.0)


# ---------------------------------------------------------------- mirror
def mir_column(rng, oc):
    return _scene("mirror/column",
                  ground=dict(kind="column", horizon=0.88, light=(0.5, 0.5, 0.6), busy=0.3),
                  figs=[_fig(cx=0.5, cy=0.62, h=1.35, mirror=True, paint=True, smear=0.6)],
                  strokes=dict(loaded=0.6, wipe=0.8, scumble=0.5, knife=0.0, nervous=0.4), swipes=1.5, fade=30.0,
                  text="margins")


def mir_eyes(rng, oc):
    # an extreme close-up band across the eyes
    return _scene("mirror/eyes",
                  ground=dict(kind="field", light=(0.5, 0.5, 0.8), busy=0.4),
                  figs=[_fig(cx=0.5, cy=0.46, h=0.46, crop="eyes", mirror=True, paint=True, smear=0.4, move=0.5)],
                  strokes=dict(loaded=0.8, wipe=1.0, scumble=0.6, knife=0.0, nervous=0.3), swipes=1.0, fade=30.0,
                  text="band")


def mir_mouth(rng, oc):
    return _scene("mirror/mouth",
                  ground=dict(kind="field", light=(0.5, 0.55, 0.8), busy=0.4),
                  figs=[_fig(cx=0.5, cy=0.52, h=0.72, crop="mouth", mirror=True, paint=True, smear=0.5, move=0.5)],
                  strokes=dict(loaded=1.0, wipe=0.8, scumble=0.6, knife=0.0, nervous=0.3), swipes=1.5, fade=30.0,
                  text="band")


def mir_face(rng, oc):
    # the face fills the frame, mirrored, a moment ago ghosting through it
    return _scene("mirror/face",
                  ground=dict(kind="column", horizon=0.95, light=(0.5, 0.45, 0.7), busy=0.3),
                  figs=[_fig(cx=0.5, cy=0.5, h=1.0, crop="face", mirror=True, src="echo1", alpha=0.35, smear=2.0, move=0.3),
                        _fig(cx=0.5, cy=0.5, h=1.0, crop="face", mirror=True, paint=True, smear=0.5, move=0.6)],
                  strokes=dict(loaded=0.8, wipe=0.8, scumble=0.6, knife=0.0, nervous=0.4), swipes=1.0, fade=30.0,
                  text="margins")


# ---------------------------------------------------------------- scrawl (surveillance wall)
def scr_wall(rng, oc):
    return _scene("scrawl/wall",
                  ground=dict(kind="wall", busy=0.7, light=(0.5, 0.45, 0.9)),
                  figs=[_fig(cx=rng.choice([0.38, 0.5, 0.62]), cy=0.56, h=0.82, paint=True, smear=0.8)],
                  cage=None, strokes=dict(loaded=0.5, wipe=0.3, scumble=0.5, knife=0.6, nervous=1.0), swipes=1.0,
                  fade=25.0, text="free")


def scr_file(rng, oc):
    # a case file: the subject small in a box with height lines, data around
    return _scene("scrawl/file",
                  ground=dict(kind="wall", busy=0.5, light=(0.3, 0.45, 0.9)),
                  figs=[_fig(cx=0.27, cy=0.52, h=0.6, crop="head", paint=True, smear=0.4, move=0.5)],
                  cage="frame", strokes=dict(loaded=0.3, wipe=0.2, scumble=0.4, knife=0.5, nervous=1.0),
                  swipes=0.5, fade=25.0, text="file")


def scr_timeline(rng, oc):
    # the visitor repeated along a line: then, then, now
    return _scene("scrawl/timeline",
                  ground=dict(kind="wall", busy=0.4, light=(0.5, 0.5, 1.0)),
                  figs=[_fig(cx=0.18, cy=0.5, h=0.46, src="echo3", smear=1.2, alpha=0.8, move=0.3),
                        _fig(cx=0.39, cy=0.5, h=0.46, src="echo2", smear=1.0, alpha=0.85, move=0.3),
                        _fig(cx=0.6, cy=0.5, h=0.46, src="echo1", smear=0.8, alpha=0.9, move=0.3),
                        _fig(cx=0.82, cy=0.5, h=0.52, paint=True, smear=0.5, move=0.5)],
                  strokes=dict(loaded=0.3, wipe=0.2, scumble=0.4, knife=0.4, nervous=1.0), swipes=0.5,
                  fade=25.0, text="timeline")


def scr_redact(rng, oc):
    return _scene("scrawl/redacted",
                  ground=dict(kind="wall", busy=0.8, light=(0.5, 0.45, 0.9)),
                  figs=[_fig(cx=0.5, cy=0.55, h=0.86, paint=True, smear=0.6)],
                  strokes=dict(loaded=0.3, wipe=0.2, scumble=0.4, knife=1.0, nervous=0.8), swipes=0.5,
                  fade=20.0, text="redact")


# ---------------------------------------------------------------- void
def void_line(rng, oc):
    return _scene("void/line",
                  ground=dict(kind="deep", light=(0.5, 0.5, 0.5), busy=0.15),
                  figs=[_fig(cx=0.5, cy=0.5, h=0.7, alpha=0.32, smear=1.5, move=0.6)],
                  strokes={}, swipes=0.0, fade=20.0, text="line")


def void_far(rng, oc):
    x = rng.choice([0.2, 0.8])
    return _scene("void/far",
                  ground=dict(kind="deep", light=(x, 0.6, 0.35), busy=0.15),
                  figs=[_fig(cx=x, cy=0.62, h=0.34, alpha=0.5, smear=2.0, move=0.8)],
                  strokes={}, swipes=0.0, fade=20.0, text="line")


def void_horizon(rng, oc):
    return _scene("void/horizon",
                  ground=dict(kind="room", horizon=0.76, light=(0.5, 0.75, 0.5), busy=0.1),
                  figs=[_fig(cx=0.5, cy=0.7, h=0.16, alpha=0.6, smear=1.0, move=1.2)],
                  strokes={}, swipes=0.0, fade=20.0, text="line")


def void_breath(rng, oc):
    return _scene("void/breath",
                  ground=dict(kind="deep", light=(0.5, 0.45, 0.6), busy=0.1),
                  figs=[_fig(cx=0.5, cy=0.45, h=0.9, crop="face", alpha=0.22, smear=2.5, move=0.4)],
                  strokes={}, swipes=0.0, fade=20.0, text="line")


VARIANTS = {
    "flesh": [flesh_dais, flesh_bench, flesh_triptych, flesh_head, flesh_corner],
    "inverted": [inv_full, inv_bust, inv_double, inv_fall],
    "mirror": [mir_column, mir_eyes, mir_mouth, mir_face],
    "scrawl": [scr_wall, scr_file, scr_timeline, scr_redact],
    "void": [void_line, void_far, void_horizon, void_breath],
}


def idle_scene(rng):
    """Nobody there: the empty room waits (a dais and its cage, no figure)."""
    return _scene("idle", ground=dict(kind="room", horizon=0.7, light=(0.5, 0.45, 0.6), busy=0.4,
                                      shadow=(0.5, 0.86, 0.15, 0.04)),
                  figs=[], props=[dict(kind="dais", x=0.5, y=0.8, w=0.4, h=0.12)], cage="box", strokes={}, swipes=0)


def profiling_scene(rng, hook):
    """While the profiler reads the visitor: one figure, scanned, in a frame."""
    return _scene("profiling", ground=dict(kind="room", horizon=0.72, light=(0.5, 0.45, 0.6), busy=0.4,
                                           shadow=(0.5, 0.86, 0.15, 0.04)),
                  figs=[_fig(cx=0.5, cy=0.5, h=0.8, paint=True, smear=0.8)],
                  props=[dict(kind="dais", x=0.5, y=0.8, w=0.4, h=0.12)], cage="box",
                  strokes=dict(loaded=0.6, wipe=0.4, scumble=0.6, knife=0.2, nervous=0.8), swipes=1.5)


def pick(hook, visitor_seed, rotation, rng, oc):
    """The variant for this visitor and this rotation. Visitors walk the list
    from a different starting point, and a shuffled stride avoids the same
    pair following each other."""
    lst = VARIANTS.get(hook) or VARIANTS["flesh"]
    n = len(lst)
    stride = 1 + (visitor_seed // 7) % max(1, n - 1)
    idx = (visitor_seed + rotation * stride) % n
    return lst[idx](rng, oc), idx


CROPS = {
    # (x centre, y centre, width, height) relative to the face: x, y in face
    # sizes from the face centre; width/height in face sizes
    "head": (0.0, 0.25, 1.9, 1.9),
    "face": (0.0, 0.0, 1.05, 1.05),
    "eyes": (0.0, -0.1, 1.2, 0.42),
    "mouth": (0.0, 0.3, 0.8, 0.5),
}


def crop_rect(crop, face, face_size, fw, fh):
    """Rect (x, y, w, h) in figure-buffer pixels for a named crop."""
    if not crop or crop not in CROPS:
        return (0, 0, fw, fh)
    ox, oy, cw, ch = CROPS[crop]
    s = max(8.0, face_size)
    w, h = cw * s, ch * s
    # a crop of a handful of camera pixels is only mush when blown up: widen it
    # around its centre until its short side has some 30 pixels of real picture
    g = max(1.0, 30.0 / max(1.0, min(w, h)))
    w = max(6, int(w * g)); h = max(6, int(h * g))
    x = int(face[0] + ox * s - w / 2)
    y = int(face[1] + oy * s - h / 2)
    x = max(0, min(fw - w, x)) if w < fw else 0
    y = max(0, min(fh - h, y)) if h < fh else 0
    return (x, y, min(w, fw), min(h, fh))
