#!/usr/bin/env bash
# INFINITE JEST: install everything on the Raspberry Pi from this USB stick.
# No internet needed. Run it on the Pi:
#
#     sudo mount -L IJ /mnt && sudo bash /mnt/IJ-BUNDLE/INSTALL.sh
#
# Safe to run again (it skips what is already done). Options:
#     --code-only     just update the show's code (fast), keep everything else
#     --no-start      install, but don't start the show at the end
#     --skip-llm      leave out the language model
#     --skip-images   leave out the image generator even if it's on the stick
#     --skip-network  don't touch the network settings
#
# A log is written to /var/log/infinite-jest-install.log and copied onto the
# stick (IJ-BUNDLE/logs/) so it can be read on the Mac.

set -uo pipefail

BUNDLE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_ONLY=0; START=1; SKIP_LLM=0; SKIP_IMAGES=0; SKIP_NET=0
for arg in "$@"; do
  case "$arg" in
    --code-only) CODE_ONLY=1 ;;
    --no-start) START=0 ;;
    --skip-llm) SKIP_LLM=1 ;;
    --skip-images) SKIP_IMAGES=1 ;;
    --skip-network) SKIP_NET=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg  (try --help)"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "This needs to run as the administrator. Running it again with sudo..."
  exec sudo bash "$0" "$@"
fi

# Whose show is this? The person who typed sudo, else "pi", else the first normal user.
WHO="${SUDO_USER:-}"
if [[ -z "$WHO" || "$WHO" == root ]]; then
  if id pi >/dev/null 2>&1; then WHO=pi; else WHO="$(getent passwd 1000 | cut -d: -f1)"; fi
fi
[[ -n "$WHO" ]] || { echo "Could not find the Pi's normal user account."; exit 1; }
HOME_DIR="$(getent passwd "$WHO" | cut -d: -f6)"
REPO="$HOME_DIR/read_the_room"
IJ="$REPO/infinite_jest"
CACHE=/var/cache/infinite-jest
LOG=/var/log/infinite-jest-install.log
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$CACHE"

exec > >(tee -a "$LOG") 2>&1
B=$'\033[1m'; R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; N=$'\033[0m'
say()  { printf '\n%s==> %s%s\n' "$B" "$*" "$N"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '    %s! %s%s\n' "$Y" "$*" "$N"; }
RESULTS=()
ok()   { RESULTS+=("${G}OK${N}      $1"); }
bad()  { RESULTS+=("${R}PROBLEM${N} $1"); }
skip() { RESULTS+=("${Y}SKIPPED${N} $1"); }
as_user() { sudo -u "$WHO" -H -- "$@"; }
have_systemd() { [[ -d /run/systemd/system ]]; }
manifest() {  # manifest KEY.PATH -> value (or empty)
  python3 - "$BUNDLE/manifest.json" "$1" <<'PY' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."):
    d = d.get(k, {}) if isinstance(d, dict) else {}
print("" if d in ({}, None) else (d if not isinstance(d, (dict, list)) else json.dumps(d)))
PY
}

cleanup() {
  rm -f /etc/apt/apt.conf.d/99infinite-jest-offline /etc/sudoers.d/99infinite-jest-install
}
finish() {
  cleanup
  say "Summary"
  for r in "${RESULTS[@]}"; do printf '    %s\n' "$r"; done
  if [[ -d "$BUNDLE/logs" ]] && touch "$BUNDLE/logs/.w" 2>/dev/null; then
    rm -f "$BUNDLE/logs/.w"
    cp "$LOG" "$BUNDLE/logs/install-$(hostname)-$STAMP.log" 2>/dev/null && \
      info "Log copied to the stick: IJ-BUNDLE/logs/install-$(hostname)-$STAMP.log"
  fi
  exit "${1:-0}"
}
stop() {
  printf '\n%sSTOPPED: %s%s\n' "$R" "$1" "$N"
  [[ -n "${2:-}" ]] && printf '%s\n' "$2"
  bad "$1"
  finish 1
}
trap cleanup EXIT
trap 'echo; stop "Interrupted. Run the same command again to continue."' INT

