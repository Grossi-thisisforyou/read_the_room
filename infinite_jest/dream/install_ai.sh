#!/usr/bin/env bash
# Put the local AIs on the Pi, offline, from Baby's USB stick and this update.
#   sudo bash install_ai.sh [USER]        (update-ssh.sh runs it; safe to run again)
#
# From the update (built off the Pi): bin/ij-llama-server, bin/ij-sd (static arm64).
# From the stick (label USB20FD, folder ij-offline/, made on the Mac):
#   models/qwen2.5-1.5b-instruct-q4_k_m.gguf      the words (Qwen, local)
#   models/sd_turbo.safetensors.part-*            the paintings (SD-Turbo, joined here)
#   models/taesd.safetensors                      fast picture decoder for SD-Turbo
#   debs/*.deb                                    the voice (espeak-ng and friends)
# The stick is also mounted read-only at /mnt/ij-stick at every boot, so the show can
# read the donated footage from it. Nothing from the stick is sent anywhere.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHO="${1:-${SUDO_USER:-pi}}"
H="$(getent passwd "$WHO" | cut -d: -f6)"
STICK=/mnt/ij-stick
say() { echo "  ai: $*"; }

# 1. the stick: find it by label (or any FAT stick with ij-offline/), mount it read-only
mkdir -p "$STICK"
DEV="$(blkid -L USB20FD 2>/dev/null || true)"
if [[ -z $DEV ]]; then
  for d in $(lsblk -rpno NAME,FSTYPE | awk '$2 ~ /vfat|exfat/ {print $1}'); do
    m=$(mktemp -d); if mount -o ro "$d" "$m" 2>/dev/null; then
      [[ -d $m/ij-offline ]] && DEV=$d; umount "$m"; fi; rmdir "$m"
    [[ -n $DEV ]] && break
  done
fi
if [[ -n $DEV ]]; then
  LABEL="$(blkid -o value -s LABEL "$DEV" 2>/dev/null || true)"
  FST="$(blkid -o value -s TYPE "$DEV" 2>/dev/null || echo vfat)"
  if ! grep -q " $STICK " /etc/fstab; then
    SRC="LABEL=$LABEL"; [[ -n $LABEL ]] || SRC="$DEV"
    echo "$SRC $STICK $FST ro,nofail,uid=$(id -u "$WHO"),gid=$(id -g "$WHO"),x-systemd.automount,x-systemd.device-timeout=5 0 0" >> /etc/fstab
    systemctl daemon-reload
    say "the stick ($LABEL) will be at $STICK at every boot (read-only)"
  fi
  mountpoint -q "$STICK" || mount "$STICK" 2>/dev/null || mount -o ro "$DEV" "$STICK"
else
  say "no USB stick with ij-offline/ found: only the parts in this update are installed"
fi
OFF="$STICK/ij-offline"

# 2. the voice
if ! command -v espeak-ng >/dev/null && ls "$OFF"/debs/*.deb >/dev/null 2>&1; then
  dpkg -i "$OFF"/debs/*.deb >/dev/null 2>&1 && say "voice installed (espeak-ng)" || say "!! voice packages did not install (dpkg)"
fi
command -v espeak-ng >/dev/null && say "voice: ok" || say "voice: missing (the TV still writes its words)"

# the natural voice (Piper): its program comes with the update as wheels (they are zip files, so no
# pip and no internet are needed); the voice files (*.onnx + *.onnx.json) come from the Mac into ~/voices
HERE_DIR="$(cd "$(dirname "$0")" && pwd)"
PYLIB="$H/.local/share/infinite-jest/pylib"
if ls "$HERE_DIR"/wheels/piper_tts-*.whl >/dev/null 2>&1; then
  sudo -u "$WHO" mkdir -p "$PYLIB"
  if sudo -u "$WHO" python3 - "$PYLIB" "$HERE_DIR"/wheels/*.whl <<'PY'
import sys, zipfile
dst = sys.argv[1]
for w in sys.argv[2:]:
    zipfile.ZipFile(w).extractall(dst)
PY
  then say "natural voice program: installed"; else say "!! natural voice program did not unpack"; fi
fi
# speech to text (faster-whisper): unpacked with the same wheels; the model folder comes from the Mac
# into ~/models/whisper/<name>/ (model.bin, config.json, tokenizer.json, vocabulary.*)
sudo -u "$WHO" mkdir -p "$H/models/whisper"
if [[ -d $OFF/whisper ]]; then sudo -u "$WHO" cp -rn "$OFF"/whisper/* "$H/models/whisper/" 2>/dev/null; fi
if ls "$H"/models/whisper/*/model.bin >/dev/null 2>&1; then
  if sudo -u "$WHO" python3 "$HERE_DIR/../pi/tools/hear_check.py" 2>/dev/null | tail -1 | grep -q "^ok"
  then say "speech to text: ok ($(ls "$H/models/whisper" | head -1))"
  else say "!! speech to text did not pass its check (run pi/tools/hear_check.py to see why); the room only hears that someone speaks"; fi
else
  say "speech to text: no model in ~/models/whisper yet (the room only hears that someone speaks)"
