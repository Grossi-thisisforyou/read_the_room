#!/bin/bash
# Double-click this file on the Mac (in Finder) to make the INFINITE JEST USB stick.
# First time: macOS may say it's from an unidentified developer. Then right-click it,
# choose Open, and Open again.
cd "$(dirname "$0")" || exit 1
clear
echo "INFINITE JEST: making the offline install stick for the Raspberry Pi"
echo
if ! /usr/bin/xcrun --find python3 >/dev/null 2>&1 && [ ! -x /usr/local/bin/python3 ] && [ ! -x /opt/homebrew/bin/python3 ]; then
  echo "This Mac needs Apple's free command line tools (they include Python)."
  echo "A window will open: click Install, wait until it's done, then double-click this file again."
  xcode-select --install 2>/dev/null
  read -r -p "Press Enter to close." _; exit 1
fi
PY=python3; [ -x /opt/homebrew/bin/python3 ] && PY=/opt/homebrew/bin/python3
if [ -d /Volumes/IJ ]; then
  OUT=/Volumes/IJ
  echo "Found the USB stick called IJ."
else
  echo "No USB stick called IJ found."
  echo "  Plug one in (8 GB or more; 16 GB for the image generator), open Disk Utility,"
  echo "  select the stick, click Erase, Name: IJ, Format: ExFAT, Erase. Then run this again."
  echo
  read -r -p "Or press Enter to put the bundle on the Desktop instead (copy it to a stick later): " _
  OUT="$HOME/Desktop"
fi
echo
read -r -p "Also the on-Pi image generator? Adds 5.2 GB and about an hour of download. [y/N] " yn
EXTRA=()
case "$yn" in [yY]*) EXTRA+=(--images) ;; esac
echo
"$PY" make_bundle.py --out "$OUT" "${EXTRA[@]}"
status=$?
echo
if [ $status -eq 0 ]; then echo "All done. Eject the stick in Finder, then take it to the Pi."; else
  echo "It stopped (see the message above). Running this again continues where it left off."; fi
read -r -p "Press Enter to close this window." _
