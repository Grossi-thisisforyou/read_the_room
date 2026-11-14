#!/usr/bin/env bash
# Paint images for the INFINITE JEST bank on this Mac.
#     ./generate_mac.sh --count 300
#     ./generate_mac.sh --per-hook 200 --postprocess
#     ./generate_mac.sh --help          (every option)
# Run install_mac.sh once first.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IJ_HOME="${IJ_HOME:-$HOME/infinite-jest-mac}"
VPY="$IJ_HOME/venv/bin/python"
if [ ! -x "$VPY" ]; then
    echo "The painting software isn't installed yet. Run this first:"
    echo "    bash \"$HERE/install_mac.sh\""
    exit 2
fi
# Let PyTorch fall back to the CPU for the odd operation the Mac GPU lacks,
# instead of stopping with an error.
export PYTORCH_ENABLE_MPS_FALLBACK=1
exec "$VPY" "$HERE/mac_generate.py" "$@"
