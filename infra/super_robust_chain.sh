#!/usr/bin/env bash
# gemma-super on the degraded held-out sets, so every candidate for uploads has robustness numbers.
# Waits for aug_chain.sh to finish (it uses the same GPU slot), rebuilds ~/merged/super
# (spec-cc + 0.5 (run2 - run1), model/soup.py), pauses gemma-ft-cc, serves super on :8009,
# scores scan/photo/lowres, then serves gemma-ft-cc again. Nothing is swapped in.
#
# Start:  tmux new-session -d -s superrob "bash ~/bt/infra/super_robust_chain.sh 2>&1 | tee -a ~/superrob.log"
source ~/.bt_env; cd ~/bt
PY=~/venv-train/bin/python
MODES=${MODES:-scan photo lowres}
log() { echo "[$(date +%H:%M:%S)] $*"; }

log "waiting for the aug chain"
until grep -q "AUG CHAIN DONE" ~/aug.log 2>/dev/null; do sleep 30; done

log "rebuild super"
[ -f ~/merged/super/model.safetensors ] || \
  $PY -m model.soup --out ~/merged/super ~/merged/spec-cc:1 ~/merged/run2:0.5 ~/merged/run1:-0.5 \
  || { log "!! super build failed"; exit 1; }

log "pause gemma-ft-cc"
tmux kill-window -t serve:gemma-ft-cc 2>/dev/null; sleep 20
if bash infra/serve.sh model gemma-super 8009 ~/merged/super 0.25; then
  for mode in $MODES; do
    log "eval gemma-super on $mode"
    JUNCTION_DATA=~/degraded/$mode MODEL_BASE_URL=http://localhost:8009/v1 \
      $PY -m model.baseline_eval --models gemma-super --label "gemma-super-$mode" --sets heldout_raster --workers 12 \
      > ~/eval-gemma-super-$mode.log 2>&1 || log "!! eval super $mode failed"
  done
else
  log "!! gemma-super did not start (~/vllm-gemma-super.log)"
fi
tmux kill-window -t serve:gemma-super 2>/dev/null; sleep 20
log "serve gemma-ft-cc again"
bash infra/serve.sh model gemma-ft-cc 8008 ~/merged/spec-cc 0.25 || log "!! gemma-ft-cc did not restart"
log "SUPER ROBUST DONE"
