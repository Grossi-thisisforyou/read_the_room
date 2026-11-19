#!/bin/bash
# Build an update zip for the Pi from this checkout:  bash make_update.sh OUT_DIR
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"; IJ="$(cd "$HERE/../.." && pwd)"
OUT="${1:?out dir}"; D="$OUT/ij-update"
rm -rf "$D"; mkdir -p "$D"
cp "$HERE/update-mac.sh" "$D/update-mac.sh"; cp "$HERE/update-ssh.sh" "$D/update-ssh.sh"; cp "$HERE/update-arm.sh" "$D/arm.sh"; cp "$HERE/update-apply.sh" "$D/apply.sh"
cp -r "$IJ" "$D/infinite_jest"
find "$D" \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
rm -rf "$D/infinite_jest/case/print"      # STLs: not needed on the Pi
(cd "$IJ" && git describe --always --dirty 2>/dev/null || date +%F) > "$D/infinite_jest/VERSION.txt"
(cd "$OUT" && rm -f ij-update.zip && python3 -c "
import zipfile,os
z=zipfile.ZipFile('ij-update.zip','w',zipfile.ZIP_DEFLATED)
for d,_,fs in os.walk('ij-update'):
    for f in fs:
        p=os.path.join(d,f); zi=zipfile.ZipInfo.from_file(p); zi.compress_type=zipfile.ZIP_DEFLATED; z.writestr(zi,open(p,'rb').read())
")
echo "$OUT/ij-update.zip"
