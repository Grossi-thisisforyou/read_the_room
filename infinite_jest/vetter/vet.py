"""The pipeline: name in, guest file out. Everything is decided on this machine."""

import datetime
import re
import urllib.parse
from collections import Counter

from . import export as _export
from . import rules, store

MAX_PAGES = 20
SENT = re.compile(r"(?<=[.!?”\"])\s+(?=[A-ZÄÖÜ“„\"])|\n+")


def sentences(text):
    return [s.strip() for s in SENT.split(text) if 25 <= len(s.strip()) <= 420]


def _tokens(hints):
    return [h.lower() for h in re.findall(r"[\wÀ-ſ]{3,}", " ".join(hints))]


def same_person(name, text, hints, trusted):
    """A page counts only if it names the person in full and matches something they told us."""
    if trusted:
        return True
    low = text.lower()
    first, last = name.lower().split()[0], name.lower().split()[-1]
    if not re.search(re.escape(first) + r"\W+(?:\w+\W+){0,2}" + re.escape(last), low):
        return False
    return any(h in low for h in _tokens(hints))


def guess_group(hints, text):
    hay = (" ".join(hints) + " " + text[:4000]).lower()
    best, hits = "default", 0
    for group, words in rules.GROUP_WORDS.items():
        n = sum(len(re.findall(r"\b%s\b" % re.escape(w), hay)) for w in words.split())
        if n > hits:
            best, hits = group, n
    return best


def vet(name, web, hints=(), urls=(), group=None, booked=None, model=None, today=None,
        delete_after="2026-12-23", root=None, write=True, years=1, export=None):
    """Build and store one guest file. `booked` is the booking date and must be given:
    the tool refuses to research someone who has not booked."""
    if not booked:
        raise ValueError("no booking date given: only people who booked are researched")
    name = " ".join(name.split())
    if len(name.split()) < 2:
        raise ValueError("a full name is needed, otherwise the pages could be about anyone")
    today = today or datetime.date.today()
    first, last = name.split()[0], name.split()[-1]
    hints, own = list(hints), {urllib.parse.urlsplit(u).netloc for u in urls}

    # 1. find pages: the guest's own links first, then Wikipedia, then search
    wiki = web.wikipedia(name)
    found = list(urls) + wiki
    for article in wiki:
        found += getattr(web, "wikipedia_sources", lambda u: [])(article)
    for q in [f'"{name}"'] + [f'"{name}" {h}' for h in hints[:3]] + [f'"{name}" interview']:
        found += web.search(q)
    seen, pages, skipped = set(), [], []
    i = 0
    while i < len(found):
        url = found[i]
        i += 1
        key = url.split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        if len(pages) >= MAX_PAGES:
            break
        got = web.page(url)
        if not got:
            continue
        title, text = got
        host = urllib.parse.urlsplit(url).netloc
        if host in own:   # read the rest of the guest's own site, one level deep
            found[found.index(url) + 1:found.index(url) + 1] = getattr(web, "links", {}).get(url, [])[:6]
        trusted = host in own or "wikipedia.org" in host and name.lower() in title.lower()
        if not same_person(name, title + "\n" + text, hints, trusted):
            skipped.append(url)
            continue
        pages.append({"url": url, "title": title, "text": text, "own": host in own})

    # 2. keep sentences about the person, drop the excluded topics, weigh each one
    cues, quotes, facts, kept, dropped = [], [], [], [], Counter()
    seen_sent, per_host = set(), Counter()      # one site cannot vote more than twice per trait
    all_text = ""
    for p in pages:
        all_text += p["text"][:6000] + "\n"
        follow = 0
        for s in sentences(p["text"]):
            norm = re.sub(r"\W+", " ", s.lower()).strip()
            if norm in seen_sent:
                continue
            seen_sent.add(norm)
            about = first in s or last in s
            if not (about or p["own"] or follow > 0):
                continue
            follow = 2 if about else follow - 1
            topic = rules.excluded_topic(s)
            if topic:
                dropped[topic] += 1
                continue
            kind, w_src = rules.speaker(s, own_site=p["own"])
            y = [int(v) for v in rules.YEAR.findall(s)]
            year = max(y) if y else None
            if years and year and year < today.year - years:
                dropped["older than the terms allow"] += 1     # terms: twelve months back
                continue
            w = round(w_src * rules.age_weight(year, today.year), 2)
            kept.append(s)
            found_cues = (model.cues(s) if model else None)
            if found_cues is None:
                found_cues = rules.lexicon_cues(s)
            host = urllib.parse.urlsplit(p["url"]).netloc
            for trait, direction in found_cues:
                per_host[(trait, direction, host)] += 1
                if per_host[(trait, direction, host)] > 2:
                    continue
                cues.append({"trait": trait, "dir": direction, "weight": w, "kind": kind, "year": year,
                             "source": p["url"], "text": s[:200]})
            if kind == "self" and len(s) < 240:
                quotes.append({"text": s, "year": year, "source": p["url"]})
            elif kind == "observer" and year and len(s) < 240:
                facts.append({"text": s, "year": year, "source": p["url"]})

    # 2b. the person's own platform download, if they handed one over
    social = None
    for path in ([export] if isinstance(export, str) else list(export or [])):
        got = _export.read(path)
        social = social or {"counts": Counter(), "themes": Counter()}
        social["counts"].update(got["counts"])
        social["themes"].update(got["themes"])
        n_before = len(cues)
        for text, year in got["posts"]:
            for s in sentences(text) or [text[:400]]:
                if rules.excluded_topic(s):
                    dropped[rules.excluded_topic(s)] += 1
                    continue
                if years and year and year < today.year - years:
                    dropped["older than the terms allow"] += 1
                    continue
                kept.append(s)
                w = round(rules.age_weight(year, today.year), 2)
                found_cues = (model.cues(s) if model else None)
                if found_cues is None:
                    found_cues = rules.lexicon_cues(s)
                for trait, direction in found_cues:
                    per_host[(trait, direction, f"own posts {year}")] += 1
                    if per_host[(trait, direction, f"own posts {year}")] > 3:
                        continue
                    cues.append({"trait": trait, "dir": direction, "weight": w, "kind": "self", "year": year,
                                 "source": "own download", "text": s[:200]})
                if len(s) < 240:
                    quotes.append({"text": s, "year": year, "source": "own download"})
    if social:
        social = {"counts": dict(social["counts"]), "themes": dict(social["themes"])}

    # 3. score with the tested rules
    group = group or guess_group(hints, all_text)
    ocean = rules.score(cues, group)
    order, room_counts = rules.rooms(kept)
    if social:      # what they follow and like is taste: let it vote on the first room
        for k, v in social["themes"].items():
            room_counts[k] += v
        order = sorted(room_counts, key=lambda k: -room_counts[k])
    # thin: nothing personal to say and no trait the evidence could move. The room should ask instead.
    thin = len(kept) < 8 or (not quotes and not any(ocean[t]["moved"] for t in rules.TRAITS))
    data = {
        "name": name, "name_spoken": first, "method": "v2",
        "consent": {"research": True, "source": f"booking {booked}"},
        "made_on": today.isoformat(), "delete_after": delete_after,
        "group": group,
        "ocean": {t: ocean[t]["pct"] / 100 for t in rules.TRAITS},
        "ocean_detail": ocean,
        "thin": thin,   # too little found: the room should treat this guest as a stranger and ask
        "hook": order[0] if room_counts[order[0]] else None,
        "hook_second": order[1] if room_counts[order[1]] else None,
        "quotes": quotes[:12], "facts": sorted(facts, key=lambda f: -f["year"])[:15],
        "sources": [p["url"] for p in pages],
        "social": social,
        "skipped_other_person": skipped,
        "dropped_by_topic": dict(dropped),
        "cues": cues[:80],
        "log": [list(x) for x in web.log],
    }
    md = markdown(data)
    if write:
        data["folder"] = store.save(name, data, md, root)
    return data, md


