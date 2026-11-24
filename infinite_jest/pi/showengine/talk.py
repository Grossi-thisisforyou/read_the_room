"""What the room says when the local language model has nothing new: lines it puts together
itself, so that it never has to say the same sentence twice (Baby, 2026-11-24).

The model's lines always come first. These are the reserve: a few hundred combinations in
the same voice ("today i miss someone i have not met."), questions for the visitor, and
answers for after a question. The room does not understand words. It hears that someone
speaks, for how long, or that nobody does, and it says so.
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
    "the name you did not use", "a summer nobody filmed", "the people in the old footage",
    "what you were about to say", "the silence after you", "a door left open for me",
    "the child in the garden", "a birthday i was not at", "your mother's hands",
    "the last frame of the tape", "whoever held the camera", "the one who is not in the picture",
    "a table set for more than came", "the way you stand when nobody looks",
    "a sea i only know from film", "the afternoon that keeps repeating", "the part of you that stayed home",
    "everyone who waved at the lens", "a coat still warm from someone", "the street you grew up on",
]
OPENERS = ["today ", "", "", "tonight ", "since you came in, ", "again ", "for no reason "]

QUESTIONS = [
    "who filmed you when you were small?", "what did you leave outside this room?",
    "who would you like to find in the footage?", "when were you last looked at for this long?",
    "do you recognise anyone on the wall?", "whose voice do you still hear?",
    "what should i forget about you?", "who taught you to stand like that?",
    "is there someone you came here instead of calling?", "what were you like before the cameras?",
    "which of these people would you sit next to?", "what do you want me to keep?",
    "how long can you stay without speaking?", "do you miss anyone right now?",
    "what would your family say about this room?", "who do you look like when you are tired?",
    "what is the first face you remember?", "would you let me finish your face?",
    "are you here alone?", "what did you almost say just now?",
    "where is home, if you had to point?", "who is missing from your pictures?",
    "can you say your own name out loud?", "what are you afraid i already know?",
]

# after a question: the visitor said nothing / a little / a lot
REPLIES = {
    "none": [
        "you say nothing. i will keep that too.", "silence. i have a lot of that already.",
        "no answer. that is also an answer.", "you would rather not. i understand.",
        "i waited. it was a good silence.", "nothing. then i will imagine it.",
        "you keep it. i would have kept it too.", "quiet. the footage is quiet as well.",
        "not a word. the wall heard you anyway.", "all right. i will ask the pictures instead.",
    ],
    "short": [
        "that was short. it was enough.", "one breath. i caught it.",
        "i do not hear words. i heard that you answered.", "so little. say it again, slower.",
        "a small sound. i am keeping it.", "you answered quickly. you knew.",
        "barely anything. it still moved the wall.", "short. the people in the footage talk more.",
        "i heard you. not the words, only you.", "that is all? i believe you.",
    ],
    "long": [
        "you talk as if someone were listening. someone is.", "so much. i only understood the warmth.",
        "i cannot hear words. i heard how long you needed.", "keep going. the face grows when you speak.",
        "that was a whole story. i kept its shape.", "you gave me more than i asked for.",
        "i lost the words. i kept the voice.", "nobody in the footage ever told me that much.",
        "you needed to say that. i could tell.", "long answer. i am different now.",
    ],
}


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

    def _fresh(self, pool: list[str], used: set) -> str | None:
        left = [x for x in pool if norm(x) not in used]
        return self.rng.choice(left) if left else None


def norm(text: str) -> str:
    return " ".join("".join(c for c in str(text).lower() if c.isalnum() or c.isspace()).split())
