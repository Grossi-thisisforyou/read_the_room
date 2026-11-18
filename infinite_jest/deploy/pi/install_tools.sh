#!/usr/bin/env bash
# Install the health and recovery tools. Called by INSTALL.sh; safe to run again.
#   sudo bash install_tools.sh [USER]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHO="${1:-${SUDO_USER:-pi}}"
install -m 755 "$HERE/ij-doctor" /usr/local/bin/ij-doctor
install -m 755 "$HERE/ij-watchdog" /usr/local/sbin/ij-watchdog
install -m 755 "$HERE/ij-blackout" /usr/local/sbin/ij-blackout
install -m 755 "$HERE/ij-room" /usr/local/bin/ij-room
install -d /etc/infinite-jest
[[ -f /etc/infinite-jest/room.conf ]] || printf "# ij-room settings (then: sudo systemctl restart ij-room)\n# MIC=auto or a device from: arecord -l   e.g. MIC=plughw:CARD=Device,DEV=0\nMIC=auto\n# CAMERA=auto, off, or a number (0 = /dev/video0)\nCAMERA=auto\n# GAIN: raise if the room reacts too little to voices, lower if too much\nGAIN=1.0\n" > /etc/infinite-jest/room.conf
echo "    ij-doctor installed (type: ij-doctor)"
if [[ -d /run/systemd/system ]]; then
  install -m 644 "$HERE/systemd/ij-watchdog.service" "$HERE/systemd/ij-blackout.service" /etc/systemd/system/
  install -d /etc/systemd/system.conf.d
  if [[ -e /dev/watchdog || -e /dev/watchdog0 ]]; then
    install -m 644 "$HERE/infinite-jest-hw-watchdog.conf" /etc/systemd/system.conf.d/infinite-jest-watchdog.conf
    echo "    hardware watchdog on: a frozen Pi reboots itself within 15 s"
  else
    echo "    (no hardware watchdog device here; skipped)"
  fi
  install -d /etc/systemd/journald.conf.d
  install -m 644 "$HERE/journald-volatile.conf" /etc/systemd/journald.conf.d/infinite-jest.conf
  systemctl restart systemd-journald 2>/dev/null || true
  echo "    logs kept in memory only (nothing about the room stays on the card)"
  systemctl daemon-reload
  sed "s/@USER@/$WHO/" "$HERE/systemd/ij-room.service" > /etc/systemd/system/ij-room.service
  systemctl daemon-reload
  systemctl enable ij-watchdog.service ij-blackout.service ij-room.service >/dev/null 2>&1
  systemctl restart ij-watchdog.service || true
  systemctl restart ij-room.service || true
  echo "    watchdog, blackout and room listener (microphone + USB camera) services on"
fi
# Quiet boot: no boot text or blinking cursor on the projector.
CMD=/boot/firmware/cmdline.txt; [[ -f $CMD ]] || CMD=/boot/cmdline.txt
if [[ -f $CMD ]]; then
  line=$(head -n1 "$CMD")
  for opt in consoleblank=0 vt.global_cursor_default=0 logo.nologo loglevel=3 quiet; do
    case " $line " in *" $opt "*) ;; *) line="$line $opt" ;; esac
  done
  printf '%s\n' "$line" > "$CMD"
  echo "    quiet boot (no text on the projector while starting)"
fi
