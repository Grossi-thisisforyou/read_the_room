#!/usr/bin/env bash
# Install stable-diffusion.cpp and the SD-Turbo model on the Raspberry Pi 5.
#
# Run this ONCE AT HOME, with internet (the venue has none):
#     bash install_sdcpp.sh
# Safe to run again: it skips whatever is already done.
#
# What it does:
#   1. installs build tools with apt (asks for your password once)
#   2. downloads the stable-diffusion.cpp source to ~/stable-diffusion.cpp
#   3. builds it for the Pi's CPU (10-30 minutes)
#   4. downloads SD-Turbo (sd_turbo.safetensors, 5.2 GB) to ~/sd-models
#   5. makes a smaller, faster 8-bit copy (sd_turbo.q8_0.gguf)
#
# Settings you can change by putting them in front of the command, e.g.
#     SDCPP_REF=master-abc1234 QUANTIZE=0 bash install_sdcpp.sh
#   SDCPP_DIR   where the source goes         (default ~/stable-diffusion.cpp)
#   MODEL_DIR   where the model goes          (default ~/sd-models)
#   SDCPP_REF   a tag or commit to pin to     (default: latest master)
#   QUANTIZE    1 = make the 8-bit copy, 0 = skip   (default 1)
#   UPDATE      1 = pull newer source and rebuild   (default 0)

set -euo pipefail

SDCPP_DIR="${SDCPP_DIR:-$HOME/stable-diffusion.cpp}"
MODEL_DIR="${MODEL_DIR:-$HOME/sd-models}"
SDCPP_REF="${SDCPP_REF:-}"
QUANTIZE="${QUANTIZE:-1}"
UPDATE="${UPDATE:-0}"
REPO_URL="https://github.com/leejet/stable-diffusion.cpp"
MODEL_URL="https://huggingface.co/stabilityai/sd-turbo/resolve/main/sd_turbo.safetensors"
MODEL_FILE="$MODEL_DIR/sd_turbo.safetensors"
QUANT_FILE="$MODEL_DIR/sd_turbo.q8_0.gguf"
MIN_MODEL_BYTES=5000000000   # the real file is about 5.2 GB

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

find_bin() {
    for b in "$SDCPP_DIR/build/bin/sd-cli" "$SDCPP_DIR/build/bin/sd"; do
        if [ -x "$b" ]; then echo "$b"; return 0; fi
    done
    return 1
}

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

# ------------------------------------------------------------------ 0. checks
say "Checking this machine"
info "$(uname -srm)"
[ "$(uname -m)" = "aarch64" ] || info "Not a 64-bit ARM machine; continuing anyway."
free_gb=$(df -Pk "$HOME" | awk 'NR==2 {print int($4/1024/1024)}')
info "Free disk in $HOME: ${free_gb} GB (need about 10 GB for source, build and model)"
[ "$free_gb" -ge 8 ] || die "Not enough free disk space."

# ------------------------------------------------------------------ 1. apt
say "1/5  Installing build tools (git, cmake, compiler)"
PKGS="git cmake build-essential ca-certificates wget"
missing=""
for p in $PKGS; do dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"; done
if [ -n "$missing" ]; then
    info "Installing:$missing"
    sudo apt-get update
    sudo apt-get install -y $missing
else
    info "Already installed."
fi

# ------------------------------------------------------------------ 2. source
say "2/5  Getting stable-diffusion.cpp source into $SDCPP_DIR"
rebuild=0
if [ ! -d "$SDCPP_DIR/.git" ]; then
    git clone --recursive "$REPO_URL" "$SDCPP_DIR"
    rebuild=1
elif [ "$UPDATE" = "1" ]; then
    info "Updating existing source (UPDATE=1)"
    git -C "$SDCPP_DIR" fetch --tags origin
    if [ -z "$SDCPP_REF" ]; then
        git -C "$SDCPP_DIR" checkout --quiet master
        git -C "$SDCPP_DIR" pull --ff-only origin master
    fi
    rebuild=1
else
    info "Already downloaded (set UPDATE=1 to pull a newer version)."
