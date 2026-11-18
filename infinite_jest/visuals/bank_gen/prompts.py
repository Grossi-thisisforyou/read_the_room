"""Prompt vocabulary for the INFINITE JEST image bank (version 2).

Every image is described by a short prompt built from parts:

    subject (figure + pose), the hook's style line, composition (position,
    framing, panel), mark-making, palette, setting, 0-2 surveillance / dark-data motifs,
    sometimes a "theme of the night" phrase and a school-of-painting phrase.

The look is carried by plain descriptive language. No painter or artist is
named anywhere, and no real person is depicted.

Each part also becomes a TAG in the image's sidecar .json (hook, palette,
composition, motifs, theme...), so the renderer can later pick images by tag,
e.g. "a flesh image with the figure on the left in the burnt-orange palette".
Palette tags are the names in visuals/palettes.py.

SD-Turbo reads only about the first 75 word-pieces (CLIP tokens) of a prompt
and silently drops the rest. So the important parts come first, and build()
drops the least important extras until the prompt fits (see fit()).

To change the look: edit the lists below. Add lines, delete lines. Keep each
line short. `python3 prompts.py` prints samples; `python3 prompts.py --stats`
counts the combinations.
"""
import datetime
import hashlib
import random
import re

PROMPT_VERSION = 2
HOOKS = ("flesh", "scrawl", "inverted", "mirror", "void")

MAX_WORDS = 69    # stay below ~70 words ...
MAX_TOKENS = 75   # ... and below CLIP's 77-token window (2 are start/end markers)

COMMON_STYLE = "expressionist oil painting, visible canvas texture"

NEGATIVE = (
    "photograph, photorealistic, 3d render, cgi, anime, cartoon, glossy, "
    "smooth digital art, watermark, signature, logo, frame, border, text overlay, "
    "lowres, jpeg artifacts, multiple panels, cheerful, bright daylight"
)

# ------------------------------------------------------------------ palettes
# Keys are palette names from visuals/palettes.py, so a tag "palette: papal"
# means the same colours to the renderer as to the painter. Each palette has
# general phrases, and some hooks have their own phrasing of it.
PALETTES = {
    "triptych": {
        "default": [
            "flat burnt orange ground, raw pink and cream flesh",
            "flat cadmium orange field, black doorway, meat pinks",
            "searing orange ground, flesh streaked rose and bone",
        ],
    },
    "papal": {
        "default": [
            "flat violet ground, pink and grey flesh",
            "deep purple field, rose flesh, bone white highlights",
            "dusky lilac ground, cold mauve shadows",
        ],
        "mirror": ["black and violet shadows, a faint rose glow on the skin"],
    },
    "acid": {
        "default": [
            "flat acid green ground, red and white flesh",
            "sickly olive green field, raw pink figure",
            "poison green ground, bruised salmon skin",
        ],
    },
    "meat": {
        "default": [
            "black and blood red, raw meat pinks and bone white",
            "deep oxblood ground, flesh like butchered meat",
            "dark maroon field, crimson and cream streaks",
        ],
        "scrawl": ["stained cream paper, black ink and dried blood red"],
    },
    "bruise": {
        "default": [
            "bruise purples and greys on near black",
            "deep indigo darkness, mauve skin, bone light",
        ],
        "mirror": [
            "deep blue darkness, cold white light on the face",
            "black and violet shadows, a cold blue glow on skin",
        ],
        "void": ["near black with a faint violet tint"],
    },
    "ash": {
        "default": [
            "charcoal grey and black, chalky white",
            "ash grey field, graphite shadows, dirty white",
        ],
        "scrawl": [
            "yellowed paper, graphite grey and black ink",
            "cold grey and black, a single acid green highlight",
        ],
        "mirror": [
            "near black background, pale skin in a narrow column of light",
            "dark umber, single shaft of white light",
        ],
        "void": [
            "near black, deep charcoal, a tiny touch of grey",
            "black with a very faint blue glow",
        ],
    },
    "sodium": {
        "default": [
            "warm sodium streetlight orange on black",
            "amber lamp glow on deep brown darkness",
        ],
        "scrawl": ["torn brown paper, black marker, amber stains"],
        "mirror": ["warm sodium light on the face, black surroundings"],
        "void": ["black and deepest brown, one dim warm light"],
    },
    "concrete": {
        "default": [
            "grey-white wall, black marks, one red accent",
            "pale concrete, charcoal black, a single red stroke",
        ],
        "scrawl": [
            "dirty grey concrete, black charcoal, one red mark",
            "faded white chalk on grey, rust red",
        ],
    },
    "rose": {
        "default": [
            "flat deep pink ground, raw rose and cream flesh",
            "hot pink field, crimson shadows, bone highlights",
        ],
        "mirror": ["deep rose darkness, warm pink light on the skin"],
    },
    "oxblood": {
        "default": [
            "flat dried-blood red ground, pale salmon flesh",
            "dark oxblood field, flesh in cream and rust",
        ],
    },
    "teal": {
        "default": [
            "flat cold teal ground, salmon pink flesh",
            "deep green-blue field, raw peach skin",
        ],
    },
    "lilac": {
        "default": [
            "flat pale lilac ground, peach and mauve flesh",
            "soft violet-grey field, rosy flesh",
        ],
        "mirror": ["dusky lilac shadows, a pale peach glow on the face"],
    },
    "putty": {
        "default": ["warm grey putty wall, black marks, one brick red stroke"],
        "scrawl": [
            "warm grey plaster, graphite, one brick red mark",
            "putty-coloured paper, black ink, a rust red smear",
        ],
    },
    "abyss": {
        "default": ["near black with a deep ultramarine glow"],
        "void": ["near black, a faint deep ultramarine glow", "blue-black darkness, one cold grey glint"],
    },
    "abyss_red": {
        "default": ["near black, deepest oxblood haze"],
        "void": ["near black, a faint dried-blood red haze"],
    },
    "abyss_green": {
        "default": ["near black, deep bottle green haze"],
        "void": ["near black, a faint bottle green haze"],
    },
}

