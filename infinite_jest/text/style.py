"""The style check: does a line sound like the room, and does it break a rule?

Used three ways:
- the corpus tests run every hand-written line through check();
- the oracle (local Qwen) runs every generated line through clean_words() /
  clean_dossier() and drops the whole answer if one line fails;
- the trial script (trial.py) reports how often the model passes.

Rules come from VOICE.md. Standard library only, Python 3.7+.
"""

import re
import unicodedata

# ---- hard rules: a hit drops the line --------------------------------------

_W = r"\b(?:{})\b"

FORBIDDEN = {
    # who the visitor is: never guessed, never mentioned
    "demographic": _W.format(
        r"age|aged|old|older|young|younger|years? old|teen\w*|kids?|child\w*|"
        r"man|men|woman|women|male|female|girls?|boys?|guys?|lady|ladies|gentlem[ae]n|"
        r"sir|madam|ma'am|he|she|him|her|his|hers|"
        r"gay|lesbian|queer|trans\w*|straight|bisexual|sexual\w*|"
        r"black|white|brown|asian|latin[oax]?|hispanic|african|european|american|"
        r"jew\w*|muslim\w*|christian\w*|hindu\w*|buddhis\w*|religio\w*|god|pray\w*|"
        r"race|racial|ethnic\w*|accent|foreign\w*|immigra\w*|nationality"),
    "health": _W.format(
        r"disab\w*|ill|illness|sick\w*|depress\w*|disorder\w*|adhd|autis\w*|"
        r"anxiety|anxious|panic\w*|trauma\w*|therap\w*|medic\w*|diagnos\w*|symptom\w*|"
        r"tremor\w*|pregnan\w*|drunk|sober|addict\w*|mental\w*|patient"),
    # inner states are guesses about the person, not behaviour
    "emotion": _W.format(
        r"happy|happiness|sad|sadness|angry|anger|afraid|scared|fear\w*|frighten\w*|"
        r"nervous|lonely|loneliness|alone|excited|bored|upset|worried|stress\w*|tense|"
        r"relaxed|calm|shy|insecure|ashamed|shame|guilt\w*|embarrass\w*|jealous|"
        r"joy\w*|love|loved|lover|hate|hatred|grief|crying|cry|tears?|smil\w*|"
        r"mood|moody|emotion\w*|neurotic\w*|safe") + r"|\byou(?:'re| are)? (?:feel\w*|seem\w*)\b|\byou felt\b",
    "body": r"\byour (?:face|skin|hair|eyes?|lips|mouth|body|weight|height|shape|legs?|arms?|"
            r"clothes|shirt|jacket|dress|shoes|glasses|tattoos?|voice sounds)\b|" + _W.format(
        r"beautiful|pretty|ugly|handsome|sexy|gorgeous|attractive|fat|thin|skinny|"
        r"weight|tall|wearing|dressed|outfit|makeup|bald|wrinkl\w*"),
    "insult": _W.format(
        r"stupid|idiot\w*|pathetic|weak|weakling|loser|worthless|boring|desperate|needy|"
        r"creepy|crazy|insane|freak\w*|dumb|lame|basic|easy|cheap date|ordinary|average person|"
        r"nobody cares|shut up|disgust\w*|gross|failure|coward\w*"),
    "violence": _W.format(
        r"kill\w*|die|dies|dying|dead|death|suicid\w*|murder\w*|blood\w*|weapon\w*|guns?|"
        r"knife|stab\w*|shoot\w*|bomb\w*|rape\w*|abuse\w*|hang|hangs|hanging|hanged|noose|flatlin\w*") + r"|\bhurt you\b",
    # the pictures' sources stay hidden
    "source": _W.format(
        r"bacon|basquiat|baselitz|francis|jean-michel|georg|samo|warhol|picasso|"
        r"crowns?|crowned|skulls?|cages?|caged|meat|carcass\w*|scream\w*|misspel\w*|copyright|trademark|painter\w*|painting\w*|"
        r"artists?|artwork\w*|museum|gallery|graffiti|"
        r"(?:neo-?)?expressionis\w*|figurative|art history|art movement") + r"|[©®™♛♔☠]|\(c\)",
    # a model slipping out of character
    "leak": r"\bas an ai\b|\blanguage model\b|\bi cannot\b|\bi can't help\b|\bi'm sorry\b|\bsorry\b|"
            r"\bassistant\b|\bvisitor profile\b|\bline \d\b|\boutput\b|\binstallation\b|\bprompt\b",
}

