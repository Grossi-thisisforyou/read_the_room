#!/usr/bin/env bash
# One-time setup for painting the INFINITE JEST image bank on a Mac.
#
# Open Terminal, then type (drag this file into the window instead of typing
# the path, if you like):
#     bash install_mac.sh
#
# Safe to run again at any time: it skips whatever is already done, and picks
# up a download where it stopped. Needs internet. Takes about 10-30 minutes
# the first time, mostly downloading (about 5 GB in all).
#
# What it does:
#   1. checks this is a Mac (Apple Silicon M1/M2/M3/M4 is best)
#   2. installs Homebrew if it is missing (the usual Mac package installer;
#      asks for your Mac password once)
#   3. installs Python 3.12 with Homebrew
#   4. makes a private Python folder, ~/infinite-jest-mac/venv, so nothing
#      else on your Mac is touched (delete that folder to undo everything)
#   5. installs the painting software into it (PyTorch, diffusers)
#   6. downloads the SD-Turbo model and paints three test images to time it
#
# Settings, put in front of the command, e.g.  SKIP_TEST=1 bash install_mac.sh
#   IJ_HOME    where the private Python folder goes (default ~/infinite-jest-mac)
#   LATEST=1   install the newest package versions instead of the tested ones
#   SKIP_TEST=1  don't download the model / paint test images now

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IJ_HOME="${IJ_HOME:-$HOME/infinite-jest-mac}"
VENV="$IJ_HOME/venv"
PY_FORMULA="python@3.12"
REQS="$HERE/requirements-mac.txt"
LATEST="${LATEST:-0}"
SKIP_TEST="${SKIP_TEST:-0}"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31mPROBLEM: %s\033[0m\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------ 1. checks
say "1/6  Checking this Mac"
[ "$(uname -s)" = "Darwin" ] || die "This script is for macOS. On the Raspberry Pi use ../install_sdcpp.sh."
info "macOS $(sw_vers -productVersion), $(uname -m)"
if [ "$(uname -m)" != "arm64" ]; then
    info "This is an Intel Mac. It will work, but slowly (no fast graphics path)."
fi
macos_major=$(sw_vers -productVersion | cut -d. -f1)
[ "$macos_major" -ge 13 ] || info "macOS 13 or newer is recommended for the graphics path (yours: $(sw_vers -productVersion))."
free_gb=$(df -Pk "$HOME" | awk 'NR==2 {print int($4/1024/1024)}')
info "Free disk: ${free_gb} GB (need about 10 GB, plus room for the images)"
[ "$free_gb" -ge 8 ] || die "Not enough free disk space (need about 10 GB)."

# ------------------------------------------------------------------ 2. Homebrew
say "2/6  Homebrew"
if ! command -v brew >/dev/null 2>&1; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -x "$b" ]; then eval "$("$b" shellenv)"; break; fi
    done
fi
if command -v brew >/dev/null 2>&1; then
    info "Already installed: $(brew --version | head -1)"
else
    info "Homebrew is not installed. Installing it now with its official installer"
    info "(https://brew.sh). It will ask for your Mac password and may ask you to"
    info "press Return. If it offers to install the Command Line Tools, say yes."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -x "$b" ]; then eval "$("$b" shellenv)"; break; fi
    done
    command -v brew >/dev/null 2>&1 || die "Homebrew did not install. Install it from https://brew.sh, then run this again."
fi

# ------------------------------------------------------------------ 3. Python
say "3/6  Python 3.12"
if brew list --versions "$PY_FORMULA" >/dev/null 2>&1; then
    info "Already installed."
else
    brew install "$PY_FORMULA"
fi
PY="$(brew --prefix "$PY_FORMULA")/bin/python3.12"
[ -x "$PY" ] || die "Python 3.12 not found at $PY after installing."
info "$("$PY" --version) at $PY"

# ------------------------------------------------------------------ 4. venv
say "4/6  Private Python folder: $VENV"
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))'; then
    info "Already made."
else
    [ -d "$VENV" ] && { info "Replacing a broken or older one."; rm -rf "$VENV"; }
    mkdir -p "$IJ_HOME"
    "$PY" -m venv "$VENV"
fi
VPY="$VENV/bin/python"

# ------------------------------------------------------------------ 5. packages
say "5/6  Painting software (PyTorch, diffusers; about 1 GB)"
stamp="$VENV/.ij-requirements"
want="$(cat "$REQS") LATEST=$LATEST"
if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$want" ] \
   && "$VPY" -c 'import torch, diffusers, transformers, PIL' >/dev/null 2>&1; then
    info "Already installed."
else
    "$VPY" -m pip install --upgrade pip
    if [ "$LATEST" = "1" ]; then
        info "Installing the newest versions (LATEST=1)."
        "$VPY" -m pip install --upgrade torch diffusers transformers accelerate safetensors huggingface_hub pillow
    else
        "$VPY" -m pip install -r "$REQS"
    fi
    printf '%s' "$want" > "$stamp"
fi
"$VPY" "$HERE/mac_generate.py" --check || die "The check above found a problem."

# ------------------------------------------------------------------ 6. model + test
say "6/6  Downloading SD-Turbo and painting test images"
cat <<'LICENSE'
    SD-Turbo is made by Stability AI under the "Stability AI Community
    License": free for research and non-commercial use, and for commercial
    use by anyone earning under US$1M a year who registers with Stability AI.
    Read it before selling work made with it:
    https://huggingface.co/stabilityai/sd-turbo/blob/main/LICENSE.md
LICENSE
if [ "$SKIP_TEST" = "1" ]; then
    info "Skipped (SKIP_TEST=1). The model downloads on the first real run instead."
else
    info "About 2.5 GB the first time (kept in ~/.cache/huggingface); later runs skip it."
    "$VPY" "$HERE/mac_generate.py" --warmup || die "The test image failed; see the message above."
fi

chmod +x "$HERE/generate_mac.sh" "$HERE/copy_to_pi.sh" "$HERE/make_images.command" 2>/dev/null || true
say "Done."
cat <<EOF
    Paint images (they go to ~/Desktop/infinite_jest_bank):
        "$HERE/generate_mac.sh" --count 300
    or double-click make_images.command in Finder.

    Then copy them to the Pi:
        "$HERE/copy_to_pi.sh"
EOF
