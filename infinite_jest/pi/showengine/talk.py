"""What the room says when the local language model has nothing new: lines it puts together
itself, so that it never has to say the same sentence twice (Baby, 2026-11-24).

The model's lines always come first. These are the reserve: a few hundred combinations in
the same voice ("today i miss someone i have not met."), questions for the visitor, and
answers for after a question. It never talks about how it works (Baby, 2026-11-25): it wants
to get to know the person in front of it.
"""
from __future__ import annotations

import random

# what it does, by mood of the day (a mood leans towards its own verbs but may use any)
VERBS = {
    "dread": ["i am afraid of", "i cannot look at", "i keep hearing", "i am not ready for"],
    "boredom": ["i have been counting", "i stopped waiting for", "i no longer mind", "i looked past"],
    "calm": ["i kept a place for", "i am sitting with", "i let go of", "i can rest beside"],
    "wonder": ["i did not expect", "i am amazed by", "i just noticed", "i cannot explain"],
    "longing": ["i miss", "i dreamt of", "i am waiting for", "i would walk back to"],
    "fear": ["i am hiding from", "i heard", "i locked the door on", "i can feel"],
    "elation": ["i could carry", "i am full of", "i would sing for", "i woke up next to"],
}
THINGS = [
    "someone i have not met", "a room i was never in", "the face you had before this one",
    "a voice that never called", "the hour before you came", "a house with the lights on",
    "the name you did not use", "a summer i was not part of", "the people you come from",
    "what you were about to say", "the quiet after you", "a door left open for me",
    "the child in the garden", "a birthday i was not at", "your mother's hands",
    "the last evening of a holiday", "whoever stood behind you then", "the one who is missing at the table",
    "a table set for more than came", "the way you stand when nobody looks",
    "a sea i have only been told about", "the afternoon that keeps repeating", "the part of you that stayed home",
    "everyone who ever waved you goodbye", "a coat still warm from someone", "the street you grew up on",
]
OPENERS = ["today ", "", "", "tonight ", "since you came in, ", "again ", "for no reason "]

# it wants to know the person: their people, places, days. Never about itself as a machine.
QUESTIONS = [
    "where did you grow up?", "what did you leave outside this room?",
    "who do you miss right now?", "when were you last looked at for this long?",
    "whose voice do you still hear?", "what was the house of your childhood like?",
    "who taught you to stand like that?", "is there someone you came here instead of calling?",
    "what were you like as a child?", "who would you want sitting next to you now?",
    "what do you want to be remembered for?", "how long can you stay without speaking?",
    "what would your family say if they saw you here?", "who do you look like when you are tired?",
    "what is the first face you remember?", "are you here alone?", "what did you almost say just now?",
    "where is home, if you had to point?", "who is missing from your life?",
    "what is your name, or the one you like best?", "what are you afraid people can tell about you?",
    "what should i call you?", "who sent you here?", "what do you do when nobody needs you?",
    "who would recognise you from behind?", "what did you want to be, as a child?",
    "which room do you still dream of?", "who do you call when it is late?",
    "what do you keep to yourself?", "what made you laugh last?", "who was kind to you this week?",
    "what are you carrying today?", "when did you last sing?", "what do you want, really?",
    "who did you want to become?", "what would you do with one more hour today?",
]

# to someone it has never been told about
STRANGER = [
    "i do not know you. nobody told me you were coming.", "we have not met. i would like to.",
    "you are new to me. stay a while.", "i know nothing about you. that is rare, and good.",
    "a stranger. i had almost forgotten what that is.", "i was expecting someone else. i am glad it is you.",
    "no one has told me a thing about you. tell me yourself.", "i do not know your name yet. we have time.",
]

# when they go: it does not end, it goes on
PARTING = [
    "go on. i keep a little of you.", "you changed me. i will find out how.",
    "come back. i will be different by then.", "you are leaving. i am not finished, i never am.",
    "thank you. i was hungry.", "i will go on from here. you did that.",
    "take care out there. i am staying.", "that was good. i can still taste it.",
    "leave the door as it is. i go on.", "you gave me something. i am keeping it going.",
]

