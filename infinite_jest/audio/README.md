# INFINITE JEST: sound engine

This folder makes the music. It is a live techno generator in a dark, industrial, warehouse style: a tuned, rumbling kick, distorted hats, metal clanks, data ticks, acid and rolling basslines, noise risers, sub drones and detuned chord stabs, all inside a big concrete-room reverb. Nothing is pre-recorded. Every sound is synthesised on the spot, and the music keeps changing to follow the show:

- **the phase of the visit**: someone walking in, being profiled, being hooked, the hinge, being let go
- **the visitor's OCEAN profile** (their five personality scores)
- **their hook**, the family of material the show has chosen for them
- **the phone's tilt and shake**

Between and across visitors it behaves like a DJ playing one long set. It builds, drops, breaks down and builds again in 8, 16 and 32 bar phrases, with drum fills and filter sweeps at the joins. Over the course of the evening it slowly changes key, scale, tempo and drum kit, so hour three does not sound like hour one.

Each visitor still gets "their" track. Their personal riff and groove come from a random-number generator seeded with the visitor's id, so the same person always gets the same motif and someone else gets a different one.

It runs on the Raspberry Pi 5 with no internet. It needs only Python 3 and numpy.

## Listen to examples

Rendered examples are in `/mnt/project-files/infinite_jest/audio_samples/v2/`:

- `set_10min.mp3` (and `set_10min.wav`): a simulated 10-minute evening with idle time, three visitors with different hooks, hinges, releases and wipes
- `hook_flesh.mp3`, `hook_scrawl.mp3`, `hook_inverted.mp3`, `hook_mirror.mp3`, `hook_void.mp3`: about 90 seconds of one visitor in each hook, including the hinge

## Hear it without the show

The demo invents a visitor and walks them through the whole arc: idle, approach, profiling, hook (with the hinge), release. Then it wipes and a new visitor arrives with a new personality and the next hook. A slow fake phone tilt sweeps the sound around.

**On a Mac or laptop**

```
pip3 install numpy sounddevice
cd read_the_room
python3 -m infinite_jest.audio.demo
```

Macs don't have `aplay`, so the demo plays through `sounddevice`. If you'd rather not install that, render to a file and open it in any player:

```
python3 -m infinite_jest.audio.demo --render test.wav --hook flesh --seconds 90
python3 -m infinite_jest.audio.demo --evening evening.wav      # the 10-minute evening
```

Options: `--ocean 0.9,0.3,0.4,0.1,0.9` fixes the five scores (in O,C,E,A,N order). `--hook scrawl` fixes the hook. `--seed 3` picks a different fake visitor. `--no-tilt` turns off the fake tilt. When it finishes rendering it prints how many times faster than real time it ran.

To measure a render (loudness, peaks, tempo, key, how repetitive it is):

```
python3 -m infinite_jest.audio.analyze evening.wav
```

**On the Pi**

```
sudo apt install python3-numpy alsa-utils
python3 -m infinite_jest.audio.demo --device plughw:1,0
```

Press Ctrl+C to stop.

## Choosing the speaker output (USB DAC or HDMI)

Run `aplay -l`. It lists the sound cards, for example `card 1: Device [USB Audio Device], device 0`. Card 1, device 0 is written `plughw:1,0`. Put that in the show config:

```
"audio_device": "plughw:1,0"
```

Use `plughw:`, not `hw:`, so ALSA can convert the format if the DAC needs it. Leave the setting as `"default"` to use the system default. The engine always sends 48 kHz, 16-bit stereo.

If no speaker is plugged in when the show starts, or the DAC is unplugged during the show, the engine keeps running silently and tries again every 7 seconds. Plug it back in and the sound returns by itself.

Other config keys, all optional:

- `audio_volume` (or `volume`): 0 to 1, 0.9 by default. It can also be changed while running (see below).
- `master_gain`: an extra multiplier on top of the volume, 1.0 by default
- `audio_latency_ms`: output buffer, 80 by default. Raise it to 150 if you hear crackles.
- `audio_sink`: `auto`, `aplay`, `sounddevice` or `null` (silent, for testing)
- `audio_seed`: changes every visitor's track and the whole evening's drift at once
- `audio_retry_s`: how often to retry a missing speaker, 7 seconds by default

## What controls what

**Phase** (the shape of the visit):

