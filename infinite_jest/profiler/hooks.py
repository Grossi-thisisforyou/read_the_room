"""Hooks and the adaptation loop: profile -> pick the hook -> test -> adapt.

A hook is a scene in the show engine (names agreed with "Build the Pi show
engine"), plus sound and text parameters tailored to the trait mix, the way
Matz et al. (2017) tailored ads to extraverts vs introverts.

The loop is a Thompson-sampling bandit. Each hook starts with a Beta prior set
by how well it fits the current OCEAN estimate (the profile is the prior); the
engagement the visitor actually shows while a hook runs is the reward (the
A/B test). As evidence comes in, what the person does outweighs what we
guessed. That is the Cambridge Analytica "test and learn" loop, per person,
per second.
"""

import random

# Trait affinities (O, C, E, A, N) per hook; positive = this trait pole is
# expected to be held by the scene. Design choices, not data.
HOOKS = {
    # Bacon: caged, smeared, screaming flesh. Anxiety, enclosure, intensity.
    "flesh":    {"O": 0.5, "C": -0.2, "E": 0.0, "A": -0.3, "N": 0.8},
    # Basquiat: scrawled words, crowns, crossed-out names, collage energy.
    "scrawl":   {"O": 0.7, "C": -0.6, "E": 0.8, "A": 0.0, "N": 0.0},
    # Baselitz: upside-down heavy figures. Contrarian, cerebral.
    "inverted": {"O": 0.8, "C": 0.0, "E": -0.2, "A": -0.5, "N": 0.2},
    # The visitor's own image, distorted. Self-focus, being seen.
    "mirror":   {"O": 0.0, "C": 0.1, "E": 0.6, "A": 0.5, "N": 0.4},
    # Near-black, slow, a single drone. For the ones who keep their distance.
    "void":     {"O": 0.2, "C": 0.7, "E": -0.8, "A": 0.2, "N": -0.2},
}

# Tailored lines (the "message" in message tailoring), one pool per trait pole.
LINES = {
    ("E", 1): ["everyone can see you", "louder", "this room is yours"],
    ("E", -1): ["no one else is here", "you can stay at the edge", "quiet now"],
    ("O", 1): ["nobody else has seen this version", "look again, it changed",
               "this was made from you"],
    ("O", -1): ["this is exactly what it looks like", "nothing to understand"],
    ("C", 1): ["this will take forty seconds", "everything is in order",
               "you are being measured precisely"],
    ("C", -1): ["there is no plan", "wander", "lose the thread"],
    ("A", 1): ["we made this for you", "thank you for staying", "you are kind to look"],
    ("A", -1): ["you don't have to like this", "push back", "nobody asked you"],
    ("N", 1): ["you are safe here. stay.", "something is behind you", "it's okay to look"],
    ("N", -1): ["nothing touches you", "colder", "you are unbothered. we noticed."],
}


def affinity(hook, ocean):
    """0..1 fit of a hook to an OCEAN estimate."""
    vec = HOOKS[hook]
    dot = sum(vec[t] * (ocean[t] - 0.5) * 2.0 for t in vec)
    norm = sum(abs(v) for v in vec.values()) or 1.0
    return max(0.0, min(1.0, 0.5 + 0.5 * dot / norm * 1.5))


def params(hook, ocean, conf, rng):
    """Sound / intensity / text tailoring for the chosen hook."""
    e, n, o = ocean["E"], ocean["N"], ocean["O"]
    bpm = int(round(118 + 22 * e))                 # 118..140, darker = slower
    if n > 0.6:
        sound = "noise"
    elif e > 0.6:
        sound = "kick"
    elif hook in ("mirror",) and e >= 0.45:
        sound = "voice"
    else:
        sound = "drone"
    intensity = round(min(1.0, 0.3 + 0.4 * o + 0.3 * n), 3)
    # Text from the most confidently extreme trait.
    best = max(ocean, key=lambda t: abs(ocean[t] - 0.5) * (0.3 + conf.get(t, 0)))
    pole = 1 if ocean[best] >= 0.5 else -1
    line = rng.choice(LINES[(best, pole)])
    return {"intensity": intensity, "tempo_bpm": bpm, "sound": sound,
            "prompt_style": TRAIT_STYLE[(best, pole)], "line": line}


TRAIT_STYLE = {
    ("E", 1): "social", ("E", -1): "solitary", ("O", 1): "novel",
    ("O", -1): "plain", ("C", 1): "orderly", ("C", -1): "loose",
    ("A", 1): "warm", ("A", -1): "blunt", ("N", 1): "reassuring",
    ("N", -1): "cold",
}


class HookBandit:
    """Thompson sampling over HOOKS with a trait-based prior."""

    def __init__(self, seed=None, prior_strength=4.0, min_dwell=8.0, trial_weight=4.0):
        self.trial_weight = trial_weight  # one 8 s trial counts as this many pulls
        self.rng = random.Random(seed)
        self.prior_strength = prior_strength
        self.min_dwell = min_dwell
        self.reset()

    def reset(self):
        self.wins = dict.fromkeys(HOOKS, 0.0)
        self.trials = dict.fromkeys(HOOKS, 0.0)
        self.current = None
        self.since = None
        self.reward_sum = 0.0
        self.reward_n = 0
        self.history = []  # (hook, seconds, mean engagement)
        self.all_sum = 0.0
        self.all_n = 0

    def observe(self, engagement):
        """Feed the current engagement (0..1) while self.current runs."""
        if self.current is not None:
            self.reward_sum += engagement
            self.reward_n += 1
        self.all_sum += engagement
        self.all_n += 1

    def _close_trial(self, ts):
        if self.current is None or self.reward_n == 0:
            return
        r = self.reward_sum / self.reward_n
        # Reward is relative to this visitor's own baseline: a calm person is
        # never as "engaged" as a lively one, so compare them to themselves.
        base = self.all_sum / self.all_n if self.all_n else 0.5
        rel = max(0.0, min(1.0, 0.5 + 2.5 * (r - base)))
        self.wins[self.current] += rel * self.trial_weight
        self.trials[self.current] += self.trial_weight
        self.history.append((self.current, round(ts - self.since, 1), round(r, 3)))

    def choose(self, ocean, confidence, ts):
        """Return the hook to run now. Holds a hook for min_dwell seconds."""
        if self.current is not None and ts - self.since < self.min_dwell:
            return self.current
        self._close_trial(ts)
        strength = self.prior_strength * confidence
        best, best_draw = None, -1.0
        for h in HOOKS:
            a = 1.0 + strength * affinity(h, ocean) + self.wins[h]
            b = 1.0 + strength * (1.0 - affinity(h, ocean)) + (self.trials[h] - self.wins[h])
            draw = self.rng.betavariate(a, b)
            if draw > best_draw:
                best, best_draw = h, draw
        if best != self.current:
            self.current = best
        self.since = ts
        self.reward_sum = 0.0
        self.reward_n = 0
        return best

    def finish(self, ts):
        self._close_trial(ts)
        self.current = None

    def ranking(self):
        """Hooks by observed mean engagement (for the reveal)."""
        seen = [(self.wins[h] / self.trials[h], h) for h in HOOKS if self.trials[h]]
        return [h for _, h in sorted(seen, reverse=True)]
