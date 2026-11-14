#!/usr/bin/env bash
# Serve Gemma with vLLM behind one OpenAI-compatible URL (contract C3).
#
#   bash infra/serve.sh base                 # dev box: gemma-base on :8001 at 35% GPU (room to train)
#   bash infra/serve.sh ft <merged_dir_or_hf_repo>   # adds gemma-ft on :8002
#   bash infra/serve.sh sweep                # sweep box: gemma-e2b on :8003, gemma-26b on :8004
#   bash infra/serve.sh model <name> <port> <model> [util]   # any model, e.g. gemma-ft-e2b 8005 ~/merged/e2b-run1 0.12
#   bash infra/serve.sh proxy                # one URL on :8000 that routes by "model" field
#
# Every vLLM gets the same API key; the proxy checks it too. Put it in .env as MODEL_API_KEY.
# Each server runs in its own tmux window; `tmux attach -t serve` to watch logs.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
: "${MODEL_API_KEY:?export MODEL_API_KEY (any long random string; share it with Harry via .env)}"
VLLM=~/venv-vllm/bin/vllm
# Gemma 4 visual token budget: 70 | 140 | 280 (default) | 560 | 1120. Floor plans have small symbols,
# so 560 is the default here; training (train_lora --max-soft-tokens, default prompt.MAX_SOFT_TOKENS) MUST use the same value.
SOFT_TOKENS=${SOFT_TOKENS:-560}
MAXLEN=${MAXLEN:-4096}
GPU_UTIL=${GPU_UTIL:-0.35}

common=(--api-key "$MODEL_API_KEY" --max-model-len "$MAXLEN"
        --limit-mm-per-prompt '{"image": 1, "audio": 0}'
        --mm-processor-kwargs "{\"max_soft_tokens\": $SOFT_TOKENS}")

start() {  # name port model util [extra...]
  local name=$1 port=$2 model=$3 util=$4; shift 4
  tmux has-session -t serve 2>/dev/null || tmux new-session -d -s serve -n shell
  # VLLM_USE_FLASHINFER_SAMPLER=0: FlashInfer's sampler JIT-compiles on first use and needs nvcc + ninja
  # on PATH, which the Verda image lacks (engine dies in profile_run). The torch sampler is fine for us.
  tmux new-window -t serve -n "$name" \
    "env VLLM_USE_FLASHINFER_SAMPLER=${VLLM_USE_FLASHINFER_SAMPLER:-0} $VLLM serve $model --served-model-name $name --port $port --gpu-memory-utilization $util ${common[*]@Q} $* 2>&1 | tee ~/vllm-$name.log"
  echo "starting $name ($model) on :$port  (log ~/vllm-$name.log)"
}

wait_ready() {  # port
  for _ in $(seq 1 120); do
    curl -sf -H "Authorization: Bearer $MODEL_API_KEY" "localhost:$1/v1/models" >/dev/null && { echo ":$1 ready"; return; }
    sleep 5
  done
  echo "!! :$1 not ready after 10 min, check the log"; return 1
}

case "${1:-}" in
  base)  start gemma-base 8001 "${BASE_MODEL:-google/gemma-4-E4B-it}" "$GPU_UTIL"; wait_ready 8001 ;;
  ft)    start gemma-ft 8002 "${2:?merged model dir or private HF repo}" "${FT_UTIL:-$GPU_UTIL}"; wait_ready 8002 ;;
  model) start "${2:?name}" "${3:?port}" "${4:?model dir or HF repo}" "${5:-$GPU_UTIL}"; wait_ready "$3" ;;
  sweep) start gemma-e2b 8003 google/gemma-4-E2B-it 0.18
         start gemma-26b 8004 google/gemma-4-26B-A4B-it 0.72
         wait_ready 8003; wait_ready 8004 ;;
  proxy) tmux has-session -t serve 2>/dev/null || tmux new-session -d -s serve -n shell
         # Pass the env explicitly: a tmux window gets the tmux *server's* env (frozen when the first
         # session started), so without this the proxy can run with no API key and no custom ROUTES.
         envs="MODEL_API_KEY=${MODEL_API_KEY@Q}"
         if [ -n "${ROUTES:-}" ]; then envs+=" ROUTES=${ROUTES@Q}"; fi
         tmux new-window -t serve -n proxy "cd ~/bt && env $envs ~/venv-vllm/bin/python infra/model_proxy.py --port 8000 2>&1 | tee ~/proxy.log"
         sleep 2; echo "proxy on :8000 -> MODEL_BASE_URL=http://<box-ip>:8000/v1" ;;
  *) echo "usage: $0 base|ft <model>|model <name> <port> <model> [util]|sweep|proxy"; exit 1 ;;
esac