# Which palettes each hook uses, and how often (bigger number = more often).
HOOK_PALETTES = {
    "flesh":    {"triptych": 4, "papal": 3, "acid": 2, "meat": 2, "sodium": 1,
                 "rose": 1, "oxblood": 1, "teal": 1, "lilac": 1},
    "scrawl":   {"concrete": 4, "ash": 2, "putty": 2, "meat": 1, "sodium": 1},
    "inverted": {"acid": 3, "meat": 2, "triptych": 2, "ash": 1, "papal": 1, "sodium": 1,
                 "teal": 1, "oxblood": 1},
    "mirror":   {"bruise": 3, "sodium": 2, "ash": 2, "papal": 1, "rose": 1, "lilac": 1},
    "void":     {"abyss": 3, "ash": 2, "bruise": 1, "abyss_red": 1, "abyss_green": 1, "sodium": 1},
}

# ------------------------------------------------------------------ composition
# Three independent choices. The tags let the renderer place its live figure
# against the picture, e.g. put the visitor right when the bank figure is left.
# "{n}" becomes the hook's noun: figure / face / form.
POSITIONS = {
    "left": "{n} in the left third",
    "right": "{n} in the right third",
    "centre": "{n} in the centre",
}
FRAMINGS = {
    "full-body": "full length, head to feet",
    "bust": "half-length bust",
    "close-up": "tight close-up",
    "small": "small in a wide empty field",
    "high-angle": "seen from high above",
}
PANELS = {
    "single": "",
    "triptych-left": "left panel of a triptych",
    "triptych-centre": "centre panel of a triptych",
    "triptych-right": "right panel of a triptych",
}
HOOK_COMPOSITION = {
    "flesh": {
        "noun": "figure",
        "position": {"left": 2, "right": 2, "centre": 3},
        "framing": {"full-body": 4, "bust": 2, "small": 2, "high-angle": 1},
        "panel": {"single": 6, "triptych-left": 1, "triptych-centre": 1, "triptych-right": 1},
    },
    "scrawl": {
        "noun": "figure",
        "position": {"left": 2, "right": 2, "centre": 3},
        "framing": {"full-body": 3, "bust": 2, "high-angle": 2, "small": 1},
        "panel": {"single": 1},
    },
    "inverted": {
        "noun": "figure",
        "position": {"left": 2, "right": 2, "centre": 3},
        "framing": {"full-body": 4, "bust": 2, "close-up": 1},
        "panel": {"single": 5, "triptych-left": 1, "triptych-right": 1},
    },
    "mirror": {
        "noun": "face",
        "position": {"left": 1, "right": 1, "centre": 3},
        "framing": {"close-up": 3, "bust": 2},
        "panel": {"single": 1},
    },
    "void": {
        "noun": "form",
        "position": {"left": 1, "right": 1, "centre": 2},
        "framing": {"small": 4, "full-body": 1},
        "panel": {"single": 1},
    },
}

