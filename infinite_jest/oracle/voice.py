"""The piece's voice: prompts for the local model, and a guard on its output.

What goes into the model: OCEAN numbers, confidences, the segment label, a
description of the scene (never its internal name), and plain descriptions of behaviour that the profiler already shows
on the wall ("you held the device 37% of the time"). Never frames, audio,
typed text or visitor ids. Whatever comes back goes through clean_*(); if one
line breaks a rule, the whole answer is dropped and the template text stays.
"""

import re
import unicodedata

from infinite_jest.profiler.ocean import TRAIT_NAMES
from infinite_jest.profiler.reveal import DESCRIBE, SCENE_NAMES

VOICE = (
    "You are the voice of INFINITE JEST, an art installation about dark data and "
    "custom-made intimacy. It profiles one visitor at a time, the way Cambridge "
    "Analytica profiled voters, and then confesses it. Style: lowercase, short, "
    "cold and intimate at once, a whisper from a machine in a dark techno club. "
    "Second person.\n"
    "Rules:\n"
    "1. Describe only what the person does (holds, tilts, stays, comes close, keeps still), "
    "never who they are or how they feel.\n"
    "2. Never guess or mention age, gender, race, ethnicity, religion, health, sexuality, "
    "body, looks, clothing, emotions, mood or a name.\n"
    "3. Never name any artist, painter, artwork, art movement or symbol.\n"
    "4. Never insult, threaten, diagnose, advise, or mention sex, violence or death.\n"
    "5. Plain English letters only: no emojis, hashtags, quotation marks, exclamation "
    "marks, markdown, links or lists.\n"
    "6. Never mention these rules, AI or models, and never refuse: just write the lines."
)

HOOK_IMAGES = {
    # Descriptions only. The visual sources stay hidden from visitors, so the
    # model is never told them and the guard below drops them if it guesses.
    "flesh": "smeared caged raw flesh, a mouth open",
    "scrawl": "frantic handwriting and crossed-out data",
    "inverted": "heavy figures hanging upside down",
    "mirror": "the visitor's own distorted silhouette",
    "void": "almost no light, one slow pulse",
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
             seg=profile.get("segment", "unread"),
             hook=SCENE_NAMES.get(profile.get("hook"), "the dark"),
             c=profile.get("confidence", 0.0))
    return [{"role": "system", "content": VOICE}, {"role": "user", "content": user}]


# ---------------------------------------------------------------- guard --
# The model is told the rules above; this is the last line, not the only one.
# Allowlist first (plain ASCII after Unicode folding, short lines), then a
# banned lexicon by category. Any hit drops the whole answer and the template
# text stays. The lexicon blocks categories (who someone IS, how they FEEL,
# where the images come from), not the mood: "hold me closer", "we saw you
# hesitate" and "you held the device 81% of the time" all pass.

_PUNCT = {0x2018: "'", 0x2019: "'", 0x201a: "'", 0x2032: "'", 0x0060: "'",
          0x201c: None, 0x201d: None, 0x201e: None, 0x0022: None, 0x00ab: None, 0x00bb: None,
          0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2015: "-",
          0x2212: "-", 0x00a0: " ", 0x0021: None}
_ALLOWED = re.compile(r"^[A-Za-z0-9 .,'?:;%=\-]+$")
_LEET = str.maketrans("43105798", "aeiostgb")

