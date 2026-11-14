# Infinite Jest · deploy

Getting the show onto the real Raspberry Pi in the room, with no internet
there, and keeping it running for days without anyone touching it.

The printable move-in-day guide (unbox to running show, with drawings of what
plugs where) is a separate page; this folder holds the tools it uses.

## The idea

1. **On the Mac, at home** (internet): double-click **`Make IJ bundle.command`**.
   It fills a USB stick named `IJ` with everything the Pi needs: about 500
   system packages for Raspberry Pi OS, the llama.cpp source, the Qwen language
   model, and the show's code. About 2.5 GB; 8 GB with the image generator.
2. **On the Pi, anywhere** (no network needed):
   ```
   sudo mount -L IJ /mnt && sudo bash /mnt/IJ-BUNDLE/INSTALL.sh
   ```
   20 to 40 minutes the first time. Safe to run again. It ends with a health check.
3. From then on the show starts by itself at every power-on.

Updating code later (seconds): make the bundle again (it only downloads what
changed), then `sudo bash /mnt/IJ-BUNDLE/INSTALL.sh --code-only`.

## What INSTALL.sh does

| Step | What |
|---|---|
| 1 | Checks: 64-bit Pi OS, which release (trixie or bookworm), disk space, clock |
| 2 | Installs the system packages from the stick. While it runs apt sees **only** the stick (an `apt.conf.d` drop-in, removed at the end), so nothing tries the internet, including the engine's own `install.sh` |
| 3 | Copies the code to `~/read_the_room/infinite_jest` (keeps generated images; saves the old code in `/var/cache/infinite-jest/`) |
| 4 | Runs the engine's `pi/install.sh` (with OpenCV), installs the `infinite-jest` service |
| 5 | Compiles llama.cpp for the Pi's CPU from the bundled source, copies the model, starts `llama-server` and the `infinite-jest-oracle` service |
| 6 | With `--images` bundles: compiles stable-diffusion.cpp, copies SD-Turbo, makes the 8-bit copy, enables the night-time image generator |
| 7 | Network (below), and the boot splash from `case/install.sh` |
| 8 | Health tools (below) |
| 9 | Starts the show, runs `ij-doctor`, prints a summary, copies its log onto the stick |

## Network

`pi/setup_network.sh` (installed as `ij-network`) with NetworkManager:

- **Cable to the Linksys first**: DHCP from the router plus the fixed show
  address `192.168.1.10` on top, so it works even if the router's DHCP or
  reservation isn't set.
- **Show Wi-Fi as fallback** when no cable is in. `ij-netguard` moves the
  `192.168.1.10` address to Wi-Fi only while the cable is out, so the Pi never
  answers from two places.
- **One settings file on the SD card's boot drive**,
  `/boot/firmware/infinitejest-network.txt`, editable on the Mac (the drive is
  called `bootfs`). Applied at the next boot.
- Wi-Fi country set and Wi-Fi unblocked (a fresh Pi keeps Wi-Fi off until then).

Router settings: [LINKSYS.md](LINKSYS.md). Phone: [N900.md](N900.md).

## Health and recovery

| Tool | What |
|---|---|
| `ij-doctor` | Plain-language check of power supply, temperature and cooler, SD space, projector (right HDMI port, Full HD, its model name), USB sound card, engine, phone, language model, image generator, network, Wi-Fi channel crowding, watchdog. Each problem comes with a fix. `--fix` points the sound at the USB card; `--sound` plays a test noise; `--json` for scripts |
| `infinite-jest.service` | the engine's own unit: restarts on crash, systemd watchdog (engine pings it from the frame loop) |
| `ij-watchdog` | restarts the engine if `/status` stops answering or `last_frame_ts` freezes, revives a unit systemd gave up on (with backoff), restarts a hung `llama-server`, pauses the image generator when memory is low, switches sound to the USB card by name when one is plugged in, and does a nightly fresh start at 06:00 while the room is empty |
| `ij-blackout` | parks the text console on an empty screen, so whenever the engine isn't drawing, the wall is black: no login prompt, no boot text, no cursor |
| hardware watchdog | if the whole Pi freezes, it reboots within 15 s and the show comes back by itself |
| volatile journal | system logs live in memory only |

Emergency, in the room: the Pi 5's own **power button** (on the board edge)
shuts down cleanly with one press; press again to start.

## Testing

- `python3 -m pytest -q tests/` : package version ordering against dpkg's rules,
  the dependency resolver, sound-card choice, projector name parsing.
- `tests/run_offline_install_test.sh` : the whole install in an emulated
  64-bit ARM machine with **networking switched off**, then a real Qwen model
  answering through the compiled `llama-server`, the engine serving `/status`,
  `ij-doctor` and `ij-netguard`. The Debian and Raspberry Pi package servers
  were not reachable from the test machine, so the test bundle uses Ubuntu
  24.04 arm64 packages as a stand-in for Raspberry Pi OS (same package format,
  same tools); everything else is the real path.

## Not verified without the real hardware

- Package lists for **Raspberry Pi OS** trixie/bookworm are resolved for the
  first time on Baby's Mac (the resolver itself is tested on Ubuntu's archive).
- Compiling llama.cpp natively on the Pi 5 (tested under emulation only).
- NetworkManager behaviour (no NetworkManager in the test container), the
  projector's EDID, the USB sound card, the Active Cooler readings,
  `vcgencmd`, the hardware watchdog, the console blackout on a real HDMI screen.
- Every Linksys and N900 step: written from manuals and community guides.