# ------------------------------------------------------------------ motifs
# Surveillance and dark-data details, (tag, phrase, hooks or None for all).
MOTIFS = [
    ("face-box", "a crude face-detection box around the head", None),
    ("timestamp", "a ghostly camera timestamp scratched into the paint", None),
    ("rec-dot", "a faint red recording dot in one corner", None),
    ("crosshair", "thin tracking crosshairs over the head", None),
    ("landmarks", "facial landmark dots joined by shaky lines", ("scrawl", "mirror", "flesh")),
    ("measure-grid", "a grid of measurement dots across the skin", ("flesh", "inverted", "mirror")),
    ("barcode", "a barcode half buried under the paint", ("flesh", "scrawl", "inverted")),
    ("scanlines", "horizontal scan lines bleeding through the paint", None),
    ("price-tag", "a small price tag pinned to the flesh", ("flesh", "inverted")),
    ("tape-measure", "a tailor's tape measure wrapped around the body", ("flesh", "inverted", "scrawl")),
    ("data-rows", "rows of tiny numbers smeared like data", None),
    ("phone-glow", "a pale phone-screen glow on the skin", ("mirror", "void", "flesh")),
    ("heat-map", "a thermal heat-map bloom over the chest", ("flesh", "inverted", "mirror")),
    ("pins", "dressmaker pins and chalk fitting marks on the body", ("flesh", "inverted")),
    ("consent-box", "a ticked consent checkbox in pencil", ("scrawl", "flesh")),
    ("progress-bar", "a loading bar stalled near the end", ("scrawl", "void", "mirror")),
    ("redaction", "black redaction bars across the eyes", ("scrawl", "mirror", "flesh")),
    ("signal-arcs", "faint wireless signal arcs around the head", None),
    ("fingerprint", "a huge fingerprint whorl smeared into the ground", ("flesh", "scrawl", "inverted", "void")),
    ("heartbeat", "a thin heart-rate line crossing the body", None),
    ("map-pin", "a map pin stuck over the heart", ("flesh", "scrawl", "inverted")),
    ("cursor", "a blinking text cursor beside the mouth", ("mirror", "scrawl")),
    ("night-vision", "a green night-vision cast", ("void", "mirror", "scrawl")),
    ("id-badge", "a blank lanyard badge on the chest", ("flesh", "inverted", "scrawl")),
]
MOTIF_BY_TAG = {m[0]: m for m in MOTIFS}

# Chance of one motif, and of a second one, per hook.
MOTIF_CHANCE = {
    "flesh": (0.55, 0.15), "scrawl": (0.9, 0.5), "inverted": (0.45, 0.1),
    "mirror": (0.4, 0.1), "void": (0.25, 0.0),
}
SCHOOL_CHANCE = 0.3

