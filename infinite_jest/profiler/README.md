# Profiler: harvest, analyse, hook, reveal

The part of INFINITE JEST that watches each visitor for about a minute, guesses
their personality on the OCEAN (Big Five) model, picks the scene most likely to
hold them, tests whether it does, and at the end tells them all of it.

It restages the Cambridge Analytica method in one room, on one person at a time, in
plain sight: **profile, pick the hook, test, adapt, reveal.** The inference is
theatre-grade. The code says so, the confidence caps say so, and the reveal
says so to the visitor's face. That gap between how sure the machine sounds
and how little it knows is the piece's subject.

Runs on a Raspberry Pi 5 with no internet. Python 3.9+ standard library only.
OpenCV (`python3-opencv`) is optional and adds face boxes and JPEG frames.

## Run it

```bash
# rehearse without a room: four simulated visitors, each with a hidden favourite scene
python3 -m infinite_jest.profiler --sim all

# tests
python3 -m unittest discover -s infinite_jest/profiler/tests -t .

# live, as its own process next to the engine
python3 -m infinite_jest.profiler --ws ws://192.168.1.10:8765/ws --debug
```

Or in-process from the engine: `create(cfg)`, then `on_sensor`, `on_frame`,
`on_visit`, `reset` (see `core.py`). Message shapes follow
`/mnt/project-files/infinite_jest/CONTRACT.md` (v1.1).

## 1. Harvesting: what the room gives us

One Nokia N900 is the only sensor. It sends its readings to the Pi, and the Pi
does the analysis.

| Source | Signal | Becomes feature |
|---|---|---|
| front camera, 160x120 gray, 4 fps, analysed on the Pi (`vision.py`) | how fast they cross the frame on entry | `pace` |
| | how big they get in frame (= how close) | `closeness`, `approach_time` |
| | frame-difference energy and how bursty it is | `motion`, `burstiness` |
| | how much of the width they wander | `roaming` |
| | a frontal face box (detection only, if OpenCV) | `gaze` |
| | seconds present | `dwell` |
| mic: level and a voiced flag only, never audio or words | how much they talk, how loud | `voice`, `loudness` |
| touchscreen | taps per minute, how much of the surface, long holds | `touch_rate`, `touch_variety`, `hold_ratio` |
| on-screen prompts (`prompts.json`) | which side they pick, how fast | trait nudges, `choice_speed` |
| slide keyboard | how much they type (count only, never text) | `typing` |
| accelerometer (when handled) | shaky hands | `shake` |
| proximity sensor | covered for 3 s | **opt-out** |

The five prompts are the "personality quiz as bait" move: harmless either/or
choices ("look closer / look away", "upside down / right way up") that are
really measurements. Each one's real-world counterpart is in `prompts.json`.

## 2. Analysis: features to OCEAN (`features.py`, `ocean.py`)

Each feature becomes a number from -1 to 1 (below or above a typical visitor;
the norms in `features.NORMS` are guesses to tune at the mini showing) plus an
evidence weight that grows as data comes in. Each feature has a weight per
trait and a reliability, taken from the research in `RESEARCH.md`. A trait is a
weighted average pulled toward 0.5 while evidence is thin. It is a small,
readable cousin of the likes-to-traits regression from the myPersonality
project that Cambridge Analytica copied.

The honest part: each cue predicts a trait at about r = .1 to .3.
Extraversion leaks most (talk, energy, closeness). Openness shows in taste and
exploration. Conscientiousness, Agreeableness and Neuroticism are close to
guesswork. So each trait's confidence is capped at E 85%, O 75%, C 55%, A 50% and
N 50%. The overall `confidence` measures how much evidence has come in, not
accuracy. The reveal spells out that difference.

Segments are named the way an ad platform names an audience, from the most
confident extreme trait: The Performer, The Lurker, The Seeker, The
Literalist, The Auditor, The Drifter, The Pleaser, The Contrarian, The Exposed
Nerve, The Cold Surface.

## 3. The hook loop (`hooks.py`)

| Hook | Image | Pulled by |
|---|---|---|
| `flesh` | Bacon: caged, smeared, screaming bodies | high N, high O, low A |
| `scrawl` | Basquiat: scrawled words, crowns, crossed-out data | high E, high O, low C |
| `inverted` | Baselitz: upside-down heavy figures | high O, low A |
| `mirror` | the visitor's own silhouette, distorted | high E, high A |
| `void` | near black, one drone, one line | high C, low E |

This is the "test and learn" loop, per person, per second. A Thompson-sampling
bandit draws a hook. Its prior is how well each hook fits the current OCEAN
guess, which is the profile. Its reward is how held the visitor actually is
while the hook runs: closer, looking, still but present, touching, talking.
That reward is compared against the visitor's own baseline, which is the A/B
test. Each hook runs for at least 8 s. What the person does soon outweighs what
we guessed about them. In simulation the hidden favourite scene wins in about 12
of 16 runs within 70 s.

Each profile also carries tailored `hook_params`, the way Matz et al. (2017)
wrote different ads for extraverts and introverts:

- tempo: 118 to 140 bpm, rising with E
- sound: drone, kick, noise or voice
- intensity
- a text line in the style of the visitor's strongest trait, for example "everyone can see you" (E+), "no one else is here" (E−), "you are safe here. stay." (N+), "nobody else has seen this version" (O+)

## 4. The reveal (`reveal.py`)

When the engine moves to `release`, the profiler sends a `reveal` with short
lines for the projection:

```
you spoke 44% of the time. people like that score more on Extraversion.
you chose "upside down". people like that score more on Openness.
OPENNESS 0.88   (confidence 65%)
...
segment: THE PERFORMER
we tried 4 scenes on you. scrawl held you best.
we chose it because it worked, not because it was true.
the machine's confidence: 93%.
its real accuracy: one minute of behaviour predicts personality at about r = .2.
Cambridge Analytica sold numbers like these as mind reading.
it is barely better than a guess. it still felt like it knew you.
this profile is being deleted now.
```

Then the engine sends `wipe` and everything is dropped.

## 5. Privacy built into the code

- Nothing is written to disk. The profiler holds one previous frame, a
  background estimate and rolling counters, in memory only.
- `reset()` on every `wipe`, every end of visit, on `blackout`, and whenever the
  connection to the engine drops.
- Typed text: only the character count is kept. The tests check this.
- Audio: only level and voiced flag arrive. No recording, no words.
- Faces: an optional detection box (is someone looking), never identity,
  landmarks, templates, age, gender, race or emotion.
- Opt-out: cover the phone's top edge for 3 s. Data is dropped and the
  visitor gets `void` until the next visit.

See `DATA_HANDLING.md` for the one-page note for the school.

## Tuning at the mini showing (Mon Nov 23)

1. Run `--ws ... --debug` and watch five real people.
2. If everyone reads as an extravert, raise the `motion` and `closeness`
   centres in `features.NORMS`. If nobody does, lower them.
3. If hooks switch too often for the visuals, raise `hook_min_dwell` in the config.
4. Check that `vision.py`'s `present` follows real people in the room's light,
   and adjust `DIFF_T` for a dark room.
5. A group is profiled as one "visitor". That's a known limit, and arguably fitting.
