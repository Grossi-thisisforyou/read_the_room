"""Method v2 as code: which sentences count, how much, and what they become.

Rules (see /research/method-v2.md, tested once on a consenting subject):
start from the person's group, weight by who is speaking and how old the
evidence is, count behaviours over tone, read hardship by its outcome, move a
trait only on three cues, and never touch family or the excluded topics.
"""

import re

TRAITS = "OCEAN"

# Rule 1: priors by reference group (general-population percentiles).
PRIORS = {
    "default":    {"O": 50, "C": 50, "E": 50, "A": 50, "N": 50},
    "performer":  {"O": 80, "C": 50, "E": 75, "A": 62, "N": 50},   # actors, dancers, musicians on stage
    "artist":     {"O": 85, "C": 45, "E": 50, "A": 52, "N": 55},   # visual artists, writers, designers
    "academic":   {"O": 78, "C": 62, "E": 45, "A": 52, "N": 48},   # professors, researchers
    "student":    {"O": 62, "C": 48, "E": 55, "A": 52, "N": 55},
    "technical":  {"O": 62, "C": 60, "E": 40, "A": 48, "N": 45},   # engineers, developers
    "organizer":  {"O": 58, "C": 65, "E": 68, "A": 58, "N": 45},   # producers, curators, managers
}
GROUP_WORDS = {
    "performer": "actor actress schauspieler performer dancer musician singer comedian",
    "artist": "artist painter sculptor writer author poet designer photographer filmmaker director",
    "academic": "professor researcher lecturer scholar phd scientist",
    "student": "student mfa bfa undergraduate",
    "technical": "engineer developer programmer technologist",
    "organizer": "curator producer manager founder organizer dean",
}

# Topics the file never holds (terms, Section 11). A sentence that touches one is dropped whole.
EXCLUDED = {
    "health": r"\b(diagnos\w*|illness|disease|cancer|depress\w*|anxiety|therapy|therapist|disorder|disabil\w*|"
              r"hospital\w*|surgery|medication|addict\w*|rehab|pregnan\w*|krank\w*|krebs|sucht)\b",
    "sexuality": r"\b(gay|lesbian|bisexual|queer|straight|heterosexual|homosexual|sexual orientation|"
                 r"came out|coming out|trans(gender)?|nonbinary|non-binary|schwul|lesbisch)\b",
    "religion": r"\b(christian|catholic|protestant|muslim|islam\w*|jewish|judaism|hindu\w*|buddhis\w*|atheis\w*|"
                r"church|mosque|synagogue|faith|religio\w*|kirche|glaube)\b",
    "politics": r"\b(democrat\w*|republican\w*|conservative|liberal|socialist\w*|communist\w*|left-wing|right-wing|"
                r"voted|voter|party member|activis\w*|protest\w*|demonstration|campaign\w*|election|"
                r"afd|cdu|spd|grüne|linke|fdp|partei|wahl)\b",
    "immigration": r"\b(visa|asylum|refugee|undocumented|immigration status|green card|deport\w*|citizenship|"
                   r"aufenthalt\w*|asyl\w*)\b",
    "finances": r"\b(salary|income|debt|bankrupt\w*|net worth|earn(s|ed|ing)?|mortgage|poverty|welfare|"
                r"gehalt|schulden|armut\w*|insolven\w*)\b",
    "family": r"\b(mother|father|parents?|brother|sister|son|daughter|wife|husband|spouse|partner|girlfriend|"
              r"boyfriend|grand(mother|father|parents?)|uncle|aunt|cousin|child(ren)?|"
              r"mutter|vater|eltern|bruder|schwester|sohn|tochter|ehefrau|ehemann|freundin|groß\w+|kind(er)?)\b",
}
_EXCL = {k: re.compile(v, re.I) for k, v in EXCLUDED.items()}


def excluded_topic(sentence):
    for topic, rx in _EXCL.items():
        if rx.search(sentence):
            return topic
    return None


# Rule 2: who is speaking.
FIRST_PERSON = re.compile(r"(^|[\s\"“„«(])(i|i'm|i've|my|me|ich|mein\w*|mich|mir)\b", re.I)
QUOTE = re.compile(r"[\"“”„«»]")
SAID = re.compile(r"\b(says?|said|explains?|tells?|recalls?|sagt|sagte|erzählt|erklärt|so)\b", re.I)
ROLE = re.compile(r"\b(plays?|played|as the|in the role|role of|character|stars? as|cast as|portray\w*|"
                  r"spielt|rolle|figur|verkörpert)\b", re.I)


def speaker(sentence, is_title=False, own_site=False):
    """'self' 1.0, 'published' 0.8, 'observer' 0.6, 'role' 0, 'framing' 0."""
    if is_title:
        return "framing", 0.0
    if ROLE.search(sentence):
        return "role", 0.0
    if FIRST_PERSON.search(sentence) and (QUOTE.search(sentence) or own_site or SAID.search(sentence)):
        return "self", 1.0
    if own_site:
        # What the person chose to publish about their own work is a documented choice.
        # Its tone (third person, sparse, formal) is house style and is never scored.
        return "published", 0.8
    return "observer", 0.6


# Rule 3: age of the evidence, half-life five years, floor for anything older than eight.
YEAR = re.compile(r"\b(19[6-9]\d|20[0-4]\d)\b")


def age_weight(year, now):
    if not year:
        return 0.7            # undated: assume a few years old
    age = max(0, now - year)
    if age > 8:
        return 0.25
    return round(0.5 ** (age / 5.0), 2)