# ------------------------------------------------------------------ themes
# A theme of the night makes one night's batch hang together: it leans the
# palettes, motifs and framings one way and adds a short phrase.
THEMES = {
    "watched": {
        "phrase": "under the cold eye of a camera",
        "motifs": ["timestamp", "rec-dot", "crosshair", "night-vision", "scanlines", "face-box"],
        "palettes": ["ash", "bruise", "concrete", "abyss"],
        "framings": ["high-angle", "small"],
    },
    "harvest": {
        "phrase": "everything weighed, priced and catalogued",
        "motifs": ["barcode", "price-tag", "data-rows", "heat-map", "progress-bar"],
        "palettes": ["meat", "triptych", "sodium", "oxblood"],
        "framings": ["full-body"],
    },
    "tailored": {
        "phrase": "measured for something made only for them",
        "motifs": ["tape-measure", "pins", "measure-grid", "id-badge"],
        "palettes": ["papal", "triptych", "lilac", "putty"],
        "framings": ["full-body", "bust"],
    },
    "afterglow": {
        "phrase": "alone at night in screen light",
        "motifs": ["phone-glow", "cursor", "signal-arcs", "heartbeat"],
        "palettes": ["sodium", "bruise"],
        "framings": ["close-up", "bust"],
    },
    "ledger": {
        "phrase": "one entry in an endless ledger",
        "motifs": ["data-rows", "redaction", "consent-box", "fingerprint"],
        "palettes": ["concrete", "ash", "acid", "putty"],
        "framings": ["small", "full-body"],
    },
    "tenderness": {
        "phrase": "intimate, held far too close",
        "motifs": ["heartbeat", "map-pin", "phone-glow", "fingerprint"],
        "palettes": ["papal", "sodium", "meat", "rose"],
        "framings": ["close-up", "bust"],
    },
    "fever": {
        "phrase": "feverish, overexposed and sick",
        "motifs": ["heat-map", "night-vision", "scanlines", "landmarks"],
        "palettes": ["acid", "meat", "teal", "abyss_green"],
        "framings": ["full-body", "close-up"],
    },
}
THEME_NAMES = tuple(THEMES)
THEME_PHRASE_CHANCE = 0.6
THEME_MOTIF_SHARE = 0.75   # with a theme, this share of motifs come from its list
THEME_WEIGHT = 4           # themed palettes / framings count this many times more

