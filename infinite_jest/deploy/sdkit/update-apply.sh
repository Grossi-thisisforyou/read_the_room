#!/bin/bash
# Runs once at boot, before the show: new code in, settings kept, backup made.
U=/boot/firmware/ij-update
R=/boot/firmware/ij-update-RESULT.txt
WHO=$(getent passwd 1000 | cut -d: -f1); H=$(getent passwd 1000 | cut -d: -f6)
REPO=$H/read_the_room
done_() {
  echo "$1 $(date) $2" > "$R"
  systemctl disable ij-update.service 2>/dev/null
  rm -f /etc/systemd/system/ij-update.service /etc/systemd/system/multi-user.target.wants/ij-update.service
  rm -rf "$U/infinite_jest"; sync; exit 0
}
[[ -d $U/infinite_jest/pi/showengine ]] || done_ FAIL "no code found in ij-update on the card"
mkdir -p /var/cache/infinite-jest
STAMP=$(date +%Y%m%d-%H%M%S)
tar -C "$REPO" -czf /var/cache/infinite-jest/code-before-update-$STAMP.tgz --exclude='bank/*' infinite_jest 2>/dev/null
# copy over the old code: generated pictures and anything not in the update stay
cp -a "$U/infinite_jest/." "$REPO/infinite_jest/" || done_ FAIL "copy failed; old code kept in /var/cache/infinite-jest"
chown -R "$WHO:$WHO" "$REPO/infinite_jest"
bash "$REPO/infinite_jest/deploy/pi/install_tools.sh" "$WHO" >/dev/null 2>&1 || true
systemctl daemon-reload
systemctl restart ij-room.service ij-watchdog.service 2>/dev/null || true
done_ OK "updated to $(cat "$U/infinite_jest/VERSION.txt" 2>/dev/null || echo 'new code'); backup /var/cache/infinite-jest/code-before-update-$STAMP.tgz"
