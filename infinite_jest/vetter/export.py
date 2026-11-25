"""Read a person's own Instagram or Facebook download ("Download your information", JSON format).

The guest (or the artist) requests the download from the platform themselves and
hands over the zip. No password is ever given to the Pi and nothing is fetched
from the platform by this tool. This is the same kind of data Cambridge Analytica
ran on (posts, likes, follows), given by its owner instead of taken.

Only three things are kept: the person's own captions and posts with their year,
how many accounts and pages they follow or liked, and which themes those names
touch. The names of followed accounts are not stored, because many are private people.
"""

import datetime
import json
import os
import zipfile

from . import rules

KINDS = (("posts", ("posts", "content/", "your_posts", "reels", "stories")),
         ("comments", ("comments",)),
         ("likes", ("likes", "liked", "reactions")),
         ("follows", ("following", "pages_you", "followed")))
SKIP = ("messages", "inbox", "ads_information", "ads_and_", "security", "login", "device",
        "contacts", "search", "location", "payment")     # private talk, other people, tracking data


def _fix(s):
    try:                       # Meta exports store UTF-8 as Latin-1 escapes
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _kind(path):
    low = path.lower()
    if any(k in low for k in SKIP) or os.path.basename(low).startswith(("followers", "blocked", "close_friends")):
        return None                     # other people's accounts and private talk are never opened
    for kind, keys in KINDS:
        if any(k in low for k in keys):
            return kind
    return None


def _walk(node, found, ts=None):
    """Collect (text, timestamp) pairs from Meta's nested JSON."""
    if isinstance(node, dict):
        ts = node.get("creation_timestamp") or node.get("timestamp") or node.get("taken_at") or ts
        for key in ("title", "text", "caption", "post", "comment", "value", "name"):
            v = node.get(key)
            if isinstance(v, str) and v.strip():
                found.append((_fix(v.strip()), ts))
        for v in node.values():
            if isinstance(v, (dict, list)):
                _walk(v, found, ts)
    elif isinstance(node, list):
        for v in node:
            _walk(v, found, ts)


def _files(path):
    """(name, loader) pairs. A file's bytes are read only when its loader is called."""
    if os.path.isdir(path):
        for base, _, names in os.walk(path):
            for n in names:
                if n.endswith(".json"):
                    full = os.path.join(base, n)
                    yield os.path.relpath(full, path), (lambda f=full: open(f, "rb").read())
    else:
        z = zipfile.ZipFile(path)
        for n in z.namelist():
            if n.endswith(".json"):
                yield n, (lambda n=n: z.read(n))


def read(path):
    """{'posts': [(text, year)], 'counts': {...}, 'themes': {...}} from a download zip or folder."""
    posts, names, counts = [], [], {"posts": 0, "comments": 0, "likes": 0, "follows": 0}
    for name, load in _files(path):
        kind = _kind(name)
        if not kind:
            continue            # decided by the file's name alone: messages and follower lists stay unread
        raw = load()
        try:
            found = []
            _walk(json.loads(raw.decode("utf-8", "replace")), found)
        except ValueError:
            continue
        for text, ts in found:
            counts[kind] += 1
            if kind in ("posts", "comments"):
                year = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).year if isinstance(ts, (int, float)) and ts > 0 else None
                if len(text) >= 25:
                    posts.append((text, year))
            else:
                names.append(text)
    _, themes = rules.rooms(names)
    return {"posts": posts, "counts": counts, "themes": themes}
