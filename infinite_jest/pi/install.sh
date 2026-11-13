#!/usr/bin/env bash
# Set up the Raspberry Pi to run the Infinite Jest show on power-on.
# Run once ON THE PI, from this folder, while the Pi has internet (home Wi-Fi,
# or an Ethernet cable to the Mac with Internet Sharing on):
#
#     bash install.sh                 # install, and start the show at every boot
#     bash install.sh --with-opencv   # ... plus OpenCV, so the Pi can count faces
#     bash install.sh --no-autostart  # install only; start by hand with: python3 -m showengine
#
# After this the room needs no internet at all. Everything comes from
# Raspberry Pi OS's own packages (apt). It asks for your password once (sudo).
set -euo pipefail
cd "$(dirname "$0")"
DIR="$PWD"
WHO="$(id -un)"
HOME_DIR="$(getent passwd "$WHO" | cut -d: -f6)"
AUTOSTART=1
OPENCV=0
for arg in "$@"; do
  case "$arg" in
    --no-autostart) AUTOSTART=0 ;;
    --with-opencv) OPENCV=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 1 ;;
  esac
done

echo "== 1/5 Installing Python libraries from apt"
sudo apt-get update
sudo apt-get install -y python3-aiohttp python3-pygame python3-numpy alsa-utils
if [[ $OPENCV == 1 ]]; then
  sudo apt-get install -y python3-opencv opencv-data
fi

echo "== 2/5 Letting $WHO use the screen, sound and keyboard without a desktop"
sudo usermod -aG video,render,input,audio "$WHO"

echo "== 3/5 Settings file"
mkdir -p "$HOME_DIR/.config/infinite-jest"
if [[ -f "$HOME_DIR/.config/infinite-jest/engine.toml" ]]; then
  echo "   keeping your existing $HOME_DIR/.config/infinite-jest/engine.toml"
else
  cp config/default.toml "$HOME_DIR/.config/infinite-jest/engine.toml"
  echo "   wrote $HOME_DIR/.config/infinite-jest/engine.toml (edit this one)"
fi

echo "== 4/5 Checking"
python3 - <<'PY'
import sys, tomllib
import aiohttp, pygame, numpy
print("python", sys.version.split()[0], "| aiohttp", aiohttp.__version__, "| pygame", pygame.version.ver, "| numpy", numpy.__version__)
PY
python3 -m showengine --help >/dev/null && echo "   engine imports fine"
aplay -l 2>/dev/null | grep -E '^card' || echo "!! no sound card listed (HDMI audio appears once a projector/TV is plugged in)"

if [[ $AUTOSTART == 1 ]]; then
  echo "== 5/5 Starting the show at every boot (systemd service: infinite-jest)"
  sed -e "s|@USER@|$WHO|g" -e "s|@DIR@|$DIR|g" -e "s|@HOME@|$HOME_DIR|g" systemd/infinite-jest.service \
    | sudo tee /etc/systemd/system/infinite-jest.service >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable infinite-jest
  # no blinking text cursor over the projection
  CMDLINE=/boot/firmware/cmdline.txt
  if [[ -f $CMDLINE ]] && ! grep -q 'vt.global_cursor_default=0' "$CMDLINE"; then
    sudo sed -i '1 s/$/ consoleblank=0 vt.global_cursor_default=0/' "$CMDLINE"
  fi
  sudo systemctl restart infinite-jest
  echo
  echo "Done. The show is running and will start by itself after every power-on."
  echo "  Watch it:     journalctl -u infinite-jest -f"
  echo "  Control page: http://$(hostname).local:8765/   (or http://192.168.1.10:8765/ on the show router)"
  echo "  Stop / start: sudo systemctl stop infinite-jest  /  sudo systemctl start infinite-jest"
  echo "  Never at boot again: sudo systemctl disable infinite-jest"
else
  echo "== 5/5 Skipped autostart"
  echo "Done. Try it:  python3 -m showengine --simulate --debug    (Esc quits)"
fi
