"""The engine is the last hop before the wall and the phone: whatever the
oracle or a profiler sends, disguised source names, symbols and glyphs the
projector cannot draw never get through, phone_text included."""
from showengine import protocol as P
from showengine.visit import clean_words, visible_text

from test_core import BUSY, make_engine, run

DISGUISED = ["like Bacon", u"B​A​C​O​N", u"ｂａｓｑｕｉａt",
             u"Báselïtz", "b a c o n", "SAMO SAYS", "Jean-Michel", "neo-expressionism",
             "a crown for you", "SKULL", "DARK DATA (c)", u"DARK DATA ©", u"YOURS™",
             u"STAY \U0001F451", u"\U0001F480", u"☠", u"你在看",
             "the scrawl held you", "Francis knows"]
OK = ["YOU STAYED", "hold me closer", "segment: THE PERFORMER", 'you chose "the scream"',
      "you came within 37% of the frame", "dwell -> E+", "is a moment"]


def test_visible_text_blocks_disguises_keeps_the_rest():
    for w in DISGUISED:
        assert visible_text(w) == "", w
    for w in OK:
        assert visible_text(w) == w, w
    assert visible_text(u"café à deux") == "cafe a deux"     # folded, not dropped
    assert visible_text(u"stay\x00here\x1b") == "stay here"
    assert visible_text(None) == "" and visible_text(True) == "" and visible_text({}) == ""
    assert len(visible_text("x" * 500)) == 80
    assert clean_words(DISGUISED + OK) == OK


def test_oracle_phone_text_is_filtered_too():
    eng, clock, sent = make_engine()
    run(eng, clock, 25, BUSY)
    vid = eng.state["visitor_id"]
    for bad in ("Basquiat would love you", u"STAY \U0001F451", u"留下来"):
        eng.handle(P.make(P.ORACLE, {"visitor_id": vid, "words": ["YOU STAYED"], "phone_text": bad}), "oracle")
    texts = [m["data"].get("text") for m, r in sent if r == {"phone"} and m["type"] == P.PHONE]
    assert not any(t and ("asquiat" in t or not t.isascii()) for t in texts), texts


def test_profiler_line_and_label_are_filtered():
    eng, clock, sent = make_engine()
    run(eng, clock, 25, BUSY)
    vid = eng.state["visitor_id"]
    eng.handle(P.make(P.PROFILE, {"visitor_id": vid, "evidence": ["dwell -> E+"],
                                  "hook_params": {"line": "a crown for you"}}), "profiler")
    assert eng.state["words"] == ["dwell -> E+"]
