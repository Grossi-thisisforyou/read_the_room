#!/usr/bin/env bash
# Copy the images painted on the Mac onto the Pi, into the same hook folders.
#     ./copy_to_pi.sh                       # from ~/Desktop/infinite_jest_bank
#     ./copy_to_pi.sh /path/to/bank         # from another folder
# The Pi must be on and on the same network. It asks for the Pi's password
# unless you have set up an SSH key. Only adds and updates pictures: it never
# deletes anything on the Pi. Running it again copies only what's new.
#
# Change the Pi's address or folder like this:
#     PI=pi@192.168.1.50 ./copy_to_pi.sh
set -euo pipefail
BANK="${1:-$HOME/Desktop/infinite_jest_bank}"
PI="${PI:-pi@inartwetrust.local}"
PI_BANK="${PI_BANK:-read_the_room/infinite_jest/visuals/bank}"   # relative to the Pi user's home

[ -d "$BANK" ] || { echo "No folder $BANK: paint some images first (generate_mac.sh)."; exit 2; }
echo "Copying $BANK  ->  $PI:$PI_BANK"
rsync -av --exclude '.incoming' --exclude '.trash' --exclude '*.tmp*' --exclude 'contact_sheet.html' \
    "$BANK/" "$PI:$PI_BANK/"
echo
echo "Done. Restart the show on the Pi (or reboot it) to load the new pictures."
