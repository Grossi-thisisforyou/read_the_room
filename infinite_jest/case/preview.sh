#!/usr/bin/env bash
# Show the boot splash on the projector for a few seconds, without rebooting.
# Run over SSH from the Mac while the projector is plugged into HDMI 0:
#     sudo ./preview.sh        # 8 seconds
#     sudo ./preview.sh 20     # 20 seconds
# Do not run this while the performance app is using the screen.
set -euo pipefail
SECONDS_TO_SHOW=${1:-8}
if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo: sudo ./preview.sh" >&2; exit 1; fi
plymouthd --tty=/dev/tty1 --mode=boot
plymouth show-splash
sleep "$SECONDS_TO_SHOW"
plymouth quit
