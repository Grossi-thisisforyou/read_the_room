"""Prompt vocabulary for the INFINITE JEST image bank.

One section per hook. Each image draws one item from each list (subject,
mark-making, palette, composition) plus, sometimes, a theme detail (dark data,
custom-made intimacy, surveillance) and an art-historical influence.

The style is carried by concrete, descriptive visual language. Painters are
named only as distant influences, never as the subject, and no real people
are depicted. The scrawl hook names no artist at all.

SD-Turbo reads roughly the first 75 words-pieces (CLIP tokens) of a prompt and
quietly drops the rest, so the most important words come first and each item
is kept short. To change the look of a hook, edit the lists below: add lines,
delete lines. Nothing else needs to change.
"""
import random

HOOKS = ("flesh", "scrawl", "inverted", "mirror", "void")

COMMON_STYLE = "expressionist oil painting, visible canvas texture"

NEGATIVE = (
    "photograph, photorealistic, 3d render, cgi, anime, cartoon, glossy, "
    "smooth digital art, watermark, signature, logo, frame, border, text overlay, "
    "lowres, jpeg artifacts, multiple panels, cheerful, bright daylight"
)

# Small details that carry the installation's themes into any hook.
THEMES = [
    "a faint red recording dot in one corner",
    "a ghostly security-camera timestamp scratched into the paint",
    "thin tracking crosshairs over the head",
    "faint grid of measurement dots across the skin",
    "a barcode half buried under paint",
    "horizontal scan lines bleeding through the paint",
    "a small price tag pinned to the flesh",
    "a blurred surveillance-camera angle from above",
    "a tape measure wrapped around the body like a tailor fitting",
    "rows of tiny numbers smeared like data",
    "a cropped rectangle like a face-detection box",
    "a pale glow like a phone screen on the skin",
]

