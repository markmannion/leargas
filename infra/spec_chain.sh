#!/usr/bin/env bash
# CubiCasa specialist (E4B), unattended (tmux session "spec", log ~/spec.log). Replaces E2B run 2.
#   1. stop the run 2 chain (it is on E2B run 2, which we dropped)
#   2. serve E4B run 2 (gemma-ft-run2 :8006 at 0.25; 0.18 was too small for E4B) -> eval + calibrate -> stop
#   3. start from whichever of run 1 / run 2 has the better held-out ALL
#   4. train spec-cc on data/sft/spec_cc.jsonl (built on the laptop with
#        python -m model.build_sft --out data/sft/spec_cc.jsonl --n 8000 --focus "<CubiCasa windows|doors|
#        sinks|showers+bathtubs, EN+FI>" --focus-frac 0.6 --paraphrase-frac 0.25), 500 steps
#   5. merge -> serve gemma-ft-cc :8008 at 0.25 (left running) -> eval + calibrate
# gemma-base and gemma-ft (run 1) keep serving the demo. The proxy is not restarted and nothing is
# swapped in: compare results/gemma-ft-cc.json with the others (python -m model.report) first.
#
# Start:  tmux new-session -d -s spec "bash ~/bt/infra/spec_chain.sh 2>&1 | tee -a ~/spec.log"
source ~/.bt_env; cd ~/bt
PY=~/venv-train/bin/python
log() { echo "[$(date +%H:%M:%S)] $*"; }

evaluate() {  # served-name port
  log "eval $1"
  MODEL_BASE_URL=http://localhost:$2/v1 $PY -m model.baseline_eval --models "$1" --out "results/$1.json" \
    > ~/eval-$1.log 2>&1 || log "!! eval $1 failed (~/eval-$1.log)"
  $PY -m model.calibrate --label "$1" > ~/calib-$1.log 2>&1 || log "!! calibrate $1 failed"
}

acc() {  # results file -> heldout_raster ALL acc (or -1)
  $PY -c "import json,sys; d=json.load(open(sys.argv[1])); print(next(iter(d.values()))['heldout_raster']['by_source_type']['ALL']['acc'])" "$1" 2>/dev/null || echo -1
}

log "stop the run 2 chain (E2B run 2 dropped for the specialist)"
tmux kill-session -t run2 2>/dev/null
pkill -f "train_lora.*e2b-run2" 2>/dev/null; sleep 30

log "eval E4B run 2"
if bash infra/serve.sh model gemma-ft-run2 8006 ~/merged/run2 0.25; then
  evaluate gemma-ft-run2 8006
else
  log "!! gemma-ft-run2 did not start (~/vllm-gemma-ft-run2.log)"
fi
tmux kill-window -t serve:gemma-ft-run2 2>/dev/null; sleep 20

r1=$(acc results/gemma-ft.json); r2=$(acc results/gemma-ft-run2.json)
INIT=~/merged/run1
$PY -c "import sys; sys.exit(0 if float(sys.argv[2]) >= float(sys.argv[1]) else 1)" "$r1" "$r2" && INIT=~/merged/run2
log "run 1 ALL=$r1, run 2 ALL=$r2 -> specialist starts from $INIT"

log "train spec-cc"
$PY -m model.train_lora --model "$INIT" --data data/sft/spec_cc.jsonl --run spec-cc --max-steps 500 \
  --hub-repo leargas/bt-gemma4-e4b-spec-cc 2>&1 | tee ~/train-spec-cc.log
echo "EXIT=${PIPESTATUS[0]}" >> ~/train-spec-cc.log
if ! grep -q '^EXIT=0' ~/train-spec-cc.log; then
  log "!! training from $INIT failed; retrying from the base E4B"
  rm -rf ~/runs/spec-cc
  $PY -m model.train_lora --model unsloth/gemma-4-E4B-it --data data/sft/spec_cc.jsonl --run spec-cc --max-steps 500 \
    --hub-repo leargas/bt-gemma4-e4b-spec-cc 2>&1 | tee ~/train-spec-cc.log
  echo "EXIT=${PIPESTATUS[0]}" >> ~/train-spec-cc.log
fi
if grep -q '^EXIT=0' ~/train-spec-cc.log; then
  $PY -m model.train_lora --merge-only --run spec-cc > ~/merge-spec-cc.log 2>&1 || log "!! merge spec-cc failed"
  if [ -f ~/merged/spec-cc/config.json ]; then
    bash infra/serve.sh model gemma-ft-cc 8008 ~/merged/spec-cc 0.25 && evaluate gemma-ft-cc 8008
  fi
else
  log "!! spec-cc training failed, see ~/train-spec-cc.log"
fi
log "SPEC CHAIN DONE"
