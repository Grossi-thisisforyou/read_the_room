#!/usr/bin/env bash
# Infinite Jest on-screen shell for Raspberry Pi OS Lite (Bookworm or newer).
#
# What it changes on the Pi:
#   1. Boot splash: installs Plymouth and the "infinitejest" theme, hides the
#      rainbow square, the raspberry logos, boot text and the blinking cursor,
#      so the projector goes from black straight to the image.
#   2. Console: a flesh / rust / bone colour palette and a large font on the
#      projector's text console, and a scrawled login banner.
#   3. SSH: a matching prompt and welcome message when you log in from the Mac,
#      plus two shortcuts: `temp` and `heat` (watch the Pi's temperature).
#
# It backs up every system file it edits to /etc/infinitejest/backup/ and
# uninstall.sh puts them back.
#
# Run on the Pi, from this folder:
#     sudo ./install.sh
#     sudo reboot
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
THEME=infinitejest
THEME_DIR=/usr/share/plymouth/themes/$THEME
STATE=/etc/infinitejest
BACKUP=$STATE/backup

say() { printf '\033[38;2;196;98;92m>>\033[0m %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo ./install.sh" >&2
    exit 1
fi

# Bookworm keeps boot files in /boot/firmware, older releases in /boot.
if [ -f /boot/firmware/cmdline.txt ]; then
    BOOT=/boot/firmware
elif [ -f /boot/cmdline.txt ]; then
    BOOT=/boot
else
    echo "Cannot find cmdline.txt in /boot/firmware or /boot. Is this a Raspberry Pi OS image?" >&2
    exit 1
fi
CMDLINE=$BOOT/cmdline.txt
CONFIG=$BOOT/config.txt

mkdir -p "$BACKUP"
backup() {  # keep the first, untouched copy only
    local f=$1
    local b="$BACKUP/$(echo "$f" | sed 's|/|%|g')"
    if [ -e "$f" ] && [ ! -e "$b" ]; then cp -a "$f" "$b"; fi
}

say "Installing Plymouth (boot splash engine)"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq plymouth kbd console-setup >/dev/null

say "Copying the splash theme to $THEME_DIR"
install -d "$THEME_DIR"
install -m 644 "$HERE/splash/plymouth/infinitejest.plymouth" \
               "$HERE/splash/plymouth/infinitejest.script" \
               "$HERE/splash/plymouth/splash.png" "$THEME_DIR/"

say "Hiding boot text, logos and cursor (cmdline.txt)"
backup "$CMDLINE"
line=$(head -n1 "$CMDLINE")
for opt in quiet splash plymouth.ignore-serial-consoles logo.nologo \
           vt.global_cursor_default=0 loglevel=3 consoleblank=0; do
    case " $line " in *" $opt "*) ;; *) line="$line $opt" ;; esac
done
# cmdline.txt must stay one single line
printf '%s\n' "$line" > "$CMDLINE"

say "Hiding the rainbow square and making sure the initramfs loads (config.txt)"
backup "$CONFIG"
grep -q '^disable_splash=1' "$CONFIG" || printf '\n# Infinite Jest: no rainbow square\ndisable_splash=1\n' >> "$CONFIG"
grep -q '^auto_initramfs=1' "$CONFIG" || printf 'auto_initramfs=1\n' >> "$CONFIG"

say "Setting the theme and rebuilding the initramfs (takes a minute)"
plymouth-set-default-theme "$THEME"
update-initramfs -u

say "Console colours and font"
install -d "$STATE"
install -m 644 "$HERE/console/vtrgb" "$STATE/vtrgb"
backup /etc/default/console-setup
if [ -f /etc/default/console-setup ]; then
    sed -i 's/^FONTFACE=.*/FONTFACE="TerminusBold"/; s/^FONTSIZE=.*/FONTSIZE="16x32"/' /etc/default/console-setup
fi
cat > /etc/systemd/system/infinitejest-console.service <<EOF
[Unit]
Description=Infinite Jest console palette
After=console-setup.service
Before=getty@tty1.service

[Service]
Type=oneshot
ExecStart=/usr/bin/setvtrgb $STATE/vtrgb
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q infinitejest-console.service

say "Login banner on the projector (/etc/issue) and welcome over SSH (/etc/motd)"
backup /etc/issue
backup /etc/motd
install -m 644 "$HERE/console/issue" /etc/issue
install -m 644 "$HERE/console/motd" /etc/motd

say "Shell prompt for interactive logins"
install -m 644 "$HERE/console/infinitejest-prompt.sh" /etc/profile.d/infinitejest-prompt.sh

echo
say "Done. Reboot to see it:  sudo reboot"
say "Preview the splash without rebooting:  sudo ./preview.sh"
say "Undo everything:  sudo ./uninstall.sh"