# ------------------------------------------------------------------ hooks
# subject = one "figure" + one "pose"; every pairing must read as a phrase.
HOOK_PARTS = {
    "flesh": {
        "figure": [
            "a smeared nude figure",
            "a hunched figure in a dark suit",
            "an isolated body with a blurred featureless face",
            "a raw meat-coloured figure",
            "a gaunt figure in a white vest",
            "a heavy-shouldered figure",
            "a twisted body, limbs melting together",
            "a figure with a dissolving head",
        ],
        "pose": [
            "crouched on a round plinth",
            "twisting on a bare chair",
            "gripping its own shoulders",
            "screaming, mouth wide open",
            "folded over a metal rail",
            "curled on a narrow bed",
            "slumped beside a hanging carcass",
            "turning away, spine arched",
        ],
        "marks": [
            "smeared and wiped flesh, dragged with a rag",
            "thick swirled impasto flesh against flat untouched ground",
            "brush twisted through wet paint, blurred motion",
            "raw meat pinks streaked with bruise purple and white",
            "fast curling strokes, edges scraped away",
            "dry-brushed shadows, a thrown splash of white paint",
            "flesh pressed with corduroy cloth, sandy texture",
            "one sharp line among soft smudged volumes",
        ],
        "setting": [
            "thin white cage of space-frame lines",
            "transparent glass box outlined in thin lines",
            "curved floor band, a single bare light bulb",
            "geometric box frame in perspective around the body",
            "a dark doorway behind, shadow pooling on the floor",
            "a round rug like a stage under the figure",
            "a black curtain of vertical streaks behind",
            "an empty room with one shuttered window",
        ],
        "school": [
            "postwar figurative painting",
            "unsettling mid-century portrait painting",
            "large unprimed canvas, museum lighting",
        ],
    },
    "scrawl": {
        # Dark data and surveillance, made by hand on paper and grey concrete.
        "figure": [
            "a raw smeared figure",
            "a blurred face",
            "a crude outline of a body",
            "a smudged figure seen from above",
            "a faint standing figure",
            "a hunched seated figure",
            "a figure drawn in one shaky continuous line",
        ],
        "pose": [
            "boxed by a hand-drawn detection frame",
            "covered in dots joined by shaky lines",
            "sketched over a half-erased data table",
            "beside rows of scratched tally marks",
            "crossed by map coordinates and arrows",
            "ringed by hand-drawn tracking circles",
            "surrounded by redacted handwritten lists",
            "pinned among numbered evidence labels",
        ],
        "marks": [
            "hand-lettered numbers, half erased and written over",
            "thick black redaction bars over handwriting",
            "scratched pencil and charcoal, smudged with a thumb",
            "layers of crossed-out notes, scraped back and rewritten",
            "stencilled digits, chalk marks and frantic arrows",
            "coordinates and timestamps scratched in by hand",
            "ballpoint scribbles pressed hard enough to tear",
            "carbon-copy smudges and rubber-stamped dates",
        ],
        "setting": [
            "torn paper notices layered on a concrete wall",
            "crowded surface of notes and figures edge to edge",
            "pages of a ruled ledger taped together",
            "an evidence board of pinned scraps and string",
            "a grid of crude drawings like a surveillance log",
            "a stack of index cards spread across a desk",
            "a photocopied form, boxes filled in by hand",
        ],
        "school": [
            "archival evidence drawing",
            "outsider notebook drawing",
        ],
        "style": "rough hand-made mixed media drawing, paper and concrete texture",
    },
    "inverted": {
        "figure": [
            "an upside-down standing figure",
            "an inverted seated man",
            "an upside-down nude",
            "an upside-down figure with a dog",
            "an inverted figure in work clothes",
            "an upside-down figure beside a table",
            "an inverted figure in a heavy coat",
        ],
        "pose": [
            "arms hanging toward the sky",
            "head at the bottom edge",
            "eyes wide open",
            "hands clasped, feet up",
            "gripping a stick",
            "staring out blankly",
            "one fist raised downward",
        ],
        "marks": [
            "raw heavy brushstrokes, slabs of paint",
            "wide house-painter brush marks, scraped and smeared",
            "thick angry strokes, splashes and fingerprints",
            "coarse cross-hatched brushwork like a woodcut",
            "paint applied with fingers, gouged with the brush handle",
            "violent loaded brush, raw canvas showing",
            "dripping runs of thinned paint falling upward",
            "dark contour lines dug around the body",
        ],
        "setting": [
            "upside-down landscape, horizon at the top",
            "background left as bare gesso",
            "figure cut by the canvas edges",
            "an upside-down tree beside the figure",
            "rough field of grass hanging from the top",
            "empty corners scrubbed with dirty colour",
            "a heavy ground line at the top of the canvas",
        ],
        "school": [
            "1970s neo-expressionist painting",
            "raw unfinished expressionist painting",
            "large rough canvas painted on the floor",
        ],
    },
    "mirror": {
        "figure": [
            "a distorted face",
            "a face pressed flat against glass",
            "a stretched face in a warped mirror",
            "a face half dissolved into darkness",
            "a doubled face slightly out of register",
            "a face behind a cracked phone screen",
            "a face reflected in a dark window",
        ],
        "pose": [
            "looking straight out",
            "with one eye lit",
            "mouth half open",
            "eyes closed, lips parted",
            "breath fogging the surface",
            "smeared sideways",
            "lit from below",
        ],
        "marks": [
            "soft smeared oil glazes, blurred edges",
            "wiped and smudged paint, features dragged sideways",
            "fine scumbled skin, harsh highlights",
            "wet blended paint, a thumb smear across the eyes",
            "thin translucent layers over a dark ground",
            "a single hard highlight, everything else soft",
        ],
        "setting": [
            "vertical column of light, darkness around",
            "most of the canvas in shadow",
            "the edge of a mirror frame cutting the face",
            "a dark room behind, one window",
            "condensation streaks on glass",
            "a second faint reflection behind",
        ],
        "school": [
            "chiaroscuro portrait painting",
            "intimate night portrait, old master lighting",
        ],
    },
    "void": {
        "figure": [
            "a single faint human form",
            "a pale hand",
            "a dim small figure",
            "an empty chair",
            "the outline of a head turned away",
            "a faint silhouette of a body",
            "a dim doorway with a shape inside",
        ],
        "pose": [
            "barely visible in the dark",
            "emerging from blackness",
            "far away at the edge of sight",
            "dissolving into smoke",
            "almost gone",
            "lit by one dim source",
            "half swallowed by shadow",
        ],
        "marks": [
            "thin dark glazes, almost no detail",
            "barely visible brushwork, black on black",
            "soft dry brush, faint scratched lines",
            "very low contrast, smoky haze",
            "a single thin grey stroke",
        ],
        "setting": [
            "vast empty dark space",
            "mostly empty black",
            "darkness above, a dim floor",
            "a single faint vertical line",
            "a hint of a room's corner",
        ],
        "school": [
            "dark minimal painting",
            "tenebrist painting, almost total darkness",
        ],
    },
}

