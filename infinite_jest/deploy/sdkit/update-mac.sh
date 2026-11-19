#!/bin/bash
# On the Mac, with the Pi's SD card in it:   bash ~/Downloads/ij-update/update-mac.sh
# Puts the new show code on the card; the Pi installs it at its next start
# (keeps your settings, keeps a backup). Nothing to type on the Pi.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
B=/Volumes/bootfs
[[ -f $B/cmdline.txt ]] || { echo "Put the Pi's SD card in the Mac first (the 'bootfs' drive)."; exit 1; }
rm -rf "$B/ij-update"; mkdir -p "$B/ij-update"
cp "$HERE/arm.sh" "$HERE/apply.sh" "$B/ij-update/"
cp -R "$HERE/infinite_jest" "$B/ij-update/infinite_jest"
find "$B/ij-update" -name '._*' -delete 2>/dev/null || true
line=$(head -n1 "$B/cmdline.txt" | sed 's| systemd.run=[^ ]*||g; s| systemd.run_success_action=[^ ]*||g; s| systemd.run_failure_action=[^ ]*||g; s| systemd.unit=kernel-command-line.target||g')
printf '%s systemd.run=/boot/firmware/ij-update/arm.sh systemd.run_success_action=reboot systemd.run_failure_action=reboot systemd.unit=kernel-command-line.target\n' "$line" > "$B/cmdline.txt"
rm -f "$B/ij-update-RESULT.txt"; sync
diskutil eject "$B" >/dev/null && echo "Done, card ejected. Put it in the Pi and power on: it restarts once, then the show runs the new version."
