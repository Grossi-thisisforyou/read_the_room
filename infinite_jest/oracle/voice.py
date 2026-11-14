"""The piece's voice: prompts for the local model, and a guard on its output.

What goes into the model: OCEAN numbers, confidences, the segment label, the
hook name, and plain descriptions of behaviour that the profiler already shows
on the wall ("you held the device 37% of the time"). Never frames, audio,
typed text or visitor ids. Whatever comes back goes through clean_*(); if one
line breaks a rule, the whole answer is dropped and the template text stays.
"""

import re

from infinite_jest.profiler.ocean import TRAIT_NAMES
from infinite_jest.profiler.reveal import DESCRIBE

VOICE = (
    "You are the voice of INFINITE JEST, an art installation about dark data and "
    "custom-made intimacy. It profiles one visitor at a time, the way Cambridge "
    "Analytica profiled voters, and then confesses it. Style: lowercase, short, "
    "cold and intimate at once, a whisper from a machine in a dark techno club. "
    "Second person. No emojis, no hashtags, no quotation marks, no exclamation marks. "
    "Describe only behaviour you are given. Never guess or mention age, gender, race, "
    "ethnicity, religion, health, sexuality, body, clothing, emotions or a name. "
    "Never name any artist, painter, artwork or art movement. "
    "Never diagnose, advise or threaten."
)

HOOK_IMAGES = {
    # Descriptions only. The visual sources stay hidden from visitors, so the
    # model is never told them and the guard below drops them if it guesses.
    "flesh": "smeared caged raw flesh, a mouth open",
    "scrawl": "frantic handwriting and crossed-out data",
    "inverted": "heavy figures hanging upside down",
    "mirror": "the visitor's own distorted silhouette",
    "void": "near black, one slow pulse",
}


def _scores(p):
    ocean, conf = p.get("ocean", {}), p.get("trait_confidence", {})
    return "; ".join("{} {:.2f} (conf {:.0%})".format(TRAIT_NAMES[t], ocean[t], conf.get(t, 0))
                     for t in ("O", "C", "E", "A", "N") if t in ocean)


def observed(profile, n=4):
    """Plain-language behaviour lines from the profile's evidence + features."""
    feats = profile.get("features", {})
    out, seen = [], set()
    for ev in profile.get("evidence", []):
        f = ev.split(" -> ")[0]
        if f in seen:
            continue
        seen.add(f)
        if f in DESCRIBE and f in feats:
            out.append(DESCRIBE[f].format(raw=feats[f]))
        elif f.startswith("choice:"):
            out.append("you answered the question " + f.split(":", 1)[1])
        if len(out) >= n:
            break
    return out


def words_messages(profile):
    """One call: a phone line (<= 8 words) and three wall fragments."""
    user = (
        "Visitor profile: {s}. Segment: {seg}. Observed: {obs}. Scene now showing: {img}. "
        "Tone: {tone}.\n"
        "Line 1: one sentence of at most 8 words for the phone screen that keeps this person here.\n"
        "Lines 2-4: three UPPERCASE fragments of 2-3 words about their behaviour, "
        "like a surveillance log.\nOutput only the 4 lines."
    ).format(s=_scores(profile), seg=profile.get("segment", "unread"),
             obs="; ".join(observed(profile, 3)) or "almost nothing yet",
             img=HOOK_IMAGES.get(profile.get("hook"), profile.get("hook", "")),
             tone=profile.get("hook_params", {}).get("prompt_style", "cold"))
    return [{"role": "system", "content": VOICE}, {"role": "user", "content": user}]


def dossier_messages(profile):
    """The confession, prepared early so it is ready at release."""
    user = (
        "Observed: {obs}. Scores: {s}. Segment: {seg}. Scene that held them: {hook}. "
        "Machine confidence {c:.0%}; real accuracy of this inference is about r = .2.\n"
        "Write 4 lines, max 10 words each: what it noticed, what it concluded, "
        "that it chose the scene because it worked, that it is mostly a guess. "
        "Output only the 4 lines."
    ).format(obs="; ".join(observed(profile)) or "very little", s=_scores(profile),
             seg=profile.get("segment", "unread"), hook=profile.get("hook", "void"),
             c=profile.get("confidence", 0.0))
    return [{"role": "system", "content": VOICE}, {"role": "user", "content": user}]


_FORBIDDEN = re.compile(
    r"\b(age|aged|old|young|years?|man|men|woman|women|male|female|girl|boy|gay|straight|"
    r"black|white|asian|latin\w*|jew\w*|muslim|christian|religio\w*|race|racial|ethnic\w*|"
    r"disab\w*|illness|sick|depress\w*|disorder|fat|thin|weight|kill|die|dead|suicid\w*|"
    r"hurt you|sad|happy|angry|afraid|scared|lonely|"
    r"bacon|basquiat|baselitz|francis|crowns?|samo|skulls?|kings?|painter|painting|(neo-?)?expressionis\w*)\b", re.I)


def _split(text, max_words):
    lines = []
    for raw in (text or "").splitlines():
        line = re.sub(r"^[\s\-\*\d\.\):]+", "", raw).strip().strip('"\'').strip()
        line = re.sub(r"^(line \d+:?\s*)", "", line, flags=re.I)
        if not line:
            continue
        if _FORBIDDEN.search(line) or "\u00a9" in line or "(c)" in line.lower() or len(line.split()) > max_words:
            return None
        lines.append(line)
    return lines or None


def clean_words(text):
    """-> (phone_text, words[]) or None."""
    lines = _split(text, 10)
    if not lines or len(lines) < 2:
        return None
    phone = lines[0].lower().rstrip(".")
    words = [l.upper().rstrip(".") for l in lines[1:4] if len(l.split()) <= 4]
    return (phone, words) if words else None


def clean_dossier(text):
    lines = _split(text, 14)
    if not lines:
        return None
    lines = [l.lower() for l in lines[:5]]
    lines.append("this profile is being deleted now.")
    return lines
