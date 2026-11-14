# text: the words of INFINITE JEST

Everything the room says, as data the show loads: the wall, the phone, the
either/or prompts, the dossier, the confession, the wipe, and the prompts that
keep the local Qwen in the same voice.

| File | What |
|---|---|
| [VOICE.md](VOICE.md) | the voice in one page: three registers (log, whisper, confession), the hard rules |
| [ARC.md](ARC.md) | one visit beat by beat with timings, per-segment differences, attract mode, refusals |
| `src/*.txt` | **the script**: every line, hand-written, grouped under `@ tags` headers. Edit these |
| `corpus/lines.json` | built from `src/` by `build.py`: 570 entries (663 lines) with ids and tags. Don't edit |
| `corpus/prompts.json` | 30 either/or prompts, same shape as `profiler/prompts.json` |
| `corpus/labels.json` | visitor-facing scene names, trait names, segment labels and their ad-platform blurbs |
| `corpus/oracle.json` | Qwen system prompt, task wording and few-shot examples |
| `corpus/cuts.json` | ids Baby cut on the score page. The loader skips them |
| `__init__.py` | loader: `Corpus.load()`, `corpus.visit().pick(...)`, `.sequence(...)`, `.reveal(...)`, `corpus.scrawl(...)` |
| `style.py` | the style check, and `clean_words` / `clean_dossier` for model output |
| `oracle_prompt.py` | drop-in replacement for `oracle/voice.py`'s message builders |
| `trial.py` | runs the prompts against the real model on the Pi and scores them |

## Tags on every line

`surface` (wall, phone, any), `phase` (engine phase), `beat` (see ARC.md),
`register` (log, whisper, confession), `hook` (flesh, scrawl, inverted, mirror,
void), `pole` (E+, E-, O+ ... the visitor's strongest trait), `tone` (tender,
cold), `lang` (en, de), `needs` (values the line needs, e.g. `handled`), plus
`chars`, `static` (no placeholders) and `scrawl` (static, at most 24 characters,
good for hand-lettering).

## Using it

```python
from infinite_jest.text import Corpus
corpus = Corpus.load()                 # german=False drops the German layer
visit = corpus.visit()                 # new one per visitor: no repeats, max 3 German lines

visit.pick(surface="phone", beat="lift")                                  # "there you are."
visit.pick({"features": feats}, surface="wall", beat="calibration")       # "GRIP 82%"
visit.pick(surface="wall", beat="testing", hook="flesh", register="log")  # "CAGE CLOSED"
visit.pick(surface="phone", beat="tailored", pole="E-")                   # "it's just us."
visit.sequence(surface="phone", beat="consent")                           # consent screen lines
visit.reveal({...})   # header + evidence + traits + segment + scene + confession, and the wipe

corpus.scrawl(hook="void", tone="cold")    # short UPPERCASE lines for the visuals
corpus.prompts(pace="fast")                # prompts suited to a fast visitor
```

`reveal()` takes the profiler's evidence tuples `(conf, trait, feature, raw, sign)`,
`ocean`, `trait_confidence`, `confidence`, `segment_pole` ("E+"), `hook`,
`scenes_tried`, `seconds`, `choices` and `vid`. A visit under 15 s gets the
short confession; an opt-out gets no dossier at all.

## The oracle (local Qwen)

`oracle_prompt.words_messages(profile)` and `dossier_messages(profile)` take the
same `profile` dict as `oracle/voice.py`. The system prompt and four few-shot
examples come first and never change, so with `cache_prompt: true` llama-server
only processes the last message per call (important on a Pi, where reading a
600-token prompt from scratch could take longer than the 15 s timeout).
`style.clean_words` / `clean_dossier` drop any answer that breaks a rule.

Not yet run against a real model (model downloads are blocked in the build
environment). On the Pi:

```bash
python3 -m infinite_jest.text.trial --url http://127.0.0.1:8080 --n 20
```

It prints each answer, PASS or DROP with the rule it broke, the pass rate and
the median time. Try Qwen2.5-1.5B and 3B; keep the one that passes more within ~8 s.
If the pass rate is low, add an example to `corpus/oracle.json` that shows the
mistake done right, rather than adding rules.

## Changing the words

1. Edit `src/*.txt` (or cut on the score page and paste its export into `corpus/cuts.json`).
2. `python3 -m infinite_jest.text.build`
3. `python3 -m unittest discover -s infinite_jest/text/tests -t .` (every line
   goes through the style check; the tests fail on a rule break)
