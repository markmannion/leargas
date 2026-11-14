#!/usr/bin/env bash
# Scan-robustness check, unattended (tmux session "robust", log ~/robust.log).
# Builds degraded copies of the held-out raster images (model/robustness.py: scan, photo, lowres),
# then scores gemma-ft (run 1) and gemma-ft-cc on each through the proxy (:8000). Nothing is
# restarted or swapped. Results: results/<model>-<mode>.json, compare with python -m model.report.
#
# Start:  tmux new-session -d -s robust "bash ~/bt/infra/robust_chain.sh 2>&1 | tee -a ~/robust.log"
source ~/.bt_env; cd ~/bt
PY=~/venv-train/bin/python
MODES=${MODES:-scan photo lowres}
log() { echo "[$(date +%H:%M:%S)] $*"; }

log "build degraded sets: $MODES"
$PY -m model.robustness --out ~/degraded --modes "$(echo $MODES | tr ' ' ,)" || { log "!! build failed"; exit 1; }

for mode in $MODES; do
  for m in gemma-ft gemma-ft-cc; do
    log "eval $m on $mode"
    JUNCTION_DATA=~/degraded/$mode MODEL_BASE_URL=http://localhost:8000/v1 \
      $PY -m model.baseline_eval --models "$m" --label "$m-$mode" --sets heldout_raster --workers 12 \
      > ~/eval-$m-$mode.log 2>&1 || log "!! eval $m $mode failed (~/eval-$m-$mode.log)"
  done
done
log "ROBUST CHAIN DONE"