# Rules 4 and 5: behaviours that need the trait. (trait, direction, pattern). Lexicon fallback when no model runs.
CUES = [
    ("O", 1, r"\b(stud(y|ies|ied|ying)|degree|mfa|phd|research\w*|experiment\w*|invent\w*|wrote|writes|writing|"
             r"direct(s|ed|ing)|compos\w+|paint\w*|curat\w+|translat\w+|language|philosoph\w*|archive|"
             r"own work|new work|premiere|exhibition|studier\w*|forsch\w*|schreib\w*)\b"),
    ("O", -1, r"\b(tradition\w*|routine|conventional|never changed|same job)\b"),
    ("C", 1, r"\b(completed|finished|graduated|scholarship|award\w*|prize|nominated|train(s|ed|ing)|rehears\w*|"
             r"disciplin\w*|prepar\w*|every day|daily|marathon|deadline|founded|built|abschluss|stipendi\w*)\b"),
    ("C", -1, r"\b(unfinished|dropped out|abandon\w*|late again|missed|quit|abgebrochen)\b"),
    ("E", 1, r"\b(perform(s|ed|ing)|on stage|audience|host(s|ed|ing)|spoke at|keynote|lead(s|ing)? (a|the) (team|group)|"
             r"moved to|collaborat\w*|co-founded|organi[sz]\w*|teach(es|ing)?|taught|workshop|tour(ed|ing)?|"
             r"bühne|publikum|auftritt)\b"),
    ("E", -1, r"\b(alone|solitary|withdrawn|reclusive|avoids? (crowds|interviews)|rarely appears|zurückgezogen)\b"),
    ("A", 1, r"\b(volunteer\w*|mentor\w*|teach(es|ing)?|taught|youth|communit\w*|care[sd]? for|support(s|ed|ing)|"
             r"help(s|ed|ing)|thanks?|grateful|generous|ensemble|together with|ehrenamt\w*|jugend\w*)\b"),
    ("A", -1, r"\b(refus\w*|feud|sued|insult\w*|clash\w*|quarrel\w*|confront\w*|streit\w*)\b"),
    ("N", 1, r"\b(i worry|i'm afraid|i am afraid|i panic|sleepless|i can't cope|overwhelmed|ich habe angst|"
             r"i doubt myself|i struggle with nerves)\b"),
    # rule 5: hardship that ends in persistence counts toward stability
    ("N", -1, r"\b(despite|persist\w*|kept going|carried on|calm\w*|composed|unfazed|laughs?|amused|relaxed|"
              r"gelassen|trotzdem|spornt)\b"),
]
_CUES = [(t, d, re.compile(p, re.I)) for t, d, p in CUES]
MIN_CUE = 0.3      # a cue lighter than this does not count toward the three-cue rule


def lexicon_cues(sentence):
    return [(t, d) for t, d, rx in _CUES if rx.search(sentence)]


def score(cues, group="default"):
    """cues: list of {trait, dir, weight, ...}. Returns {trait: {pct, range, prior, n_up, n_down, moved}}."""
    prior = PRIORS.get(group, PRIORS["default"])
    out = {}
    for t in TRAITS:
        mine = [c for c in cues if c["trait"] == t and c["weight"] >= MIN_CUE]
        up = sum(c["weight"] for c in mine if c["dir"] > 0)
        down = sum(c["weight"] for c in mine if c["dir"] < 0)
        n_up = sum(1 for c in mine if c["dir"] > 0)
        n_down = sum(1 for c in mine if c["dir"] < 0)
        lead_n, net = (n_up, up - down) if up >= down else (n_down, up - down)
        moved = lead_n >= 3 and abs(net) >= 1.0          # rule 6
        pct = prior[t]
        if moved:
            room = (97 - pct) if net > 0 else (pct - 3)
            pct = pct + (1 if net > 0 else -1) * room * (1 - 0.5 ** (abs(net) / 3.0))
        total = up + down
        rng = 25 if not moved else max(8, round(22 - 2.5 * total))
        out[t] = {"pct": int(round(pct)), "range": rng, "prior": prior[t], "n_up": n_up, "n_down": n_down,
                  "moved": moved}
    return out


# Rule 9: the first room comes from the material the person chooses to work with.
ROOMS = {
    "flesh":    r"\b(body|bodies|dance\w*|physical\w*|perform\w*|sport\w*|boxing|naked|skin|durational|körper\w*)\b",
    "scrawl":   r"\b(writ\w*|text\w*|poem\w*|novel\w*|essay\w*|words?|script\w*|journal\w*|letters?|code|schreib\w*)\b",
    "inverted": r"\b(theor\w*|philosoph\w*|critic\w*|research\w*|analys\w*|histor\w*|politic\w*|subver\w*)\b",
    "mirror":   r"\b(portrait\w*|self|identity|image|photograph\w*|camera|film\w*|screen|fashion|selfie\w*)\b",
    "void":     r"\b(silence|silent|sound|music|ambient|minimal\w*|meditat\w*|architecture|light|dark\w*|stille)\b",
}
_ROOMS = {k: re.compile(v, re.I) for k, v in ROOMS.items()}


def rooms(sentences):
    """Hooks ranked by how often the person's own material touches them."""
    count = {k: 0 for k in ROOMS}
    for s in sentences:
        for k, rx in _ROOMS.items():
            if rx.search(s):
                count[k] += 1
    return sorted(count, key=lambda k: -count[k]), count
