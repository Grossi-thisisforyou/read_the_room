"""Unit tests for the deploy tools (run: python3 -m pytest -q infinite_jest/deploy/tests)."""
import importlib.machinery
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
sys.path.insert(0, DEPLOY)
import make_bundle as mb  # noqa: E402


def load(name):
    path = os.path.join(DEPLOY, "pi", name)
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_version_order_matches_dpkg():
    # pairs (a, b, sign of a-b), from dpkg's own test-suite cases
    cases = [("1.0", "1.0", 0), ("1.0", "1.1", -1), ("1.0~rc1", "1.0", -1), ("1:0.1", "2.0", 1),
             ("1.0-1", "1.0-1+deb12u1", -1), ("2.36-9+deb12u7", "2.36-9+deb12u10", -1),
             ("1.0a", "1.0", 1), ("1.0+", "1.0", 1), ("0.9", "0.10", -1), ("1.2.3-1ubuntu1", "1.2.3-1", 1),
             ("7.4.2", "7.4.2-0.1", -1), ("1:2.0", "1:2.0", 0), ("1.0~~", "1.0~", -1)]
    for a, b, want in cases:
        got = mb.vcmp(a, b)
        assert (got > 0) - (got < 0) == want, (a, b, got)


def test_parse_deps_and_resolve():
    idx = mb.Index("arm64")
    pk = [
        {"Package": "app", "Version": "1", "Architecture": "arm64", "Depends": "libfoo (>= 2), mta | postfix, python3:any"},
        {"Package": "libfoo", "Version": "1", "Architecture": "arm64"},
        {"Package": "libfoo", "Version": "3", "Architecture": "arm64", "Pre-Depends": "libc6"},
        {"Package": "exim", "Version": "1", "Architecture": "arm64", "Provides": "mta"},
        {"Package": "python3", "Version": "3.11", "Architecture": "arm64"},
        {"Package": "libc6", "Version": "2.36", "Architecture": "arm64"},
        {"Package": "other", "Version": "1", "Architecture": "armhf"},
    ]
    for st in pk:
        idx.add(st, "Package: %s" % st["Package"], "http://x")
    idx.finish()
    chosen, missing = mb.resolve(idx, ["app"])
    assert not missing
    assert set(chosen) == {"app", "libfoo", "exim", "python3", "libc6"}
    assert chosen["libfoo"]["Version"] == "3"
    chosen, missing = mb.resolve(idx, ["other"])
    assert missing == ["other"]


def test_pick_audio():
    wd = load("ij-watchdog")
    assert wd.pick_audio("default", ["Device"]) == "plughw:CARD=Device,DEV=0"
    assert wd.pick_audio("plughw:1,0", ["Device"]) == "plughw:CARD=Device,DEV=0"
    assert wd.pick_audio("plughw:CARD=Device,DEV=0", ["Device"]) is None
    assert wd.pick_audio("plughw:CARD=Old,DEV=0", ["New"]) == "plughw:CARD=New,DEV=0"
    assert wd.pick_audio("pulse", ["Device"]) is None          # set by hand: leave it
    assert wd.pick_audio("default", []) is None                # no USB card: leave it


def test_edid_name(tmp_path):
    doc = load("ij-doctor")
    e = bytearray(128)
    e[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    e[72:90] = b"\x00\x00\x00\xfc\x00" + b"EPSON PJ\n     "
    p = tmp_path / "edid"
    p.write_bytes(bytes(e))
    assert doc.edid_name(str(p)) == "EPSON PJ"
