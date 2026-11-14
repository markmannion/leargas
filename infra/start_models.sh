#!/usr/bin/env bash
# Bring the served models and the model proxy back after a reboot (the backend and Caddy are
# systemd services and come back on their own; vLLM and the proxy run in tmux and do not).
# Starts only what is not already answering, so it is safe to run at any time.
#
# Installed as a root cron job by itself:  bash ~/bt/infra/start_models.sh --install
#   -> @reboot sleep 60 && bash ~/bt/infra/start_models.sh >> ~/start_models.log 2>&1
#
# What is served (Sat 14 Nov 23:00): gemma-ft = augmented model, gemma-ft-cc = CubiCasa specialist,
# gemma-base = base E4B. GPU shares 0.35 + 0.30 + 0.25 of the A100.
set -u
if [ "${1:-}" = "--install" ]; then
  line='@reboot sleep 60 && bash ~/bt/infra/start_models.sh >> ~/start_models.log 2>&1'
  ( crontab -l 2>/dev/null | grep -v 'infra/start_models.sh'; echo "$line" ) | crontab -
  crontab -l | grep start_models
  exit 0
fi

source ~/.bt_env
cd ~/bt
log() { echo "[$(date '+%F %T')] $*"; }
up() { curl -sf -m 5 -H "Authorization: Bearer $MODEL_API_KEY" "localhost:$1/v1/models" >/dev/null; }

log "start_models: checking"
# name port weights gpu-share, in start order (each vLLM reserves its share of the GPU at start)
while read -r name port weights util; do
  if up "$port"; then
    log "$name :$port already up"
  else
    tmux kill-window -t "serve:$name" 2>/dev/null
    log "starting $name :$port ($weights)"
    bash infra/serve.sh model "$name" "$port" "$weights" "$util" || log "!! $name did not come up (~/vllm-$name.log)"
  fi
done <<EOF
gemma-base 8001 google/gemma-4-E4B-it 0.35
gemma-ft 8002 $HOME/merged/spec-cc-aug 0.30
gemma-ft-cc 8008 $HOME/merged/spec-cc 0.25
EOF

if curl -s -m 5 -o /dev/null localhost:8000; then
  log "proxy :8000 already up"
else
  tmux kill-window -t serve:proxy 2>/dev/null
  log "starting the proxy :8000"
  bash infra/serve.sh proxy
fi
log "start_models: done"
