#!/usr/bin/env bash
# Build llama.cpp and download a small Qwen model, then run it as a service on
# 127.0.0.1:8080 (only the Pi itself can reach it). Called by: bash install.sh --with-llm
# Needs internet once (about 1 GB download, 10-20 minutes of compiling on a Pi 5).
#
#   MODEL_URL=...  bash llm_install.sh   # a different GGUF (e.g. a 3B for better text, slower)
set -euo pipefail
cd "$(dirname "$0")"
WHO="$(id -un)"
HOME_DIR="$(getent passwd "$WHO" | cut -d: -f6)"
MODEL_URL="${MODEL_URL:-https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf}"
MODEL="$HOME_DIR/models/$(basename "$MODEL_URL")"

echo "== LLM 1/4 Build tools"
sudo apt-get install -y build-essential cmake git curl

echo "== LLM 2/4 llama.cpp (in $HOME_DIR/llama.cpp)"
if [[ ! -d "$HOME_DIR/llama.cpp" ]]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp "$HOME_DIR/llama.cpp"
fi
cmake -S "$HOME_DIR/llama.cpp" -B "$HOME_DIR/llama.cpp/build" -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DLLAMA_CURL=OFF
cmake --build "$HOME_DIR/llama.cpp/build" --target llama-server -j4

echo "== LLM 3/4 Model ($MODEL)"
mkdir -p "$HOME_DIR/models"
if [[ ! -s "$MODEL" ]]; then
  curl -L --fail -o "$MODEL.part" "$MODEL_URL" && mv "$MODEL.part" "$MODEL"
fi

echo "== LLM 4/4 Service: llama-server"
sed -e "s|@USER@|$WHO|g" -e "s|@HOME@|$HOME_DIR|g" -e "s|@MODEL@|$MODEL|g" systemd/llama-server.service \
  | sudo tee /etc/systemd/system/llama-server.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now llama-server
for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:8080/health >/dev/null && break
  sleep 2
done
if curl -sf http://127.0.0.1:8080/health >/dev/null; then
  echo "   model is up. Quick test:"
  curl -s http://127.0.0.1:8080/v1/chat/completions -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"Say three cold words about data."}],"max_tokens":16}' \
    | python3 -c 'import json,sys; print("   ", json.load(sys.stdin)["choices"][0]["message"]["content"])' || true
else
  echo "!! llama-server didn't answer yet; check: journalctl -u llama-server -f"
fi
