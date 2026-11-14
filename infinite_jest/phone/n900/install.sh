#!/bin/sh
# Install the INFINITE JEST phone agent on a Nokia N900 (Maemo 5).
#
# On the N900, in X Terminal, as root ("sudo gainroot", needs the rootsh package):
#     sh /home/user/MyDocs/infinite_jest_phone/install.sh
#
# Copies the agent to /opt/infinite-jest-phone, installs the upstart job so
# it starts full screen at every boot, and sets the screen and lock settings
# an exhibit needs. Run it again to update. Remove with:  sh install.sh --remove
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DST=/opt/infinite-jest-phone
JOB=/etc/event.d/infinite-jest-phone

if [ "$(id -u)" != "0" ]; then
    echo "Run me as root: sudo gainroot, then sh $0"; exit 1
fi

if [ "$1" = "--remove" ]; then
    stop infinite-jest-phone 2>/dev/null || true
    rm -f "$JOB"; rm -rf "$DST"
    echo "Removed. Reboot to get the normal desktop back."; exit 0
fi

if [ ! -x /usr/bin/python2.5 ]; then
    echo "Python 2.5 is missing. Install 'python' and 'python-gtk' (PyMaemo) from"
    echo "Maemo Extras first, or copy their .deb files over and run: dpkg -i *.deb"
    exit 1
fi
/usr/bin/python2.5 -c "import gtk, cairo" 2>/dev/null || \
    echo "WARNING: pygtk/pycairo missing, the agent will run without a screen (headless)."
command -v gst-launch-0.10 >/dev/null 2>&1 || command -v gst-launch >/dev/null 2>&1 || \
    echo "WARNING: gst-launch not found, no camera or microphone."

mkdir -p "$DST"
cp "$SRC"/*.py "$DST"/
# the profiler's either/or prompts, if the whole infinite_jest folder was copied
for p in "$SRC/../../profiler/prompts.json" "$SRC/prompts.json"; do
    [ -f "$p" ] && cp "$p" "$DST/profiler_prompts.json" && break
done
# the written phone text (consent versions, opt-out lines, prompts), if present
[ -f "$SRC/../../text/corpus/lines.json" ] && cp "$SRC/../../text/corpus/lines.json" "$DST/text_lines.json"
[ -f "$SRC/../../text/corpus/prompts.json" ] && cp "$SRC/../../text/corpus/prompts.json" "$DST/text_prompts.json"
[ -f /home/user/.ij-phone.conf ] || cp "$SRC/ij-phone.conf.example" /home/user/.ij-phone.conf
chown user:users /home/user/.ij-phone.conf 2>/dev/null || true
cp "$SRC/infinite-jest-phone.upstart" "$JOB"

# battery gauge in sysfs (optional, harmless if it fails)
modprobe bq27x00_battery 2>/dev/null || true

# exhibit settings, as user "user": long blank timeout, no auto-lock
su - user -c "gconftool-2 -s /system/osso/dsm/display/display_blank_timeout -t int 3600" || true
su - user -c "gconftool-2 -s /system/osso/dsm/display/display_dim_timeout -t int 3000" || true
su - user -c "gconftool-2 -s /system/osso/dsm/locks/touchscreen_keypad_autolock_enabled -t bool false" || true
su - user -c "gconftool-2 -s /system/osso/dsm/locks/devicelock_autolock_enabled -t bool false" || true

echo "Installed. Starting now (and at every boot)."
stop infinite-jest-phone 2>/dev/null || true
start infinite-jest-phone || echo "Could not start; reboot the phone."
echo "Log: /home/user/.ij-phone.log   Quit on the phone: hold the top-left corner 5 s, or Ctrl+Q."
