#!/bin/bash
# On the Mac, Pi switched on and on the same Wi-Fi:   bash ~/Downloads/ij-update/update-ssh.sh
# Sends the new show code to the Pi over the network and restarts the show.
# Keeps your settings and generated pictures, saves a backup of the old code.
HERE="$(cd "$(dirname "$0")" && pwd)"
PI="${1:-}"
if [[ -z $PI ]]; then
  for h in 192.168.1.102 inartwetrust.local 192.168.0.10 192.168.1.10; do
    ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "pi@$h" true 2>/dev/null && { PI=$h; break; }
  done
fi
[[ -n $PI ]] || { echo "Can't reach the Pi (tried inartwetrust.local, 192.168.0.10). Is it on and on the same Wi-Fi?"; exit 1; }
echo "Pi found at $PI. Sending the new code..."
ssh "pi@$PI" 'rm -rf /tmp/ij-new && mkdir -p /tmp/ij-new' || exit 1
COPYFILE_DISABLE=1 tar --no-xattrs -C "$HERE" -czf - infinite_jest 2>/dev/null | ssh "pi@$PI" 'tar --warning=no-unknown-keyword --warning=no-timestamp -m -C /tmp/ij-new -xzf -' || { echo "Copy failed."; exit 1; }
ssh "pi@$PI" 'bash -s' <<'REMOTE'
set -e
R=$HOME/read_the_room
sudo mkdir -p /var/cache/infinite-jest
STAMP=$(date +%Y%m%d-%H%M%S)
sudo tar -C "$R" -czf /var/cache/infinite-jest/code-before-update-$STAMP.tgz --exclude='bank/*' infinite_jest
cp -a /tmp/ij-new/infinite_jest/. "$R/infinite_jest/"
rm -rf /tmp/ij-new
sudo bash "$R/infinite_jest/deploy/pi/install_tools.sh" "$USER" >/dev/null 2>&1 || true
[[ -f "$R/infinite_jest/dream/install_ai.sh" ]] && { sudo bash "$R/infinite_jest/dream/install_ai.sh" "$USER" || echo "(local AI install had a problem; the show runs anyway)"; }
# the room's spoken voice (small; skipped quietly if there's no internet)
command -v espeak-ng >/dev/null || sudo apt-get install -y -q espeak-ng >/dev/null 2>&1 || { timeout 300 sudo apt-get update -q >/dev/null 2>&1; timeout 300 sudo apt-get install -y -q espeak-ng >/dev/null 2>&1; } \
  || echo "(espeak-ng could not be installed now: the room stays silent in words, everything else works)"
sudo systemctl daemon-reload
sudo systemctl restart infinite-jest ij-room ij-watchdog
sleep 8
echo "Show: $(systemctl is-active infinite-jest)   version: $(cat $R/infinite_jest/VERSION.txt 2>/dev/null)"
echo "(old code saved in /var/cache/infinite-jest/code-before-update-$STAMP.tgz)"
REMOTE
