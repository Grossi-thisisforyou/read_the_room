# INFINITE JEST: sound engine

This folder makes the music. It is a live techno generator in a dark industrial, Berlin-warehouse style: a rumbling kick, distorted hats, metal clanks, data ticks, noise risers, sub drones and detuned stabs. Nothing is pre-recorded. Every sound is synthesised on the spot, and the track keeps changing to follow the show:

- **the phase of the visit**: someone walking in, being profiled, being hooked, being let go
- **the visitor's OCEAN profile** (their five personality scores)
- **their hook**, the imagery family the show has chosen for them
- **the phone's tilt and shake**

Each visitor gets "their" track. The patterns come from a random-number generator seeded with the visitor's id, so the same person always gets the same groove, and someone else gets a different one.

It runs on the Raspberry Pi 5 with no internet. It needs only Python 3 and numpy.

## Hear it without the show

The demo invents a visitor and walks them through the whole arc: idle, approach, profiling, hook, release. Then it wipes and a new visitor arrives with a new personality and the next hook. A slow fake phone tilt sweeps the sound around.

**On a Mac or laptop**

```
pip3 install numpy sounddevice
cd read_the_room
python3 -m infinite_jest.audio.demo
```

Macs don't have `aplay`, so the demo plays through `sounddevice`. If you'd rather not install that, render to a file and open it in any player:

```
python3 -m infinite_jest.audio.demo --render test.wav --seconds 90
```

Options: `--ocean 0.9,0.3,0.4,0.1,0.9` fixes the five scores (in O,C,E,A,N order). `--hook scrawl` fixes the hook. `--seed 3` picks a different fake visitor. `--no-tilt` turns off the fake tilt.

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

Other config keys, all optional:

- `master_gain`: overall volume, 1.0 by default
- `audio_latency_ms`: output buffer, 150 by default
- `audio_sink`: `auto`, `aplay`, `sounddevice` or `null` (silent, for testing)
- `audio_seed`: changes every visitor's track at once

## What controls what

**Phase** (the shape of the visit; changes glide over about a bar):

| phase | what you hear |
|---|---|
| idle | a sparse breathing drone, with a distant, muffled kick every other bar |
| approach | the kick comes in at half time, then four-on-the-floor, with rumble under it |
| profiling | hats, ticking "data" clicks, clanks, risers: tension |
| hook | the full groove, tuned to this visitor; an impact marks the drop |
| release | breakdown: the kick drops out, leaving the drone and a long reverb wash |
| wipe | fades to silence in 2 seconds, forgets the visitor, then the idle drone returns |

**OCEAN** (personality; each score glides over about two bars):

| score | high | low |
|---|---|---|
| O openness | odd variations, 3-against-4 (or 5/7) clank polyrhythm, weird metallic timbres | a fixed clank position, plain timbres |
| C conscientiousness | tight, quantised, repeating patterns | swing, random ghost notes, flams, dropouts |
| E extraversion | louder, brighter, faster (tempo about 126 + 14×E), more hats, open hats, claps | darker, sparser, fewer claps |
| A agreeableness | consonant minor drone and chord stabs; clanks tuned to the visitor's key | atonal clusters, harsh ring-modulated metal, more distortion |
| N neuroticism | glitch stutters, noise risers, detuned drone and stabs, hat rolls | stable, in tune, few risers |

**Intensity** (0 to 1) sets how many hits play, the distortion drive, how open the filters are and how loud the percussion is.

**Tempo**: the show's `tempo` is used directly, clamped to 120 to 145 BPM. If no tempo is sent, it comes from extraversion.

**Hook** (picks the arrangement family; OCEAN still tunes the details inside it). Hooks crossfade over about two bars. They take full effect in the hook phase and partial effect in the phases on either side.

| hook | character |
|---|---|
| flesh | slow, heavy, low kick; big rumble; loud low drones (Bacon) |
| scrawl | broken kick patterns, choppy cut-up "spoken fragment" bursts (formant-filtered, not real speech), lots of stutter |
| inverted | reversed clanks, stabs and hats, reverse-reverb swells into each bar, off-grid hats |
| mirror | close, quiet, intimate: breaths near the ear, soft sub, kick almost gone |
| void | sub-bass and almost silence |
| anything else | the neutral mix above |

**Phone** (follows within about 150 ms):

| movement | effect |
|---|---|
| left/right (`steer.x` or `tilt.x`) | moves the percussion and stabs across the stereo field; sweeps the stab and drone filter |
| forward/back (`steer.y` or `tilt.y`) | forward opens the main filter, brightens the whole mix and adds reverb; back closes it down |
| upside down (`steer.flip`) | sounds play reversed |
| shake (`steer.shake` or `tilt_energy`) | a stutter or glitch burst plus a short noise riser, at most once per bar |

## For the show engine

```python
from infinite_jest import audio
eng = audio.create(config)
eng.start()
eng.on_state(state)     # any time the show state changes, as often as you like
eng.on_sensor(data)     # raw phone data (steer / tilt / tilt_energy / shake / accel)
eng.on_wipe()           # fade out, forget the visitor, go back to idle
eng.stop()
```

The sound runs in its own process, so it never slows down the visuals. Any state field can be missing or malformed; the engine ignores what it can't read. When only the old orientation format is available, `tilt` can also be sent in degrees as `{beta, gamma}`.

## CPU

The engine renders about 11× faster than real time on one core of a desktop x86 CPU, which is roughly 9 to 11% of a core including the process overhead. On the Pi 5 (Cortex-A76) we expect about 20 to 30% of one core, but this is an estimate and has not been measured on the Pi yet. That leaves room for the visuals and a local LLM on the other cores. To check it on the Pi, run the demo with `--render x.wav`; it prints the realtime factor when it finishes.

## Files

- `synth.py`: the music, covering patterns, phases, hooks and the OCEAN mapping
- `voices.py`: the sounds themselves (kick, rumble, hats, clank, stab and so on)
- `dsp.py`: filters, reverb and delay
- `engine.py`: runs the synth in its own process
- `sinks.py`: the audio output (aplay, sounddevice or silent)
- `demo.py`: the demo
