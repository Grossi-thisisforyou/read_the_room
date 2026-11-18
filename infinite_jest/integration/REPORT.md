# Integration report: the whole show, run together

Night of 13 to 14 Nov 2026. Branch `claude/project-thread-x69blu`, PR #11.

Every module of INFINITE JEST ran together for the first time: the Pi show engine,
the profiler and oracle, the voice of the room (text corpus), the visuals, the techno,
and the N900 phone agent. Nothing here has run on the real Pi, N900, projector or
speaker yet. Everything ran on a 4-core x86 cloud machine.

## How it was tested

| Tool | What it runs | Result |
|---|---|---|
| `integration/live_test.py` | Real engine process at 1920x1080, real oracle process, real N900 agent code against a fake sysfs tree, over real sockets (WebSocket, UDP 8766, TCP 8767 JPEG, HTTP fallbacks). A scripted visitor picks up, tilts, flips, shakes, holds still, puts down, then a second visitor opts out. | 49 checks; all pass after the fixes below |
| `integration/film.py` | The same modules in one process on a virtual clock, frame-exact, with the real techno synth rendered offline. Five scripted visitor types. | Five full visits filmed (see Films) |
| `pi/tests/test_privacy_integration.py` | End-to-end privacy promises across all modules (wipe, opt-out, model input) | 19 of 19 pass |
| Module suites, final run | pi 93, phone 45 (+1 skipped), visuals 21, profiler, oracle 24, text, audio | all pass |

## What was broken and is now fixed

Found by running the pieces together; each fix went into the owning module and the
owning thread pulled it into its own PR.

