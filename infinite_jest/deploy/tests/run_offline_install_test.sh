#!/usr/bin/env bash
# End-to-end test of the offline install, in an emulated 64-bit ARM machine with
# its network switched OFF (docker --network none), the same way the Pi runs it.
#
# Debian/Raspberry Pi mirrors may be out of reach from the test machine, so the
# test bundle uses Ubuntu 24.04 arm64 packages (profile test-ubuntu-noble) as a
# stand-in for Raspberry Pi OS. Everything else is the real thing: the resolver,
# the local package store, INSTALL.sh, the engine's install.sh, compiling
# llama.cpp from the bundled source, a real Qwen GGUF answering, the engine
# serving /status, ij-doctor and ij-netguard.
#
#   bash run_offline_install_test.sh BUNDLE_PARENT_DIR [IMAGE]
#
# IMAGE is a "Pi-like" base: arm64 Ubuntu with python3, sudo and a user "pi"
# (Raspberry Pi OS Lite has those). Needs docker with arm64 emulation (binfmt).
set -euo pipefail
OUT="${1:?bundle parent dir}"; IMAGE="${2:-ij-pi-sim:noble}"
docker run --rm --platform linux/arm64 --network none \
  -e IJ_RELEASE=test-ubuntu-noble -e IJ_GGML_NATIVE=OFF \
  -v "$OUT":/mnt "$IMAGE" bash -c '
set -e
cd /home/pi
echo "### network inside the test machine:"; ip -br addr || true
su pi -c "sudo IJ_RELEASE=$IJ_RELEASE IJ_GGML_NATIVE=$IJ_GGML_NATIVE bash /mnt/IJ-BUNDLE/INSTALL.sh"
echo "### after install"
su pi -c "python3 -c \"import aiohttp, pygame, numpy, cv2; print(\\\"imports ok\\\", aiohttp.__version__, numpy.__version__, cv2.__version__)\""
LS=/home/pi/llama.cpp/build/bin/llama-server
MODEL=$(ls /home/pi/models/*.gguf | head -1)
su pi -c "$LS --model $MODEL --host 127.0.0.1 --port 8080 --threads 4 --ctx-size 512 >/tmp/llama.log 2>&1 &"
for i in $(seq 1 120); do python3 -c "import urllib.request,sys; sys.exit(0 if b\"ok\" in urllib.request.urlopen(\"http://127.0.0.1:8080/health\",timeout=2).read() else 1)" 2>/dev/null && break; sleep 5; done
python3 - <<PY
import json, urllib.request, time
t=time.time()
req=urllib.request.Request("http://127.0.0.1:8080/v1/chat/completions", data=json.dumps({"messages":[{"role":"user","content":"Say three cold words about data."}],"max_tokens":12}).encode(), headers={"Content-Type":"application/json"})
r=json.load(urllib.request.urlopen(req, timeout=600))
print("### llama-server answered in %.0fs (emulated, so slow): %r" % (time.time()-t, r["choices"][0]["message"]["content"]))
PY
cd /home/pi/read_the_room/infinite_jest/pi
su pi -c "cd $PWD && SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 90 python3 -m showengine --simulate >/tmp/engine.log 2>&1 &"
for i in $(seq 1 40); do python3 -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8765/status\",timeout=2)" 2>/dev/null && break; sleep 2; done
sleep 10
echo "### engine /status:"; python3 -c "import urllib.request,json; d=json.load(urllib.request.urlopen(\"http://127.0.0.1:8765/status\")); print({k:d.get(k) for k in (\"phase\",\"fps\",\"last_frame_ts\",\"clients\")})"
echo "### ij-doctor (no Pi hardware here, so hardware lines say so):"
su pi -c "ij-doctor" || true
echo "### ij-netguard --once (no eth0 carrier in a sealed container):"; /usr/local/sbin/ij-netguard --once; ip -br addr
echo "### TEST DONE"
'
