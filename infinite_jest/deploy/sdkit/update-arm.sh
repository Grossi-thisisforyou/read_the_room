#!/bin/bash
CMD=/boot/firmware/cmdline.txt
sed -i 's| systemd.run=[^ ]*||g; s| systemd.run_success_action=[^ ]*||g; s| systemd.run_failure_action=[^ ]*||g; s| systemd.unit=kernel-command-line.target||g' "$CMD"
mount -o remount,rw / 2>/dev/null || true
cat > /etc/systemd/system/ij-update.service <<'U'
[Unit]
Description=Infinite Jest: install the code update from the SD card
Before=infinite-jest.service
After=local-fs.target
[Service]
Type=oneshot
ExecStart=/bin/bash /boot/firmware/ij-update/apply.sh
[Install]
WantedBy=multi-user.target
U
mkdir -p /etc/systemd/system/multi-user.target.wants
ln -sf /etc/systemd/system/ij-update.service /etc/systemd/system/multi-user.target.wants/ij-update.service
sync
exit 0