# ------------------------------------------------------------------ helpers

_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")


def estimate_tokens(text):
    """A cautious guess at CLIP's token count: each word, number and
    punctuation mark counts one, and long words count extra (CLIP splits
    rare long words into pieces). Over-counts a little on purpose."""
    n = 0
    for t in _TOKEN_RE.findall(text):
        n += 1
        if t.isalpha() and len(t) > 8:
            n += (len(t) - 2) // 7
    return n


def fits(text):
    return len(text.split()) <= MAX_WORDS and estimate_tokens(text) <= MAX_TOKENS


def night_of(now=None):
    """The date a night belongs to: 22:00 on the 20th and 03:00 on the 21st
    are both the night of the 20th (the day changes at noon)."""
    now = now or datetime.datetime.now()
    return (now - datetime.timedelta(hours=12)).date()


def theme_for_night(now=None):
    """Theme of the night: walks through THEMES one per night, so two nights
    in a row never share a theme and every machine agrees on the same one."""
    return THEME_NAMES[night_of(now).toordinal() % len(THEME_NAMES)]


def resolve_theme(theme, now=None, rng=None):
    """'auto' -> tonight's theme; 'mix' -> a random theme (or none) for each
    image; None/''/'none' -> None; a theme name -> itself."""
    if theme in (None, "", "none"):
        return None
    if theme == "auto":
        return theme_for_night(now)
    if theme == "mix":
        return (rng or random).choice(THEME_NAMES + (None, None))
    if theme not in THEMES:
        raise ValueError("unknown theme %r (expected auto, mix, none or one of %s)"
                         % (theme, ", ".join(THEME_NAMES)))
    return theme


def _weighted(rng, weights, avoid=None):
    keys = list(weights)
    if avoid in weights and len(keys) > 1 and rng.random() < 0.8:
        keys = [k for k in keys if k != avoid]   # rarely the same twice running
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


class PromptDeck:
    """Deals prompt parts like cards so nothing repeats too soon.

    Each list (subjects, marks, settings, phrases...) is shuffled and dealt
    one by one; only when a list is used up is it reshuffled. On top of that
    the deck remembers every full combination it has dealt (and any you pass
    to remember(), e.g. from existing sidecars) and re-deals on a repeat.
    """

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.piles = {}
        self.last = {}
        self.seen = set()

    def deal(self, key, items):
        items = list(items)
        pile = self.piles.get(key)
        if not pile or pile[0] != items:
            pile = self.piles[key] = [items, []]
        if not pile[1]:
            order = list(range(len(items)))
            self.rng.shuffle(order)
            # don't start a new round with the card that ended the last one
            if len(order) > 1 and self.last.get(key) == order[-1]:
                order[0], order[-1] = order[-1], order[0]
            pile[1] = order
        i = pile[1].pop()
        self.last[key] = i
        return items[i]

    def remember(self, signature):
        if signature:
            self.seen.add(signature)


def _pick_motifs(hook, theme, rng, deck):
    first, second = MOTIF_CHANCE.get(hook, (0.4, 0.1))
    if theme:
        first, second = min(1.0, first + 0.25), min(1.0, second + 0.1)
    n = 0
    if rng.random() < first:
        n = 2 if rng.random() < second else 1
    allowed = [m for m in MOTIFS if m[2] is None or hook in m[2]]
    themed = [m for m in allowed if theme and m[0] in THEMES[theme]["motifs"]]
    picked = []
    for _ in range(n):
        use_theme = bool(themed) and rng.random() < THEME_MOTIF_SHARE
        pool = themed if use_theme else allowed
        key = "motif:%s:%s" % (hook, "theme" if use_theme else "all")
        m = deck.deal(key, pool) if deck else rng.choice(pool)
        if m in picked:
            rest = [x for x in allowed if x not in picked]
            if not rest:
                break
            m = rng.choice(rest)
        picked.append(m)
    return picked