def markdown(d):
    L = [f"# Guest file: {d['name']}", "",
         f"Made on {d['made_on']} on the installation's own computer. Deleted after {d['delete_after']}.",
         "It was built from public web pages and is kept on this computer only. To build it, the name was",
         "sent to a web search engine.", ""]
    if d["thin"]:
        L += ["**Very little was found.** The room will get to know this guest by talking instead.", ""]
    L += ["## Reading", "", "| Trait | Guess (0 to 100) | Plus or minus | Starting point | Evidence |", "|---|---|---|---|---|"]
    names = {"O": "Openness", "C": "Conscientiousness", "E": "Extraversion", "A": "Agreeableness", "N": "Reactivity"}
    for t in rules.TRAITS:
        o = d["ocean_detail"][t]
        ev = f"{o['n_up']} up, {o['n_down']} down" + ("" if o["moved"] else " (too little, kept the starting point)")
        L.append(f"| {names[t]} | {o['pct']} | {o['range']} | {o['prior']} ({d['group']}) | {ev} |")
    L += ["", "These are guesses. Research on this method puts it at about r = 0.3: weak for one person.", ""]
    L += ["## First room", "", f"{d['hook'] or 'none chosen'}" + (f", then {d['hook_second']}" if d["hook_second"] else ""), ""]
    L += ["## In their own words", ""] + [f"- \"{q['text']}\" ({q['year'] or 'undated'}, {q['source']})" for q in d["quotes"]] + [""]
    L += ["## Facts", ""] + [f"- {f['year']}: {f['text']} ({f['source']})" for f in d["facts"]] + [""]
    if d.get("social"):
        c = d["social"]["counts"]
        L += ["## From their own download", "",
              f"{c.get('posts', 0)} posts, {c.get('comments', 0)} comments, {c.get('likes', 0)} likes, "
              f"{c.get('follows', 0)} follows. Names of accounts are not kept.", ""]
    L += ["## Pages read", ""] + [f"- {u}" for u in d["sources"]] + [""]
    if d["skipped_other_person"]:
        L += ["## Pages left out because they might be about someone else", ""] + [f"- {u}" for u in d["skipped_other_person"]] + [""]
    L += ["## Left out on purpose", "",
          "Sentences touching these topics were dropped unread into the file: "
          + (", ".join(f"{k} ({v})" for k, v in sorted(d["dropped_by_topic"].items())) or "none found") + ".", ""]
    return "\n".join(L)
