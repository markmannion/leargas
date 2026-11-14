#!/usr/bin/env bash
# Run the Léargas backend on the Verda box, next to the model proxy (:8000), with a public https URL.
#   ssh <box> 'bash -s' < infra/serve_backend.sh     (from your laptop; re-run to pull new code and restart)
# The box clones LEARGAS_BRANCH (default main), so push/merge first.
# Needs HF_TOKEN (in ~/.bt_env from setup_box.sh) and MODEL_API_KEY for the local proxy.
# Prints the https URL to set as VITE_API_BASE on Vercel.
set -euo pipefail
[ -f ~/.bt_env ] && . ~/.bt_env
: "${HF_TOKEN:?export HF_TOKEN (read access to leargas/junction-dataset)}"
export PATH="$HOME/.local/bin:$PATH"

APP=${LEARGAS_APP:-$HOME/leargas-app}
BRANCH=${LEARGAS_BRANCH:-main}
PORT=${LEARGAS_PORT:-8100}
VENV=$HOME/venv-app

echo "== code ($BRANCH)"
if [ -d "$APP/.git" ]; then
  git -C "$APP" fetch -q origin "$BRANCH" && git -C "$APP" checkout -q "$BRANCH" && git -C "$APP" reset -q --hard "origin/$BRANCH"
else
  git clone -q -b "$BRANCH" https://github.com/markmannion/leargas.git "$APP"
fi

echo "== venv"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
[ -d "$VENV" ] || uv venv -q "$VENV" --python 3.11
uv pip install -q --python "$VENV/bin/python" \
  -r "$APP/backend/requirements-dxf.txt" -r "$APP/backend/requirements-ifc.txt" -r "$APP/backend/requirements-sheet.txt" \
  "huggingface_hub[cli]>=0.34"

if ! command -v cloudflared >/dev/null; then
  echo "== cloudflared"
  curl -fsSL -o /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  sudo dpkg -i /tmp/cloudflared.deb >/dev/null
fi

echo "== start (tmux session: app)"
ENVS="PATH=$VENV/bin:\$PATH HF_TOKEN=$HF_TOKEN PORT=$PORT LEARGAS_HOME=$HOME/leargas-data \
MODEL_BASE_URL=${MODEL_BASE_URL:-http://127.0.0.1:8000/v1} MODEL_API_KEY=${MODEL_API_KEY:-} \
ELEVENLABS_API_KEY=${ELEVENLABS_API_KEY:-}"
API="cd $APP && env $ENVS bash deploy/start.sh 2>&1 | tee ~/app-api.log"
if tmux list-windows -t app -F '#W' 2>/dev/null | grep -qx tunnel; then
  # Keep the tunnel (and so its URL); restart only the API with the new code.
  tmux respawn-window -k -t app:api "$API"
else
  tmux kill-session -t app 2>/dev/null || true
  tmux new-session -d -s app -n api "$API"
  tmux new-window -t app -n tunnel "cloudflared tunnel --no-autoupdate --url http://localhost:$PORT 2>&1 | tee ~/app-tunnel.log"
fi
sleep 3

echo "waiting for the API (the first run downloads the dataset, ~10 min)"
until curl -sf "localhost:$PORT/health" >/dev/null; do
  sleep 5
  tmux has-session -t app 2>/dev/null || { echo "API stopped, see ~/app-api.log" >&2; exit 1; }
done
URL=""
for _ in $(seq 30); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' ~/app-tunnel.log 2>/dev/null | head -1) && [ -n "$URL" ] && break
  sleep 2
done
echo
echo "API ready:  $URL/health"
echo "On Vercel set  VITE_API_BASE=$URL  and redeploy."
