#!/bin/bash
# Runs ONCE, very early at boot, because prepare_sd.sh added it to cmdline.txt.
# It only arms the real installer (ij-kit.service, which runs once the Pi is
# fully up) and takes itself back out of cmdline.txt. Then the Pi reboots.
BOOT=/boot/firmware; [[ -d $BOOT/ij-kit ]] || BOOT=/boot
CMD=$BOOT/cmdline.txt
# first, so that whatever happens next the Pi boots normally afterwards
sed -i 's| systemd.run=[^ ]*||g; s| systemd.run_success_action=[^ ]*||g; s| systemd.run_failure_action=[^ ]*||g; s| systemd.unit=kernel-command-line.target||g' "$CMD"
mount -o remount,rw / 2>/dev/null || true
sed "s|@BOOT@|$BOOT|g" "$BOOT/ij-kit/ij-kit.service" > /etc/systemd/system/ij-kit.service
mkdir -p /etc/systemd/system/multi-user.target.wants
ln -sf /etc/systemd/system/ij-kit.service /etc/systemd/system/multi-user.target.wants/ij-kit.service
echo "$(date) armed" >> "$BOOT/ij-kit/progress.txt"
sync
exit 0