| phase | what you hear |
|---|---|
| idle | the "room" plays on its own: long ambient stretches, dub-like pulses, and now and then a slow build into a gentle groove. It keeps drifting in key and kit so the space never sounds stuck. |
| approach | the music turns towards the visitor: the kick comes in at half time, then four-on-the-floor, with rumble under it |
| profiling | builds tension: hats, ticking "data" clicks, clanks, risers, a filter slowly opening |
| hook | a build, then the drop into the full groove tuned to this visitor, with their personal riff. It then moves through peak, break and drop sections like a real track. |
| hinge (`hinge: true`, about 4 s) | almost everything cuts out, leaving only the sub-bass humming. When the hinge ends the full track slams back in on the downbeat. |
| release (50 s) | an evolving comedown: a breakdown with the kick gone, then an afterglow of chords and reverb, then a slow outro that thins out to the drone |
| wipe (about 12 s) | the music dissolves (the filter closes, reverb tails ring out), the visitor is forgotten, and the idle drone returns |

**Sections**: inside each phase the arranger picks sections (ambient, pulse, dub, intro, build, pre-drop, drop, peak, break, afterglow, outro) based on the phase and the show's intensity. A section lasts 8, 16 or 32 bars. The last bar of a phrase often gets a drum fill, a snare roll, a filter sweep or a reverb throw, so the joins sound played rather than looped. In long peaks, layers (hats, clank, stab, bass and so on) rotate in and out so the groove keeps moving.

**The set clock** (slow drift over the evening, mainly heard while idle): every few minutes the key or scale (minor, phrygian, dorian) shifts, the idle tempo wanders between about 120 and 135 BPM, and every 10 to 20 minutes the drum kit changes. There are five kits: concrete, steel, bunker, machine and tunnel, each with its own kick, snare and metal sounds. Overall energy, room size and grit also drift slowly.

**OCEAN** (personality; each score glides over about two bars):

| score | high | low |
|---|---|---|
| O openness | odd variations, 3-against-4 (or 5/7) clank polyrhythm, weird metallic timbres | a fixed clank position, plain timbres |
| C conscientiousness | tight, quantised, repeating patterns | swing, random ghost notes, flams, dropouts |
| E extraversion | louder, brighter, faster (tempo about 126 + 14×E), more hats, open hats, claps | darker, sparser, fewer claps |
| A agreeableness | consonant minor drone and chord stabs; clanks tuned to the visitor's key | atonal clusters, harsh ring-modulated metal, more distortion |
| N neuroticism | glitch stutters, noise risers, detuned drone and stabs, hat rolls | stable, in tune, few risers |

**Intensity** (0 to 1) picks how hard the arrangement goes (gentle sections or drops and peaks), how many hits play, the distortion drive, how open the filters are and how loud the percussion is.

**Tempo**: the show's `tempo` is used directly, clamped to 120 to 145 BPM. If no tempo is sent, it comes from extraversion, nudged by the hook.

**Hook** (picks the arrangement family; OCEAN still tunes the details inside it). Hooks crossfade over about two bars. They take full effect in the hook phase and partial effect in the phases on either side.

| hook | what it sounds like |
|---|---|
| flesh | slower and heavy: a deep, boomy kick, big rumble, loud low drones and a squelchy acid bassline |
| scrawl | broken, stumbling kick patterns, choppy cut-up "spoken fragment" bursts (formant-filtered noise, not real speech), lots of stutter, a rolling bassline |
| inverted | reversed clanks, stabs and hats, reverse-reverb swells sucking into each bar, off-grid hats, a rolling bassline |
| mirror | close, quiet and intimate: breaths near the ear, soft sub, the kick almost gone |
| void | sub-bass and near silence (deliberately very quiet) |
| anything else | the neutral mix above |

**Phone** (follows within about 150 ms):

| movement | effect |
|---|---|
| left/right (`steer.x` or `tilt.x`) | moves the percussion and stabs across the stereo field, and turns up the resonance of the main filter, so tilting gives the classic "squelchy" whistling sweep |
| forward/back (`steer.y` or `tilt.y`) | forward opens the main filter, brightens the whole mix and adds reverb; back closes it down to a muffled thud |
| upside down (`steer.flip`) | sounds play reversed |
| shake (`steer.shake` or `tilt_energy`) | a stutter or glitch burst plus a short noise riser, at most once per bar |

## For the show engine

```python
from infinite_jest import audio
eng = audio.create(config)
eng.start()
eng.on_state(state)     # any time the show state changes, as often as you like
eng.on_sensor(data)     # raw phone data (steer / tilt / tilt_energy / shake / accel)
eng.set_volume(0.7)     # 0..1, glides smoothly, no clicks
eng.on_wipe()           # dissolve, forget the visitor, go back to idle
eng.stop()
```