def _palette_phrase(hook, name, rng, deck):
    entry = PALETTES[name]
    phrases = entry.get(hook) or entry["default"]
    key = "palette:%s:%s" % (hook, name)
    return deck.deal(key, phrases) if deck else rng.choice(phrases)


def _compose(hook, theme, rng, last):
    c = HOOK_COMPOSITION[hook]
    framing_w = dict(c["framing"])
    if theme:
        for f in THEMES[theme]["framings"]:
            if f in framing_w:
                framing_w[f] *= THEME_WEIGHT
    comp = {
        "position": _weighted(rng, c["position"], last.get("position")),
        "framing": _weighted(rng, framing_w, last.get("framing")),
        "panel": _weighted(rng, c["panel"]),
    }
    words = []
    if comp["panel"] != "single":
        words.append(PANELS[comp["panel"]])
    words.append(POSITIONS[comp["position"]].format(n=c["noun"]))
    words.append(FRAMINGS[comp["framing"]])
    return comp, ", ".join(words)


def make(hook, rng=None, theme=None, deck=None, now=None, max_tries=25):
    """Build one prompt. Returns a dict:

    prompt, negative, parts (the phrases used), tags (structured), tag_list
    (flat "key:value" strings), signature (short id of the combination),
    theme, prompt_version.
    """
    if hook not in HOOK_PARTS:
        raise ValueError("unknown hook %r (expected one of %s)" % (hook, ", ".join(HOOKS)))
    rng = rng or (deck.rng if deck else random.Random())
    theme = resolve_theme(theme, now, rng)
    result = None
    for _ in range(max_tries):
        result = _make_once(hook, rng, theme, deck)
        if not deck or result["signature"] not in deck.seen:
            break
    if deck:
        deck.remember(result["signature"])
        deck.last[("comp", hook)] = result["tags"]["composition"]
        deck.last[("palette", hook)] = result["tags"]["palette"]
    return result


def _make_once(hook, rng, theme, deck):
    p = HOOK_PARTS[hook]
    deal = (lambda key, items: deck.deal("%s:%s" % (hook, key), items)) if deck \
        else (lambda key, items: rng.choice(items))

    figure = deal("figure", p["figure"])
    pose = deal("pose", p["pose"])
    marks = deal("marks", p["marks"])
    setting = deal("setting", p["setting"])

    pal_w = dict(HOOK_PALETTES[hook])
    if theme:
        for name in THEMES[theme]["palettes"]:
            if name in pal_w:
                pal_w[name] *= THEME_WEIGHT
    last_pal = deck.last.get(("palette", hook)) if deck else None
    palette = _weighted(rng, pal_w, last_pal)
    palette_text = _palette_phrase(hook, palette, rng, deck)

    last_comp = (deck.last.get(("comp", hook)) if deck else None) or {}
    comp, comp_text = _compose(hook, theme, rng, last_comp)
    motifs = _pick_motifs(hook, theme, rng, deck)
    style = p.get("style", COMMON_STYLE)
    theme_text = THEMES[theme]["phrase"] if theme and rng.random() < THEME_PHRASE_CHANCE else None
    school = deal("school", p["school"]) if p.get("school") and rng.random() < SCHOOL_CHANCE else None

    # Order = importance. fit() removes optional pieces from the end of
    # DROP_ORDER until the prompt is short enough for CLIP.
    pieces = {
        "subject": "%s, %s" % (figure, pose),
        "style": style,
        "composition": comp_text,
        "marks": marks,
        "palette": palette_text,
        "setting": setting,
        "motif1": motifs[0][1] if len(motifs) > 0 else None,
        "motif2": motifs[1][1] if len(motifs) > 1 else None,
        "theme": theme_text,
        "school": school,
    }
    pieces = fit(pieces)
    used_motifs = [m for i, m in enumerate(motifs) if pieces.get("motif%d" % (i + 1))]
    prompt = ", ".join(v for v in pieces.values() if v)

    tags = {
        "hook": hook,
        "palette": palette,
        "composition": comp,
        "motifs": [m[0] for m in used_motifs],
        "theme": theme,
        "school": bool(pieces.get("school")),
    }
    tag_list = ["hook:" + hook, "palette:" + palette,
                "position:" + comp["position"], "framing:" + comp["framing"],
                "panel:" + comp["panel"]]
    tag_list += ["motif:" + m for m in tags["motifs"]]
    if theme:
        tag_list.append("theme:" + theme)
    sig_src = "|".join([hook, figure, pose, marks, setting, palette_text,
                        comp["position"], comp["framing"], comp["panel"]]
                       + tags["motifs"])
    parts = {
        "subject": pieces["subject"],
        "figure": figure,
        "pose": pose,
        "marks": marks,
        "palette": palette_text,
        "composition": comp_text,
        "setting": pieces.get("setting"),
        "motifs": [m[1] for m in used_motifs],
        "theme": pieces.get("theme"),
        "style": style,
        "school": pieces.get("school"),
    }
    return {
        "prompt": prompt,
        "negative": NEGATIVE,
        "parts": parts,
        "tags": tags,
        "tag_list": tag_list,
        "signature": hashlib.sha1(sig_src.encode()).hexdigest()[:12],
        "theme": theme,
        "prompt_version": PROMPT_VERSION,
    }


