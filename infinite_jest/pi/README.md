# Infinite Jest · Pi show engine

The program that runs the whole installation on the Raspberry Pi 5, unattended.
Power the Pi on and the show starts: it listens to the Nokia N900, notices when
someone walks in, reads them for a minute or two, plays the imagery and sound
that hold them best, shows them what it guessed, and then deletes them.

```
 N900 (sensors, camera) ──ws / udp / tcp──►  ┌──────────── Pi 5 ────────────┐
 profiler (in process or over /ws) ────────► │ hub ─► presence ─► visit ─►  │ ──HDMI──► projector
 Baby's laptop: control page ──────────────► │        director ─► "state"   │ ──audio─► speaker
                                             └──────────────────────────────┘
```

## One visit

| Phase | What happens | Default length |
|---|---|---|
| `idle` | near-black room, low hum, waiting | until someone arrives |
| `approach` | the room notices: scanning, "I see you." on the phone | 3 s |
| `profiling` | the dossier builds; the profiler guesses OCEAN scores | 6 to 20 s |
| `hook` | the scene that holds this person: `flesh`, `scrawl`, `inverted`, `mirror` or `void`, tuned to their scores | while they stay, max 180 s |
| `release` | the reveal: what the machine thinks it learned | 6 s |
| `wipe` | a visible erase; every module drops everything about the visitor | 4 s |

In the default `handheld` mode, picking up the N900 starts a visit and putting
it down for 8 s ends it (`mode = "fixed"` lets the camera and mic start visits
instead). A visitor who covers the phone's proximity sensor opts out; the room
goes quiet. All of this is in [`config/default.toml`](config/default.toml).

## Tilt

The phone's tilt is the main interaction. Every `state` carries:

- `steer`: `{x, y}` from -1 to 1 (roll and pitch, 0,0 = flat), `flip` (phone upside
  down, the Baselitz flip), `shake` 0..1 and `still_s` (seconds held still).
- `tilt`: the raw angles plus the smoothed `x`, `y` and `energy` (how much it's moving now).

It's smoothed every frame, so the picture moves at 30 fps although readings
arrive at 10 Hz. Moving the phone also lifts the intensity. Visuals and audio
also get the raw phone reading through an optional `on_sensor(data)`.

## The local language model

`bash install.sh --with-llm` builds llama.cpp and downloads Qwen2.5-1.5B-Instruct
(4-bit, about 1 GB), then runs it as the `llama-server` service on
`127.0.0.1:8080`. It uses 2 threads on CPU cores 2-3 at low priority, so the
picture and sound keep the rest. The oracle module (`infinite_jest/oracle/`)
asks it for words; the engine shows `oracle` messages as `state.words` and the
phone text on the N900. If the model is slow or off, the profiler's own lines
are used instead. A bigger model: `MODEL_URL=<gguf url> bash llm_install.sh`.

## Try it on a laptop (no Pi, no phone)

```bash
cd infinite_jest/pi
pip install aiohttp pygame numpy          # once
python3 -m showengine --windowed --simulate --debug
```

Fake visitors walk in and out. Open http://localhost:8765/ for the control
page (next phase, wipe, blackout, force a hook). Keys in the window: `D` debug
overlay, `N` next phase, `W` wipe, `B` blackout, `Esc` quit.

## Put it on the Pi

1. Get this repo onto the Pi (git clone, or copy the folder over).
2. Give the Pi internet once (home Wi-Fi, or Ethernet to the Mac with Internet Sharing).
3. On the Pi:
   ```bash
   cd read_the_room/infinite_jest/pi
   bash install.sh            # add --with-opencv if you want the Pi to count faces
   ```
4. That's it. It now starts on every power-on. Check with `journalctl -u infinite-jest -f`.

In the room the Pi goes on the Linksys by Ethernet with the reserved address
`192.168.1.10`; the control page is then http://192.168.1.10:8765/.

Sound: the Pi 5 has no headphone jack, so sound goes over HDMI to the projector
by default. For a USB sound card set `audio_device` in
`~/.config/infinite-jest/engine.toml` (run `aplay -l` to see the cards).

## How the parts plug in

The message format and ports are in [`docs/CONTRACT.md`](../../docs/CONTRACT.md).
In short, port 8765 on the Pi:

- `ws://…:8765/ws`: everyone. First message `{"type":"hello","data":{"role":"phone|profiler|oracle|visuals|audio|control"}}`.
- `POST /api/sensor`, `POST /api/frame`: HTTP fallback for the N900.
- `GET /status`: health JSON. `GET /`: control page. `GET /phone/`: files from `infinite_jest/phone/`.
- UDP 8766: one `sensor` envelope per datagram. TCP 8767: raw JPEG stream from the N900 camera.

The sibling modules load in-process if present, and each is optional:

| Module | Engine calls |
|---|---|
| `infinite_jest/visuals` | `create(size, cfg)` → `on_state(state)`, `render(surface, dt)`, `on_frame(rgb)`, `on_wipe()` |
| `infinite_jest/audio` | `create(cfg)` → `start()`, `on_state(state)`, `on_wipe()`, `stop()` |
| `infinite_jest/profiler` | `create(cfg)` → `on_sensor(data, ts)`, `on_frame(data, ts)`, `on_visit(visit, ts)` return a profile/reveal or None; `reset()` |

Missing one? The engine uses its own: a built-in procedural look and a built-in
techno loop (`showengine/outputs/`), and a crude on-Pi OCEAN guess
(`showengine/fallback_profile.py`). A crashing module is logged and skipped, never fatal.

## Privacy, as built

- Nothing is written to disk: no frames, no audio, no sensor logs. Frames are
  measured and dropped.
- Each visit gets a random id like `v-7f3a`. The log records phases and
  counts only, never ids.
- `wipe` at the end of every visit empties the engine's visitor data in place
  and tells every module to do the same.
- `blackout` (control page or `B`) stops sensing and projection at once.

## Tests

```bash
cd infinite_jest/pi
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python3 -m pytest -q
```

The visit logic runs on a fake clock (minutes of show in milliseconds); the hub
test opens real WebSocket, HTTP, UDP and TCP connections on localhost.

## Files

```
showengine/
  __main__.py        command line
  app.py             runner: display, modules, frame loop
  hub.py             aiohttp server, UDP, TCP JPEG stream, control page
  engine.py          message handling, phase changes, wipe
  visit.py           the per-visitor state machine (pure logic)
  presence.py        is someone there? (hysteresis; handheld or fixed)
  tilt.py            phone tilt -> smooth steering, flip, shake, stillness
  director.py        phase + profile -> scene, intensity, palette, tempo
  fallback_profile.py crude OCEAN guess when no profiler runs
  frames.py          N900 camera frames -> motion, light, faces
  sim.py             fake visitors
  outputs/           built-in fallback visuals and audio
config/default.toml  every setting, commented
systemd/             the boot services (engine, llama-server)
install.sh           one-time Pi setup
llm_install.sh       llama.cpp + Qwen (via install.sh --with-llm)
tests/
```