1. **Profiler used the phone's clock.** The N900 has no network time on the offline LAN.
   The engine handed the profiler the phone's timestamps for sensors but its own clock
   for visit changes. With the phone's clock ahead, the profiler revealed in the first
   second and stopped profiling, so every scene came from the engine's crude fallback
   guess. Now one clock (the engine's); contract v1.4 says so.
2. **The voice of the room never loaded.** The engine's plugin loader required a
   `create()` function; the text corpus is a library with `Corpus`. Every visit silently
   used the old placeholder phone lines.
3. **The phone was blank during profiling.** The engine's open question had no answer
   options, and the agent only showed questions with two options.
4. **Opt-out was half-built and not in the contract.** Covering the phone's eye only
   reached the profiler; the visit ended and restarted on the same person, who also got
   the reveal and "Thank you for your data." Now the engine handles it, the visit stays
   quiet until the phone is put down, then wipes with no reveal. Contract v1.4 defines it.
5. **Put-down took about 16 s instead of 8**, because the phone's own slowly falling
   presence guess overrode "held".
6. **Profiles for the wrong visitor reached the language model** (a pre-visit id, and
   profiles after an opt-out).
7. **Debug strings on the wall.** Without the model, the wall showed `handled -> E+`.
   Now readable lines: `YOU TURNED IT THROUGH 140 DEGREES  O+`.
8. **Volume control did nothing**; tilt on the wall flickered between two scales; reveal
   lines were cut mid-word.
9. **Two privacy leaks:** after an opt-out the profiler kept the visitor's last profile
   in memory; the painted body and last camera figure outlived the wipe by 2.5 s.
10. **Giveaway marks.** The phone's consent and live screens drew a crown and a ©; the
    web phone drew a crown and showed raw hook names; the wall font could draw a ©. All
    replaced with neutral marks (a tally) and filters extended.

Found in the first films, fixed by the owning threads overnight:

11. **The adaptation never settled.** In every visit the scene changed every 8 s through
    all five, so "made for you" looked like a carousel. Handheld engagement barely moved
    (holding was always 1). Now engagement is steadiness relative to the visitor's own
    average, and the visuals need 6 s of steady request and 20 s on screen per scene.
12. **The confession card ran off the right edge** and was half unreadable.
13. **A very still visitor was invisible.** A gentle holder stopped counting as "held"
    4 s after the pick-up. Now "held" latches from the pick-up until the phone rests flat.

Found in the final films and fixed here (handed to the owning threads):

14. **A gentle pick-up was missed.** The lurker turned the phone up slowly with no visible
    tremor; the visit only started when they put it down, 100 s later. Leaving the flat now
    counts as a pick-up (phone PR #7 has it).
15. **The confession lied about the scenes.** Every reveal said "you were shown 1 scenes" and
    named the profiler's last request. The engine now counts the seconds each scene was really
    on the wall, wipes that with the visitor, and the reveal uses it ("you were shown three
    scenes. you stayed longest with the mirror."). The card no longer repeats its title as
    the first line.
16. **Opt-out still looked like reading.** After the refuser covered the eye, the wall kept
    scrawling lines picked by tone ("YOU HOLD ME GENTLY.") and the figure painted from their
    camera stayed 2.5 s. The state now carries `opted_out`; the wall shows only NOT READING
    YOU / NOTHING KEPT / EYE CLOSED, and the painted body goes at once.

## Still open

- **No real language model.** huggingface.co is blocked from the cloud machine (and from
  the Mac's sandbox), so the oracle ran with no model: it stays quiet and the profiler's
  and corpus's fixed text fill in, which is the designed fallback. The model path was
  checked only with a stand-in server (`live_test.py --fake-llm`).
- **Next visitor during the confession.** The confession now lasts 50 s. If the next
  person picks the phone up during it, the new visit waits until the wipe, and that person
  reads the previous visitor's reveal on the wall. Decide: cut the confession short on a
  pick-up, or keep it.
- **The reveal names Cambridge Analytica.** The text corpus explains the method with it.
  That names the concept's inspiration (not an artist). Baby's call.
- **Personality guesses are close together.** Scripted visitors who behave very
  differently still land within about 0.1 on most traits. Theatre-grade by design, but
  the reveal reads as more certain than it is.
- **Images from the on-Pi generator** (bank_gen) were not in the films: the image bank
  is empty until the Pi has run overnight.

## Measured speed (x86 cloud machine, NOT the Pi)

Intel Xeon @ 2.30 GHz, 4 cores. `live_test.py`, engine at 1920x1080 with the real visuals
v2, real audio in its own process (null sink), profiler in process. CPU = utime+stime from
`/proc`, as a share of one core. FPS = the engine loop's own count from `/status`.

| Window | Engine CPU | Audio process CPU | FPS mean / min |
|---|---|---|---|
| Idle, 9 s | 24.5% | 8.9% | 29.2 / 28.8 |
| Visit, 120 s | 67.3% | 14.3% | 28.9 / 27.6 |
| Whole run, 207 s | 56.1% | 13.6% | 29.0 / 27.6 |

A Pi 5 core (Cortex-A76, 2.4 GHz) is roughly 1.5 to 2.5 times slower than this one for
numpy and pygame work. The engine is single-threaded, so expect it near or over one full
Pi core during a visit: likely 20 to 30 fps rather than 30, before the language model
takes cores 2 and 3. **Measure on the Pi first** (`python3 -m infinite_jest.visuals.bench`
and the `/status` fps); if it is short, lower the visuals' `internal_size`.

## Only the real hardware can answer

- Pi: real fps and CPU temperature at 1080p over HDMI (KMS/DRM), with the Active Cooler;
  llama.cpp Qwen speed next to the show; USB DAC output; boot to show unattended.
- N900: Python 2.5 + pygtk start-up; sysfs paths for the accelerometer, proximity and
  light; the front camera pipeline; Wi-Fi to the WRT150N; real hand tremor against the
  "held" thresholds (the accelerometer reads in steps of about 18 mg); battery on the tether.
- The room: projector brightness against the lounge's daylight; speaker level; whether
  visitors understand "pick it up".

## Films

In `/mnt/project-files/infinite_jest/integration/films/` (not in git), stills in `../stills/`.

- `infinite_jest_show_explained.mp4`: all five visits back to back (13 min 24 s), with the
  phone's screen inset and a caption of phase, scene and the profiler's guess.
- `visit_<persona>_projector.mp4`: exactly what the projector and speaker would put out,
  1920x1080, 30 fps, with the real techno. `visit_<persona>_timeline.json`: every phase,
  scene, phone line and profile, with times.

What the five visits did (seed 3, final code):

| Visitor | Picks up / puts down | Scenes (where it settled) | Ending |
|---|---|---|---|
| The lurker (barely moves) | 6 s / 106 s | the dark almost throughout, one try of the fall | confession, "two scenes were tested on you. the dark won." |
| The performer (big gestures, talks) | 6 s / 111 s | the mirror 40 s, then the writing 50 s | confession, "we tried four scenes on you. the mirror held you best." |
| The one who says no | 6 s / 28 s, covers the eye at 18 s | the dark | no confession, quiet wall, wipe |
| The nervous one (shakes, quick) | 6 s / 101 s | the fall 45 s, then the wound 40 s | confession |
| The seeker (turns it upside down) | 6 s / 116 s | the fall 50 s, then the wound 55 s | confession |

The scenes settle now (one or two per visit, 40 s or more each) instead of cycling every 8 s.
Each persona's scripted favourite gets one of the long runs (first for the lurker, performer
and seeker, second for the nervous one), but the room then moves on to a second scene for
three of them, so "made for you" is a direction, not a lock. The OCEAN guesses still sit
close together.