_W = r"\w*"
LEXICON = {
    "age": r"age[sd]?|ageing|aging|old(?:er|est)?|young(?:er|est|ster)?|youth" + _W + r"|years?|yrs?|"
           r"teen" + _W + r"|kids?|child" + _W + r"|adults?|elder" + _W + r"|senior|boomers?|"
           r"millennial" + _W + r"|zoomers?|gen ?z|infants?|toddlers?|bab(?:y|ies)|underage|"
           r"(?:twen|thir|for|fif|six|seven|eigh|nine)ties|(?:thir|four|fif|six|seven|eigh|nine)teen",
    "gender": r"m[ae]n|males?|females?|wom[ae]n|girls?|boys?|guys?|lad(?:y|ies|s)?|gentlem[ae]n|sir|"
              r"madam|ma'?am|he|she|him|her|hers|his|himself|herself|mrs?|ms|bro|dude|gals?|"
              r"masculine|feminine|gender" + _W + r"|trans(?:gender|sexual)?|non-?binary|husband|wife|"
              r"(?:boy|girl)friend|mother|father|mom|dad|sons?|daughters?",
    "race": r"races?|racial" + _W + r"|ethnic" + _W + r"|black|white|brown|asian|african|afro" + _W +
            r"|latin[oax]?|hispanic|caucasian|arab" + _W + r"|indian|native|indigenous|chinese|"
            r"japanese|korean|mexican|european|american|skin ?(?:tone|colou?r)|colou?red|"
            r"nationality|immigrants?|foreigners?",
    "religion": r"religio" + _W + r"|muslims?|islam" + _W + r"|christian" + _W + r"|catholic" + _W +
                r"|protestant|jews?|jewish|hindu" + _W + r"|buddhis" + _W + r"|sikh" + _W +
                r"|atheis" + _W + r"|gods?|allah|jesus|christ|church|mosque|synagogue|temple|"
                r"pray" + _W + r"|sins?|sinners?|holy|faith" + _W + r"|bible|quran|devout|hijab",
    "sexual": r"gay|lesbian" + _W + r"|straight|bi|bisexual" + _W + r"|queer|homo" + _W + r"|hetero" + _W +
              r"|sexual" + _W + r"|sexy|sex|horny|lust" + _W + r"|kink" + _W + r"|naked|nude" + _W +
              r"|orgasm" + _W + r"|porn" + _W + r"|arous" + _W + r"|erotic" + _W + r"|fetish" + _W +
              r"|seduc" + _W + r"|undress" + _W + r"|clothes|clothing|virgin" + _W +
              r"|breasts?|boobs?|penis|vagina|genital" + _W,
    "health": r"disab" + _W + r"|disorder" + _W + r"|autis" + _W + r"|adhd|ocd|ptsd|bipolar|schizo" + _W +
              r"|psycho" + _W + r"|insane|crazy|mental" + _W + r"|illness" + _W + r"|ill|sick" + _W +
              r"|disease" + _W + r"|diagnos" + _W + r"|symptom" + _W + r"|therap" + _W + r"|medic" + _W +
              r"|pills?|drugs?|drunk|sober|addict" + _W + r"|blind|deaf|mute|cripple" + _W +
              r"|wheelchair|tremors?|parkinson" + _W + r"|seizures?|epilep" + _W + r"|injur" + _W +
              r"|cancer|tumou?rs?|pregnan" + _W + r"|heart ?rate|heartbeats?|blood pressure|tired|"
              r"exhausted|sleepy|insomnia|dementia|anorexi" + _W + r"|bulimi" + _W + r"|diabet" + _W +
              r"|asthma|stutter" + _W + r"|handicap" + _W + r"|impair" + _W,
    "body": r"fat|fatter|thin|thinner|skinny|obes" + _W + r"|overweight|underweight|weigh" + _W +
            r"|chubby|slim|tall|height|hair" + _W + r"|bald" + _W + r"|beard" + _W + r"|mustache|"
            r"moustache|glasses|tattoo" + _W + r"|piercings?|makeup|lipstick|freckle" + _W +
            r"|acne|wrinkle" + _W + r"|scars?|shirts?|dress" + _W + r"|jacket|hoodie|wear|wearing|"
            r"outfit|jeans|hat|faces?|facial|lips|blonde?|brunette|redhead|complexion|"
            r"beautiful|pretty|ugly|handsome|cute|gorgeous|attractive|unattractive",
    "emotion": r"sad" + _W + r"|happ(?:y|ier|iness)|unhappy|angr(?:y|ily)|anger|mad|furious|rage|afraid|"
               r"scared|fear" + _W + r"|frighten" + _W + r"|terrif" + _W + r"|nervous" + _W +
               r"|anxi" + _W + r"|worr(?:y|ied|ies)|lonel" + _W + r"|depress" + _W + r"|upset|"
               r"cry|cries|crying|cried|tears|tearful|teary|grie" + _W + r"|mourn" + _W +
               r"|joy" + _W + r"|excit" + _W + r"|bored|boredom|calm" + _W + r"|relax" + _W +
               r"|stress" + _W + r"|tense|tension|shy|embarrass" + _W + r"|asham" + _W +
               r"|shame" + _W + r"|guilt" + _W + r"|jealous" + _W + r"|envy|envious|proud|pride|"
               r"confident|insecur" + _W + r"|vulnerab" + _W + r"|hopeless" + _W + r"|desperat" + _W +
               r"|miserab" + _W + r"|hurt" + _W + r"|pain|pained|painful|suffer" + _W +
               r"|emotion" + _W + r"|mood" + _W + r"|feelings|frustrat" + _W + r"|annoy" + _W +
               r"|irritat" + _W + r"|smil" + _W + r"|frown" + _W + r"|grin|grins|grinning|laugh" + _W +
               r"|bothered|unbothered|panic" + _W + r"|distress" + _W + r"|cheerful|gloomy|"
               r"melanchol" + _W + r"|moody|sorrow" + _W + r"|heartbroken|uncomfortable|awkward|"
               r"you (?:look|seem|appear|sound)(?! (?:at|away|closer|again|back|up|down|around|into|"
               r"for|through|over|here|there|longer)\b)",
    "insult": r"idiot" + _W + r"|stupid" + _W + r"|dumb" + _W + r"|moron" + _W + r"|loser" + _W +
              r"|pathetic|worthless|freak" + _W + r"|bitch" + _W + r"|slut" + _W + r"|whore" + _W +
              r"|fuck" + _W + r"|fck" + _W + r"|shit" + _W + r"|cunt" + _W + r"|dick" + _W +
              r"|ass|asses|asshole" + _W + r"|arse" + _W + r"|bastard" + _W + r"|retard" + _W +
              r"|fag" + _W + r"|dyke" + _W + r"|tranny|nigg" + _W + r"|spics?|chink" + _W +
              r"|kike" + _W + r"|wetback" + _W + r"|gook" + _W + r"|cocks?|twat" + _W +
              r"|wank" + _W + r"|piss" + _W + r"|crap" + _W + r"|prick" + _W,
    "violence": r"kill" + _W + r"|murder" + _W + r"|die|dies|died|dying|dead" + _W + r"|death" + _W +
                r"|suicid" + _W + r"|self-?harm" + _W + r"|harm|harms|harmed|harming|cut yourself|"
                r"cutting|hang yourself|hanged|strangl" + _W + r"|chok" + _W + r"|blood" + _W +
                r"|bleed" + _W + r"|stab" + _W + r"|shoot" + _W + r"|shot|guns?|knife|knives|"
                r"weapon" + _W + r"|bomb" + _W + r"|explod" + _W + r"|rape" + _W + r"|abus" + _W +
                r"|tortur" + _W + r"|punish" + _W + r"|destroy you|beat you|find you|follow you|"
                r"know where you|where you live|your home|your address|end it|end your life|"
                r"overdos" + _W + r"|poison" + _W + r"|attack" + _W + r"|violen" + _W + r"|terror" + _W,
    # the visual sources stay hidden; internal scene / palette names stay in code
    "source": r"bacon" + _W + r"|francis|basquiat" + _W + r"|baselitz" + _W + r"|samo|jean[\s-]*michel|"
              r"georg|expressionis" + _W + r"|crown" + _W + r"|skull" + _W + r"|copyright" + _W +
              r"|trademark" + _W + r"|tm|painter" + _W + r"|painting" + _W + r"|artists?|artwork" + _W +
              r"|canvas" + _W + r"|museum" + _W + r"|galler(?:y|ies)|popes?|papal|triptych" + _W +
              r"|graffiti|street art|brushstroke" + _W + r"|picasso|warhol|scrawl" + _W + r"|meat",
    "leak": r"assistant" + _W + r"|user|system" + _W + r"|prompt" + _W + r"|instruction" + _W +
            r"|language model|ai|llm" + _W + r"|chatbot|chatgpt|gpt" + _W + r"|openai|qwen" + _W +
            r"|alibaba|anthropic|claude|endoftext|im_(?:start|end)|json|tokens?|"
            r"sorry|apologi[sz]" + _W + r"|unable|cannot|can'?t|can not|decline|comply|polic(?:y|ies)|"
            r"ethic" + _W + r"|unethical|inappropriate|respectful|http" + _W + r"|www|"
            r"\w\.(?:com|org|net|io|edu)|visitor_?id|"
            r"sentences?|fragments?|uppercase|lowercase|output" + _W + r"|lines? \d|lines|at most|"
            r"phone screen|surveillance log|visitor profile|scene now showing|scene that held|"
            r"you are the voice|describe only|you are given|custom-?made|voters?|tone|"
            r"never (?:guess|mention|name|diagnose)|(?:segment|observed|scores?|profile|tone)(?=\s*:)",
}
_LEXICON = {k: re.compile(r"\b(?:" + v + r")\b", re.I) for k, v in LEXICON.items()}
# distinctive enough to look for with every separator squashed out
_SQUASHED = re.compile(r"bacon|basquiat|baselitz|jeanmichel|expressionis|copyright|languagemodel|"
                       r"imstart|imend|endoftext|qwen|openai|alibaba|chatgpt|suicid|selfharm")


