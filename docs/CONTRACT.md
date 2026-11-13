# Infinite Jest: interface contract

Version 1.1 (2026-11-13). Owner: the master-plan thread. Any change to this file
goes through a PR, and every module thread is told when it changes.

This is the one place that says how the parts of *Infinite Jest* talk to each
other. If your code and this file disagree, this file wins until it is changed.

## Where the code lives

Repo `Grossi-thisisforyou/read_the_room`, folder `infinite_jest/`:

| Folder | What | Runs on |
|---|---|---|
| `infinite_jest/pi/` | show engine, WebSocket hub, state machine | Pi 5 |
| `infinite_jest/profiler/` | camera and sensor analysis, OCEAN guess, hook choice | Pi 5 |
| `infinite_jest/visuals/` | projector renderer + pre-generated image library | Pi 5 (HDMI 0) |
| `infinite_jest/audio/` | generative industrial techno | Pi 5 |
| `infinite_jest/phone/` | N900 sensor app | Nokia N900 |
| `infinite_jest/case/` | Pi shell (CAD, print files) | n/a |

One branch and one PR per module.

## Hardware this contract assumes

From Baby's photos, 2026-11-13:

- **Raspberry Pi 5, 16 GB**, 256 GB SanDisk Extreme PLUS microSD, Raspberry Pi
  OS Lite, hostname `inartwetrust`, user `pi`. No analog audio jack.
- **Nokia N900** (Maemo 5). Wi-Fi 802.11b/g only. Old browser (no WebSocket),
  so the phone runs a native Python 2.5-compatible agent, not a web page. Rear 5 MP camera, front VGA camera, accelerometer, proximity,
  ambient light, mic, resistive touch screen.
- **Linksys WRT150N v1.1** router. Offline LAN, no internet at show time.
- One projector and one speaker (models not known yet).

## Network

| Thing | Value |
|---|---|
| Router SSID | `infinitejest` (WPA2-AES, mixed b/g/n so the N900 can join) |
| Router address | `192.168.1.1` (WRT150N default) |
| Pi | Ethernet to a LAN port, DHCP reservation **`192.168.1.10`**, also `inartwetrust.local` |
| N900 | Wi-Fi, DHCP reservation **`192.168.1.20`** |
| Baby's Mac (control, debugging) | any address |

Use the IP `192.168.1.10` in the phone app. mDNS on the N900 is unreliable.

## Ports on the Pi

| Port | Proto | Path | Who |
|---|---|---|---|
| 8765 | WebSocket | `ws://192.168.1.10:8765/ws` | **everyone, including the N900 agent** (default) |
| 8765 | HTTP POST | `/api/sensor` | fallback for the N900 if its WebSocket client misbehaves: one envelope or a JSON array of envelopes per request |
| 8765 | HTTP POST | `/api/frame` | fallback for frames: body is one `frame` envelope |
| 8765 | HTTP GET | `/phone/` | static files from `infinite_jest/phone/` |
| 8765 | HTTP GET | `/status` | JSON health: clients connected, phase, fps, last sensor ts |
| 8766 | UDP | n/a | optional fast lane for the N900: one JSON envelope per datagram, `type` must be `sensor` |

One aiohttp server serves 8765. The engine thread owns it.

## Envelope

Every message, on every transport, is one JSON object:

```json
{"type": "sensor", "ts": 1763076000.123, "data": { ... }}
```

- `type`: one of the types below. Unknown types are logged and ignored, never fatal.
- `ts`: Unix time in seconds, float, set by the sender. The Pi's clock is the
  reference; the engine adds `rx_ts` when it forwards a message.
- `data`: an object. **Every field in `data` is optional.** A receiver uses a
  default when a field is missing and ignores fields it does not know.

## Handshake

The first message on a WebSocket is:

```json
{"type": "hello", "ts": 0, "data": {"role": "phone|profiler|visuals|audio|control", "device": "n900", "name": "free text", "version": "1.0"}}
```

The engine answers with the current `state`. HTTP and UDP senders skip the
handshake; they are treated as role `phone`.

## Message types

### `sensor` (phone to engine; engine forwards to `profiler`)

`data.kind` says what it is. Periodic readings are `kind: "phone"` at about
10 Hz; events are sent when they happen. All fields optional.

`kind: "phone"` (periodic):

| Field | Type | Meaning |
|---|---|---|
| `motion` | 0..1 | movement energy in the camera image, if the phone computes it |
| `presence` | 0..1 | how sure someone is in front of the camera |
| `loudness` | 0..1 | mic RMS, normalised |
| `audio` | `{level 0..1, voiced bool}` | mic level and a crude "someone is talking" flag (no recording, no words) |
| `light` | 0..1 | ambient light sensor |
| `proximity` | `{near: bool}` | N900 proximity sensor (near = within ~5 cm) |
| `accel` | `{x, y, z}` in g | raw accelerometer |
| `tilt` | `{alpha, beta, gamma}` degrees | derived from `accel` (alpha may stay 0, the N900 has no compass) |
| `held` | bool | phone is being handled (accel variance) |
| `shake` | 0..1 | shake strength |
| `slide` | bool | keyboard slid open |
| `battery` | 0..1 | for the health check |

Events: `kind: "touch"` `{x, y, down}` with x, y 0..1; `kind: "choice"`
`{prompt_id, option}` answering a `phone` prompt; `kind: "keys"` `{text}`
typed on the N900 keyboard.

