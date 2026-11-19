#!/bin/bash
# On the Mac, with the Pi's SD card in it:   bash prepare_sd.sh
# Copies the kit onto the card's "bootfs" drive, asks for the hotspot, and
# arms a one-time install that runs when the Pi next starts.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
B=/Volumes/bootfs
[[ -f $B/cmdline.txt ]] || { echo "Can't find the SD card's 'bootfs' drive. Put the Pi's card in the Mac and try again."; exit 1; }
echo "Copying the kit to the SD card..."
rm -rf "$B/ij-kit"; mkdir -p "$B/ij-kit"
cp "$HERE/firstrun.sh" "$HERE/ij-kit-run.sh" "$HERE/ij-kit.service" "$B/ij-kit/"
cp -R "$HERE/code" "$B/ij-kit/code"
find "$B/ij-kit" -name '._*' -delete 2>/dev/null || true
echo
# a Wi-Fi already written into the kit's hotspot.txt is the default
DEF_SSID=$(sed -n 's/^WIFI_NAME=//p' "$HERE/hotspot.txt" 2>/dev/null | tr -d '\r')
DEF_PSK=$(sed -n 's/^WIFI_PASSWORD=//p' "$HERE/hotspot.txt" 2>/dev/null | tr -d '\r')
echo "The Pi needs a Wi-Fi with internet ONCE (about 1.5 GB). With the IJ USB stick it needs none."
if [[ -n $DEF_SSID ]]; then
  read -r -p "Wi-Fi name [Enter = $DEF_SSID]: " SSID
  if [[ -z $SSID ]]; then SSID=$DEF_SSID; PSK=$DEF_PSK; else read -r -p "Password: " PSK; fi
else
  read -r -p "Wi-Fi name (Enter = none, I use the USB stick): " SSID
  PSK=""; [[ -n $SSID ]] && read -r -p "Password: " PSK
fi
printf 'WIFI_NAME=%s\nWIFI_PASSWORD=%s\n' "$SSID" "$PSK" > "$B/ij-kit/hotspot.txt"
cp "$B/cmdline.txt" "$B/ij-kit/cmdline.before.txt"
line=$(head -n1 "$B/cmdline.txt" | sed 's| systemd.run=[^ ]*||g; s| systemd.run_success_action=[^ ]*||g; s| systemd.run_failure_action=[^ ]*||g; s| systemd.unit=kernel-command-line.target||g')
printf '%s systemd.run=/boot/firmware/ij-kit/firstrun.sh systemd.run_success_action=reboot systemd.run_failure_action=reboot systemd.unit=kernel-command-line.target\n' "$line" > "$B/cmdline.txt"
rm -f "$B/ij-kit/RESULT.txt" "$B/ij-kit/progress.txt"
sync
[[ -n ${IJ_NO_EJECT:-} ]] && exit 0
diskutil eject "$B" >/dev/null 2>&1 && echo "SD card ejected." || echo "Now eject the 'bootfs' drive in Finder."
cat <<MSG

Ready. Now:
  1. Put the card back in the Pi. Projector on HDMI 0 (the port next to the power plug),
     USB microphone / sound card, speaker, and the IJ USB stick plugged in.
  2. Power on. The Pi restarts once by itself, then the screen shows the install.
     About 30 minutes. Don't unplug it.
  3. It ends with "DONE" and the show starts. Next to the Pi: ij-kit/RESULT.txt on
     the card says OK or what went wrong.
MSG
