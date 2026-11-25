"""Guest files on the Pi's own disk. Nothing here opens a network connection."""

import datetime
import json
import os
import re
import shutil

DEFAULT_DIR = os.path.expanduser("~/.local/share/infinite-jest/guests")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "guest"


def folder(name, root=None):
    return os.path.join(root or DEFAULT_DIR, slug(name))


def save(name, data, markdown, root=None):
    d = folder(name, root)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    for fn, body in (("guest.json", json.dumps(data, ensure_ascii=False, indent=2)), ("guest.md", markdown)):
        path = os.path.join(d, fn)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
    return d


def show(name, root=None):
    """The whole file as text, for a guest who asks what is held about them."""
    path = os.path.join(folder(name, root), "guest.md")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def delete(name, root=None):
    d = folder(name, root)
    if os.path.isdir(d):
        shutil.rmtree(d)
        return True
    return False


def purge(today=None, root=None):
    """Delete every guest file whose delete_after date has passed. Returns the names removed."""
    today = today or datetime.date.today().isoformat()
    root = root or DEFAULT_DIR
    gone = []
    if not os.path.isdir(root):
        return gone
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry, "guest.json")
        try:
            with open(path, encoding="utf-8") as f:
                after = json.load(f).get("delete_after", "")
        except (OSError, ValueError):
            continue
        if after and after < today:
            shutil.rmtree(os.path.join(root, entry))
            gone.append(entry)
    return gone
