#!/usr/bin/env bash
# Put the Pi on the INFINITE JEST show network, in a way that's hard to get wrong.
#
#   sudo bash setup_network.sh --install   # once (INSTALL.sh does this)
#   sudo bash setup_network.sh --apply     # re-read the settings file now
#   bash setup_network.sh --show           # what the Pi is connected to
#
# The settings live in ONE text file on the SD card's boot partition, which
# the Mac can open when the card is in it (the drive is called "bootfs"):
#
#     /boot/firmware/infinitejest-network.txt
#
# What it sets up (NetworkManager, the standard on Raspberry Pi OS):
#   1. Ethernet (cable to a Linksys LAN port): takes an address from the router
#      AND always also answers on 192.168.1.10, even if the router's DHCP is
#      off or the reservation was never made.
#   2. Wi-Fi "infinitejest" as fallback when no cable is in: same 192.168.1.10.
#   3. Your home Wi-Fi stays as it was (for internet at home).
#   4. A small guard (ij-netguard) checks every 10 s that 192.168.1.10 is on
#      the live connection, and moves it if you swap cable for Wi-Fi.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOT=/boot/firmware; [[ -d $BOOT ]] || BOOT=/boot
CONF="$BOOT/infinitejest-network.txt"
STATE=/var/lib/infinite-jest/network.applied

