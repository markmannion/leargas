#!/usr/bin/env bash
# Run 2 for both Gemma models, unattended (tmux window "run2", log ~/run2.log).
# Same recipe as run 1; only the data changes: data/sft/run2.jsonl, built on the laptop with
#   python -m model.build_sft --out data/sft/run2.jsonl --n 20000 \
#       --reweight results/preds/gemma-ft__heldout_raster.jsonl --paraphrase-frac 0.25
# (weak families oversampled, a quarter of the English questions reworded, Stoa-style abstain rows).
#
#   1. stop gemma-ft-e2b (run 1's E2B; the router does not use it) to make room
#   2. E4B run 2 -> leargas/bt-gemma4-e4b-run2 (private) -> merge -> serve gemma-ft-run2 :8006 -> eval + calibrate
#   3. stop gemma-ft-run2; E2B run 2 -> leargas/bt-gemma4-e2b-run2 -> merge -> serve gemma-ft-e2b-run2 :8007
#      -> eval + calibrate
# gemma-base and gemma-ft (run 1) keep serving the demo the whole time. Nothing is swapped in
# automatically: compare results/gemma-ft-run2.json with results/gemma-ft.json first (model.report).
#
# Start:  tmux new-window -t serve -n run2 "bash ~/bt/infra/run2_chain.sh 2>&1 | tee -a ~/run2.log"
source ~/.bt_env; cd ~/bt
PY=~/venv-train/bin/python
E2B=unsloth/gemma-4-E2B-it
log() { echo "[$(date +%H:%M:%S)] $*"; }

evaluate() {  # served-name port: talk to that vLLM directly, so the proxy needs no new route
  log "eval $1"
  MODEL_BASE_URL=http://localhost:$2/v1 $PY -m model.baseline_eval --models "$1" --out "results/$1.json" \
    > ~/eval-$1.log 2>&1 || log "!! eval $1 failed (~/eval-$1.log)"
  $PY -m model.calibrate --label "$1" > ~/calib-$1.log 2>&1 || log "!! calibrate $1 failed"
}

train() {  # run-name model hub-repo
  log "train $1 ($2)"
  $PY -m model.train_lora --model "$2" --data data/sft/run2.jsonl --run "$1" --hub-repo "$3" 2>&1 | tee ~/train-$1.log
  echo "EXIT=${PIPESTATUS[0]}" >> ~/train-$1.log
  grep -q '^EXIT=0' ~/train-$1.log
}

log "check: every run 2 image exists on the box"
$PY - <<'EOF' || { log "!! missing images: stopping before any change"; exit 1; }
import json, sys
sys.path.insert(0, ".")
from model.common import abs_path
rows = [json.loads(l) for l in open("data/sft/run2.jsonl", encoding="utf-8")]
missing = [r["image"] for r in rows if not abs_path(r["image"]).exists()]
print(f"{len(rows)} rows, {len(missing)} missing images", missing[:3])
sys.exit(1 if missing else 0)
EOF

log "stop gemma-ft-e2b to free GPU memory"
tmux kill-window -t serve:gemma-ft-e2b 2>/dev/null; sleep 20

if train run2 unsloth/gemma-4-E4B-it leargas/bt-gemma4-e4b-run2; then
  $PY -m model.train_lora --merge-only --run run2 > ~/merge-run2.log 2>&1 || log "!! merge run2 failed"
  if [ -f ~/merged/run2/config.json ]; then
    bash infra/serve.sh model gemma-ft-run2 8006 ~/merged/run2 0.18 && evaluate gemma-ft-run2 8006
    tmux kill-window -t serve:gemma-ft-run2 2>/dev/null; sleep 20
  fi
else
  log "!! E4B run 2 failed, see ~/train-run2.log"
fi

if train e2b-run2 $E2B leargas/bt-gemma4-e2b-run2; then
  $PY -m model.train_lora --merge-only --run e2b-run2 > ~/merge-e2b-run2.log 2>&1 || log "!! merge e2b-run2 failed"
  [ -f ~/merged/e2b-run2/config.json ] && bash infra/serve.sh model gemma-ft-e2b-run2 8007 ~/merged/e2b-run2 0.12 \
    && evaluate gemma-ft-e2b-run2 8007
else
  log "!! E2B run 2 failed, see ~/train-e2b-run2.log"
fi
log "RUN2 CHAIN DONE"
