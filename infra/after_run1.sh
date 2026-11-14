#!/usr/bin/env bash
# Runs unattended on the box once run 1 finishes (tmux window "chain", log ~/chain.log):
#   M8   merge run 1 -> serve gemma-ft (:8002) -> eval + throughput for gemma-ft and gemma-base
#   E2B  fine-tune Gemma 4 E2B with run 1's exact recipe and data -> leargas/bt-gemma4-e2b-run1 (private)
#        -> merge -> eval + throughput for base E2B (gemma-e2b :8003), then the fine-tune (gemma-ft-e2b :8005)
# Leaves serving: gemma-base, gemma-ft, gemma-ft-e2b (~68 of 80 GB). Stop gemma-ft-e2b before run 2.
source ~/.bt_env; cd ~/bt
export MODEL_BASE_URL=http://localhost:8000/v1 MODEL_USD_PER_HOUR=2.38
PY=~/venv-train/bin/python
E2B=unsloth/gemma-4-E2B-it
log() { echo "[$(date +%H:%M:%S)] $*"; }

evaluate() {  # served-name
  log "eval $1"
  $PY -m model.baseline_eval --models "$1" --out "results/$1.json" > ~/eval-$1.log 2>&1 || log "!! eval $1 failed (~/eval-$1.log)"
  $PY -m model.calibrate --label "$1" > ~/calib-$1.log 2>&1 || log "!! calibrate $1 failed"
  $PY -m model.throughput --model "$1" --gpu "A100 80GB (shared)" --n 128 --workers 32 > ~/tput-$1.log 2>&1 \
    || log "!! throughput $1 failed"
}

log "waiting for run 1"
until grep -q '^EXIT=' ~/train-run1.log; do sleep 30; done
code=$(grep '^EXIT=' ~/train-run1.log | tail -1 | cut -d= -f2)
if [ "$code" != 0 ]; then log "run 1 EXIT=$code: stopping, nothing else started"; exit 1; fi

log "M8: merge run 1"
$PY -m model.train_lora --merge-only --run run1 > ~/merge-run1.log 2>&1 || log "!! merge run1 failed (~/merge-run1.log)"
if [ -f ~/merged/run1/config.json ]; then
  FT_UTIL=0.30 bash infra/serve.sh ft ~/merged/run1 && evaluate gemma-ft
fi
# gemma-base throughput while the box is quiet (its accuracy is already in results/baseline.json)
$PY -m model.throughput --model gemma-base --gpu "A100 80GB (shared)" --n 128 --workers 32 > ~/tput-gemma-base.log 2>&1

log "E2B: processor check + train"
$PY -m model.train_lora --check-processor --model $E2B > ~/check-e2b.log 2>&1
$PY -m model.train_lora --model $E2B --data data/sft/run1.jsonl --run e2b-run1 \
    --hub-repo leargas/bt-gemma4-e2b-run1 2>&1 | tee ~/train-e2b-run1.log
echo "EXIT=${PIPESTATUS[0]}" >> ~/train-e2b-run1.log

log "E2B base: serve + eval, then stop it (no room for both E2Bs next to run 2)"
bash infra/serve.sh model gemma-e2b 8003 $E2B 0.18 && evaluate gemma-e2b
tmux kill-window -t serve:gemma-e2b 2>/dev/null; sleep 15

if grep -q '^EXIT=0' ~/train-e2b-run1.log; then
  log "E2B fine-tune: merge + serve + eval"
  $PY -m model.train_lora --merge-only --run e2b-run1 > ~/merge-e2b.log 2>&1 || log "!! merge e2b failed"
  [ -f ~/merged/e2b-run1/config.json ] && bash infra/serve.sh model gemma-ft-e2b 8005 ~/merged/e2b-run1 0.18 \
    && evaluate gemma-ft-e2b
else
  log "!! E2B training failed, see ~/train-e2b-run1.log"
fi

log "upload merged weights (private) for an L40S / sweep box: CPU + network only, no re-merge on the GPU"
for r in run1:e4b e2b-run1:e2b; do
  d=~/merged/${r%%:*}; repo=leargas/bt-gemma4-${r##*:}-run1-merged
  [ -f $d/config.json ] && { ~/venv-train/bin/hf upload "$repo" "$d" . --private > ~/upload-${r%%:*}.log 2>&1 \
    && log "uploaded $repo" || log "!! upload $repo failed"; }
done
log "CHAIN DONE"
