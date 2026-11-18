#!/bin/bash
# The one-time installer, run by ij-kit.service once the Pi is up.
# Progress goes to the screen on HDMI and to ij-kit/progress.txt on the card
# (readable on the Mac: the "bootfs" drive).
BOOT=/boot/firmware; [[ -d $BOOT/ij-kit ]] || BOOT=/boot
KIT=$BOOT/ij-kit
P=$KIT/progress.txt
WORK=/var/cache/ij-kit
mkdir -p $WORK
chvt 1 2>/dev/null; setterm --term linux --blank 0 --cursor off >/dev/tty1 2>/dev/null
exec > >(tee -a "$P" $WORK/install.log /dev/tty1) 2>&1
say() { echo; echo "==== $(date +%H:%M)  $*"; }
finish() {   # finish OK|FAIL message   (on FAIL it tries again at the next start)
  echo "$1 $(date) $2" > "$KIT/RESULT.txt"
  say "$2"
  if [[ $1 == OK ]]; then
    systemctl disable ij-kit.service 2>/dev/null
    rm -f /etc/systemd/system/ij-kit.service /etc/systemd/system/multi-user.target.wants/ij-kit.service
  fi
  sync
  exit 0
}
WHO=$(getent passwd 1000 | cut -d: -f1); WHO=${WHO:-pi}
say "INFINITE JEST: installing (about 30 minutes, do not unplug)"

# ---- 1. a USB stick made on the Mac (no internet needed at all)?
STICK=""
sleep 10      # give a USB stick time to show up
mkdir -p /mnt/ij-stick
for dev in $(lsblk -rpno NAME,TYPE | awk '$2=="part"{print $1}'); do
  case $dev in /dev/mmcblk0*) continue ;; esac
  mp=$(lsblk -rno MOUNTPOINT "$dev" | head -n1)
  if [[ -z $mp ]]; then mount "$dev" /mnt/ij-stick 2>/dev/null && mp=/mnt/ij-stick || continue; fi
  if [[ -f $mp/IJ-BUNDLE/manifest.json ]]; then STICK=$mp/IJ-BUNDLE; break; fi
  [[ $mp == /mnt/ij-stick ]] && umount /mnt/ij-stick
done
if [[ -n $STICK ]]; then
  say "Installing from the USB stick ($STICK), no internet needed"
  bash "$STICK/INSTALL.sh" --no-start \
    || finish FAIL "INSTALL FAILED: bring ij-kit/progress.txt (and the stick's IJ-BUNDLE/logs) to Claude. Start the Pi again to retry."
else
# ---- 1b. no stick: internet, once
conf() { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$KIT/hotspot.txt" | tr -d '\r' | sed 's/^"\(.*\)"$/\1/' | head -n1; }
SSID=$(conf WIFI_NAME); PSK=$(conf WIFI_PASSWORD)
online() {
  if command -v curl >/dev/null; then curl -sSk -I -m 30 -o /dev/null https://pypi.org/simple/ 2>/dev/null
  else python3 -c "import urllib.request,ssl;urllib.request.urlopen(urllib.request.Request("https://pypi.org/simple/",method="HEAD"),timeout=30,context=ssl._create_unverified_context())" 2>/dev/null; fi
}
command -v rfkill >/dev/null && rfkill unblock wifi
if ! online && [[ -n $SSID ]]; then
  say "Joining the Wi-Fi '$SSID'"
  for i in $(seq 1 12); do
    nmcli device wifi rescan >/dev/null 2>&1; sleep 4
    if nmcli connection show ij-kit-wifi >/dev/null 2>&1; then
      nmcli connection up ij-kit-wifi >/dev/null 2>&1 && break
    elif nmcli device wifi connect "$SSID" password "$PSK" name ij-kit-wifi >/dev/null 2>&1; then
      nmcli connection modify ij-kit-wifi connection.autoconnect-priority 1 >/dev/null 2>&1
      break
    fi
    echo "   not yet ($i/12)... is the hotspot on and close by?"
  done
fi
for i in $(seq 1 20); do online && break; sleep 3; done
online || finish FAIL "NO INTERNET. Check the Wi-Fi name and password in ij-kit/hotspot.txt on the card (bootfs drive on the Mac), then start the Pi again."
# a Pi without a clock battery may think it's months ago: certificates then fail
d=$(curl -sSkI -m 8 https://pypi.org/ | sed -n 's/^[Dd]ate: //p' | tr -d '\r')
[[ -n $d ]] && date -s "$d" >/dev/null && echo "   clock: $(date)"
echo "   online."
command -v curl >/dev/null || { apt-get update -q && apt-get install -y -q curl ca-certificates; }

# ---- 2. download onto the Pi itself (packages come from apt during the install)
. /etc/os-release
REL=${IJ_KIT_RELEASE:-${VERSION_CODENAME:-trixie}}; export IJ_RELEASE=$REL
say "Downloading the language model and llama.cpp ($REL)"
rm -rf $WORK/code; cp -r "$KIT/code" $WORK/code
python3 $WORK/code/infinite_jest/deploy/make_bundle.py --out $WORK --release "$REL" --online ${IJ_KIT_BUNDLE_ARGS:-} \
  || finish FAIL "DOWNLOAD FAILED: see ij-kit/progress.txt. Start the Pi again to retry (it continues where it stopped)."

# ---- 3. install everything
say "Installing (this compiles the language model engine: ~15 min)"
bash $WORK/IJ-BUNDLE/INSTALL.sh --no-start ${IJ_KIT_INSTALL_ARGS:-} \
  || finish FAIL "INSTALL FAILED: bring ij-kit/progress.txt to Claude. Start the Pi again to retry."

fi

# ---- 4. no phone needed: the room itself starts a visit
CFG=$(getent passwd "$WHO" | cut -d: -f6)/.config/infinite-jest/engine.toml
if [[ -f $CFG ]]; then
  sed -i 's/^mode = "handheld"/mode = "fixed"/' "$CFG"
  grep -q '^mode = "fixed"' "$CFG" || sed -i '1i mode = "fixed"' "$CFG"
  echo "   mode: fixed (microphone and camera start visits; the phone is optional)"
fi
ij-doctor --fix >/dev/null 2>&1 || true     # sound to the USB card if there is one
systemctl restart infinite-jest.service ij-room.service 2>/dev/null || true
sleep 15
ij-doctor || true
finish OK "DONE. The show is running and starts by itself at every power-on. No internet needed from now on."
