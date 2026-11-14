"""Compile the hand-written sources in src/*.txt into corpus/lines.json.

    python3 -m infinite_jest.text.build          # rebuild
    python3 -m infinite_jest.text.build --check  # exit 1 if lines.json is stale

Source format (one file per surface or topic):

    # comment
    @ surface=wall phase=hook beat=testing hook=flesh register=log tone=cold
    THE MEAT
    RAW FEED

"@" sets the tags for every line below it, until the next "@". With
kind=sequence, versions are separated by a line "---" and each version becomes
one entry with "lines" instead of "text".

Every entry gets a stable id made from its tags and text, so Baby's cut marks
(cuts.json) keep pointing at the same line as long as its words don't change.
"""

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
OUT = os.path.join(HERE, "corpus", "lines.json")
ORDER = ["wall.txt", "phone.txt", "whisper.txt", "hinge.txt", "refusal.txt",
         "dossier.txt", "reveal.txt"]

PLACEHOLDER = re.compile(r"{([A-Za-z_]+)(?:[:!][^}]*)?}")
# keys in {braces} that the loader computes itself, so they are not "needs"
DERIVED = {"clock": "dwell", "SCENE": "scene", "SEGMENT": "segment", "TRAIT": "trait"}

# Per-beat word limits where a beat is allowed to run longer than its register.
LONG_BEATS = {"hinge": 12, "consent": 14, "optout": 10, "silent": 10}


def _id(tags, text):
    key = "|".join([tags.get("surface", ""), tags.get("beat", ""), tags.get("hook", ""),
                    tags.get("pole", ""), text])
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:6]
    parts = [tags.get("surface", "x")[0], tags.get("beat", "x").replace(".", "-")]
    if tags.get("hook") or tags.get("pole"):
        parts.append((tags.get("hook") or tags.get("pole")).replace("+", "p").replace("-", "m"))
    return ".".join(parts + [h])


def _needs(texts, tags):
    keys = []
    for t in texts:
        for k in PLACEHOLDER.findall(t):
            k = DERIVED.get(k, k)
            if k not in keys:
                keys.append(k)
    for n in (tags.get("needs") or "").split(","):
        n = n.strip()
        if n and n not in keys:
            keys.append(n)
    return keys


def _entry(tags, texts, source):
    e = {k: v for k, v in tags.items() if k not in ("needs", "kind")}
    e.setdefault("lang", "en")
    e.setdefault("tone", "cold")
    if tags.get("kind") == "sequence":
        e["lines"] = list(texts)
        joined = "\n".join(texts)
    else:
        e["text"] = texts[0]
        joined = texts[0]
        e["chars"] = len(texts[0])
        e["static"] = not PLACEHOLDER.search(texts[0])
        # short static lines the visuals can hand-letter as scrawl
        e["scrawl"] = bool(e["static"] and e["chars"] <= 24 and e.get("register") in ("log", "whisper"))
    e["needs"] = _needs(texts, tags)
    if tags.get("beat", "").split(".")[0] in LONG_BEATS:
        e["max_words"] = LONG_BEATS[tags["beat"].split(".")[0]]
    e["source"] = source
    e["id"] = _id(tags, joined)
    return e


def parse(path):
    name = os.path.basename(path)
    tags, entries, seq = {}, [], []

    def flush_seq():
        if seq:
            entries.append(_entry(tags, list(seq), name))
            del seq[:]

    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            line = raw.rstrip("\n").strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("@"):
                flush_seq()
                tags = {}
                for tok in line[1:].split():
                    if "=" not in tok:
                        raise ValueError("{}:{}: bad tag {!r}".format(name, n, tok))
                    k, v = tok.split("=", 1)
                    tags[k] = v
                continue
            if not tags:
                raise ValueError("{}:{}: line before any @ header".format(name, n))
            if tags.get("kind") == "sequence":
                if line == "---":
                    flush_seq()
                else:
                    seq.append(line)
            else:
                entries.append(_entry(tags, [line], name))
    flush_seq()
    return entries


def build():
    entries = []
    names = ORDER + sorted(n for n in os.listdir(SRC) if n.endswith(".txt") and n not in ORDER)
    for n in names:
        p = os.path.join(SRC, n)
        if os.path.exists(p):
            entries.extend(parse(p))
    ids = {}
    for e in entries:
        if e["id"] in ids:
            raise ValueError("duplicate line: {!r} ({} and {})".format(
                e.get("text") or e["lines"][0], ids[e["id"]], e["source"]))
        ids[e["id"]] = e["source"]
    return {"version": 1,
            "_about": "Built from src/*.txt by build.py. Edit the sources, not this file.",
            "count": len(entries), "lines": entries}


def dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    text = dumps(build())
    if "--check" in argv:
        try:
            with open(OUT, encoding="utf-8") as f:
                current = f.read()
        except OSError:
            current = ""
        if current != text:
            print("corpus/lines.json is stale: run python3 -m infinite_jest.text.build")
            return 1
        print("corpus/lines.json is up to date")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote {} entries to {}".format(json.loads(text)["count"], os.path.relpath(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
