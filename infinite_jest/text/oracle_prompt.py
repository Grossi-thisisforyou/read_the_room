"""Messages for the local Qwen, built from corpus/oracle.json.

Drop-in for infinite_jest/oracle/voice.py: same inputs (the profiler's
`profile` dict), same output shape (OpenAI-style chat messages), and the same
cleaning contract (style.clean_words / style.clean_dossier return None when
the answer breaks a rule, so the template text stays).

    from infinite_jest.text import oracle_prompt, style
    msgs = oracle_prompt.words_messages(profile)
    phone, words = style.clean_words(model_answer) or (None, None)

The static part (system prompt + few-shot turns) always comes first and never
changes, so llama-server's prompt cache makes every call after the first one
fast on the Pi. Only the last user message carries this visitor's numbers.
"""

import json
import os

from . import CORPUS, Corpus, fill

_TRAIT_NAMES = {"O": "openness", "C": "conscientiousness", "E": "extraversion",
                "A": "agreeableness", "N": "neuroticism"}

_cfg = None
_corpus = None


def config():
    global _cfg
    if _cfg is None:
        with open(os.path.join(CORPUS, "oracle.json"), encoding="utf-8") as f:
            _cfg = json.load(f)
    return _cfg


def _c():
    global _corpus
    if _corpus is None:
        _corpus = Corpus.load()
    return _corpus


def _scores(p):
    o = p.get("ocean") or {}
    return ", ".join("{} {:.2f}".format(t, o[t]) for t in ("O", "C", "E", "A", "N") if t in o) or "unknown"


def _strongest(p):
    o = p.get("ocean") or {}
    conf = p.get("trait_confidence") or {}
    if not o:
        return "unknown"
    t = max(o, key=lambda k: abs(o[k] - 0.5) * (0.3 + conf.get(k, 0)))
    pole = "high" if o[t] >= 0.5 else "low"
    style = (p.get("hook_params") or {}).get("prompt_style")
    return "{} {}{}".format(pole, _TRAIT_NAMES.get(t, t), " ({})".format(style) if style else "")


def observed(p, n=3):
    """Plain behaviour lines from the profile's evidence, in the corpus's words.

    Evidence items are the profiler's strings "feature -> E+" (or tuples).
    Only features with a value in p["features"] are described.
    """
    feats = p.get("features") or {}
    out, seen = [], set()
    obs = _c().lines(surface="wall", beat="observe")
    for ev in p.get("evidence") or []:
        feat = ev.split(" -> ")[0] if isinstance(ev, str) else ev[2]
        if feat in seen:
            continue
        seen.add(feat)
        if feat.startswith("choice:"):
            opt = (p.get("choices") or {}).get(feat.split(":", 1)[1])
            if opt:
                out.append("you chose {}".format(opt))
        elif feat in feats:
            for e in obs:
                if e.get("needs") == [feat]:
                    line = fill(e["text"], {feat: feats[feat]})
                    if line:
                        out.append(line)
                        break
        if len(out) >= n:
            break
    return out


def _shots(task):
    msgs = []
    for ex in config()[task]["examples"]:
        msgs.append({"role": "user", "content": ex["user"]})
        msgs.append({"role": "assistant", "content": ex["assistant"]})
    return msgs


def words_messages(p):
    cfg = config()
    scene = _c().scene_name(p.get("hook"))
    user = "Scores: {}\nStrongest: {}\nScene: {}\nSeen: {}\n{}".format(
        _scores(p), _strongest(p), scene, "; ".join(observed(p)) or "almost nothing yet",
        cfg["words"]["task"])
    return ([{"role": "system", "content": cfg["system"]}] + _shots("words")
            + [{"role": "user", "content": user}])


def dossier_messages(p):
    cfg = config()
    scene = _c().scene_name(p.get("hook"))
    seg = str(p.get("segment") or "unread").lower()
    user = "Seen: {}\nSegment: {}\nScene that held them: {}\nMachine confidence: {:.0%}\n{}".format(
        "; ".join(observed(p, 2)) or "very little", seg, scene,
        float(p.get("confidence") or 0), cfg["dossier"]["task"])
    return ([{"role": "system", "content": cfg["system"]}] + _shots("dossier")
            + [{"role": "user", "content": user}])


def request_body(messages, task, model="qwen"):
    """The JSON body for llama-server's /v1/chat/completions."""
    t = config()[task]
    return {"model": model, "messages": messages, "max_tokens": t["max_tokens"],
            "temperature": t["temperature"], "top_p": 0.9, "stream": False,
            "cache_prompt": True}