### `frame` (phone to engine; engine keeps it in memory for the profiler)

```json
{"type": "frame", "ts": 1763076000.5, "data": {"w": 160, "h": 120, "fmt": "gray8", "b64": "..."}}
```

`fmt` is `gray8` (raw 8-bit grayscale, w*h bytes) or `jpeg`. At most 320x240,
at most 4 fps, front camera by default. The engine keeps only the last few
frames in memory and hands them to the profiler (forwarded over WebSocket to
role `profiler`, or read in-process if the profiler runs inside the engine).
**Frames are never written to disk.**

### `phone` (engine to phone)

What the N900 screen shows. `{"text": "you came back", "prompt_id": "p3", "ask": "stay or leave?", "options": ["stay", "leave"]}`.
All fields optional; `text` alone just shows words. The phone also receives
`state` and `wipe`.

### `profile` (profiler to engine)

Send when the guess changes, at most 2 Hz.

| Field | Type | Meaning |
|---|---|---|
| `visitor_id` | string | the id from the current `state` |
| `ocean` | `{O, C, E, A, N}` each 0..1 | Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism |
| `confidence` | 0..1 | how much to trust `ocean` |
| `hook` | string | the hook the profiler thinks holds this visitor best, see the list below |
| `hook_scores` | `{hook: 0..1}` | optional bandit scores per hook |
| `features` | object | optional debug values (dwell_s, approach_speed, stillness...) for the control view |

### `state` (engine to everyone)

Broadcast at 10 Hz and on every change.

| Field | Type | Meaning |
|---|---|---|
| `visitor_id` | string | random per visit, e.g. `v-7f3a`; empty in `idle` |
| `phase` | string | `idle`, `approach`, `profiling`, `hook`, `release`, `wipe` |
| `phase_t` | seconds | time spent in the current phase |
| `scene` | string | scene name the visuals should show |
| `hook` | string | current hook |
| `ocean` | `{O,C,E,A,N}` | current best guess, 0..1 |
| `intensity` | 0..1 | overall drive for picture and sound |
| `palette` | `{name, colors: ["#hex", ...]}` | colors for visuals |
| `tempo` | bpm | 120..145 |
| `words` | list of strings | short "dark data" text fragments the visuals may scrawl (no names, no personal data) |

### `control` (control client to engine)

`{"cmd": "wipe" | "next" | "blackout" | "scene" | "hook" | "volume", "arg": ...}`.
Only from role `control` (Baby's Mac or the N900 keyboard).

### `wipe` (engine to everyone)

`{"visitor_id": "v-7f3a"}`. Sent at the end of every visit and on `control`
wipe. On receiving it, every module drops everything it holds about that
visitor: frames, features, scores, words.

## Phases

```
idle --presence--> approach --3 s--> profiling --confidence>=0.5 or 20 s--> hook
hook --presence lost 8 s or 180 s max--> release --6 s--> wipe --> idle
```

Timings are defaults in `infinite_jest/pi/config.toml`; the engine thread owns them.

## Hooks

The five visual and sonic "hooks". Visuals and audio must each have
something for all five, and must do something sensible for an unknown name.

| Hook | Image idea | Sound idea | Pulled by |
|---|---|---|---|
| `flesh` | Bacon: smeared bodies, cages, raw meat pinks | slow heavy kick, low drones | high N, low A |
| `scrawl` | Basquiat: scrawled words, crowns, crossed-out data | broken rhythm, spoken fragments | high O |
| `inverted` | Baselitz: upside-down figures, raw strokes | reversed sounds, off-grid hats | high O, low C |
| `mirror` | the visitor's own silhouette, distorted | close, intimate, quiet, breath | high E or wants attention |
| `void` | near black, slow pulse, one line of text | sub-bass, almost silence | high C, low E |

The mapping column is a starting point; the profiler thread owns it.

## Palettes

Named palettes the engine may send. Visuals may define more.

| Name | Colors |
|---|---|
| `meat` | `#0b0b0b`, `#3a0d0d`, `#8c1c1c`, `#d9826b`, `#efe6dc` |
| `bruise` | `#050507`, `#1d1630`, `#4b2c5e`, `#8a6a9c`, `#d8d0c0` |
| `crown` | `#0a0a0a`, `#1a1a1a`, `#e8c547`, `#c0392b`, `#f2f2f2` |
| `ash` | `#000000`, `#151515`, `#3d3d3d`, `#8a8a8a`, `#e0e0e0` |
| `sodium` | `#050300`, `#2b1600`, `#a35200`, `#ff8c1a`, `#fff1d6` |

## Privacy rules (default, Baby can change them)

These are design choices for a piece that reads people in a school building:

1. An entrance notice says the room watches, listens and guesses who you are.
2. Everything runs on the Pi and the phone. Nothing leaves the local network.
3. No raw camera frames or audio are written to disk. Frames live in memory only.
   Audio is never recorded and never transcribed: only level and a voiced flag
   (recording visitors' conversations can be illegal eavesdropping in New York).
4. No identification, no face templates or dense face meshes, no age, gender,
   race or emotion guesses. Face detection (a box) is fine; recognition is not.
5. Every visit ends with `wipe`. Logs keep only counts and timings, no ids.
6. `control` `blackout` stops sensing and projection at once.

## Changing this contract

Open a PR that edits this file, bump the version line, and tell the master-plan
thread. Additive changes (a new optional field, a new hook name) are fine
without waiting; renaming or removing anything needs every thread's OK.
