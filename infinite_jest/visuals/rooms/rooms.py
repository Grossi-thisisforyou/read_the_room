"""Haunted rooms: prompts for the machine's dreamt interiors.

A second strand of generated pictures, next to the colour-field abstractions:
photographic, empty, ordinary rooms that feel as if someone has just left, or
has not quite left. Realistic, not painted. No one identifiable is ever in
them: at most a blur, a shadow, a shape under a sheet, a silhouette behind
frosted glass, a stain that almost looks like a face.

Each prompt is built from five parts, most important first, because SD-Turbo
only reads the first ~75 word-pieces:

    room        the place (ordinary, a little out of time)
    haunt       what is wrong with it (an absence, a trace, a presence)
    light       where the light comes from
    camera      what kind of photograph it is
    palette     the colour of the night, named like visuals/palettes.py

The parts are tags in the sidecar .json (kind: room, room, haunt, light,
camera, palette), so the show can pick, e.g. "a sodium room with a presence".

Standing rules: no artist is named or quoted; no crowns, skulls or (c) marks;
no faces. `python3 rooms.py` prints samples, `--stats` counts combinations.
"""
import hashlib
import random

PROMPT_VERSION = 1
KIND = "room"

# (tag, phrase). Keep phrases short and concrete: the model draws nouns, not moods.
ROOMS = [
    ("bedroom", "an empty childhood bedroom, unmade single bed, an old television showing static"),
    ("livingroom", "a 1990s living room, sofa under clear plastic, family photos turned to the wall"),
    ("corridor", "a long hotel corridor, patterned carpet, every door closed but one"),
    ("motel", "a motel room, two beds made tight, a bedside lamp left on"),
    ("hospital", "a hospital corridor at night, an empty wheelchair against the wall"),
    ("pool", "an indoor swimming pool after closing, still black water, wet tiles"),
    ("classroom", "a school classroom, chairs upside down on the desks"),
    ("kitchen", "a kitchen at four in the morning, the fridge door open, its light on the floor"),
    ("stairwell", "a narrow concrete stairwell going down into darkness"),
    ("laundromat", "a laundromat at night, rows of machines, one drum still turning"),
    ("waiting", "an empty waiting room, rows of plastic chairs, a number display"),
    ("office", "an open-plan office after hours, monitors still glowing on empty desks"),
    ("bathroom", "a tiled bathroom, fogged mirror, the bath full and still"),
    ("archive", "a basement archive, metal shelves of boxes and old files"),
    ("servers", "a small windowless room of humming servers, one office chair"),
    ("seminar", "a seminar room with black curtains, a projector beam on an empty wall"),
    ("dancefloor", "an empty club dance floor at closing, smoke hanging, one light rig"),
    ("dining", "a dining table set for six, food untouched, chairs pushed back"),
    ("nursery", "a nursery at night, an empty cot, a mobile turning slowly"),
    ("hall", "a community hall, folding chairs in a circle, one chair empty in the middle"),
    ("garage", "an underground parking level at night, one car with its door open"),
    ("elevator", "inside an old elevator, doors half open onto darkness"),
    ("studio", "a photo studio, grey backdrop paper, an empty stool under a softbox"),
    ("locker", "a gym locker room, one locker hanging open"),
    ("tvroom", "a dark living room lit only by a television, an armchair facing it"),
    ("parlour", "an old sitting room, lace doilies, a clock that has stopped"),
    ("gallery", "a museum gallery at night, empty picture frames on the walls"),
    ("train", "an empty train carriage at night, windows black"),
    ("attic", "an attic under the roof, one small window, a rocking chair"),
    ("landing", "an apartment block landing, a door ajar, light under it"),
]

