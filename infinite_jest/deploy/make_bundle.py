#!/usr/bin/env python3
"""Build the Infinite Jest offline install bundle.

Run this on a computer WITH internet (Baby's Mac, or any Linux machine). It
downloads everything the Raspberry Pi needs and puts it in one folder, usually
on a USB stick. On the Pi, with no network at all:

    sudo mount -L IJ /mnt && sudo bash /mnt/IJ-BUNDLE/INSTALL.sh

What goes into the bundle:

  debs/<release>/   every .deb the Pi needs (and everything those need),
                    for 64-bit Raspberry Pi OS. By default both releases:
                    trixie (images from Oct 2025 on) and bookworm (older).
  src/              llama.cpp source (and stable-diffusion.cpp with --images),
                    pinned versions, checked by SHA-256. Compiled on the Pi.
  models/           the Qwen language model (and SD-Turbo with --images).
  code/             this repo's infinite_jest/ folder as it is right now.
  INSTALL.sh        the one command to run on the Pi.

Only Python's standard library and `curl` are used, both built into macOS.
Every download resumes if interrupted; run it again and it continues.

    python3 make_bundle.py --out /Volumes/IJ             # usual
    python3 make_bundle.py --out /Volumes/IJ --images    # + image generator (5.2 GB more)
    python3 make_bundle.py --help
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

try:
    import lzma
except ImportError:  # some odd Python builds lack it; we fall back to .gz
    lzma = None

HERE = os.path.dirname(os.path.abspath(__file__))
IJ_DIR = os.path.dirname(HERE)  # .../infinite_jest
BUNDLE_FORMAT = 1

# --------------------------------------------------------------- what we need

# apt packages the Pi needs, by job. Names are the same on bookworm and trixie.
APT_PACKAGES = {
    "engine": ["python3-aiohttp", "python3-pygame", "python3-numpy", "alsa-utils"],
    "faces": ["python3-opencv", "opencv-data"],
    "build": ["build-essential", "cmake", "curl", "ca-certificates"],
    "tools": ["rfkill", "iw", "wireless-regdb", "exfatprogs", "kbd"],
    "look": ["plymouth", "console-setup"],   # boot splash (infinite_jest/case/install.sh)
}

# Package repositories, per OS release. A release is what Raspberry Pi OS is
# built on: images from October 2025 on are "trixie" (Debian 13), older
# images are "bookworm" (Debian 12).
DEBIAN = "https://deb.debian.org/debian"
SECURITY = "https://deb.debian.org/debian-security"
RPI = "https://archive.raspberrypi.com/debian"
PROFILES = {
    "trixie": [
        (DEBIAN, "trixie", ["main", "contrib", "non-free", "non-free-firmware"]),
        (DEBIAN, "trixie-updates", ["main", "contrib", "non-free", "non-free-firmware"]),
        (SECURITY, "trixie-security", ["main", "contrib", "non-free", "non-free-firmware"]),
        (RPI, "trixie", ["main"]),
    ],
    "bookworm": [
        (DEBIAN, "bookworm", ["main", "contrib", "non-free", "non-free-firmware"]),
        (DEBIAN, "bookworm-updates", ["main", "contrib", "non-free", "non-free-firmware"]),
        (SECURITY, "bookworm-security", ["main", "contrib", "non-free", "non-free-firmware"]),
        (RPI, "bookworm", ["main"]),
    ],
    # Used only by the automated test (an Ubuntu arm64 container stands in for
    # the Pi where Debian mirrors are out of reach). Not for the real Pi.
    "test-ubuntu-noble": [
        ("https://ports.ubuntu.com/ubuntu-ports", "noble", ["main", "universe"]),
        ("https://ports.ubuntu.com/ubuntu-ports", "noble-updates", ["main", "universe"]),
        ("https://ports.ubuntu.com/ubuntu-ports", "noble-security", ["main", "universe"]),
    ],
}
DEFAULT_RELEASES = ["trixie", "bookworm"]

# Pinned sources. The PyPI source packages of the Python bindings carry the
# complete C++ source of llama.cpp and stable-diffusion.cpp (with ggml), so one
# file each, fixed version, fixed checksum, from a host that never moves files.
SOURCES = {
    "llama": {
        "file": "llama_cpp_python-0.3.36.tar.gz",
        "url": "https://files.pythonhosted.org/packages/ec/e9/e7de2b0463ea3ffbf0ede6cb21b58c1258a8f6521aae45ca773a59fe7cf3/llama_cpp_python-0.3.36.tar.gz",
        "sha256": "832db0699007f1be95a7e41ef12e88926b02ba836461e36a36372db2760c1a2e",
        "size": 76589250,
        "subdir": "llama_cpp_python-0.3.36/vendor/llama.cpp",
    },
    "sd": {
        "file": "stable_diffusion_cpp_python-0.4.7.tar.gz",
        "url": "https://files.pythonhosted.org/packages/b1/06/300aba9ac36e2166fbe45b4a29039a76f725ef08796f5472caf3e8c4e08d/stable_diffusion_cpp_python-0.4.7.tar.gz",
        "sha256": "998d1957260dd5ae4e18a8acc0c14b0a8757aaa9f96515197b6d5bbf46df9282",
        "size": 20561087,
        "subdir": "stable_diffusion_cpp_python-0.4.7/vendor/stable-diffusion.cpp",
    },
}

# Language models. Each has mirrors tried in order. "dockerhub:" sources are
# OCI model artifacts on Docker Hub (same GGUF files), used if Hugging Face
# is unreachable.
MODELS = {
    "qwen2.5-1.5b": {
        "file": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "min_size": 900000000,
        "sources": [
            "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        ],
        "fallback": "qwen2.5-3b",
        "about": "Qwen2.5 1.5B Instruct, 4-bit (about 1.1 GB). Fast on a Pi 5. Apache 2.0.",
    },
    "qwen2.5-3b": {
        "file": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "min_size": 1700000000,
        "sources": [
            "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
            "dockerhub:ai/qwen2.5:3B-Q4_K_M",
        ],
        "about": "Qwen2.5 3B Instruct, 4-bit (about 2 GB). Better words, about half as fast. Qwen Research license.",
    },
    # test-only: small, from Docker Hub, used by the automated container test
    "test-qwen2.5-0.5b": {
        "file": "qwen2.5-0.5b-instruct-f16.gguf",
        "min_size": 900000000,
        "sources": ["dockerhub:ai/qwen2.5:0.5B-F16"],
        "about": "test only",
    },
}
SD_MODEL = {
    "file": "sd_turbo.safetensors",
    "min_size": 5000000000,
    "sources": ["https://huggingface.co/stabilityai/sd-turbo/resolve/main/sd_turbo.safetensors"],
    "about": "SD-Turbo (Stability AI Community License), 5.2 GB.",
}

# --------------------------------------------------------------- small helpers

def say(msg):
    print("\n\033[1m==> %s\033[0m" % msg, flush=True)


def info(msg):
    print("    " + msg, flush=True)


def die(msg):
    print("\n\033[31mSTOPPED: %s\033[0m\n" % msg, file=sys.stderr, flush=True)
    sys.exit(1)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" if unit in ("B", "KB") else "%.1f %s") % (n, unit)
        n /= 1024.0


def sha256_of(path, bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def curl(url, dest, headers=(), quiet=False, resume=True, tries=5):
    """Download with curl (built into macOS; uses the system's certificates)."""
    part = dest + ".part"
    cmd = ["curl", "--fail", "--location", "--retry", "5", "--retry-delay", "3",
           "--connect-timeout", "30", "--output", part]
    if resume and os.path.exists(part):
        cmd += ["--continue-at", "-"]
    cmd += ["--silent", "--show-error"] if quiet else ["--progress-bar"]
    for h in headers:
        cmd += ["--header", h]
    cmd.append(url)
    for attempt in range(1, tries + 1):
        r = subprocess.call(cmd)
        if r == 0:
            os.replace(part, dest)
            return True
        if r == 33 and resume:  # server doesn't support resume: start over
            try:
                os.remove(part)
            except OSError:
                pass
            cmd = [c for c in cmd if c not in ("--continue-at", "-")]
        elif r == 22:  # HTTP error (404 etc.): no point retrying
            return False
        time.sleep(min(30, 3 * attempt))
    return False


def fetch_bytes(url, headers=()):
    cmd = ["curl", "--fail", "--location", "--silent", "--show-error",
           "--retry", "4", "--connect-timeout", "30"]
    for h in headers:
        cmd += ["--header", h]
    cmd.append(url)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return None
    return p.stdout


# --------------------------------------------------------------- Debian versions

def _order(c):
    if c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    if c == "~":
        return -1
    if c:
        return ord(c) + 256
    return 0


def _cmp_part(a, b):
    """dpkg's verrevcmp."""
    i = j = 0
    while i < len(a) or j < len(b):
        first_diff = 0
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = _order(a[i]) if i < len(a) else 0
            bc = _order(b[j]) if j < len(b) else 0
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def split_version(v):
    epoch = 0
    if ":" in v:
        e, v = v.split(":", 1)
        epoch = int(e)
    if "-" in v:
        up, rev = v.rsplit("-", 1)
    else:
        up, rev = v, ""
    return epoch, up, rev


def vcmp(a, b):
    ea, ua, ra = split_version(a)
    eb, ub, rb = split_version(b)
    if ea != eb:
        return ea - eb
    c = _cmp_part(ua, ub)
    if c:
        return c
    return _cmp_part(ra, rb)


def satisfies(version, op, want):
    if op is None:
        return True
    c = vcmp(version, want)
    return {"<<": c < 0, "<=": c <= 0, "=": c == 0, ">=": c >= 0, ">>": c > 0,
            "<": c <= 0, ">": c >= 0}[op]


# --------------------------------------------------------------- package index

def parse_stanzas(text):
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        d = {}
        key = None
        for line in block.split("\n"):
            if not line:
                continue
            if line[0] in " \t" and key:
                d[key] += "\n" + line
            else:
                k, _, v = line.partition(":")
                key = k.strip()
                d[key] = v.strip()
        if "Package" in d:
            yield d, block.strip()


DEP_RE = re.compile(r"^\s*([a-z0-9][a-z0-9+.\-]*)(?::[a-z0-9]+)?\s*(?:\(\s*(<<|<=|=|>=|>>|<|>)\s*([^)\s]+)\s*\))?\s*(?:\[[^\]]*\])?\s*(?:<[^>]*>)?\s*$")


def parse_deps(field):
    groups = []
    if not field:
        return groups
    for group in field.split(","):
        alts = []
        for alt in group.split("|"):
            m = DEP_RE.match(alt)
            if m:
                alts.append((m.group(1), m.group(2), m.group(3)))
        if alts:
            groups.append(alts)
    return groups


class Index(object):
    def __init__(self, arch):
        self.arch = arch
        self.pkgs = {}        # name -> best candidate dict
        self.provides = {}    # virtual name -> list of (provider name, provided version or None)

    def add(self, stanza, raw, base_url):
        if stanza.get("Architecture") not in (self.arch, "all"):
            return
        name = stanza["Package"]
        cur = self.pkgs.get(name)
        if cur is None or vcmp(stanza["Version"], cur["Version"]) > 0:
            stanza = dict(stanza)
            stanza["_raw"] = raw
            stanza["_base"] = base_url
            self.pkgs[name] = stanza

    def finish(self):
        self.provides = {}
        for name, st in self.pkgs.items():
            for alts in parse_deps(st.get("Provides", "")):
                for vname, op, ver in alts:
                    self.provides.setdefault(vname, []).append((name, ver if op == "=" else None))

    def candidates(self, name, op, ver):
        """Real or virtual packages that satisfy (name op ver), best first."""
        out = []
        st = self.pkgs.get(name)
        if st is not None and satisfies(st["Version"], op, ver):
            out.append(name)
        for prov, pver in sorted(self.provides.get(name, [])):
            if prov in out:
                continue
            if op is None or (pver is not None and satisfies(pver, op, ver)):
                out.append(prov)
        return out


def load_index(profile, arch, cache_dir):
    idx = Index(arch)
    for base, dist, comps in PROFILES[profile]:
        for comp in comps:
            stem = "%s/dists/%s/%s/binary-%s/Packages" % (base, dist, comp, arch)
            key = re.sub(r"[^A-Za-z0-9]+", "_", stem.split("://", 1)[1])
            cached = os.path.join(cache_dir, key)
            text = None
            if os.path.exists(cached) and time.time() - os.path.getmtime(cached) < 6 * 3600:
                with open(cached, "rb") as f:
                    text = f.read().decode("utf-8", "replace")
            else:
                for ext, dec in ((".xz", lzma.decompress if lzma else None),
                                 (".gz", gzip.decompress), ("", lambda b: b)):
                    if dec is None:
                        continue
                    data = fetch_bytes(stem + ext)
                    if data:
                        raw = dec(data)
                        with open(cached, "wb") as f:
                            f.write(raw)
                        text = raw.decode("utf-8", "replace")
                        break
            if text is None:
                info("(no %s %s/%s index, skipping)" % (dist, comp, arch))
                continue
            n = 0
            for st, raw in parse_stanzas(text):
                idx.add(st, raw, base)
                n += 1
            info("%-18s %-17s %6d packages" % (dist, comp, n))
    idx.finish()
    if not idx.pkgs:
        die("Could not download any package list. Is this computer online?")
    return idx


def resolve(idx, wanted):
    """Everything `wanted` needs, recursively (Depends + Pre-Depends).

    Deliberately generous: it takes the whole dependency closure, including
    packages the Pi almost certainly has already. apt on the Pi only installs
    what is actually missing, so extras cost only space, while a missing
    package would stop the install.
    """
    chosen = {}
    missing = []
    queue = []
    for name in wanted:
        c = idx.candidates(name, None, None)
        if not c:
            missing.append(name)
            continue
        queue.append(c[0])
    while queue:
        name = queue.pop()
        if name in chosen:
            continue
        st = idx.pkgs[name]
        chosen[name] = st
        for field in ("Pre-Depends", "Depends"):
            for alts in parse_deps(st.get(field, "")):
                # already satisfied by something we chose?
                done = False
                for n, op, v in alts:
                    for c in idx.candidates(n, op, v):
                        if c in chosen or c in queue:
                            done = True
                            break
                    if done:
                        break
                if done:
                    continue
                pick = None
                for n, op, v in alts:
                    c = idx.candidates(n, op, v)
                    if c:
                        pick = c[0]
                        break
                if pick is None:
                    missing.append("%s (needed by %s)" % (" | ".join(a[0] for a in alts), name))
                else:
                    queue.append(pick)
    return chosen, missing


# --------------------------------------------------------------- bundle steps

def do_debs(out, profile, cache_dir, groups):
    say("Packages for Raspberry Pi OS %s (64-bit)" % profile)
    idx = load_index(profile, "arm64", cache_dir)
    wanted = []
    for g in groups:
        wanted += APT_PACKAGES[g]
    chosen, missing = resolve(idx, wanted)
    if missing:
        die("These packages could not be found for %s:\n      %s" % (profile, "\n      ".join(missing)))
    total = sum(int(st.get("Size", 0)) for st in chosen.values())
    info("%d packages, %s in total" % (len(chosen), human(total)))
    ddir = os.path.join(out, "debs", profile)
    os.makedirs(ddir, exist_ok=True)
    keep = set()
    stanzas = []
    done = 0
    for name in sorted(chosen):
        st = chosen[name]
        fn = os.path.basename(st["Filename"])
        keep.add(fn)
        dest = os.path.join(ddir, fn)
        want_sha = st.get("SHA256")
        if os.path.exists(dest) and os.path.getsize(dest) == int(st["Size"]) and \
                (not want_sha or sha256_of(dest) == want_sha):
            pass
        else:
            url = st["_base"] + "/" + st["Filename"]
            ok = curl(url, dest, quiet=True)
            if not ok:
                die("Could not download %s" % url)
            if want_sha and sha256_of(dest) != want_sha:
                os.remove(dest)
                die("Checksum mismatch for %s (download corrupted?). Run again." % fn)
        before = done * 20 // max(total, 1)
        done += int(st["Size"])
        if done * 20 // max(total, 1) != before or done == total:
            sys.stdout.write("\r    downloaded %s of %s   " % (human(done), human(total)))
            sys.stdout.flush()
        raw = re.sub(r"(?m)^Filename: .*$", "Filename: ./" + fn, st["_raw"])
        stanzas.append(raw)
    print()
    # drop stale files from an older run
    for fn in os.listdir(ddir):
        if fn.endswith(".deb") and fn not in keep:
            os.remove(os.path.join(ddir, fn))
    text = "\n\n".join(stanzas) + "\n"
    with open(os.path.join(ddir, "Packages"), "w") as f:
        f.write(text)
    with gzip.open(os.path.join(ddir, "Packages.gz"), "wb") as f:
        f.write(text.encode("utf-8"))
    with open(os.path.join(ddir, "wanted.txt"), "w") as f:
        f.write("\n".join(wanted) + "\n")
    return {"packages": len(chosen), "bytes": total, "wanted": wanted}


def dockerhub_url(ref):
    """'ai/qwen2.5:3B-Q4_K_M' -> (blob url, auth header) of its GGUF layer."""
    repo, tag = ref.split(":", 1)
    tok = fetch_bytes("https://auth.docker.io/token?service=registry.docker.io&scope=repository:%s:pull" % repo)
    if not tok:
        return None, None
    token = json.loads(tok.decode())["token"]
    auth = "Authorization: Bearer " + token
    man = fetch_bytes("https://registry-1.docker.io/v2/%s/manifests/%s" % (repo, tag),
                      headers=[auth, "Accept: application/vnd.oci.image.manifest.v1+json"])
    if not man:
        return None, None
    for layer in json.loads(man.decode()).get("layers", []):
        if "gguf" in layer.get("mediaType", ""):
            return ("https://registry-1.docker.io/v2/%s/blobs/%s" % (repo, layer["digest"]), auth)
    return None, None


def download_model(spec, dest_dir):
    dest = os.path.join(dest_dir, spec["file"])
    if os.path.exists(dest) and os.path.getsize(dest) >= spec["min_size"]:
        info("already have %s (%s)" % (spec["file"], human(os.path.getsize(dest))))
        return dest
    for src in spec["sources"]:
        headers = []
        url = src
        if src.startswith("dockerhub:"):
            url, auth = dockerhub_url(src[len("dockerhub:"):])
            if not url:
                info("could not reach %s" % src)
                continue
            headers = [auth]
        info("from %s" % (src if not src.startswith("http") else src.split("/")[2]))
        if curl(url, dest, headers=headers) and os.path.getsize(dest) >= spec["min_size"]:
            with open(dest, "rb") as f:
                magic = f.read(4)
            if dest.endswith(".gguf") and magic != b"GGUF":
                os.remove(dest)
                info("that file is not a GGUF model, trying the next source")
                continue
            return dest
        info("that source failed, trying the next one")
    return None


def do_models(out, model_key, images):
    mdir = os.path.join(out, "models")
    os.makedirs(mdir, exist_ok=True)
    result = {}
    if model_key:
        say("Language model")
        key = model_key
        path = None
        while key:
            spec = MODELS[key]
            info(spec["about"])
            path = download_model(spec, mdir)
            if path:
                break
            key = spec.get("fallback")
            if key:
                info("trying the fallback model instead")
        if not path:
            die("Could not download a language model. Check the internet connection and run again.")
        info("computing checksum ...")
        result["llm"] = {"file": os.path.basename(path), "size": os.path.getsize(path),
                         "sha256": sha256_of(path), "key": key}
    if images:
        say("Image model (5.2 GB, this is the long one)")
        info(SD_MODEL["about"])
        path = download_model(SD_MODEL, mdir)
        if not path:
            die("Could not download the SD-Turbo model. Run again to resume.")
        result["sd"] = {"file": os.path.basename(path), "size": os.path.getsize(path)}
    return result


def do_sources(out, which):
    say("Program source code (compiled on the Pi)")
    sdir = os.path.join(out, "src")
    os.makedirs(sdir, exist_ok=True)
    res = {}
    for key in which:
        s = SOURCES[key]
        dest = os.path.join(sdir, s["file"])
        if not (os.path.exists(dest) and sha256_of(dest) == s["sha256"]):
            info("downloading %s (%s)" % (s["file"], human(s["size"])))
            if not curl(s["url"], dest):
                die("Could not download %s" % s["url"])
            if sha256_of(dest) != s["sha256"]:
                os.remove(dest)
                die("Checksum mismatch for %s. Run again." % s["file"])
        else:
            info("already have %s" % s["file"])
        res[key] = {"file": s["file"], "sha256": s["sha256"], "subdir": s["subdir"]}
    return res


def do_code(out):
    say("The Infinite Jest code (this folder: %s)" % IJ_DIR)
    dest = os.path.join(out, "code", "infinite_jest")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".DS_Store",
                                    "*.part", "node_modules", ".git")
    # don't copy a bundle into itself if someone points --out inside the repo
    real_out = os.path.realpath(out)

    def _ignore(d, names):
        skip = set(ignore(d, names))
        for n in names:
            if os.path.realpath(os.path.join(d, n)) == real_out:
                skip.add(n)
        return skip
    shutil.copytree(IJ_DIR, dest, ignore=_ignore)
    # the repo-level docs (CONTRACT.md) if present
    docs = os.path.join(os.path.dirname(IJ_DIR), "docs")
    if os.path.isdir(docs):
        shutil.copytree(docs, os.path.join(out, "code", "docs"), dirs_exist_ok=True, ignore=ignore)
    rev = ""
    try:
        rev = subprocess.run(["git", "-C", IJ_DIR, "describe", "--always", "--dirty"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode().strip()
    except OSError:
        pass
    n = sum(len(f) for _, _, f in os.walk(dest))
    info("%d files%s" % (n, (" (git " + rev + ")") if rev else ""))
    return {"git": rev, "files": n}


def check_target(out, images):
    """Warn about USB sticks the Pi can't read, or FAT32 with a 5 GB file."""
    if platform.system() != "Darwin" or not out.startswith("/Volumes/"):
        return
    vol = "/".join(out.split("/")[:3])
    p = subprocess.run(["diskutil", "info", vol], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    text = p.stdout.decode("utf-8", "replace")
    m = re.search(r"Type \(Bundle\):\s*(\S+)", text) or re.search(r"File System Personality:\s*(.+)", text)
    fs = (m.group(1) if m else "").lower()
    info("USB stick format: %s" % (fs or "unknown"))
    if "apfs" in fs or "hfs" in fs:
        die("This stick is formatted for Macs only (%s); the Pi can't read it.\n"
            "    In Disk Utility: select the stick, Erase, Name: IJ, Format: ExFAT. Then run this again." % fs)
    if ("msdos" in fs or "fat" in fs) and images:
        die("This stick is FAT32, which can't hold the 5.2 GB image model.\n"
            "    In Disk Utility: Erase, Name: IJ, Format: ExFAT. Then run this again.")
    name = vol.split("/")[-1]
    if name != "IJ":
        info("Tip: name the stick IJ (Disk Utility, or click its name in Finder) so the Pi")
        info("command 'sudo mount -L IJ /mnt' finds it. Otherwise use the longer command in README.txt.")


def free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="where to put IJ-BUNDLE (a USB stick, e.g. /Volumes/IJ). "
                    "Default: an IJ stick if plugged in, else ~/Desktop")
    ap.add_argument("--release", action="append", choices=sorted(PROFILES),
                    help="which Raspberry Pi OS release(s) to fetch packages for "
                    "(default: both trixie and bookworm; repeat to pick)")
    ap.add_argument("--model", default="qwen2.5-1.5b", choices=sorted(MODELS),
                    help="language model (default: %(default)s)")
    ap.add_argument("--no-llm", action="store_true", help="skip the language model and llama.cpp")
    ap.add_argument("--images", action="store_true",
                    help="also the on-Pi image generator: stable-diffusion.cpp + SD-Turbo (5.2 GB)")
    ap.add_argument("--no-faces", action="store_true", help="skip OpenCV (saves about 150 MB)")
    ap.add_argument("--no-models", action="store_true", help="skip model downloads (testing)")
    a = ap.parse_args()

    for tool in ("curl",):
        if not shutil.which(tool):
            die("'%s' is missing on this computer." % tool)

    out = a.out
    if not out:
        if os.path.isdir("/Volumes/IJ"):
            out = "/Volumes/IJ"
        else:
            out = os.path.join(os.path.expanduser("~"), "Desktop")
    out = os.path.abspath(os.path.expanduser(out))
    if not os.path.isdir(out):
        die("%s doesn't exist. Plug in the stick, or give another folder with --out." % out)
    check_target(out, a.images)
    bundle = os.path.join(out, "IJ-BUNDLE")
    os.makedirs(bundle, exist_ok=True)
    cache = os.path.join(bundle, ".cache")
    os.makedirs(cache, exist_ok=True)

    releases = a.release or list(DEFAULT_RELEASES)
    # The Pi's SD card in the Mac tells us the release (issue.txt on "bootfs").
    if not a.release:
        issue = "/Volumes/bootfs/issue.txt"
        if os.path.exists(issue):
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", open(issue).read())
            if m:
                rel = "trixie" if (int(m.group(1)), int(m.group(2))) >= (2025, 10) else "bookworm"
                info("The Pi's SD card is in this Mac: image from %s, so %s only." % (m.group(0), rel))
                releases = [rel]

    need = (700 << 20) * len(releases) + (0 if a.no_llm or a.no_models else 1300 << 20) + \
           (5600 << 20 if a.images and not a.no_models else 0)
    if free_bytes(out) < need:
        die("Not enough free space in %s: need about %s, have %s." % (out, human(need), human(free_bytes(out))))

    print("\033[1mINFINITE JEST offline bundle\033[0m  ->  %s" % bundle)
    print("Releases: %s.  Language model: %s.  Image generator: %s." % (
        ", ".join(releases), "no" if a.no_llm else a.model, "yes" if a.images else "no"))

    groups = ["engine", "tools", "look"]
    if not a.no_faces:
        groups.append("faces")
    if not a.no_llm or a.images:
        groups.append("build")

    manifest = {"format": BUNDLE_FORMAT, "made": time.strftime("%Y-%m-%d %H:%M:%S"),
                "made_on": platform.platform(), "releases": {}, "options": {
                    "llm": not a.no_llm, "images": a.images, "faces": not a.no_faces}}
    for rel in releases:
        manifest["releases"][rel] = do_debs(bundle, rel, cache, groups)
    which = ([] if a.no_llm else ["llama"]) + (["sd"] if a.images else [])
    manifest["sources"] = do_sources(bundle, which) if which else {}
    manifest["models"] = {} if a.no_models else do_models(bundle, None if a.no_llm else a.model, a.images)
    manifest["code"] = do_code(bundle)

    for name in ("INSTALL.sh", "README.txt"):
        src = os.path.join(HERE, "bundle", name)
        shutil.copy(src, os.path.join(bundle, name))
    os.makedirs(os.path.join(bundle, "logs"), exist_ok=True)
    with open(os.path.join(bundle, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    shutil.rmtree(cache, ignore_errors=True)

    size = 0
    for d, _, files in os.walk(bundle):
        for fn in files:
            size += os.path.getsize(os.path.join(d, fn))
    say("Done: %s in %s" % (human(size), bundle))
    print("""
    Next, on the Pi (keyboard and screen, or ssh):
      1. Plug this stick into the Pi.
      2. Type:   sudo mount -L IJ /mnt && sudo bash /mnt/IJ-BUNDLE/INSTALL.sh
      3. Wait (20 to 40 minutes the first time: it compiles the language model
         program). It tells you what to do at the end.
""")
    if platform.system() == "Darwin" and out.startswith("/Volumes/"):
        print("    Eject the stick in Finder before pulling it out.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped. Run the same command again to continue where it left off.")
        sys.exit(130)