HOOK_PARTS = {
    "flesh": {
        "subject": [
            "a single smeared figure sitting alone on a low dais",
            "an isolated twisted body crouched on a round plinth",
            "a screaming open mouth in a blurred head, body dissolving",
            "a figure folded over a bare chair, limbs melting into each other",
            "a hunched nude figure gripping its own shoulders",
            "a man-shaped mass of raw meat on a pedestal",
            "two blurred figures wrestling into one shape on a bed",
            "a businessman-shaped silhouette with a smeared featureless face",
            "a hanging carcass beside a seated figure",
        ],
        "marks": [
            "smeared and wiped flesh, dragged with a rag",
            "thick swirled impasto flesh against flat untouched ground",
            "brush twisted through wet paint, blurred motion",
            "raw meat pinks streaked with bruise purple and white",
            "flesh rendered in fast curling strokes, edges scraped away",
            "dry-brushed shadows, a thrown splash of white paint",
        ],
        "palette": [
            "flat saturated orange ground, raw meat pinks",
            "flat violet ground, pink and grey flesh",
            "flat cadmium orange background, black void doorway",
            "deep magenta ground, sickly ochre flesh",
            "flat acid green ground, red and white flesh",
            "dusty rose ground, brown and crimson flesh",
        ],
        "composition": [
            "thin white cage of space-frame lines around the figure",
            "transparent glass box outlined in thin lines",
            "curved floor band, empty room, single bare light bulb",
            "figure small in the center of a large empty field",
            "geometric box frame in perspective enclosing the body",
            "a dark doorway behind the figure, shadow pooling on the floor",
        ],
        "influence": [
            "in the spirit of postwar British figurative painting",
            "echoing Francis Bacon's isolated figures",
            "triptych panel, 1950s London painting",
        ],
    },
    "scrawl": {
        # Dark data and surveillance, hand-made. No artist is named here on purpose.
        "subject": [
            "a raw smeared figure with a crude face-detection box drawn around its head",
            "a blurred face covered in hand-drawn landmark dots joined by shaky lines",
            "a hand-ruled data table of numbers, half erased, a figure sketched over it",
            "rows of tally marks scratched beside a faint standing figure",
            "a crude outline of a body crossed by map coordinates and arrows",
            "a smudged figure seen from above, ringed by hand-drawn tracking circles",
            "a barcode drawn by hand across a torso",
            "a page of handwritten names and numbers blacked out with redaction bars",
        ],
        "marks": [
            "hand-lettered words and numbers, half erased and written over",
            "thick black redaction bars over lines of handwriting",
            "scratched pencil and charcoal, smudged with a thumb",
            "layers of crossed-out text, scraped back and rewritten",
            "stencilled digits, chalk marks and frantic arrows",
            "coordinates and timestamps scratched in by hand",
        ],
        "palette": [
            "grey concrete wall, black charcoal, one red mark",
            "yellowed paper, graphite grey and black ink",
            "dirty grey ground, faded white chalk, rust red",
            "torn brown paper, black marker, pale blue ballpoint",
            "cold grey and black, a single acid green highlight",
            "stained cream paper, black ink and dried blood red",
        ],
        "composition": [
            "torn posters layered on a concrete wall",
            "crowded surface of notes, numbers and figures edge to edge",
            "a single figure in the middle, data scrawled all around it",
            "pages of a ruled ledger taped together, drawn over",
            "an evidence board of pinned paper scraps and string",
            "a grid of crude drawings like a surveillance log",
        ],
        "style": "rough hand-made mixed media drawing, visible paper and concrete texture",
        "influence": [],
    },
    "inverted": {
        "subject": [
            "an upside-down figure standing, head at the bottom",
            "an inverted portrait of a seated man, feet at the top",
            "an upside-down woodcutter figure with a dog",
            "an inverted nude with arms hanging toward the sky",
            "an upside-down head and shoulders, eyes open",
            "an upside-down eagle shape over a tree",
            "an inverted figure lying in a field, legs in the air",
        ],
        "marks": [
            "raw heavy brushstrokes, slabs of paint",
            "wide house-painter brush marks, scraped and smeared",
            "thick angry strokes, splashes and fingerprints",
            "coarse cross-hatched brushwork like a woodcut",
            "paint applied with fingers, gouged with the brush handle",
            "violent loaded brush, unfinished raw canvas showing",
        ],
        "palette": [
            "earthy browns, dirty greens, raw white",
            "harsh red and black on dirty yellow",
            "grey ground, flesh pink and ultramarine",
            "acid yellow figure on a muddy violet ground",
            "black and white with one slash of orange",
            "dark green ground, blood red and bone white",
        ],
        "composition": [
            "figure fills the whole canvas, upside down",
            "large canvas, figure off-center, empty corners",
            "upside-down landscape horizon at the top",
            "figure cut by the edges of the canvas",
            "rough outline, background left as bare gesso",
        ],
        "influence": [
            "in the spirit of 1970s German neo-expressionism",
            "echoing Georg Baselitz's upside-down paintings",
            "German expressionist painting",
        ],
    },
    "mirror": {
        "subject": [
            "a close-up of a distorted face, eyes looking straight out",
            "a face pressed against glass, features flattened",
            "a stretched face in a warped mirror, mouth half open",
            "a face half dissolved into darkness, one eye lit",
            "a face seen through a phone screen, stretched and smeared",
            "two faces overlapping into one, slightly out of register",
            "a face reflected in a dark window, doubled",
        ],
        "marks": [
            "soft smeared oil glazes, blurred edges",
            "wiped and smudged paint, features dragged sideways",
            "fine scumbled skin, harsh highlights",
            "wet blended paint, a thumb smear across the eyes",
            "thin translucent layers over a dark ground",
        ],
        "palette": [
            "near black background, pale skin in a narrow column of light",
            "deep blue darkness, cold white light on the face",
            "warm sodium light on the face, black surroundings",
            "dark umber, single shaft of white light",
            "black and violet shadows, a cold blue glow on skin",
        ],
        "composition": [
            "tight intimate close-up, face fills the frame",
            "vertical column of light down the center, darkness around",
            "face lit from below like a screen glow",
            "off-center face, most of the canvas in shadow",
            "extreme close-up of eyes and nose, cropped",
        ],
        "influence": [
            "chiaroscuro portrait painting",
            "intimate night portrait, old master lighting",
            "echoing Francis Bacon's self-portraits",
        ],
    },
    "void": {
        "subject": [
            "a single faint human form barely visible",
            "a faint pale hand emerging from darkness",
            "a dim small figure standing far away",
            "a faint empty chair",
            "the faint outline of a head turned away",
            "a dim glowing doorway with a shape inside",
            "a faint silhouette of a body lying down",
        ],
        "marks": [
            "thin dark glazes, almost no detail",
            "barely visible brushwork in black on black",
            "soft dry brush, faint scratched lines",
            "very low contrast, smoky haze",
        ],
        "palette": [
            "near black, deep charcoal, tiny touch of grey",
            "black with a very faint blue glow",
            "black and deepest brown, one dim warm light",
            "near black with a faint violet tint",
        ],
        "composition": [
            "vast empty dark space, form small in the center",
            "minimal composition, mostly empty black",
            "form at the lower edge, darkness above",
            "single faint vertical shape in emptiness",
        ],
        "influence": [
            "dark minimal painting",
            "tenebrist painting, almost total darkness",
        ],
    },
}

THEME_CHANCE = 0.5      # how often a theme detail is added
INFLUENCE_CHANCE = 0.35  # how often an influence phrase is added
# The void and mirror hooks stay quieter: fewer theme details.
THEME_CHANCE_BY_HOOK = {"void": 0.2, "mirror": 0.35}


def build_prompt(hook, rng=None):
    """Return (prompt, negative_prompt, parts) for one hook."""
    rng = rng or random
    if hook not in HOOK_PARTS:
        raise ValueError("unknown hook %r (expected one of %s)" % (hook, ", ".join(HOOKS)))
    p = HOOK_PARTS[hook]
    parts = {
        "subject": rng.choice(p["subject"]),
        "marks": rng.choice(p["marks"]),
        "palette": rng.choice(p["palette"]),
        "composition": rng.choice(p["composition"]),
    }
    pieces = [parts["subject"], parts["marks"], parts["palette"], parts["composition"]]
    if rng.random() < THEME_CHANCE_BY_HOOK.get(hook, THEME_CHANCE):
        parts["theme"] = rng.choice(THEMES)
        pieces.append(parts["theme"])
    pieces.append(p.get("style", COMMON_STYLE))
    if p.get("influence") and rng.random() < INFLUENCE_CHANCE:
        parts["influence"] = rng.choice(p["influence"])
        pieces.append(parts["influence"])
    return ", ".join(pieces), NEGATIVE, parts


if __name__ == "__main__":
    # python3 prompts.py  -> prints two sample prompts per hook
    for h in HOOKS:
        for _ in range(2):
            print("[%s] %s\n" % (h, build_prompt(h)[0]))
