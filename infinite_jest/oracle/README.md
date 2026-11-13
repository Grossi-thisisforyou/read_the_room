# Oracle: the local language model's voice

A small Qwen model runs on the Pi under llama.cpp's `llama-server`, with no
internet. The oracle reads the profiler's guesses and writes three things:

- `phone_text`: one line (8 words or fewer) for the N900 screen
- `words`: three UPPERCASE surveillance-log fragments for the projection, e.g. HOLDS DEVICE CLOSE
- `dossier`: the confession shown at release

It sends them as `{"type": "oracle", "data": {visitor_id, words, phone_text, dossier}}`
(contract 1.3). If the model is down, slow (15 s timeout) or breaks a rule, the
oracle sends nothing and the engine keeps the profiler's template text, so the
show never waits on the model.

## Model

The default is Qwen2.5-1.5B-Instruct, Q4_K_M GGUF (about 1 GB). On a Pi 5 it
should manage roughly 8 to 12 tokens/s on 3 threads (the engine thread's
estimate; not measured yet). Calls are capped at 40 tokens for words and 70
for the dossier, so each answer should land in about 4 to 8 s. Qwen2.5-3B is
likely to write better but take about twice as long. Try both at the mini
showing.

`llama-server` is set up as a systemd service on `127.0.0.1:8080` by the Pi
engine's install script. Test it like this:

```bash
python3 -m infinite_jest.oracle --try performer          # one words call + one dossier call, timed
python3 -m infinite_jest.oracle --ws ws://127.0.0.1:8765/ws --debug
```

## Rules (voice.py)

- The model gets only OCEAN numbers, confidences, the segment label, the hook
  name and plain behaviour lines the wall already shows. It never gets frames,
  audio, typed text or ids.
- The system prompt forbids guessing age, gender, race, religion, health,
  sexuality, body, clothing, emotions or names.
- A word filter drops any answer that does it anyway, or any line that is too long.
- Answers for a visitor who has already been wiped are thrown away.
