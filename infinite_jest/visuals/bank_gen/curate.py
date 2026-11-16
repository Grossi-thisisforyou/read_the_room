#!/usr/bin/env python3
"""Review the image bank in a web browser and throw out what you don't like.

    python3 curate.py sheet            # 1. make bank/contact_sheet.html (add --open to open it)
                                       # 2. in the browser: click Delete / Keep on pictures,
                                       #    then "Save list" (it lands in Downloads)
    python3 curate.py apply ~/Downloads/curate_list.txt
                                       # 3. carry out the list (asks before doing anything)
    python3 curate.py restore          # undo the last apply
    python3 curate.py empty-trash      # really delete what apply set aside

"Delete" moves the picture, its .json and its post-processed versions into
bank/.trash/ (the show never looks there), so nothing is lost until you empty
the trash. "Keep" marks a favourite: the generator's per-hook limit will never
delete it.

The list uses paths relative to the bank (like flesh/2026...png), so you can
make it on one machine and apply it on another that has the same bank, e.g.
review on the Mac, apply on the Pi.

Python standard library only. The page works offline, with no server.
"""
import argparse
import datetime
import html
import json
import os
import re
import shutil
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bankfiles  # noqa: E402

DEFAULT_BANK = os.path.normpath(os.path.join(HERE, "..", "bank"))
SHEET_NAME = "contact_sheet.html"
LIST_NAME = "curate_list.txt"
TRASH = ".trash"


class CurateError(Exception):
    pass


# ------------------------------------------------------------------ collect

def collect(bank, hooks=bankfiles.HOOKS, derived=False):
    """Every image in the bank as a dict for the sheet."""
    items = []
    for hook in hooks:
        hook_dir = os.path.join(bank, hook)
        paths = bankfiles.list_images(hook_dir)
        if derived:
            paths += bankfiles.list_images(os.path.join(hook_dir, bankfiles.DERIVED_DIR))
        for p in paths:
            meta = bankfiles.read_sidecar(p)
            base, variant = bankfiles.split_variant(os.path.basename(p))
            tags = meta.get("tag_list")
            if not isinstance(tags, list):
                tags = ["hook:" + hook]
            try:
                st = os.stat(p)
            except OSError:
                continue
            items.append({
                "path": os.path.relpath(p, bank).replace(os.sep, "/"),
                "hook": hook,
                "variant": variant or "original",
                "derived": os.path.basename(os.path.dirname(p)) == bankfiles.DERIVED_DIR,
                "tags": [str(t) for t in tags],
                "prompt": str(meta.get("prompt") or ""),
                "theme": meta.get("theme") or "",
                "keep": meta.get("keep") is True,
                "kb": int(st.st_size / 1024),
                "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                "mtime": st.st_mtime,
            })
    # newest first within each hook, each original followed by its versions
    rank = {"original": 0, "wide": 1, "mono": 2, "poster": 3, "cutout": 4}
    for i in items:
        i["base"] = bankfiles.split_variant(os.path.basename(i["path"]))[0]
    newest = {}
    for i in items:
        k = (i["hook"], i["base"])
        newest[k] = max(newest.get(k, 0), i["mtime"])
    items.sort(key=lambda i: (bankfiles.HOOKS.index(i["hook"]) if i["hook"] in bankfiles.HOOKS else 99,
                              -newest[(i["hook"], i["base"])], i["base"], rank.get(i["variant"], 9)))
    return items


