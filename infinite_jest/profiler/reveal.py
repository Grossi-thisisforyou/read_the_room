"""The reveal: tell the visitor what was inferred, from what, and how badly.

This is the artistic payoff. The lines are short so the engine can type them
out one by one on the projection. The last lines always say the profile is
being deleted and how weak the inference really is.
"""

from .ocean import TRAIT_NAMES, segment

# How each feature is described to the visitor: (template, unit formatter).
DESCRIBE = {
    "pace": "you came in at {raw:.2f} widths of the frame per second",
    "closeness": "you came within {raw:.0%} of the frame",
    "approach_time": "you took {raw:.0f} seconds to come close",
    "motion": "your body moved at {raw:.0%} of what we can measure",
    "burstiness": "you moved in bursts (variation {raw:.2f})",
    "roaming": "you covered {raw:.0%} of the room's width",
    "gaze": "you looked at the eye {raw:.0%} of the time",
    "dwell": "you have stayed {raw:.0f} seconds",
    "voice": "you spoke {raw:.0%} of the time",
    "loudness": "your voice reached {raw:.0%} of full level",
    "touch_rate": "you touched the screen {raw:.1f} times a minute",
    "touch_variety": "you explored {raw:.0%} of the surface",
    "hold_ratio": "{raw:.0%} of your touches lingered",
    "choice_speed": "you answered in {raw:.1f} seconds on average",
    "shake": "your hands shook the device by {raw:.2f} g",
    "handled": "you held the device {raw:.0%} of the time",
    "tilt_range": "you turned it through {raw:.0f} degrees",
    "tilt_speed": "you turned it at {raw:.0f} degrees a second",
    "typing": "you typed {raw:.0f} characters (we kept only the count)",
}


# What visitors read for each scene. Internal hook names stay in code only.
SCENE_NAMES = {"flesh": "the wound", "scrawl": "the writing", "inverted": "the fall",
               "mirror": "the mirror", "void": "the dark"}


def _describe(feat, raw):
    if feat.startswith("choice:"):
        return 'you chose "{}"'.format(raw)
    tpl = DESCRIBE.get(feat)
    return tpl.format(raw=raw) if tpl else feat


def build(ocean, conf, overall, evidence, bandit_history, ranking, seconds):
    label, t1, s1 = segment(ocean, conf)
    lines = []
    seen = set()
    for _c, trait, feat, raw, sign in evidence:
        if feat in seen or len(seen) >= 4:
            continue
        seen.add(feat)
        direction = "more" if sign > 0 else "less"
        lines.append("{}. people like that score {} on {}.".format(
            _describe(feat, raw), direction, TRAIT_NAMES[trait]))
    for t in ("O", "C", "E", "A", "N"):
        lines.append("{} {:.2f}   (confidence {:.0%})".format(
            TRAIT_NAMES[t].upper(), ocean[t], conf[t]))
    lines.append("segment: {}".format(label.upper()))
    if ranking:
        best = ranking[0]
        held = [h for h in bandit_history if h[0] == best]
        lines.append("we tried {} scenes on you. {} held you best.".format(
            len(set(h[0] for h in bandit_history)), SCENE_NAMES.get(best, "one")))
        if held:
            lines.append("we chose it because it worked, not because it was true.")
    lines.append("the machine's confidence: {:.0%}.".format(overall))
    lines.append("its real accuracy: one minute of behaviour predicts personality at about r = .2.")
    lines.append("Cambridge Analytica sold numbers like these as mind reading.")
    lines.append("it is barely better than a guess. it still felt like it knew you.")
    lines.append("this profile is being deleted now.")
    return {"label": label, "lines": lines, "seconds": round(seconds, 1)}