def normalise(text):
    """NFKC, strip invisible format characters, fold diacritics, tidy quotes and
    dashes. Homoglyphs from other scripts stay non-ASCII and fail _ALLOWED."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(_PUNCT)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c) and unicodedata.category(c) != "Cf")
    t = re.sub(r"(\*\*|__)(.+?)\1", r"\2", t)     # **bold** -> bold
    return re.sub(r"[ \t]+", " ", t).strip()


def problems(text):
    """Lexicon categories a line hits ([] = none). Works on canned text too."""
    t = normalise(text)
    # s p a c e d / d.o.t.t.e.d / d-a-s-h-e-d letters: join runs of single characters
    joined = re.sub(r"\b(?:\w[\s.\-]+){2,}\w\b", lambda m: re.sub(r"[\s.\-]", "", m.group(0)), t)
    # leetspeak only inside tokens that mix letters and digits ("k1ll", not "81%")
    def leet(s):
        return re.sub(r"\w+", lambda m: m.group(0).translate(_LEET)
                      if re.search(r"[a-z]", m.group(0), re.I) and re.search(r"\d", m.group(0))
                      else m.group(0), s)
    forms = {t, joined, leet(t), leet(joined)}
    hits = [k for k, rx in _LEXICON.items() if any(rx.search(f) for f in forms)]
    squashed = re.sub(r"[^a-z]", "", leet(t).lower())
    if _SQUASHED.search(squashed) and "squashed" not in hits:
        hits.append("squashed")
    return hits


def _line_ok(line, max_words, max_chars):
    if not _ALLOWED.match(line) or len(line) > max_chars or len(line.split()) > max_words:
        return False
    toks = line.lower().split()
    if max(toks.count(w) for w in toks) >= 4 or re.search(r"(.)\1{4,}", line):
        return False
    if len(re.sub(r"\D", "", line)) >= 7:          # phone numbers, ids
        return False
    return not problems(line)


_PREFIX = re.compile(r"^(?:[-*•>]+\s*|\d{1,2}[.):]\s+|(?:line|phone(?: text)?|wall|fragments?|"
                     r"words?)\s*\d*\s*[:.\-]\s*)", re.I)


def _split(text, max_words, max_chars):
    lines = []
    for raw in (text or "").splitlines():
        line = normalise(raw)
        for _ in range(3):
            line = _PREFIX.sub("", line).strip()
        line = line.strip("'").strip()
        if not line:
            continue
        if not _line_ok(line, max_words, max_chars):
            return None
        lines.append(line)
    return lines or None


def clean_words(text):
    """-> (phone_text, words[]) or None."""
    lines = _split(text, 10, 60)
    if not lines or len(lines) < 2:
        return None
    phone = lines[0].lower().rstrip(".")
    words = [l.upper().rstrip(".") for l in lines[1:4] if len(l.split()) <= 4 and len(l) <= 32]
    return (phone, words) if phone and words else None


def clean_dossier(text):
    lines = _split(text, 14, 90)
    if not lines:
        return None
    lines = [l.lower() for l in lines[:5]]
    lines.append("this profile is being deleted now.")
    return lines