The sound runs in its own process, so it never slows down the visuals. If that process ever crashes, a watchdog restarts it after 1 second (then 2, 4 ... up to 30 seconds if it keeps crashing), logs it, and sends it the last show state, so the music comes back by itself. `on_wipe`, `set_volume` and `stop` work even while it is restarting. Any state field can be missing or malformed; the engine ignores what it can't read. When only the old orientation format is available, `tilt` can also be sent in degrees as `{beta, gamma}`. The new state field `hinge` (true or false) triggers the hinge described above.

For the film rig, `TechnoSynth(seed=0)`, `set_state()`, `render_block()` and `.B` work as before: one `render_block()` call gives one block of 1024 stereo frames.

## Loudness and sound quality

The master chain ends in a clean-up stage like a mastering engineer's: low-frequency DC removal, a gentle "glue" compressor, and a limiter that looks ahead so peaks never clip, including the in-between peaks that MP3 encoders and DACs can create. Everything below about 120 Hz is kept mono so the kick and sub hit hard on any PA, and everything above is spread wide.

Measured on the 10-minute evening: about -11 LUFS overall, with hook sections at -9 to -11 LUFS (club-loud), true peak -0.8 dBTP, no DC offset and no clicks at block boundaries.

## CPU

Offline the engine renders about 11 to 13 times faster than real time on one core of a desktop x86 CPU. Played live, the sound process uses about 9% of one desktop core. On the Pi 5 (Cortex-A76) we expect about 22 to 30% of one core, but this is an estimate and has not been measured on a Pi yet. That leaves room for the visuals and a local LLM on the other cores. To check it on the Pi, run the demo with `--render x.wav`; it prints the realtime factor when it finishes. Below about 4x on the Pi would be a warning sign.

## Files

- `synth.py`: the music, covering patterns, phases, hooks, the hinge, the wipe, the OCEAN mapping and the master chain
- `compose.py`: the long-form structure: sections, phrases, fills, chord progressions, kits and the set clock
- `bass.py`: the acid and rolling basslines
- `voices.py`: the drum and effect sounds themselves (five kick families, rumble, hats, clank, stab and so on)
- `dsp.py`: filters, distortion, the warehouse reverb, delay, compressor and limiter
- `engine.py`: runs the synth in its own process, with the watchdog and speaker retry
- `sinks.py`: the audio output (aplay, sounddevice or silent)
- `demo.py`: the demo, the 10-minute evening and the per-hook samples
- `analyze.py`: measures a rendered file (loudness, peaks, tempo, key, repetition)
- `tests/`: automatic tests for the speaker retry and crash restart. Run them with `python3 -m unittest infinite_jest.audio.tests.test_robust`

## CHANGES

**v2 (this version)**

- *Structure:* the music now has long-form structure: sections and phrases with fills and sweeps, chord progressions, and a set clock that drifts key, scale, tempo, kit and energy over hours. It no longer loops one groove per phase.
- *New controls:*
  - The hinge: a new `hinge` state that drops to sub-bass only, then slams back in.
  - Release now lasts 50 s and evolves (break, afterglow, outro).
  - Wipe now dissolves over about 12 s instead of 2 s.
  - Phone left/right tilt now drives a resonant filter sweep.
  - `set_volume()` changes the volume live, smoothly. `volume` is accepted as a config name for `audio_volume`.
- *New sounds:*
  - five tuned kick families
  - a sidechained rumble
  - acid and rolling basslines (flesh, scrawl, inverted)
  - a warehouse reverb with early reflections
  - better distortion (no harsh aliasing)
  - a wide stereo image that stays mono in the bass
- *Mastering:* a proper master chain (DC removal, glue compressor, true-peak limiter) at club loudness.
- *Robustness:*
  - the engine retries a missing or unplugged speaker every 7 s
  - a watchdog restarts a crashed sound process
  - tests cover both
- *Latency:* the default buffer is now 80 ms (was 150 ms), so tilt feels more immediate.
- *Same as before:* the show interface is unchanged (`create`, `on_state`, `on_sensor`, `start`, `stop`, `on_wipe`), and so is the film rig interface.
- *Dropped:* the visual-inspiration references were removed from the hook descriptions.

## Known limits

- CPU use on the Pi is estimated, not measured. Please run `--render` on the Pi once and check the realtime factor.
- The rumble is subtle under the kick on small speakers.
- The same visitor always gets the same motif, kit and riff. If they arrive at a different moment in the evening, though, their hits can land a bar earlier or later, and the key may differ.
- `void` and `mirror` are much quieter than the other hooks on purpose.
- scrawl and inverted can be quite bright at their peaks.
