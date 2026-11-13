"""Behavioural features -> rough OCEAN estimates with honest confidence.

This is theatre-grade inference. Every single cue below correlates with a
trait at roughly r = .1 to .3 in the literature (see RESEARCH.md), which is
useless for diagnosing one person. Extraversion leaks most, Openness shows in
taste and exploration, Conscientiousness, Agreeableness and Neuroticism are
close to guesswork from a minute of behaviour. The confidence caps below say
so, and the reveal tells the visitor.

Method (a small, legible cousin of the likes-to-traits regressions the
myPersonality / Cambridge Analytica pipeline used): each feature is a z-like
value in [-1, 1]; each has a weight per trait and a reliability. A trait score
is a shrunk weighted average around 0.5; confidence grows with evidence mass.
"""

import math

TRAITS = ("O", "C", "E", "A", "N")
TRAIT_NAMES = {
    "O": "Openness", "C": "Conscientiousness", "E": "Extraversion",
    "A": "Agreeableness", "N": "Neuroticism",
}

# feature: (reliability, {trait: weight}). Signs follow the research notes;
# sizes are dramaturgical, tuned so that a lively visitor reads as E+ in ~20 s.
WEIGHTS = {
    "pace":          (0.3, {"E": 0.3, "C": 0.3, "O": 0.1, "N": -0.2}),
    "closeness":     (0.5, {"E": 0.5, "N": -0.4, "O": 0.2, "A": -0.1}),
    "approach_time": (0.4, {"E": 0.3, "O": 0.2, "N": -0.3}),
    "motion":        (0.6, {"E": 0.6, "C": -0.2, "N": 0.1}),
    "burstiness":    (0.3, {"N": 0.5, "C": -0.3}),
    "roaming":       (0.4, {"O": 0.5, "E": 0.2}),
    "gaze":          (0.4, {"E": 0.4, "A": 0.3, "N": -0.3, "O": 0.1}),
    "dwell":         (0.5, {"O": 0.5, "C": -0.1}),
    "voice":         (0.8, {"E": 0.8, "A": 0.1}),
    "loudness":      (0.5, {"E": 0.5, "A": -0.1}),
    "touch_rate":    (0.4, {"E": 0.3, "O": 0.3, "C": -0.1}),
    "touch_variety": (0.4, {"O": 0.6, "C": -0.2}),
    "hold_ratio":    (0.3, {"C": 0.3, "N": 0.2, "E": -0.2}),
    "choice_speed":  (0.3, {"C": -0.4, "N": 0.2, "E": 0.2}),
    "shake":         (0.3, {"N": 0.4, "E": 0.2, "C": -0.2}),
    "typing":        (0.4, {"E": 0.4, "O": 0.3, "A": 0.2}),
}
CHOICE_RELIABILITY = 0.6

# How sure we are ever allowed to sound about each trait.
CONFIDENCE_CAP = {"E": 0.85, "O": 0.75, "C": 0.55, "A": 0.5, "N": 0.5}
PRIOR_MASS = 0.6     # pulls scores toward 0.5 while evidence is thin
OVERALL_SCALE = 2.5  # evidence mass for ~63% overall confidence


def estimate(summary, choices=(), prompts=None):
    """summary: {feature: (value, evidence, raw)} from Features.summary().
    choices: [(prompt_id, option, latency_ms)]. prompts: {id: prompt dict}.

    Returns (ocean {t: 0..1}, trait_conf {t: 0..1}, overall_conf, evidence)
    where evidence is a list of (abs contribution, trait, feature, raw, sign)
    sorted strongest first, used by the reveal.
    """
    num = dict.fromkeys(TRAITS, 0.0)
    mass = dict.fromkeys(TRAITS, 0.0)
    evidence = []
    for feat, (value, ev, raw) in summary.items():
        if feat not in WEIGHTS:
            continue
        rel, weights = WEIGHTS[feat]
        for t, w in weights.items():
            m = abs(w) * ev * rel
            c = value * w * ev * rel
            num[t] += c
            mass[t] += m
            evidence.append((abs(c), t, feat, raw, 1 if c >= 0 else -1))
    prompts = prompts or {}
    for pid, option, _lat in choices:
        p = prompts.get(pid)
        if not p or option not in p["options"]:
            continue
        nudges = p["traits"][p["options"].index(option)]
        for t, w in nudges.items():
            c = w * CHOICE_RELIABILITY
            num[t] += c
            mass[t] += abs(c)
            evidence.append((abs(c), t, "choice:" + pid, option, 1 if c >= 0 else -1))

    ocean, conf = {}, {}
    for t in TRAITS:
        ocean[t] = round(0.5 + 0.5 * math.tanh(1.6 * num[t] / (mass[t] + PRIOR_MASS)), 3)
        conf[t] = round(CONFIDENCE_CAP[t] * (1.0 - math.exp(-mass[t] / 0.8)), 3)
    total = sum(mass.values())
    overall = round(1.0 - math.exp(-total / OVERALL_SCALE), 3)
    evidence.sort(reverse=True)
    return ocean, conf, overall, evidence


# Segment labels, the way an ad platform names an audience. Picked from the
# two most extreme traits. Deliberately cold.
LABELS = {
    ("E", 1): "The Performer", ("E", -1): "The Lurker",
    ("O", 1): "The Seeker", ("O", -1): "The Literalist",
    ("C", 1): "The Auditor", ("C", -1): "The Drifter",
    ("A", 1): "The Pleaser", ("A", -1): "The Contrarian",
    ("N", 1): "The Exposed Nerve", ("N", -1): "The Cold Surface",
}


def segment(ocean, conf):
    ranked = sorted(TRAITS, key=lambda t: abs(ocean[t] - 0.5) * (0.3 + conf[t]),
                    reverse=True)
    t1 = ranked[0]
    s1 = 1 if ocean[t1] >= 0.5 else -1
    return LABELS[(t1, s1)], t1, s1