load_conf() {
  SHOW_SSID=infinitejest; SHOW_PASSWORD=""; PI_ADDRESS=192.168.1.10; ROUTER=192.168.1.1
  PREFIX=24; COUNTRY=US; HOME_SSID=""; HOME_PASSWORD=""
  if [[ -f $CONF ]]; then
    # KEY=value lines only; tolerate Mac line endings and spaces around '='
    while IFS= read -r line || [[ -n $line ]]; do
      line="${line%$'\r'}"
      [[ $line =~ ^[[:space:]]*([A-Z_]+)[[:space:]]*=[[:space:]]*(.*)$ ]] || continue
      key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]}"
      val="${val%"${val##*[![:space:]]}"}"            # trim right
      [[ $val =~ ^\"(.*)\"$ ]] && val="${BASH_REMATCH[1]}"
      case $key in
        SHOW_SSID|SHOW_PASSWORD|PI_ADDRESS|ROUTER|PREFIX|COUNTRY|HOME_SSID|HOME_PASSWORD) printf -v "$key" '%s' "$val" ;;
      esac
    done < "$CONF"
  fi
}

have_nm() { command -v nmcli >/dev/null && nmcli -t general status >/dev/null 2>&1; }

nm_set() {  # nm_set NAME TYPE [ifname] -- props...
  local name="$1" type="$2" ifname="$3"; shift 3
  if nmcli -t -f NAME connection show | grep -qxF "$name"; then
    nmcli connection modify "$name" "$@"
  else
    nmcli connection add type "$type" con-name "$name" ifname "$ifname" "$@" >/dev/null
  fi
}

apply() {
  load_conf
  echo "    Show network: Wi-Fi '$SHOW_SSID', Pi at $PI_ADDRESS, router $ROUTER"
  # Wi-Fi is switched off on a fresh Pi until a country is set.
  if command -v raspi-config >/dev/null; then raspi-config nonint do_wifi_country "$COUNTRY" >/dev/null 2>&1 || true; fi
  command -v rfkill >/dev/null && rfkill unblock wifi 2>/dev/null || true
  if ! have_nm; then
    echo "    ! NetworkManager is not running here; only the address guard will be used."
    return 0
  fi
  # 1. Ethernet: DHCP plus the fixed show address on top. If no DHCP answers,
  #    NM keeps trying instead of giving up, so the fixed address stays.
  nm_set ij-wired ethernet eth0 \
    connection.autoconnect yes connection.autoconnect-priority 100 \
    ipv4.method auto ipv4.addresses "$PI_ADDRESS/$PREFIX" \
    ipv4.dhcp-timeout 2147483647 ipv4.may-fail yes ipv6.method ignore
  # Older Raspberry Pi OS made "Wired connection 1"; keep it out of the way.
  for c in "Wired connection 1" "preconfigured-eth0"; do
    nmcli -t -f NAME connection show | grep -qxF "$c" && nmcli connection modify "$c" connection.autoconnect no || true
  done
  # 2. Show Wi-Fi as fallback
  if [[ -n $SHOW_PASSWORD ]]; then
    nm_set ij-show-wifi wifi wlan0 \
      ssid "$SHOW_SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$SHOW_PASSWORD" \
      connection.autoconnect yes connection.autoconnect-priority 50 \
      ipv4.method auto ipv4.dhcp-timeout 2147483647 ipv4.may-fail yes ipv6.method ignore \
      802-11-wireless.powersave 2
    # (the fixed address is put on Wi-Fi by ij-netguard, only while no cable is in,
    #  so the Pi never answers on 192.168.1.10 from two places at once)
    echo "    Show Wi-Fi '$SHOW_SSID' saved."
  else
    echo "    (no SHOW_PASSWORD in $CONF, so no show Wi-Fi fallback; Ethernet only)"
  fi
  # 3. Optional home/internet Wi-Fi
  if [[ -n $HOME_SSID ]]; then
    nm_set ij-home-wifi wifi wlan0 ssid "$HOME_SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$HOME_PASSWORD" \
      connection.autoconnect yes connection.autoconnect-priority 10
    echo "    Home Wi-Fi '$HOME_SSID' saved."
  fi
  nmcli connection up ij-wired >/dev/null 2>&1 || true
  mkdir -p "$(dirname "$STATE")"
  [[ -f $CONF ]] && sha256sum "$CONF" > "$STATE" || true
}

install() {
  load_conf
  if [[ ! -f $CONF ]]; then
    cp "$HERE/infinitejest-network.txt" "$CONF"
    echo "    Wrote $CONF (open it on the Mac: the SD card's 'bootfs' drive)."
  fi
  install -m 755 "$HERE/setup_network.sh" /usr/local/sbin/ij-network
  install -m 755 "$HERE/ij-netguard" /usr/local/sbin/ij-netguard
  install -m 644 "$HERE/infinitejest-network.txt" /usr/local/share/infinitejest-network.example.txt
  if [[ -d /run/systemd/system ]]; then
    install -m 644 "$HERE/systemd/ij-network.service" /etc/systemd/system/
    install -m 644 "$HERE/systemd/ij-netguard.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable ij-network.service ij-netguard.service >/dev/null 2>&1
    systemctl restart ij-netguard.service || true
  fi
  # The router can't be reached by name; make the Pi findable as inartwetrust.local
  command -v avahi-daemon >/dev/null || echo "    ! avahi-daemon missing: use the address $PI_ADDRESS instead of the name."
  apply
}

boot() {  # at every boot: re-apply only if the file changed on the Mac
  if [[ -f $CONF ]] && ! sha256sum --status -c "$STATE" 2>/dev/null; then
    echo "infinitejest-network.txt changed, applying"
    apply
  fi
}

show() {
  load_conf
  echo "Settings file: $CONF $( [[ -f $CONF ]] && echo '(present)' || echo '(missing: defaults used)')"
  ip -br addr | grep -v '^lo' || true
  have_nm && nmcli -f NAME,TYPE,DEVICE,ACTIVE connection show || true
  ping -c1 -W1 "$ROUTER" >/dev/null 2>&1 && echo "Router $ROUTER answers." || echo "Router $ROUTER does NOT answer."
}

[[ $EUID -eq 0 || ${1:-} == --show ]] || { echo "Run with sudo."; exit 1; }
case "${1:---show}" in
  --install) install ;;
  --apply) apply ;;
  --boot) boot ;;
  --show) show ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac
