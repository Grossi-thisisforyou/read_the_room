# INFINITE JEST: the phone

The phone is the piece's input and its most intimate surface. Visitors pick it
up, tilt it, talk near it, answer its questions on the screen or on the
slide-out keyboard. It streams all of that to the Pi, which turns it into
picture and sound.

The phone is a **Nokia N900** (Maemo 5, 2009). Its browser is too old for
camera, microphone or WebSockets, so it runs a **native Python app** that takes
over the screen at boot. A browser version for a modern phone is the backup.

| Folder / file | What |
|---|---|
| `n900/` | the N900 app (Python 2.5 compatible, also runs on Python 3 for tests) |
| `index.html` | backup: browser app for a modern iPhone / Android (needs https for sensors) |
| `tests/` | end-to-end test against a mock Pi, and a screen renderer |

## What the N900 sends (see `CONTRACT.md`)

All over `ws://192.168.1.10:8765/ws`, falling back to UDP port 8766 while the
WebSocket is down:

- `hello` `{role:"phone", device:"n900"}` on connect.
- `sensor` kind `phone` **20 times a second**: `tilt {alpha, beta, gamma}`,
  `accel {x,y,z}` in g, `held`, `shake`, `motion` (front camera), `presence`,
  `loudness`, `audio {level, voiced}`, `light`, `proximity {near}`, `slide`,
  `battery`.
- events: `touch {x, y, down, gesture, duration_ms}`, `choice {prompt_id,
  option, latency_ms}`, `keys {text, typing_ms, backspaces}`, `optout`.
- `frame` `{w:160, h:120, fmt:"gray8", b64}` from the front camera, 4 per second,
  so the Pi can find faces. Frames live in RAM only, on both ends.

It shows what the Pi sends: `state` (palette, tempo, intensity, hook, words
drive the screen), `phone` (words, and either/or prompts split across the
screen), and `wipe` (everything cleared, back to the first screen).

## Consent and privacy, built in

- The first screen says plainly: *This room is recording you. The camera,
  microphone and motion of this phone feed a performance made only for you.
  Nothing leaves this room. Everything is erased when you leave.*
- **Opt-out**: covering the proximity sensor ("the eye", top left of the
  screen) for 3 seconds stops all reading of that visitor until the phone has
  been out of anyone's hands for 8 seconds (`optout_release_s`, judged from
  the accelerometer and touch only), even if the Pi ends the visit sooner.
  While the sensor stays covered it stays closed, unless the phone lies still
  face-down (that is the plinth). After the opt-out ends, the sensor must read
  uncovered once before it can opt out again, so a phone left face-down does
  not loop. The screen says *you are not being read*.
- Sound is reduced to a level and a yes/no "someone is talking" on the phone
  itself. No audio is ever recorded or sent.
- Nothing is written to the phone's disk except settings and a log of errors.
- After 90 s with nobody there, the phone wipes itself and goes back to the
  first screen.

## The look

Rendered previews (800x480, the N900's screen) come from
`python3 tests/render_screens.py OUTDIR`. Near-black, grain and scanlines,
raw off-white condensed type; Basquiat crowns and crossed-out words, Baselitz's
upside-down title and words, a Bacon head that won't hold its shape (the mouth
opens with the room's loudness, motion tears it, tilt moves it). A "dark data"
readout keeps telling the visitor what it is collecting: tilt, voice, how
often they deleted what they typed, how sure it is they are there.

## Installing on the N900

You need, once: **Python 2.5 + PyGTK** (PyMaemo, from Maemo Extras) and
**rootsh** (for `sudo gainroot`). If the phone ran Python apps before (the OSC
tilt sender), they are probably there already: check in X Terminal with
`python2.5 -c "import gtk, cairo"`.

1. Connect the N900 to the Mac by USB and pick **Mass storage mode**.
2. Copy the whole `infinite_jest` folder to the phone's drive as
   `infinite_jest_phone` (the profiler's `prompts.json` comes along).
3. Unplug. On the N900 open **X Terminal** and type:
   ```
   sudo gainroot
   sh /home/user/MyDocs/infinite_jest_phone/phone/n900/install.sh
   ```
4. The screen turns black with *THIS ROOM IS RECORDING YOU*. That's it: it
   starts by itself at every boot from now on.

Check it worked: the small dot in the top-right corner is **pale** when the Pi
is connected, **blinking yellow** when only the UDP fallback works, **blinking
red** when it can't reach the Pi. The log is `/home/user/.ij-phone.log`.

To quit on the phone: hold the top-left corner for 5 seconds, or Ctrl+Q on the
keyboard. To uninstall: `sh install.sh --remove` as root.

Settings (Pi address, rates, camera) are in `/home/user/.ij-phone.conf`.

## Network

Router: Linksys WRT150N, SSID `infinitejest`, WPA2-AES, **mixed b/g/n** (the
N900 only does 802.11b/g). Pi on Ethernet at `192.168.1.10`, N900 reserved at
`192.168.1.20`. In the N900's Settings > Internet connections, save the network
and set **Connect automatically: WLAN**. The app retries the Pi forever on its
own.

## Letting visitors handle it

Baby wants visitors to pick it up and tilt it, so:

- **Power**: keep it on the charger with a long, slack micro-USB cable from a
  wall charger (not a computer port, which flips it into USB mode). Tape or
  strain-relieve the cable at the phone; the N900's micro-USB socket is its
  famous weak point and tears off the board if yanked. Consider a short
  right-angle cable.
- **Tether**: a lanyard or a thin steel security cable through a case or a
  glued anchor, long enough to tilt it in every direction, short enough that
  it can't hit the floor.
- **Battery**: it must have a battery in to run. Use a fresh BL-5J and look at
  it before the show: a swollen battery lifts the back cover. Don't enclose the
  phone airtight; it gets warm on a charger.
- **Buttons**: the app keeps the screen on and undoes a power-button lock
  within 10 s. Tape over the power button and the camera key if visitors keep
  finding them. The volume keys do nothing.
- **Keyboard**: sliding it open shows the typing line; the hinge is sturdy.

## Testing without a phone

```
pip install websockets pycairo
python3 tests/test_agent.py          # fake sensors vs a mock Pi: 27 checks
python3 tests/render_screens.py .    # PNG previews of every screen
python3 n900/agent.py --fake --headless --host 192.168.1.10   # stream fake data to a real Pi
```

## Not tested yet on the real phone

Written and tested on a laptop with fake sensors. Things to confirm on the
N900 itself, in this order:

1. `python2.5 -c "import gtk, cairo"` works.
2. The camera pipeline: the app tries raw UYVY from `/dev/video1` first, then
   two gray pipelines, and logs which one runs. If none does, run
   `gst-inspect-0.10 v4l2camsrc` and send me the output.
3. `ls /sys/devices/platform/gpio-switch/` shows `proximity` and `slide`.
4. How fast the screen animates (aim: 10 fps; drop `FPS` in `ui.py` if laggy).
5. The tilt axes feel right when you hold it (beta forward/back, gamma left/right).
