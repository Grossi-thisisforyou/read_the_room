#!/usr/bin/env bash
# Undo install.sh: restore every backed-up file and switch Plymouth back
# to the stock theme. Leaves the plymouth package installed (harmless).
#     sudo ./uninstall.sh && sudo reboot
set -euo pipefail

STATE=/etc/infinitejest
BACKUP=$STATE/backup

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo ./uninstall.sh" >&2
    exit 1
fi
if [ ! -d "$BACKUP" ]; then
    echo "Nothing to undo: $BACKUP does not exist." >&2
    exit 1
fi

for b in "$BACKUP"/*; do
    [ -e "$b" ] || continue
    target=$(basename "$b" | sed 's|%|/|g')
    echo "restoring $target"
    cp -a "$b" "$target"
done

systemctl disable -q infinitejest-console.service 2>/dev/null || true
rm -f /etc/systemd/system/infinitejest-console.service /etc/profile.d/infinitejest-prompt.sh
systemctl daemon-reload

if command -v plymouth-set-default-theme >/dev/null; then
    plymouth-set-default-theme -R text 2>/dev/null || plymouth-set-default-theme -R details || true
fi
rm -rf /usr/share/plymouth/themes/infinitejest "$STATE"
echo "Undone. Reboot: sudo reboot"