printf '%sINFINITE JEST installer%s  (%s)\n' "$B" "$N" "$(date)"
info "Bundle: $BUNDLE"
info "Made:   $(manifest made) on $(manifest made_on)"
info "For:    user $WHO, code goes to $IJ"

# ------------------------------------------------------------------ 1. checks
say "1. Checking this Pi"
[[ -f "$BUNDLE/manifest.json" ]] || stop "This doesn't look like a complete bundle (no manifest.json)." \
  "    Make it again on the Mac with make_bundle.py."
ARCH="$(uname -m)"
info "Machine: $ARCH, $(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo 'not a Raspberry Pi?')"
if [[ "$ARCH" != aarch64 && -z "${IJ_ALLOW_ANY_ARCH:-}" ]]; then
  stop "This Pi runs a 32-bit system ($ARCH). The show needs Raspberry Pi OS Lite (64-bit)." \
    "    Re-flash the card with Raspberry Pi Imager and pick 'Raspberry Pi OS Lite (64-bit)'."
fi
. /etc/os-release
RELEASE="${IJ_RELEASE:-${VERSION_CODENAME:-unknown}}"
info "System:  ${PRETTY_NAME:-unknown} ($RELEASE)"
DEBS="$BUNDLE/debs/$RELEASE"
if [[ $CODE_ONLY == 0 && ! -f "$DEBS/Packages" ]]; then
  have="$(ls "$BUNDLE/debs" 2>/dev/null | tr '\n' ' ')"
  stop "The stick has packages for: ${have:-nothing}, but this Pi runs '$RELEASE'." \
    "    On the Mac run:  python3 make_bundle.py --release $RELEASE   and try again."
fi
free_gb=$(df -Pk / | awk 'NR==2 {print int($4/1024/1024)}')
need_gb=4; [[ -d "$BUNDLE/models" ]] && need_gb=$((need_gb + $(du -sk "$BUNDLE/models" | awk '{print int($1/1024/1024)+1}')))
info "Free space: ${free_gb} GB (need about ${need_gb} GB)"
(( free_gb >= need_gb )) || stop "Not enough free space on the Pi's card." \
  "    Free some space, or use a bigger card."
# A Pi with no internet may think it's an older date; compiling then misbehaves.
made_epoch=$(date -d "$(manifest made)" +%s 2>/dev/null || echo 0)
if (( made_epoch > 0 && $(date +%s) < made_epoch )); then
  date -s "@$made_epoch" >/dev/null && warn "The Pi's clock was behind; set it to $(date)."
fi
ok "Pi checked ($RELEASE, $ARCH, ${free_gb} GB free)"

