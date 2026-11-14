#!/usr/bin/env bash
# Model soups (E4B), unattended (tmux session "soup", log ~/soup.log).
#   gemma-soup  = 0.5 run1 + 0.5 run2
#   gemma-super = spec-cc + 0.5 (run2 - run1)   (the soup with the specialist's delta on top)
# Pauses gemma-ft-cc (:8008, not routed yet) to free its 0.25 of the GPU, serves each soup on :8009,
# eval + calibrate, then serves gemma-ft-cc again. gemma-base and gemma-ft keep serving the demo.
# Nothing is swapped in: compare with python -m model.report first.
#
# Start:  tmux new-session -d -s soup "bash ~/bt/infra/soup_chain.sh 2>&1 | tee -a ~/soup.log"
source ~/.bt_env; cd ~/bt
PY=~/venv-train/bin/python
log() { echo "[$(date +%H:%M:%S)] $*"; }

evaluate() {  # served-name port
  log "eval $1"
  MODEL_BASE_URL=http://localhost:$2/v1 $PY -m model.baseline_eval --models "$1" --out "results/$1.json" \
    > ~/eval-$1.log 2>&1 || log "!! eval $1 failed (~/eval-$1.log)"
  $PY -m model.calibrate --label "$1" > ~/calib-$1.log 2>&1 || log "!! calibrate $1 failed"
}

log "build soups"
$PY -m model.soup --out ~/merged/soup ~/merged/run1:0.5 ~/merged/run2:0.5 || log "!! soup build failed"
$PY -m model.soup --out ~/merged/super ~/merged/spec-cc:1 ~/merged/run2:0.5 ~/merged/run1:-0.5 \
  || log "!! super build failed"

log "pause gemma-ft-cc"
tmux kill-window -t serve:gemma-ft-cc 2>/dev/null; sleep 20

for pair in "gemma-soup:soup" "gemma-super:super"; do
  name=${pair%%:*}; dir=~/merged/${pair##*:}
  [ -f "$dir/model.safetensors" ] || { log "!! $dir missing, skip $name"; continue; }
  if bash infra/serve.sh model "$name" 8009 "$dir" 0.25; then
    evaluate "$name" 8009
  else
    log "!! $name did not start (~/vllm-$name.log)"
  fi
  tmux kill-window -t "serve:$name" 2>/dev/null; sleep 20
done

log "serve gemma-ft-cc again"
bash infra/serve.sh model gemma-ft-cc 8008 ~/merged/spec-cc 0.25 || log "!! gemma-ft-cc did not restart"
log "SOUP CHAIN DONE"