fi
if [ -n "$SDCPP_REF" ]; then
    current=$(git -C "$SDCPP_DIR" rev-parse HEAD)
    wanted=$(git -C "$SDCPP_DIR" rev-parse "$SDCPP_REF^{commit}" 2>/dev/null || true)
    [ -n "$wanted" ] || { git -C "$SDCPP_DIR" fetch --tags origin; wanted=$(git -C "$SDCPP_DIR" rev-parse "$SDCPP_REF^{commit}"); }
    if [ "$current" != "$wanted" ]; then
        info "Switching to $SDCPP_REF"
        git -C "$SDCPP_DIR" checkout --quiet "$SDCPP_REF"
        rebuild=1
    fi
fi
git -C "$SDCPP_DIR" submodule update --init --recursive
info "Version: $(git -C "$SDCPP_DIR" describe --tags --always 2>/dev/null)"

# ------------------------------------------------------------------ 3. build
say "3/5  Building for this CPU (Release, CPU only)"
if [ "$rebuild" = "0" ] && SD_BIN=$(find_bin); then
    info "Already built: $SD_BIN"
else
    info "This takes roughly 10-30 minutes on a Pi 5. Leave it alone."
    mkdir -p "$SDCPP_DIR/build"
    # Plain CPU build, as in the project's docs/build.md. ggml compiles for the
    # CPU it is built on (ARM NEON / dot-product on the Pi 5's Cortex-A76).
    cmake -S "$SDCPP_DIR" -B "$SDCPP_DIR/build" -DCMAKE_BUILD_TYPE=Release
    cmake --build "$SDCPP_DIR/build" --config Release -j "$(nproc)"
    SD_BIN=$(find_bin) || die "Build finished but no sd-cli/sd program in $SDCPP_DIR/build/bin"
    info "Built: $SD_BIN"
fi

# ------------------------------------------------------------------ 4. model
say "4/5  Downloading SD-Turbo into $MODEL_DIR (5.2 GB)"
cat <<'LICENSE'
    SD-Turbo is made by Stability AI and comes under the
    "Stability AI Community License". In short (read it yourself):
      - free for research, personal and non-commercial use;
      - commercial use is free for people/organisations earning under
        US$1M a year, but you must register at stability.ai/community-license;
      - you must follow Stability's Acceptable Use Policy.
    Showing it in an art-school exhibition is very likely fine, but please read
    https://huggingface.co/stabilityai/sd-turbo/blob/main/LICENSE.md
    before selling or commissioning work made with it.
LICENSE
mkdir -p "$MODEL_DIR"
if [ "$(file_size "$MODEL_FILE")" -ge "$MIN_MODEL_BYTES" ]; then
    info "Already downloaded: $MODEL_FILE"
else
    info "Downloading (resumes if it was interrupted)..."
    wget -c --progress=dot:giga -O "$MODEL_FILE.part" "$MODEL_URL"
    [ "$(file_size "$MODEL_FILE.part")" -ge "$MIN_MODEL_BYTES" ] \
        || die "Download looks incomplete ($(file_size "$MODEL_FILE.part") bytes). Run the script again to resume."
    mv "$MODEL_FILE.part" "$MODEL_FILE"
    info "Saved $MODEL_FILE"
fi

# ------------------------------------------------------------------ 5. quantize
say "5/5  Making the 8-bit model copy"
if [ "$QUANTIZE" != "1" ]; then
    info "Skipped (QUANTIZE=0). generate.py will use $MODEL_FILE"
elif [ -s "$QUANT_FILE" ]; then
    info "Already made: $QUANT_FILE"
else
    info "Converting to q8_0 (a few minutes). Smaller in memory, usually faster on CPU."
    "$SD_BIN" -M convert -m "$MODEL_FILE" -o "$QUANT_FILE.part" -v --type q8_0
    [ -s "$QUANT_FILE.part" ] || die "Conversion produced no file."
    mv "$QUANT_FILE.part" "$QUANT_FILE"
    info "Saved $QUANT_FILE ($(du -h "$QUANT_FILE" | cut -f1))"
    info "generate.py picks this file automatically. If images look worse than"
    info "with the full model, delete it and the full model is used instead."
fi

say "Done."
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cat <<EOF
    Program: $SD_BIN
    Models:  $(ls "$MODEL_DIR" | tr '\n' ' ')

    Make one test image now (takes a few minutes):
        python3 "$HERE/generate.py" --count 1 --anytime

    Then see README.md for leaving it running overnight.
EOF