# ------------------------------------------------------------------ 2. packages
if [[ $CODE_ONLY == 0 ]]; then
  say "2. Installing system packages from the stick (no internet)"
  mkdir -p "$CACHE/debs" "$CACHE/lists/partial" "$CACHE/empty.d"
  info "Copying $(ls "$DEBS"/*.deb | wc -l) packages to the Pi..."
  rm -f "$CACHE/debs/"*.deb
  cp "$DEBS"/*.deb "$DEBS/Packages" "$DEBS/Packages.gz" "$CACHE/debs/" || stop "Could not copy the packages off the stick."
  echo "deb [trusted=yes] file:$CACHE/debs ./" > "$CACHE/sources.list"
  # While this runs, apt (including the engine's own install.sh) sees ONLY the
  # stick's packages, so nothing tries the internet. Removed again at the end.
  cat > /etc/apt/apt.conf.d/99infinite-jest-offline <<EOF
Dir::Etc::SourceList "$CACHE/sources.list";
Dir::Etc::SourceParts "$CACHE/empty.d";
Dir::State::Lists "$CACHE/lists";
APT::Install-Recommends "false";
APT::Get::Assume-Yes "true";
Acquire::Languages "none";
EOF
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q || stop "apt could not read the packages from the stick." "    See the log: $LOG"
  # shellcheck disable=SC2046
  if apt-get install -q -y $(cat "$DEBS/wanted.txt"); then
    ok "System packages ($(wc -l < "$DEBS/wanted.txt") wanted, all from the stick)"
  else
    stop "Installing the system packages failed." \
      "    Bring the log file on the stick (IJ-BUNDLE/logs) to Claude, or read: $LOG"
  fi
else
  skip "System packages (--code-only)"
fi

# ------------------------------------------------------------------ 3. code
say "3. Copying the show's code to $IJ"
mkdir -p "$REPO"
if [[ -d "$IJ" ]]; then
  info "Updating the existing copy (your generated images and settings stay)."
  tar -C "$REPO" -czf "$CACHE/code-before-$STAMP.tgz" --exclude='bank/*' infinite_jest 2>/dev/null && \
    info "Old code saved in $CACHE/code-before-$STAMP.tgz"
fi
cp -a "$BUNDLE/code/infinite_jest" "$REPO/" || stop "Could not copy the code."
[[ -d "$BUNDLE/code/docs" ]] && cp -a "$BUNDLE/code/docs" "$REPO/"
chown -R "$WHO:" "$REPO"
ok "Code ($(manifest code.git || echo 'version unknown'))"

if [[ $CODE_ONLY == 1 ]]; then
  if have_systemd; then systemctl restart infinite-jest 2>/dev/null && ok "Show restarted with the new code"; fi
  finish 0
fi

# ------------------------------------------------------------------ 4. engine
say "4. Setting up the show engine"
# The engine's own installer uses sudo; let it, without a password, just for now.
echo "$WHO ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/99infinite-jest-install
chmod 440 /etc/sudoers.d/99infinite-jest-install
eng_args=(--no-autostart)
grep -qx python3-opencv "$DEBS/wanted.txt" && eng_args+=(--with-opencv)
if (cd "$IJ/pi" && as_user env DEBIAN_FRONTEND=noninteractive bash ./install.sh "${eng_args[@]}"); then
  ok "Show engine (Python libraries, settings file)"
else
  stop "The engine's installer failed (see above)."
fi
# systemd service, done here so we can start it last
if have_systemd; then
  sed -e "s|@USER@|$WHO|g" -e "s|@DIR@|$IJ/pi|g" -e "s|@HOME@|$HOME_DIR|g" "$IJ/pi/systemd/infinite-jest.service" \
    > /etc/systemd/system/infinite-jest.service
  systemctl daemon-reload
  systemctl enable infinite-jest >/dev/null 2>&1 && ok "Show starts at every power-on (service infinite-jest)"
else
  skip "Autostart (no systemd here; test machine?)"
fi

# ------------------------------------------------------------------ 5. language model
build_from_src() {  # build_from_src KEY DEST [TARGETS...]
  local key="$1" dest="$2"; shift 2
  local file subdir sha
  file="$(manifest "sources.$key.file")"; subdir="$(manifest "sources.$key.subdir")"; sha="$(manifest "sources.$key.sha256")"
  [[ -n "$file" && -f "$BUNDLE/src/$file" ]] || return 2
  if [[ -f "$dest/.ij-built" && "$(cat "$dest/.ij-built")" == "$sha" ]]; then
    info "Already built from this exact source; skipping."
    return 0
  fi
  info "Checking the source file..."
  echo "$sha  $BUNDLE/src/$file" | sha256sum -c --quiet - || { warn "Source file is damaged; make the bundle again."; return 1; }
  info "Unpacking..."
  rm -rf "$dest.new" && mkdir -p "$dest.new"
  tar -xzf "$BUNDLE/src/$file" -C "$dest.new" --strip-components="$(awk -F/ '{print NF}' <<<"$subdir")" "$subdir" || return 1
  [[ -d "$dest" ]] && rm -rf "$dest.old" && mv "$dest" "$dest.old"
  mv "$dest.new" "$dest" && rm -rf "$dest.old"
  chown -R "$WHO:" "$dest"
  info "Compiling for this Pi's processor. This is the slow part (10 to 25 minutes)."
  local jobs; jobs=$(nproc); (( jobs > 4 )) && jobs=4
  as_user cmake -S "$dest" -B "$dest/build" -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE="${IJ_GGML_NATIVE:-ON}" \
      -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
      -DBUILD_SHARED_LIBS=OFF >"$CACHE/build-$key.log" 2>&1 || { tail -20 "$CACHE/build-$key.log"; return 1; }
  local t0=$SECONDS
  local targets=()
  (( $# > 0 )) && targets=(--target "$@")
  as_user cmake --build "$dest/build" --config Release -j "$jobs" "${targets[@]}" >>"$CACHE/build-$key.log" 2>&1 \
    || { tail -30 "$CACHE/build-$key.log"; return 1; }
  info "Compiled in $(( (SECONDS - t0) / 60 )) min."
  echo "$sha" > "$dest/.ij-built"
}

LLM_FILE="$(manifest models.llm.file)"
if [[ $SKIP_LLM == 1 ]]; then
  skip "Language model (--skip-llm)"
elif [[ -z "$(manifest sources.llama.file)" ]]; then
  skip "Language model (not on this stick)"
else
  say "5. Language model (llama.cpp + ${LLM_FILE:-no model file})"
  if build_from_src llama "$HOME_DIR/llama.cpp" llama-server llama-cli; then
    ok "llama.cpp compiled ($HOME_DIR/llama.cpp/build/bin/llama-server)"
    if [[ -n "$LLM_FILE" ]]; then
      mkdir -p "$HOME_DIR/models"
      src="$BUNDLE/models/$LLM_FILE"; dst="$HOME_DIR/models/$LLM_FILE"
      if [[ -f "$dst" && $(stat -c %s "$dst") == $(stat -c %s "$src") ]]; then
        info "Model already on the Pi."
      else
        info "Copying the model ($(du -h "$src" | cut -f1))..."
        cp "$src" "$dst.part" && mv "$dst.part" "$dst"
      fi
      want="$(manifest models.llm.sha256)"
      info "Checking the model file..."
      if [[ -n "$want" ]] && ! echo "$want  $dst" | sha256sum -c --quiet - ; then
        rm -f "$dst"; bad "Language model file damaged on the stick; make the bundle again"
      else
        chown -R "$WHO:" "$HOME_DIR/models"
        if have_systemd; then
          sed -e "s|@USER@|$WHO|g" -e "s|@HOME@|$HOME_DIR|g" -e "s|@MODEL@|$dst|g" \
            "$IJ/pi/systemd/llama-server.service" > /etc/systemd/system/llama-server.service
          systemctl daemon-reload
          systemctl enable llama-server >/dev/null 2>&1
          systemctl restart llama-server
        fi
        ok "Language model $LLM_FILE (service llama-server, only reachable from the Pi itself)"
        if [[ -d "$IJ/oracle" ]] && have_systemd; then
          sed -e "s|@USER@|$WHO|g" -e "s|@REPO@|$REPO|g" "$IJ/deploy/pi/systemd/infinite-jest-oracle.service" \
            > /etc/systemd/system/infinite-jest-oracle.service
          systemctl daemon-reload; systemctl enable infinite-jest-oracle >/dev/null 2>&1
          ok "Oracle: the model's words go to the wall and the phone (service infinite-jest-oracle)"
        fi
      fi
    else
      skip "Language model file (not on this stick)"
    fi
  else
    bad "llama.cpp did not compile; the show runs without it (log: $CACHE/build-llama.log)"
  fi
fi

# ------------------------------------------------------------------ 6. image generator
SD_FILE="$(manifest models.sd.file)"
if [[ $SKIP_IMAGES == 1 ]]; then
  skip "Image generator (--skip-images)"
elif [[ -z "$(manifest sources.sd.file)" ]]; then
  skip "Image generator (not on this stick; the show uses its built-in pictures)"
else
  say "6. Image generator (stable-diffusion.cpp + SD-Turbo)"
  if build_from_src sd "$HOME_DIR/stable-diffusion.cpp"; then
    SD_BIN="$HOME_DIR/stable-diffusion.cpp/build/bin/sd-cli"; [[ -x "$SD_BIN" ]] || SD_BIN="$HOME_DIR/stable-diffusion.cpp/build/bin/sd"
    ok "stable-diffusion.cpp compiled ($SD_BIN)"
    if [[ -n "$SD_FILE" ]]; then
      mkdir -p "$HOME_DIR/sd-models"
      dst="$HOME_DIR/sd-models/$SD_FILE"
      [[ -f "$dst" && $(stat -c %s "$dst") == $(stat -c %s "$BUNDLE/models/$SD_FILE") ]] || \
        { info "Copying the image model (5 GB)..."; cp "$BUNDLE/models/$SD_FILE" "$dst.part" && mv "$dst.part" "$dst"; }
      q8="$HOME_DIR/sd-models/sd_turbo.q8_0.gguf"
      if [[ ! -s "$q8" && -x "$SD_BIN" ]]; then
        info "Making the smaller 8-bit copy (a few minutes)..."
        as_user "$SD_BIN" -M convert -m "$dst" -o "$q8.part" --type q8_0 >>"$CACHE/build-sd.log" 2>&1 && mv "$q8.part" "$q8" \
          || warn "8-bit copy failed; the full model is used instead."
      fi
      chown -R "$WHO:" "$HOME_DIR/sd-models"
      unit="$IJ/visuals/bank_gen/infinite-jest-bankgen.service"
      if [[ -f "$unit" ]] && have_systemd; then
        sed -e "s|/home/pi/read_the_room|$REPO|g" -e "s|^User=pi|User=$WHO|" -e "s|^Group=pi|Group=$WHO|" "$unit" \
          > /etc/systemd/system/infinite-jest-bankgen.service
        systemctl daemon-reload; systemctl enable infinite-jest-bankgen >/dev/null 2>&1
        ok "Image generator runs at night, pauses for visitors (service infinite-jest-bankgen)"
      else
        skip "Image generator service (the visuals code on this stick has none yet)"
      fi
    fi
  else
    bad "stable-diffusion.cpp did not compile (log: $CACHE/build-sd.log)"
  fi
fi

# ------------------------------------------------------------------ 7. network
if [[ $SKIP_NET == 1 ]]; then
  skip "Network (--skip-network)"
else
  say "7. Show network (Linksys 'infinitejest', Pi at 192.168.1.10)"
  if bash "$IJ/deploy/pi/setup_network.sh" --install; then
    ok "Network: Ethernet first, show Wi-Fi as fallback, always 192.168.1.10"
  else
    bad "Network setup had a problem (see above); the show itself still runs"
  fi
fi

# ------------------------------------------------------------------ 7b. boot look
if [[ -f "$IJ/case/install.sh" ]] && have_systemd; then
  say "7b. Boot look (black splash, no boot text on the projector)"
  if (cd "$IJ/case" && bash ./install.sh); then ok "Boot splash"; else bad "Boot splash had a problem (the show still runs)"; fi
fi

# ------------------------------------------------------------------ 8. health tools
say "8. Health check, watchdog and safe blackout"
if bash "$IJ/deploy/pi/install_tools.sh" "$WHO"; then
  ok "ij-doctor, watchdog, black screen when the show is down"
else
  bad "Health tools had a problem (see above)"
fi

# ------------------------------------------------------------------ 9. start
cleanup
if [[ $START == 1 ]] && have_systemd; then
  say "9. Starting the show"
  systemctl restart infinite-jest && sleep 8
  if systemctl is-active --quiet infinite-jest; then ok "Show is running"; else bad "Show did not start: run  ij-doctor"; fi
fi
say "Health check"
if command -v ij-doctor >/dev/null; then ij-doctor --after-install || true; fi
cat <<EOF

    ${B}Done.${N} From now on the show starts by itself when the Pi gets power.
      Check everything:   ij-doctor
      Control page:       http://192.168.1.10:8765/   (from the Mac on the Linksys)
      Update code later:  sudo bash /mnt/IJ-BUNDLE/INSTALL.sh --code-only
    Unmount the stick before pulling it out:  sudo umount /mnt
EOF
finish 0