# ------------------------------------------------------------------ sheet

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bank Contact Sheet</title>
<style>
:root {
  --bg: #121110; --panel: #1c1a18; --line: #34302c; --text: #ece6dc; --dim: #9a9187;
  --del: #d2452f; --keep: #6fae5a; --focus: #e8c27a;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #f3efe8; --panel: #ffffff; --line: #d8d0c4; --text: #1d1a17; --dim: #6b635a;
  }
}
:root[data-theme="light"] { --bg: #f3efe8; --panel: #ffffff; --line: #d8d0c4; --text: #1d1a17; --dim: #6b635a; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
header { position: sticky; top: 0; z-index: 5; background: var(--bg); border-bottom: 1px solid var(--line);
  padding: 10px 16px; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }
h1 { font-size: 16px; margin: 0 8px 0 0; letter-spacing: .04em; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
button, .chip { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--line);
  border-radius: 999px; padding: 4px 11px; cursor: pointer; }
.chip[aria-pressed="true"] { border-color: var(--focus); color: var(--focus); }
button.primary { background: var(--focus); color: #1d1a17; border-color: var(--focus); font-weight: 600; }
input[type=search] { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 9px; min-width: 200px; flex: 1 1 200px; max-width: 360px; }
select { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 4px; }
.count { color: var(--dim); }
.count b.d { color: var(--del); } .count b.k { color: var(--keep); }
.help { margin: 12px 16px 0; color: var(--dim); max-width: 70em; }
.help code { color: var(--text); background: var(--panel); padding: 1px 5px; border-radius: 4px; }
main { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; padding: 14px 16px 60px; }
.card { background: var(--panel); border: 2px solid transparent; border-radius: 8px; overflow: hidden;
  display: flex; flex-direction: column; }
.card.del { border-color: var(--del); } .card.del img { opacity: .35; filter: grayscale(1); }
.card.keep { border-color: var(--keep); }
.card img { display: block; width: 100%; aspect-ratio: 1 / 1; object-fit: cover; background: #000; cursor: zoom-in; }
.card .wide img { aspect-ratio: 16 / 9; }
.meta { padding: 6px 8px; font-size: 12px; color: var(--dim); flex: 1; }
.meta .tags { color: var(--text); word-break: break-word; }
.acts { display: flex; border-top: 1px solid var(--line); }
.acts button { flex: 1; border-radius: 0; border: 0; padding: 7px 0; background: transparent; }
.acts button + button { border-left: 1px solid var(--line); }
.card.del .b-del { background: var(--del); color: #fff; }
.card.keep .b-keep { background: var(--keep); color: #10200b; }
.hidden { display: none !important; }
#view { position: fixed; inset: 0; background: rgba(0,0,0,.92); z-index: 10; display: flex; flex-direction: column;
  align-items: center; justify-content: center; padding: 16px; gap: 10px; color: #ece6dc; }
#view img { max-width: 100%; max-height: 72vh; object-fit: contain; }
#view p { max-width: 60em; margin: 0; font-size: 13px; text-align: center; }
#view .keys { color: #9a9187; font-size: 12px; }
#view .vacts { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
#view.del img { opacity: .4; }
@media (max-width: 520px) { main { grid-template-columns: repeat(2, 1fr); gap: 8px; } h1 { width: 100%; } }
</style>
</head>
<body>
<header>
  <h1>INFINITE JEST · bank</h1>
  <div class="chips" id="hooks"></div>
  <input type="search" id="q" placeholder="filter: palette:papal, motif:barcode, words in the prompt…">
  <select id="show" aria-label="show">
    <option value="all">all</option><option value="unmarked">not marked yet</option>
    <option value="del">marked delete</option><option value="keep">marked keep</option>
  </select>
  <span class="count" id="count"></span>
  <button id="delvis" title="Mark every picture shown now for deletion">Delete all shown</button>
  <button id="clear">Clear marks</button>
  <button id="copy">Copy list</button>
  <button class="primary" id="save">Save list</button>
</header>
<p class="help">Click <b>Delete</b> on pictures you don't want and <b>Keep</b> on favourites (the generator's
limit will never remove those). Click a picture to see it large: there, <b>D</b> = delete, <b>K</b> = keep,
arrow keys = next/previous, <b>Esc</b> = close. Marks are remembered in this browser. When you are done press
<b>Save list</b>, then in the terminal run <code>python3 curate.py apply ~/Downloads/__LIST__</code>.
Nothing is deleted until then. __SUMMARY__</p>
<main id="grid">
__CARDS__
</main>
<div id="view" class="hidden" role="dialog" aria-modal="true">
  <img id="vimg" alt="">
  <p id="vtags"></p>
  <p id="vprompt"></p>
  <div class="vacts"><button id="vprev">‹ previous</button><button id="vdel">Delete (D)</button>
  <button id="vkeep">Keep (K)</button><button id="vnext">next ›</button><button id="vclose">Close (Esc)</button></div>
  <p class="keys" id="vpath"></p>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
  var DATA = JSON.parse(document.getElementById("data").textContent);
  var KEY = "ij-curate:" + DATA.bank;
  var marks = {};
  try { marks = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { marks = {}; }
  var cards = Array.prototype.slice.call(document.querySelectorAll(".card"));
  var byPath = {};
  DATA.items.forEach(function (it, i) { it.el = cards[i]; byPath[it.path] = it; });
  var hook = "all", viewIdx = -1;

  function state(it) {
    if (marks[it.path]) return marks[it.path];
    return it.keep ? "keep" : "";
  }
  function store() { try { localStorage.setItem(KEY, JSON.stringify(marks)); } catch (e) {} }
  function setMark(it, m) {
    var cur = state(it);
    var next = (cur === m) ? "" : m;
    if (next === (it.keep ? "keep" : "")) delete marks[it.path];
    else marks[it.path] = next || "none";
    paint(it); count(); store();
  }
  function paint(it) {
    var s = state(it);
    it.el.classList.toggle("del", s === "del");
    it.el.classList.toggle("keep", s === "keep");
  }
  function visible() { return DATA.items.filter(function (it) { return !it.el.classList.contains("hidden"); }); }
  function count() {
    var d = 0, k = 0;
    DATA.items.forEach(function (it) { var s = state(it); if (s === "del") d++; if (s === "keep") k++; });
    document.getElementById("count").innerHTML = visible().length + " shown · <b class=d>" + d +
      " to delete</b> · <b class=k>" + k + " kept</b>";
  }
  function filter() {
    var q = document.getElementById("q").value.toLowerCase().trim().split(/[\\s,]+/).filter(Boolean);
    var show = document.getElementById("show").value;
    DATA.items.forEach(function (it) {
      var hay = (it.tags.join(" ") + " " + it.prompt + " " + it.path + " variant:" + it.variant).toLowerCase();
      var s = state(it);
      var ok = (hook === "all" || it.hook === hook) && q.every(function (w) { return hay.indexOf(w) >= 0; }) &&
        (show === "all" || (show === "unmarked" ? !s : s === show));
      it.el.classList.toggle("hidden", !ok);
    });
    count();
  }
  function listText() {
    var lines = ["# INFINITE JEST curate list, " + new Date().toISOString().slice(0, 16).replace("T", " "),
                 "# apply with:  python3 curate.py apply " + DATA.list_name];
    DATA.items.forEach(function (it) {
      var m = marks[it.path];
      if (m === "del") lines.push("delete " + it.path);
      else if (m === "keep") lines.push("keep " + it.path);
      else if (m === "none" && it.keep) lines.push("unkeep " + it.path);
    });
    return lines.join("\\n") + "\\n";
  }
  // hook chips
  var hooksEl = document.getElementById("hooks");
  ["all"].concat(DATA.hooks).forEach(function (h) {
    var n = h === "all" ? DATA.items.length : DATA.items.filter(function (it) { return it.hook === h; }).length;
    var b = document.createElement("button");
    b.className = "chip"; b.textContent = h + " " + n; b.setAttribute("aria-pressed", h === hook);
    b.onclick = function () {
      hook = h;
      Array.prototype.forEach.call(hooksEl.children, function (c) { c.setAttribute("aria-pressed", c === b); });
      filter();
    };
    hooksEl.appendChild(b);
  });
  // cards
  DATA.items.forEach(function (it, i) {
    paint(it);
    it.el.querySelector(".b-del").onclick = function () { setMark(it, "del"); };
    it.el.querySelector(".b-keep").onclick = function () { setMark(it, "keep"); };
    it.el.querySelector("img").onclick = function () { openView(i); };
  });
  document.getElementById("q").oninput = filter;
  document.getElementById("show").onchange = filter;
  document.getElementById("delvis").onclick = function () {
    var v = visible();
    if (!v.length || !confirm("Mark all " + v.length + " shown pictures for deletion?")) return;
    v.forEach(function (it) { if (state(it) !== "del") { marks[it.path] = "del"; paint(it); } });
    count(); store();
  };
  document.getElementById("clear").onclick = function () {
    if (!confirm("Forget all marks made on this page?")) return;
    marks = {}; DATA.items.forEach(paint); count(); store();
  };
  document.getElementById("save").onclick = function () {
    var blob = new Blob([listText()], { type: "text/plain" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = DATA.list_name;
    document.body.appendChild(a); a.click(); a.remove();
  };
  document.getElementById("copy").onclick = function () {
    var t = listText();
    if (navigator.clipboard) navigator.clipboard.writeText(t).then(function () { alert("List copied."); },
      function () { prompt("Copy this list:", t); });
    else prompt("Copy this list:", t);
  };
  // big view
  var view = document.getElementById("view");
  function openView(i) {
    viewIdx = i; var it = DATA.items[i];
    document.getElementById("vimg").src = it.path;
    document.getElementById("vtags").textContent = it.tags.join("  ");
    document.getElementById("vprompt").textContent = it.prompt;
    document.getElementById("vpath").textContent = it.path + " · " + it.date + " · " + it.kb + " KB";
    view.classList.toggle("del", state(it) === "del");
    document.getElementById("vdel").textContent = state(it) === "del" ? "Undo delete (D)" : "Delete (D)";
    document.getElementById("vkeep").textContent = state(it) === "keep" ? "Unkeep (K)" : "Keep (K)";
    view.classList.remove("hidden");
  }
  function step(d) {
    var v = visible(); if (!v.length) return;
    var pos = v.indexOf(DATA.items[viewIdx]);
    var next = v[(pos + d + v.length) % v.length];
    openView(DATA.items.indexOf(next));
  }
  function closeView() { view.classList.add("hidden"); viewIdx = -1; }
  document.getElementById("vclose").onclick = closeView;
  document.getElementById("vnext").onclick = function () { step(1); };
  document.getElementById("vprev").onclick = function () { step(-1); };
  document.getElementById("vdel").onclick = function () { setMark(DATA.items[viewIdx], "del"); openView(viewIdx); };
  document.getElementById("vkeep").onclick = function () { setMark(DATA.items[viewIdx], "keep"); openView(viewIdx); };
  view.onclick = function (e) { if (e.target === view) closeView(); };
  document.addEventListener("keydown", function (e) {
    if (viewIdx < 0) return;
    var k = e.key.toLowerCase();
    if (k === "escape") closeView();
    else if (k === "arrowright") step(1);
    else if (k === "arrowleft") step(-1);
    else if (k === "d") { setMark(DATA.items[viewIdx], "del"); step(1); }
    else if (k === "k") { setMark(DATA.items[viewIdx], "keep"); openView(viewIdx); }
  });
  filter();
})();
</script>
</body>
</html>
"""


def _card(it):
    e = html.escape
    tags = " ".join(t.split(":", 1)[-1] for t in it["tags"] if not t.startswith("hook:"))
    cls = "card"
    inner = "wide" if it["variant"] in ("wide", "mono", "poster") else ""
    return ('<div class="%s"><div class="%s"><img loading="lazy" src="%s" alt="%s"></div>'
            '<div class="meta"><div class="tags">%s</div>%s · %s%s</div>'
            '<div class="acts"><button class="b-del">Delete</button><button class="b-keep">Keep</button></div></div>'
            % (cls, inner, e(it["path"], quote=True), e(it["prompt"][:120], quote=True),
               e(tags or it["hook"]), e(it["hook"]), e(it["date"]),
               (" · " + e(it["variant"])) if it["variant"] != "original" else ""))


def build_sheet(bank, out=None, hooks=bankfiles.HOOKS, derived=False):
    """Write the contact sheet; returns (path, number of images)."""
    bank = os.path.abspath(bank)
    out = out or os.path.join(bank, SHEET_NAME)
    items = collect(bank, hooks, derived)
    # image links are relative to the page, so the page must sit in the bank
    # or the links are rewritten relative to wherever it goes
    rel = os.path.relpath(bank, os.path.dirname(os.path.abspath(out)))
    if rel != ".":
        for it in items:
            it["path"] = (rel.replace(os.sep, "/") + "/" + it["path"])
    data = {
        "bank": bank,
        "list_name": LIST_NAME,
        "hooks": [h for h in hooks if any(i["hook"] == h for i in items)],
        "items": [{k: it[k] for k in ("path", "hook", "variant", "tags", "prompt", "keep", "date", "kb")}
                  for it in items],
    }
    if rel != ".":  # the list must hold bank-relative paths
        data["prefix"] = rel.replace(os.sep, "/") + "/"
    # "<" escaped so no text in a prompt can end the <script> block early
    blob = json.dumps(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    per_hook = ", ".join("%s %d" % (h, sum(1 for i in items if i["hook"] == h)) for h in data["hooks"])
    summary = html.escape("%d pictures (%s), made %s." % (
        len(items), per_hook or "none", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    subs = {"CARDS": "\n".join(_card(i) for i in items), "DATA": blob,
            "LIST": LIST_NAME, "SUMMARY": summary}
    # one pass, so text inside a prompt is never itself replaced
    page = re.sub(r"__(CARDS|DATA|LIST|SUMMARY)__", lambda m: subs[m.group(1)], PAGE)
    if rel != ".":  # strip the prefix again when writing the list
        page = page.replace('var m = marks[it.path];',
                            'var m = marks[it.path]; var p = it.path.slice(DATA.prefix.length);')
        page = page.replace('lines.push("delete " + it.path)', 'lines.push("delete " + p)')
        page = page.replace('lines.push("keep " + it.path)', 'lines.push("keep " + p)')
        page = page.replace('lines.push("unkeep " + it.path)', 'lines.push("unkeep " + p)')
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, out)
    return out, len(items)


# ------------------------------------------------------------------ list

def parse_list(text):
    """-> list of (action, relative path). Bare paths mean delete."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        action, _, rest = line.partition(" ")
        if action not in ("delete", "keep", "unkeep"):
            action, rest = "delete", line
        rest = rest.strip()
        if not rest:
            raise CurateError("line %d: no picture named" % n)
        out.append((action, rest))
    return out


def resolve(bank, rel):
    """Bank-relative path -> absolute path, refusing anything outside the bank."""
    bank = os.path.realpath(bank)
    if os.path.isabs(rel) or rel.startswith("~"):
        raise CurateError("%s: paths must be relative to the bank (like flesh/x.png)" % rel)
    p = os.path.realpath(os.path.join(bank, rel))
    if os.path.commonpath([bank, p]) != bank or p == bank:
        raise CurateError("%s: outside the bank, refused" % rel)
    parts = os.path.relpath(p, bank).split(os.sep)
    if parts[0] not in bankfiles.HOOKS or not bankfiles.is_image(parts[-1]):
        raise CurateError("%s: not a picture in a hook folder, refused" % rel)
    return p


def files_for(bank, path):
    """The picture, its sidecar and (for originals) every version made from it."""
    out = [path]
    side = bankfiles.sidecar_path(path)
    if os.path.exists(side):
        out.append(side)
    base, variant = bankfiles.split_variant(os.path.basename(path))
    if variant is None:
        d = os.path.dirname(path)
        hook_dir = os.path.dirname(d) if os.path.basename(d) == bankfiles.DERIVED_DIR else d
        out += bankfiles.derived_files(hook_dir, base)
        # a 16:9 copy promoted into the hook folder takes its moved original along
        moved = os.path.join(hook_dir, bankfiles.DERIVED_DIR, base)
        for ext in bankfiles.IMAGE_EXT + (".json",):
            if os.path.exists(moved + ext):
                out.append(moved + ext)
    elif variant == "wide" and bankfiles.read_sidecar(path).get("derived_from", "").startswith(
            bankfiles.DERIVED_DIR + "/"):
        # deleting a promoted 16:9 copy deletes the original behind it too
        hook_dir = os.path.dirname(path)
        orig = os.path.join(hook_dir, bankfiles.read_sidecar(path)["derived_from"])
        if os.path.exists(orig):
            out += files_for(bank, orig)
    seen, uniq = set(), []
    for p in out:
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def plan(bank, entries):
    """Check every entry; -> (deletes [(rel, [files])], keeps [path], unkeeps [path], problems)."""
    deletes, keeps, unkeeps, problems = [], [], [], []
    for action, rel in entries:
        try:
            p = resolve(bank, rel)
        except CurateError as e:
            problems.append(str(e))
            continue
        if not os.path.exists(p):
            problems.append("%s: not found (already deleted?)" % rel)
            continue
        if action == "delete":
            deletes.append((rel, files_for(bank, p)))
        elif action == "keep":
            keeps.append(p)
        else:
            unkeeps.append(p)
    return deletes, keeps, unkeeps, problems


def set_keep(path, keep):
    side = bankfiles.sidecar_path(path)
    meta = bankfiles.read_sidecar(path)
    if keep:
        meta["keep"] = True
    else:
        meta.pop("keep", None)
    bankfiles.write_json_atomic(side, meta)


def apply(bank, entries, batch=None, out=print):
    """Carry out a parsed list. Returns the trash batch folder (or None)."""
    bank = os.path.abspath(bank)
    deletes, keeps, unkeeps, problems = plan(bank, entries)
    for p in keeps:
        set_keep(p, True)
    for p in unkeeps:
        set_keep(p, False)
    batch_dir = None
    moved = []
    if deletes:
        batch = batch or time.strftime("%Y%m%d-%H%M%S")
        batch_dir = os.path.join(bank, TRASH, batch)
        n = 1
        while os.path.exists(batch_dir):
            n += 1
            batch_dir = os.path.join(bank, TRASH, "%s-%d" % (batch, n))
        for _rel, files in deletes:
            for f in files:
                if not os.path.exists(f):
                    continue
                r = os.path.relpath(f, bank)
                dst = os.path.join(batch_dir, r)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(f, dst)
                moved.append(r.replace(os.sep, "/"))
        bankfiles.write_json_atomic(os.path.join(batch_dir, "manifest.json"),
                                    {"moved": moved, "when": bankfiles.now_iso()})
    out("moved %d picture(s) (%d files) to %s; kept %d; un-kept %d" % (
        len(deletes), len(moved), os.path.relpath(batch_dir, bank) if batch_dir else "trash", len(keeps), len(unkeeps)))
    for msg in problems:
        out("  skipped: " + msg)
    return batch_dir


def batches(bank):
    d = os.path.join(bank, TRASH)
    try:
        return sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n, "manifest.json")))
    except OSError:
        return []


def restore(bank, batch=None, out=print):
    names = batches(bank)
    if not names:
        raise CurateError("nothing to restore: the trash is empty")
    batch = batch or names[-1]
    if batch not in names:
        raise CurateError("no trash batch called %s (have: %s)" % (batch, ", ".join(names)))
    bdir = os.path.join(bank, TRASH, batch)
    with open(os.path.join(bdir, "manifest.json")) as f:
        moved = json.load(f).get("moved", [])
    back, clash = 0, []
    for r in moved:
        src = os.path.join(bdir, r)
        dst = os.path.join(bank, r)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            clash.append(r)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        back += 1
    if not clash:
        shutil.rmtree(bdir, ignore_errors=True)
    out("put back %d file(s) from %s%s" % (back, batch, "; %d already existed and were left in the trash" % len(clash)
                                         if clash else ""))
    return back


def trash_size(bank):
    total, files = 0, 0
    for root, _dirs, names in os.walk(os.path.join(bank, TRASH)):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                pass
    return files, total


def confirm(question, yes):
    if yes:
        return True
    if not sys.stdin.isatty():
        print("Not asking without a terminal; add --yes to go ahead.")
        return False
    try:
        return input(question + " Type yes and press Enter: ").strip().lower() in ("yes", "y")
    except EOFError:
        return False


def find_list(given):
    if given:
        p = os.path.expanduser(given)
        if not os.path.isfile(p):
            raise CurateError("list not found: %s" % p)
        return p
    # newest curate_list*.txt in Downloads (browsers add (1), (2) ... to repeats)
    dl = os.path.expanduser("~/Downloads")
    try:
        cands = [os.path.join(dl, n) for n in os.listdir(dl)
                 if n.startswith("curate_list") and n.endswith(".txt")]
    except OSError:
        cands = []
    if not cands:
        raise CurateError("no list given and no curate_list*.txt in ~/Downloads")
    return max(cands, key=os.path.getmtime)


# ------------------------------------------------------------------ cli

def main(argv=None):
    p = argparse.ArgumentParser(description="Review the image bank and remove pictures you don't want.")
    p.add_argument("--bank", default=DEFAULT_BANK, help="bank folder (default: %(default)s)")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("sheet", help="make the contact sheet page")
    s.add_argument("--out", help="where to write it (default: <bank>/%s)" % SHEET_NAME)
    s.add_argument("--hook", choices=bankfiles.HOOKS, action="append")
    s.add_argument("--derived", action="store_true", help="also show the post-processed versions")
    s.add_argument("--open", action="store_true", help="open it in the web browser")
    a_ = sub.add_parser("apply", help="carry out a saved list")
    a_.add_argument("list", nargs="?", help="the saved list (default: newest curate_list*.txt in ~/Downloads)")
    a_.add_argument("--yes", action="store_true", help="don't ask first")
    a_.add_argument("--dry-run", action="store_true", help="only say what would happen")
    r = sub.add_parser("restore", help="put back what the last apply moved to the trash")
    r.add_argument("--batch", help="a particular trash batch (folder name in bank/.trash)")
    e = sub.add_parser("empty-trash", help="really delete everything in the trash")
    e.add_argument("--yes", action="store_true")
    a = p.parse_args(argv)
    bank = os.path.abspath(os.path.expanduser(a.bank))
    if not a.cmd:
        p.print_help()
        return 2
    if not os.path.isdir(bank):
        print("bank folder not found: %s" % bank)
        return 2
    try:
        if a.cmd == "sheet":
            out, n = build_sheet(bank, a.out, a.hook or bankfiles.HOOKS, a.derived)
            url = "file://" + os.path.abspath(out)
            print("contact sheet with %d pictures: %s" % (n, url))
            if a.open:
                webbrowser.open(url)
            else:
                print("open it in a web browser (on a Mac: open \"%s\")" % out)
            return 0
        if a.cmd == "apply":
            path = find_list(a.list)
            with open(path, encoding="utf-8") as f:
                entries = parse_list(f.read())
            deletes, keeps, unkeeps, problems = plan(bank, entries)
            print("list: %s" % path)
            print("  %d picture(s) to delete (%d files incl. sidecars and versions), %d to keep, %d to un-keep"
                  % (len(deletes), sum(len(f) for _r, f in deletes), len(keeps), len(unkeeps)))
            for msg in problems:
                print("  will skip: " + msg)
            if a.dry_run:
                for rel, files in deletes:
                    print("  delete %s (+%d)" % (rel, len(files) - 1))
                return 0
            if not (deletes or keeps or unkeeps):
                print("nothing to do")
                return 0
            if not confirm("Deleted pictures go to the trash (undo with: curate.py restore).", a.yes):
                print("nothing changed")
                return 1
            apply(bank, entries)
            print("done. Rebuild the page with: python3 curate.py sheet")
            return 0
        if a.cmd == "restore":
            restore(bank, a.batch)
            return 0
        if a.cmd == "empty-trash":
            files, size = trash_size(bank)
            if not files:
                print("the trash is empty")
                return 0
            if not confirm("Really delete %d file(s), %.1f MB, for good?" % (files, size / 1e6), a.yes):
                print("nothing changed")
                return 1
            shutil.rmtree(os.path.join(bank, TRASH))
            print("trash emptied")
            return 0
    except CurateError as e:
        print("problem: %s" % e)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
