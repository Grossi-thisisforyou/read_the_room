# Technical breakdown

Everything runs on one Raspberry Pi 5, offline. No cloud, no internet during the show.

## Hardware

| Part | What it does |
|---|---|
| Raspberry Pi 5, 16 GB, official Active Cooler, 27 W supply | Runs the whole show |
| 256 GB microSD card | System, code, models |
| USB stick | Offline installer for the models, and the donated family footage (read in place, never copied) |
| NEC wall screen in room 401 (HDMI 0) | The picture |
| Second output (HDMI 1, optional) | The "machine view" or a projector after dark |
| USB audio interface + powered speaker | Sound, 48 kHz |
| Cardioid USB microphone | Hears *that* someone speaks and for how long |
| USB webcam | Presence, stillness, live images (memory only) |
| Stone case, 3D printed | See [the shell](shell.md) |
| Mac (laptop) | Updates over a network cable; the Pi has no keyboard |

The Pi boots straight into the show with a custom boot splash. If it crashes, a
watchdog restarts it. Shutdown is always clean (`sudo poweroff` or the power button).

## Software

```
 mic (level, voice yes/no) ─┐
 webcam (frames, RAM only) ─┼─► room sensing ─► profiler ─► director ─┬─► screen (HDMI 0)
 guest file (from booking) ─┘    presence        OCEAN        tide     ├─► second screen (HDMI 1)
                                 stillness       bandit       mood     └─► speaker
                                 speech turns                    ▲
                                                                 │
          local AI services:  words (Qwen) · paintings (SD-Turbo) · dream + face nets · voice (Piper)
```

- **Show engine** (`infinite_jest/pi`, Python): an asyncio app with a 30 fps renderer
  (pygame + numpy) and a local control page on port 8765. It moves a visit through
  its phases (idle, approach, profiling, hook, release, wipe) and holds the "duet" of
  two screens.
- **Tide** (`duet.arc`): one slow wave of 2.5 to 5.5 minutes that drives both the picture
  and the music, so they build and ebb together.
- **Collage**: family footage (about 45% of the time), the guest's public pictures, the
  Pi's own paintings and the live camera, with hard glitch cuts.
- **Conversation** (`talk.py`): asks a question, listens about 11 s by voice activity,
  classifies the answer as none, short or long, and replies. A ledger guarantees that
  no sentence is ever said twice.
- **Daily mood** (`mood.py`): a random mood each boot or 24 hours colours every line.
- **Music** (`audio/ambient.py`): a synthesiser written in numpy that runs in its own
  process, tuned by numbers only, no samples. Ducks under the voice.
- **Privacy by design**: frames live only in RAM; the mic yields a level and a voiced
  flag, nothing else; every module drops the visitor at the wipe.

## The AI models

All of them run on the Pi's CPU. Sizes are on-disk.

| Model | Job in the piece | How it runs | Size |
|---|---|---|---|
| **Qwen2.5-1.5B-Instruct** (Alibaba), 4-bit GGUF (Q4_K_M) | Writes fresh lines live: follow-up answers in the conversation, words on the wall, the profile text. Hand-written lines are the fallback. | llama.cpp server on 127.0.0.1:8080, 2 threads at low priority so picture and sound keep the rest | 1.1 GB |
| **SD-Turbo** (Stability AI) + **TAESD** decoder | Paints new images in the background, one step per image, for the collage and the wall | stable-diffusion.cpp, built static for the Pi 5 | 5.2 GB |
| **Dream net** (our own) | The live, ever-changing wall image: a small decoder that walks between "anchor" points so the stream never stops and never repeats | trained off the Pi with PyTorch (generative latent optimisation), run on the Pi in pure numpy, about 0.3 GFLOP per frame | 1.9 MB |
| **Face net** (our own) | Grows a face on the screen in bursts while the visitor stays | same decoder, trained per guest from public pictures, stepped through its training checkpoints | about 1.6 MB per step |
| **Piper** (neural text to speech) | The room's spoken voice, mixed into the music | ONNX Runtime; voice files copied from the Mac. espeak-ng is the fallback voice | about 60 MB per voice |
| **Profiler** (not a neural net) | OCEAN estimate with capped confidence, then a Thompson-sampling bandit over the five scenes | plain Python | tiny |

What is deliberately *not* used: speech recognition, face recognition, emotion
detection, any cloud API.

### Status (Nov 24)

- All models ship in the current update and are being tested on the Pi before the install.
- Piper is not yet confirmed on the Pi; espeak-ng speaks until it is.
- The microphone works; the Canon camera was not recognised over USB, so a webcam or an
  HDMI capture stick will be used.

## Updates

Updates go to the Pi as one zip (`ij-update.zip`) copied from the Mac over a network
cable and installed by a script that keeps the Pi's own settings. The models install
offline from the USB stick.