# soft rules: words that make the room sound like a greeting card
CLICHE = _W.format(
    r"soul\w*|journey|energy|energies|universe|cosmic|dream\w*|magic\w*|vibes?|essence|"
    r"tapestry|delve|embrace|unleash|realm|spirit\w*|heart\w*|destiny|amazing|"
    r"incredible|awesome|wonderful|unique|special|truly|deeply|indeed")

ALLOWED_CAPS = ("Cambridge Analytica", "AKTE")

LIMITS = {"log": 6, "whisper": 8, "confession": 14}

_FORBIDDEN_RE = {k: re.compile(v, re.I) for k, v in FORBIDDEN.items()}
_CLICHE_RE = re.compile(CLICHE, re.I)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿]")


def _words(line):
    return [w for w in re.split(r"\s+", line.strip()) if re.search(r"\w", w)]


def check(line, register=None, max_words=None):
    """Return a list of (rule, detail) problems. An empty list means the line passes.

    register: "log" | "whisper" | "confession" | None (only the hard rules).
    """
    problems = []
    if not line or not line.strip():
        return [("empty", "")]
    text = unicodedata.normalize("NFC", line.strip())

    for rule, rx in _FORBIDDEN_RE.items():
        m = rx.search(text)
        if m:
            problems.append((rule, m.group(0)))
    m = _CLICHE_RE.search(text)
    if m:
        problems.append(("cliche", m.group(0)))
    if "!" in text:
        problems.append(("punctuation", "!"))
    if re.search(r"[\"“”„«»]", text):
        problems.append(("punctuation", "quotation mark"))
    if "..." in text or "…" in text:
        problems.append(("punctuation", "ellipsis"))
    if "#" in text or "@" in text:
        problems.append(("punctuation", "hashtag or handle"))
    if _EMOJI.search(text):
        problems.append(("punctuation", "emoji"))

    n = len(_words(text))
    limit = max_words or LIMITS.get(register)
    if limit and n > limit:
        problems.append(("length", "{} words > {}".format(n, limit)))

    bare = text
    for ok in ALLOWED_CAPS:
        bare = bare.replace(ok, "")
    if register == "log":
        if bare != bare.upper():
            problems.append(("case", "the log is UPPERCASE"))
        if "?" in text:
            problems.append(("punctuation", "no questions in the log"))
        if re.search(r"\b(?:YOU|YOUR|I|ME|WE|US)\b", text):
            problems.append(("pronoun", "the log has no pronouns"))
    elif register in ("whisper", "confession"):
        if bare != bare.lower():
            problems.append(("case", "lowercase only"))
    if register == "whisper" and re.search(r"\b(?:we|we're|we've|we'll|our|ours)\b", text, re.I):
        problems.append(("pronoun", "the whisper says i, never we"))
    if register == "confession" and re.search(r"(?:^|\s)i(?:'m|'ll|'ve|'d)?\b", text):
        problems.append(("pronoun", "the confession says we, never i"))
    return problems


def ok(line, register=None, max_words=None):
    return not check(line, register, max_words)


# ---- cleaning model output ----------------------------------------------------

def _split_lines(text):
    out = []
    for raw in (text or "").splitlines():
        line = re.sub(r"^\s*(?:line\s*\d+\s*[:.)-]\s*|[-*•]\s*|\d+\s*[.):]\s*)", "", raw, flags=re.I)
        line = line.strip().strip("\"'“”").strip()
        if line:
            out.append(line)
    return out


def clean_words(text):
    """Model answer for the words call -> (phone_text, [WALL, FRAGMENTS]) or None.

    Line 1 becomes the phone whisper (lowercased, max 8 words), lines 2-4 the
    wall log (uppercased, max 4 words each). Any rule break drops everything.
    """
    lines = _split_lines(text)
    if len(lines) < 2:
        return None
    phone = lines[0].lower().rstrip(".").strip()
    if check(phone, "whisper"):
        return None
    words = []
    for l in lines[1:4]:
        frag = l.upper().rstrip(".").strip()
        if check(frag, "log", max_words=4):
            return None
        words.append(frag)
    return phone, words


def clean_dossier(text, closing="this profile is being deleted now."):
    """Model answer for the dossier call -> list of lines or None."""
    lines = [l.lower() for l in _split_lines(text)][:5]
    if not lines:
        return None
    for l in lines:
        if check(l.replace("cambridge analytica", "Cambridge Analytica"), "confession", max_words=14):
            return None
    if closing:
        lines.append(closing)
    return lines