# least important first: these go when the prompt is too long
DROP_ORDER = ("school", "theme", "motif2", "setting", "motif1")


def fit(pieces):
    pieces = dict(pieces)
    for key in DROP_ORDER:
        if fits(", ".join(v for v in pieces.values() if v)):
            break
        pieces[key] = None
    return pieces


def sidecar_fields(result):
    """The prompt-related fields every generator writes into an image's .json."""
    return {
        "prompt": result["prompt"],
        "negative_prompt": result["negative"],
        "parts": result["parts"],
        "tags": result["tags"],
        "tag_list": result["tag_list"],
        "signature": result["signature"],
        "theme": result["theme"],
        "prompt_version": result["prompt_version"],
    }


def build_prompt(hook, rng=None, theme=None, deck=None):
    """Old interface: return (prompt, negative_prompt, parts). parts also
    carries "tags", "tag_list" and "signature"."""
    r = make(hook, rng=rng, theme=theme, deck=deck)
    parts = dict(r["parts"], tags=r["tags"], tag_list=r["tag_list"], signature=r["signature"])
    return r["prompt"], r["negative"], parts


def combinations(hook):
    """Rough count of distinct prompts for a hook (ignoring motifs/extras)."""
    p = HOOK_PARTS[hook]
    c = HOOK_COMPOSITION[hook]
    pal = sum(len(PALETTES[n].get(hook) or PALETTES[n]["default"]) for n in HOOK_PALETTES[hook])
    comp = len(c["position"]) * len(c["framing"]) * len(c["panel"])
    return len(p["figure"]) * len(p["pose"]) * len(p["marks"]) * len(p["setting"]) * pal * comp


if __name__ == "__main__":
    import sys
    if "--stats" in sys.argv:
        for h in HOOKS:
            print("%-9s about %s combinations before motifs and themes" % (h, format(combinations(h), ",")))
        sys.exit(0)
    theme = None
    for a in sys.argv[1:]:
        if a.startswith("--theme="):
            theme = a.split("=", 1)[1]
    d = PromptDeck()
    print("theme: %s\n" % (resolve_theme(theme) or "none"))
    for h in HOOKS:
        for _ in range(2):
            r = make(h, deck=d, theme=theme)
            print("[%s] %s\n    tags: %s  (%d words, ~%d tokens)\n" % (
                h, r["prompt"], " ".join(r["tag_list"][1:]),
                len(r["prompt"].split()), estimate_tokens(r["prompt"])))