fi
sudo -u "$WHO" mkdir -p "$H/voices"
if ls "$OFF"/voices/*.onnx >/dev/null 2>&1; then sudo -u "$WHO" cp -n "$OFF"/voices/*.onnx "$OFF"/voices/*.onnx.json "$H/voices/" 2>/dev/null; fi
if ls "$H"/voices/*.onnx >/dev/null 2>&1; then
  if sudo -u "$WHO" python3 -c "import sys; sys.path.append('$PYLIB'); sys.path.insert(0, '$H/read_the_room'); from infinite_jest.audio import speech; s = speech.render('hello'); assert s is not None and speech._piper['voice'] is not None" 2>/dev/null
  then say "natural voice: ok ($(cat "$H/voices/use.txt" 2>/dev/null || ls "$H"/voices/*.onnx | head -1 | xargs basename))"
  else say "!! natural voice did not load; the old voice is used"; fi
else
  say "natural voice: no voice file in ~/voices yet (the old voice is used until one is copied there)"
fi

# 3. the programs (built for the Pi 5 off the Pi; no compiler needed here)
for b in ij-llama-server ij-sd; do
  [[ -f $HERE/bin/$b ]] && install -m 755 "$HERE/bin/$b" /usr/local/bin/$b
done

# 4. the models, copied from the stick to the card (the stick can then come out, but the footage lives there)
install -d -o "$WHO" -g "$WHO" "$H/models" "$H/sd-models"
Q="$H/models/qwen2.5-1.5b-instruct-q4_k_m.gguf"
if [[ ! -s $Q && -s $OFF/models/qwen2.5-1.5b-instruct-q4_k_m.gguf ]]; then
  say "copying the language model (1.1 GB)..."; cp "$OFF/models/qwen2.5-1.5b-instruct-q4_k_m.gguf" "$Q.part" && mv "$Q.part" "$Q"
fi
SD="$H/sd-models/sd_turbo.safetensors"
if [[ ! -s $SD ]]; then
  if ls "$OFF"/models/sd_turbo.safetensors.part-* >/dev/null 2>&1; then
    say "joining the painting model (5.2 GB)..."; cat "$OFF"/models/sd_turbo.safetensors.part-* > "$SD.part" && mv "$SD.part" "$SD"
  elif ls "$OFF"/models/*turbo*.gguf >/dev/null 2>&1; then
    G=$(ls "$OFF"/models/*turbo*.gguf | head -1); SD="$H/sd-models/$(basename "$G")"
    [[ -s $SD ]] || { say "copying the painting model..."; cp "$G" "$SD.part" && mv "$SD.part" "$SD"; }
  fi
fi
[[ -s $OFF/models/taesd.safetensors && ! -s $H/sd-models/taesd.safetensors ]] && cp "$OFF/models/taesd.safetensors" "$H/sd-models/taesd.safetensors"
if [[ -f $OFF/SHA256SUMS.txt ]] && command -v sha256sum >/dev/null; then
  want=$(grep -E 'qwen2\.5-1\.5b' "$OFF/SHA256SUMS.txt" | awk '{print $1}' | head -1)
  if [[ -n $want && -s $Q ]] && [[ "$(sha256sum "$Q" | cut -d' ' -f1)" != "$want" ]]; then
    say "!! the language model copy is damaged; removing it (run this again)"; rm -f "$Q"
  fi
fi
SDM=$(ls -S "$H"/sd-models/sd_turbo* 2>/dev/null | grep -v '\.part$' | head -1)
chown -R "$WHO:$WHO" "$H/models" "$H/sd-models"

# 5. services: words (llama-server) and paintings (the background painter)
if [[ -x /usr/local/bin/ij-llama-server && -s $Q ]]; then
  cat > /etc/systemd/system/ij-words.service <<EOF
[Unit]
Description=Infinite Jest: local language model (Qwen, only reachable from the Pi itself)
After=local-fs.target
[Service]
User=$WHO
ExecStart=/usr/local/bin/ij-llama-server -m $Q --host 127.0.0.1 --port 8080 -t 2 -c 2048 --no-webui
Nice=10
CPUAffinity=2 3
Restart=on-failure
RestartSec=20
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload; systemctl enable ij-words.service >/dev/null 2>&1; systemctl restart ij-words.service
  say "words: on (local Qwen)"
else
  say "words: off (no language model yet; the TV uses the guest file's lines)"
fi
if [[ -x /usr/local/bin/ij-sd && -n $SDM ]]; then
  TAESD=""; [[ -s $H/sd-models/taesd.safetensors ]] && TAESD="-- --taesd $H/sd-models/taesd.safetensors"
  GEN="$H/read_the_room/infinite_jest/visuals/bank_gen/generate.py"
  cat > /etc/systemd/system/ij-paint.service <<EOF
[Unit]
Description=Infinite Jest: paints new pictures all the time (SD-Turbo), pauses while the face grows
After=local-fs.target
[Service]
User=$WHO
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $GEN --anytime --theme mix --steps 1 --width 384 --height 384 --threads 2 --nice 15 --max-per-hook 80 --abort-after 900 --sd-bin /usr/local/bin/ij-sd --model $SDM $TAESD
Nice=15
CPUWeight=20
IOSchedulingClass=idle
Restart=on-failure
RestartSec=60
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload; systemctl enable ij-paint.service >/dev/null 2>&1; systemctl restart ij-paint.service
  say "paintings: on (SD-Turbo, one picture at a time, new ones drift through the wall)"
else
  say "paintings: off (no painting model yet)"
fi
exit 0