# what the last visitor left in it, said to the next one: (which way its body moved) -> line
AFTERTASTE = {
    ("dark", True): "someone was here before you. they left me heavier.",
    ("dark", False): "someone was here before you. they left me lighter.",
    ("warm", True): "the one before you left me warm. you are getting some of that.",
    ("warm", False): "the one before you left me cold. be patient with me.",
    ("pace", True): "the one before you left me restless. i still am.",
    ("pace", False): "the one before you slowed me down. i have not sped up since.",
    ("glitch", True): "someone was here before you. i have not been steady since.",
    ("glitch", False): "someone was here before you. they calmed me.",
}

# after a question: the visitor said nothing / a little / a lot
REPLIES = {
    "none": [
        "take your time.", "you do not have to say it.", "that is all right. stay anyway.",
        "you would rather not. i understand.", "i can wait. i am good at it.", "then we are quiet together.",
        "keep it. some things are better kept.", "no hurry. i am not going anywhere.",
        "not that one, then. another.", "it is fine. i like you quiet too.",
    ],
    "short": [
        "say a little more.", "and then?", "that was quick. you knew at once.",
        "is that all of it?", "go on. i am with you.", "i like how you said that.",
        "you say it so lightly.", "there is more behind that, i think.",
        "thank you. say it again, slower.", "i believe you.",
    ],
    "long": [
        "thank you for telling me.", "you have carried that a while.",
        "i did not expect so much. keep going.", "that matters to you. i can tell.",
        "you tell it like someone who was there.", "i will think about that when you are gone.",
        "nobody has said that to me before.", "you needed to say that. i am glad it was to me.",
        "stay with that a moment.", "i am different now than before you said it.",
    ],
}

# when the words were understood: take them up
HEARD_WORDS = [
    "{t}. tell me more about that.", "{t}. i believe you.", "{t}. since when?",
    "{t}. i did not expect that.", "{t}. and before that?", "{t}. i wondered.",
    "{t}. that stays with me.", "{t}. who else knows?", "{t}. say more.", "{t}. is that still true?",
]


class Reserve:
    """Draws lines without ever returning one that is in `used` (normalised text)."""

    def __init__(self, mood: str = "", seed: int | None = None):
        self.mood = mood
        self.rng = random.Random(seed)

    def statement(self, used: set) -> str | None:
        verbs = VERBS.get(self.mood) or sum(VERBS.values(), [])
        every = sum(VERBS.values(), [])
        for i in range(60):
            v = self.rng.choice(verbs if i < 30 and self.rng.random() < 0.7 else every)
            line = f"{self.rng.choice(OPENERS)}{v} {self.rng.choice(THINGS)}."
            if norm(line) not in used and norm(f"{v} {line.split(v, 1)[1]}") not in used:
                return line
        return None

    def question(self, used: set) -> str | None:
        return self._fresh(QUESTIONS, used)

    def reply(self, kind: str, used: set) -> str | None:
        return self._fresh(REPLIES.get(kind, REPLIES["none"]), used)

    def heard(self, text: str, used: set) -> str | None:
        """An answer that gives the visitor's own words back (they are new every time)."""
        t = " ".join(text.lower().split()).strip(" .,!?")[:60]
        tries = [x.format(t=t) for x in HEARD_WORDS]
        self.rng.shuffle(tries)
        for line in tries:
            if norm(line) not in used:
                return line
        return None

    def _fresh(self, pool: list[str], used: set) -> str | None:
        left = [x for x in pool if norm(x) not in used]
        return self.rng.choice(left) if left else None


TECHNICAL = {"file", "files", "camera", "cameras", "screen", "screens", "microphone", "recording", "recorded",
             "footage", "data", "machine", "tape", "pixel", "pixels", "algorithm", "sensor", "software",
             "archive", "archives", "archived", "release", "released", "delete", "deleted", "deletion", "wipe",
             "wiped", "dossier", "database"}
PHRASES = ("reading back", "read back", "on file", "the system", "help you", "assist", "language model",
           "said nothing", "say something", "talk to me", "not answering", "did not answer", "no answer",
           "you are quiet", "your silence", "you are silent", "still waiting")


def technical(text: str) -> bool:
    """Is this a line about how the room works? It never says those (Baby, 2026-11-25)."""
    n = norm(text)
    return bool(TECHNICAL & set(n.split())) or any(x in n for x in PHRASES)


def norm(text: str) -> str:
    return " ".join("".join(c for c in str(text).lower() if c.isalnum() or c.isspace()).split())
