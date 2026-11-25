"""Optional helper: the Pi's own language model reads a sentence and names the cue.

Only a loopback address is accepted, so no sentence about a guest can be sent
to a model outside the room. Any failure falls back to the word lists in rules.py.
"""

import json
import urllib.parse
import urllib.request

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PROMPT = ("You label one sentence about a person for a Big Five reading. Reply with JSON only: "
          '{"cues":[{"trait":"O|C|E|A|N","dir":1 or -1}]}. Count only things the person DID or SAID about '
          "themselves. Roles they played, headlines and style give no cues. Hardship that ended in persistence is "
          'N -1. If nothing counts reply {"cues":[]}.')


class LocalModel:
    def __init__(self, url="http://127.0.0.1:8080/v1/chat/completions", timeout=20):
        host = urllib.parse.urlsplit(url).hostname
        if host not in LOOPBACK:
            raise ValueError("the vetter only talks to a model on this machine (127.0.0.1)")
        self.url, self.timeout, self.ok = url, timeout, True

    def cues(self, sentence):
        """List of (trait, dir), or None when the model is unavailable or unclear."""
        if not self.ok:
            return None
        body = json.dumps({"messages": [{"role": "system", "content": PROMPT},
                                        {"role": "user", "content": sentence[:400]}],
                           "max_tokens": 60, "temperature": 0}).encode()
        try:
            req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                text = json.load(r)["choices"][0]["message"]["content"]
            data = json.loads(text[text.index("{"):text.rindex("}") + 1])
            out = []
            for c in data.get("cues", [])[:3]:
                if c.get("trait") in "OCEAN" and c.get("dir") in (1, -1):
                    out.append((c["trait"], c["dir"]))
            return out
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            if isinstance(e, OSError):
                self.ok = False       # model not running: stop asking, use the word lists
            return None
