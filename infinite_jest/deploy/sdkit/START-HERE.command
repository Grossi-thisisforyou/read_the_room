#!/bin/bash
# INFINITE JEST: make the Pi's SD card and the USB stick, on the Mac.
# Double-click (or in Terminal: bash START-HERE.command).
# Before: the Pi's SD card in the Mac ("bootfs" drive), and a USB stick
# erased in Disk Utility as  Name: IJ   Format: ExFAT.
cd "$(dirname "$0")"
HERE="$(pwd)"
echo; echo "== INFINITE JEST kit =="
REL=""
if [[ -f /Volumes/bootfs/cmdline.txt ]]; then
  IJ_NO_EJECT=1 bash "$HERE/prepare_sd.sh" || { read -r; exit 1; }
else
  echo "! The Pi's SD card (bootfs) is not in the Mac. Put it in and run this again."; read -r; exit 1
fi
if [[ -d /Volumes/IJ ]]; then
  command -v python3 >/dev/null || { echo "Making the stick needs Python 3: run  xcode-select --install  and try again."; read -r; exit 1; }
  echo; echo "Filling the USB stick 'IJ' (packages + Qwen model, about 2.5 GB download)..."
  python3 "$HERE/code/infinite_jest/deploy/make_bundle.py" --out /Volumes/IJ || { echo "Making the stick failed (see above)."; read -r; exit 1; }
  diskutil eject /Volumes/IJ >/dev/null 2>&1 && echo "USB stick ejected."
else
  echo "(No USB stick named IJ: the Pi downloads everything over the Wi-Fi itself. That's fine.)"
fi
diskutil eject /Volumes/bootfs >/dev/null 2>&1 && echo "SD card ejected."
cat <<MSG

Ready. Now:
  1. SD card back in the Pi. Projector on HDMI 0 (next to the power plug), second
     screen on HDMI 1, USB microphone / sound card and speaker, and the IJ stick.
  2. Power on. The Pi restarts once by itself, then the screen shows the install
     (20 to 40 minutes, it compiles the language model). Don't unplug it.
  3. It ends with "DONE" and the show starts. ij-kit/RESULT.txt on the card says
     OK or what went wrong.
MSG
read -r -p "Press Enter to close."
