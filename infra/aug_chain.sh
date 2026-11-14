#!/usr/bin/env bash
# Augmented specialist (E4B), unattended (tmux session "aug", log ~/aug.log).
# A/B against gemma-ft-cc: same data (spec_cc.jsonl), same start (run 1), same 500 steps; the only
# change is that half the rows show a randomly degraded image (model/augment_sft.py).
#   1. augment -> data/sft/spec_cc_aug.jsonl + ~/aug/spec_cc/*.png
#   2. pause gemma-ft-cc (:8008) to free GPU memory for training; the router falls back to gemma-ft
#   3. train spec-cc-aug from ~/merged/run1 -> merge -> serve gemma-ft-cc-aug :8009
#   4. eval clean (held-out + judge) + calibrate, then each degraded set from robust_chain.sh
#   5. stop gemma-ft-cc-aug, serve gemma-ft-cc again on :8008. Nothing is swapped in.
#
# Start:  tmux new-session -d -s aug "bash ~/bt/infra/aug_chain.sh 2>&1 | tee -a ~/aug.log"
source ~/.bt_env; cd ~/bt
PY=~/venv-train/bin/python
MODES=${MODES:-scan photo lowres}
NAME=gemma-ft-cc-aug
log() { echo "[$(date +%H:%M:%S)] $*"; }

log "augment spec_cc.jsonl"
$PY -m model.augment_sft --data data/sft/spec_cc.jsonl --out data/sft/spec_cc_aug.jsonl \
  --img-dir ~/aug/spec_cc --frac 0.5 || { log "!! augment failed"; exit 1; }

log "pause gemma-ft-cc for training"
tmux kill-window -t serve:gemma-ft-cc 2>/dev/null; sleep 20

log "train spec-cc-aug"
$PY -m model.train_lora --model ~/merged/run1 --data data/sft/spec_cc_aug.jsonl --run spec-cc-aug --max-steps 500 \
  --hub-repo leargas/bt-gemma4-e4b-spec-cc-aug 2>&1 | tee ~/train-spec-cc-aug.log
echo "EXIT=${PIPESTATUS[0]}" >> ~/train-spec-cc-aug.log

if grep -q '^EXIT=0' ~/train-spec-cc-aug.log; then
  $PY -m model.train_lora --merge-only --run spec-cc-aug > ~/merge-spec-cc-aug.log 2>&1 || log "!! merge failed"
fi
if [ -f ~/merged/spec-cc-aug/config.json ] && bash infra/serve.sh model $NAME 8009 ~/merged/spec-cc-aug 0.25; then
  log "eval $NAME (clean)"
  MODEL_BASE_URL=http://localhost:8009/v1 $PY -m model.baseline_eval --models $NAME --out results/$NAME.json \
    > ~/eval-$NAME.log 2>&1 || log "!! eval $NAME failed"
  $PY -m model.calibrate --label $NAME > ~/calib-$NAME.log 2>&1 || log "!! calibrate $NAME failed"
  for mode in $MODES; do
    log "eval $NAME on $mode"
    JUNCTION_DATA=~/degraded/$mode MODEL_BASE_URL=http://localhost:8009/v1 \
      $PY -m model.baseline_eval --models $NAME --label "$NAME-$mode" --sets heldout_raster --workers 12 \
      > ~/eval-$NAME-$mode.log 2>&1 || log "!! eval $NAME $mode failed"
  done
  tmux kill-window -t serve:$NAME 2>/dev/null; sleep 20
else
  log "!! spec-cc-aug not trained/merged/served (see ~/train-spec-cc-aug.log, ~/vllm-$NAME.log)"
fi

log "serve gemma-ft-cc again"
bash infra/serve.sh model gemma-ft-cc 8008 ~/merged/spec-cc 0.25 || log "!! gemma-ft-cc did not restart"
log "AUG CHAIN DONE"