# Fine rooms: calm, expensive modernist interiors, the same haunting. Described in plain
# words only (open plan, glass walls, stone, steel, high-tech structure); no names.
FINE_ROOMS = [
    ("pavilion", "a glass pavilion at night, floor-to-ceiling glass walls, travertine floor, chrome cross-shaped columns"),
    ("onyxwall", "a minimalist open-plan room, a freestanding wall of polished onyx, one leather lounge chair"),
    ("glasshouse", "a glass house in a dark forest, open plan, thin white steel frame, a low sofa"),
    ("reflecting", "a walled courtyard with a still reflecting pool, marble walls, glass doors"),
    ("lobby", "a vast marble office lobby, black steel mullions, a single bench"),
    ("library", "a severe modernist library, long oak tables, glass walls, rows of lamps"),
    ("atrium", "a towering high-tech glass atrium, exposed white steel structure, escalators"),
    ("canopy", "a huge glass-roofed courtyard, a curved lattice canopy of steel and glass"),
    ("glasstower", "the top floor of a curved glass tower, diamond-pattern steel frame, city lights below"),
    ("terminal", "an empty airport terminal, a light steel roof on slender tree-like columns"),
    ("hangar", "a sleek white high-tech hall, exposed steel trusses, polished grey floor"),
    ("penthouse", "a penthouse with glass walls, white terrazzo, a grand piano under a dust sheet"),
]
FINE_SHARE = 0.4               # how often the room is a fine one rather than a worn one
FINE = {r[0] for r in FINE_ROOMS}

# What is wrong. "presence" ones carry an unidentifiable someone; the others are traces.
# An optional 4th item limits a haunt to rooms where it makes sense.
HAUNTS = [
    ("door", "trace", "a door left ajar onto pure black"),
    ("chair", "trace", "a chair pulled out as if someone just stood up"),
    ("footprints", "trace", "wet footprints crossing the floor"),
    ("curtain", "trace", "a curtain lifting with no window open"),
    ("phone", "trace", "a telephone off the hook, cord hanging"),
    ("cup", "trace", "a cup still steaming on the table", ("kitchen", "livingroom", "dining", "office", "parlour", "tvroom", "motel", "waiting")),
    ("turned", "trace", "every chair turned to face the wall", ("classroom", "waiting", "hall", "dining", "seminar", "office", "library", "lobby", "terminal")),
    ("handprint", "trace", "a faint handprint on the glass"),
    ("dust", "trace", "dust turning in a single beam of light"),
    ("bed", "trace", "a hollow in the bed as if someone just got up", ("bedroom", "motel", "nursery", "attic", "glasshouse")),
    ("stain", "trace", "a damp stain on the wallpaper shaped almost like a face"),
    ("sheet", "presence", "a tall shape standing under a white sheet"),
    ("blur", "presence", "a motion-blurred dark figure crossing, seen from behind, no face"),
    ("glass", "presence", "a dark silhouette behind frosted glass"),
    ("shadow", "presence", "a tall shadow on the wall with no one to cast it"),
    ("coat", "presence", "a long coat hanging on the door like a person"),
    ("far", "presence", "a small faceless figure far away at the end, out of focus"),
]
PRESENCE_SHARE = 0.35          # how often the haunt is a presence rather than a trace

LIGHTS = [
    ("bulb", "lit by one bare bulb"),
    ("fluorescent", "cold fluorescent light, one tube flickering"),
    ("blinds", "streetlight through venetian blinds"),
    ("moon", "blue moonlight through net curtains"),
    ("exit", "lit only by a red exit sign"),
    ("tungsten", "one dim tungsten lamp, deep shadows"),
    ("emergency", "green emergency lighting"),
    ("screen", "the cold glow of a screen on the ceiling"),
    ("flash", "harsh direct flash, black behind"),
]

CAMERAS = [
    ("film", "35mm film photograph, heavy grain"),
    ("disposable", "disposable camera flash photo, slightly tilted"),
    ("cctv", "security camera still, high corner angle, low resolution"),
    ("longexp", "long exposure photograph, slight motion blur"),
    ("polaroid", "faded instant photo, soft focus"),
    ("documentary", "documentary photograph, wide angle, still"),
    ("architecture", "architectural photograph, symmetrical, wide lens"),
    ("night", "night photograph, underexposed, high iso noise"),
]

# Keys are visuals/palettes.py names, so the grade in grade.py and the show agree.
PALETTES = {
    "sodium": ["sodium orange light on black shadows", "amber and deep brown, black corners"],
    "bruise": ["violet and blue-black, cold pale highlights", "deep indigo shadows, mauve light"],
    "teal": ["cold teal shadows, warm peach highlights", "deep green-blue darkness, warm pale highlights"],
    "oxblood": ["dried-blood red light, near black shadows", "dark maroon tones, cream highlights"],
    "abyss": ["near black with deep ultramarine blue", "blue-black, one cold grey glint"],
    "abyss_green": ["near black, deep bottle green haze", "murky green-black, pale highlights"],
    "lilac": ["dusky lilac haze, pale peach light", "soft violet-grey dusk"],
    "rose": ["deep pink haze, crimson shadows", "rose light, maroon darkness"],
    "ash": ["black and white, charcoal shadows", "monochrome, deep grey, chalky light"],
}
PALETTE_WEIGHTS = {"sodium": 4, "bruise": 3, "teal": 3, "oxblood": 2, "abyss": 2,
                   "abyss_green": 2, "lilac": 1, "rose": 1, "ash": 1}

