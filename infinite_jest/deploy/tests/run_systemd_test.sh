#!/usr/bin/env bash
# Install from the bundle in an emulated arm64 machine that boots real systemd
# (network off), then check the services, the watchdog's restarts and the units.
#   bash run_systemd_test.sh BUNDLE_PARENT_DIR [CONTAINER]
# CONTAINER: a running container booted from ij-pi-sim:noble-systemd with the
# bundle parent mounted at /mnt (see the README in this folder).
set -uo pipefail
C="${2:-ijsd}"
x() { docker exec "$C" bash -c "$*"; }
echo "### install (language model skipped: the other test covers it)"
x 'su pi -c "sudo IJ_RELEASE=test-ubuntu-noble bash /mnt/IJ-BUNDLE/INSTALL.sh --skip-llm"' | tail -40
echo "### unit files"
x 'systemd-analyze verify /etc/systemd/system/infinite-jest.service /etc/systemd/system/ij-*.service 2>&1 | grep -v "proc-sys-fs\|getty\|Unknown section" || true'
echo "### service states"
x 'for u in infinite-jest ij-watchdog ij-blackout ij-netguard ij-network; do printf "%-16s %s\n" $u "$(systemctl is-active $u) / $(systemctl is-enabled $u)"; done'
echo "### engine status"
x 'python3 -c "import urllib.request,json; d=json.load(urllib.request.urlopen(\"http://127.0.0.1:8765/status\",timeout=5)); print({k:d.get(k) for k in (\"phase\",\"fps\",\"last_frame_ts\")})"'
echo "### kill -9 the engine: systemd should restart it"
x 'P=$(systemctl show -p MainPID --value infinite-jest); kill -9 $P; sleep 15; echo "old pid $P, new pid $(systemctl show -p MainPID --value infinite-jest), $(systemctl is-active infinite-jest), restarts $(systemctl show -p NRestarts --value infinite-jest)"'
echo "### freeze the engine (SIGSTOP): watchdog should restart it"
x 'P=$(systemctl show -p MainPID --value infinite-jest); kill -STOP $P; echo "stopped $P at $(date +%T)"; for i in $(seq 1 30); do sleep 5; N=$(systemctl show -p MainPID --value infinite-jest); [ "$N" != "$P" ] && [ "$N" != 0 ] && { echo "restarted as $N at $(date +%T)"; break; }; done'
x 'journalctl -u ij-watchdog -u infinite-jest --no-pager -n 15 | tail -15'
echo "### a show stopped on purpose stays stopped"
x 'systemctl stop infinite-jest; sleep 20; echo "after 20 s: $(systemctl is-active infinite-jest)"; systemctl start infinite-jest'
echo "### ij-doctor"
x 'su pi -c ij-doctor' || true
echo "### SYSTEMD TEST DONE"