# The Pi's painter uses no guidance (cfg 1), so this is stored for other models only.
NEGATIVE = ("painting, illustration, drawing, brush strokes, cartoon, anime, 3d render, "
            "text, watermark, logo, signature, face, portrait, crowd, skull, crown, "
            "bright daylight, cheerful, clean")

MAX_WORDS = 69


class Deck:
    """Deals each list in shuffled rounds so the same room or light does not come back
    until the rest have had a turn; remembers full combinations it has dealt."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.piles = {}
        self.seen = set()

    def deal(self, key, items):
        pile = self.piles.get(key)
        if not pile:
            pile = list(range(len(items)))
            self.rng.shuffle(pile)
            self.piles[key] = pile
        return items[pile.pop()]


def _palette(rng, deck, forced=None):
    if forced:
        name = forced
    else:
        keys = list(PALETTE_WEIGHTS)
        name = rng.choices(keys, weights=[PALETTE_WEIGHTS[k] for k in keys])[0]
    return name, (deck.deal("pal:" + name, PALETTES[name]) if deck else rng.choice(PALETTES[name]))


def make(rng=None, deck=None, palette=None, presence=None, fine=None, max_tries=25):
    """One prompt as a dict: prompt, negative, tags, tag_list, signature, prompt_version."""
    rng = rng or (deck.rng if deck else random.Random())
    deal = (lambda k, items: deck.deal(k, items)) if deck else (lambda k, items: rng.choice(items))
    for _ in range(max_tries):
        is_fine = fine if fine is not None else (rng.random() < FINE_SHARE)
        room = deal("room:fine", FINE_ROOMS) if is_fine else deal("room", ROOMS)
        want = presence if presence is not None else (rng.random() < PRESENCE_SHARE)
        fits = [h for h in HAUNTS if (h[1] == "presence") == want
                and (len(h) < 4 or room[0] in h[3])]
        haunt = deal("haunt:%s:%s" % (want, room[0]), fits)
        light = deal("light", LIGHTS)
        camera = deal("camera", CAMERAS)
        pal_name, pal_phrase = _palette(rng, deck, palette)
        sig = hashlib.sha1("|".join((room[0], haunt[0], light[0], camera[0], pal_name))
                           .encode()).hexdigest()[:12]
        if not deck or sig not in deck.seen:
            break
    if deck:
        deck.seen.add(sig)
    prompt = ", ".join((room[1], haunt[2], light[1], camera[1], pal_phrase,
                        "empty, eerie, quiet, photorealistic"))
    words = prompt.split()
    if len(words) > MAX_WORDS:
        prompt = " ".join(words[:MAX_WORDS])
    tags = {"kind": KIND, "room": room[0], "style": "fine" if room[0] in FINE else "worn", "haunt": haunt[0], "presence": haunt[1] == "presence",
            "light": light[0], "camera": camera[0], "palette": pal_name}
    return {
        "prompt": prompt,
        "negative": NEGATIVE,
        "tags": tags,
        "tag_list": ["%s:%s" % (k, v) for k, v in tags.items()],
        "signature": sig,
        "prompt_version": PROMPT_VERSION,
    }


def combinations():
    return (len(ROOMS) + len(FINE_ROOMS)) * len(HAUNTS) * len(LIGHTS) * len(CAMERAS) * sum(len(v) for v in PALETTES.values())


if __name__ == "__main__":
    import sys
    if "--stats" in sys.argv:
        print("about %s combinations" % format(combinations(), ","))
        sys.exit(0)
    d = Deck(random.Random(7))
    for _ in range(8):
        r = make(deck=d)
        print("%-40s %2d words\n  %s\n" % (" ".join(r["tag_list"][1:]), len(r["prompt"].split()), r["prompt"]))
