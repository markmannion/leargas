#!/usr/bin/env bash
# Run the Léargas backend on the Verda box (as root), next to the model proxy (:8000).
#   ssh <box> "LEARGAS_DOMAIN=<a-b-c-d>.sslip.io bash -s" < infra/serve_backend.sh
# Re-run it to pull new code and restart. The API and Caddy are systemd services:
# they restart after a crash and after a reboot. Caddy gets the https certificate itself
# (ports 80 and 443 must be open). The API is then at https://$LEARGAS_DOMAIN.
# Needs HF_TOKEN and MODEL_API_KEY in ~/.bt_env (from setup_box.sh).
set -euo pipefail
[ -f ~/.bt_env ] && . ~/.bt_env
: "${HF_TOKEN:?export HF_TOKEN (read access to leargas/junction-dataset)}"
: "${LEARGAS_DOMAIN:?set LEARGAS_DOMAIN, the box IP with dashes plus .sslip.io}"
export PATH="$HOME/.local/bin:$PATH"

APP=${LEARGAS_APP:-$HOME/leargas-app}
BRANCH=${LEARGAS_BRANCH:-main}
PORT=${LEARGAS_PORT:-8100}
VENV=$HOME/venv-app

echo "== code ($BRANCH)"
if [ -d "$APP/.git" ]; then
  git -C "$APP" fetch -q origin "$BRANCH"
  git -C "$APP" checkout -q -B "$BRANCH" "origin/$BRANCH"
else
  git clone -q -b "$BRANCH" https://github.com/markmannion/leargas.git "$APP"
fi

echo "== venv"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
[ -d "$VENV" ] || uv venv -q "$VENV" --python 3.11
uv pip install -q --python "$VENV/bin/python" \
  -r "$APP/backend/requirements-dxf.txt" -r "$APP/backend/requirements-ifc.txt" -r "$APP/backend/requirements-sheet.txt" \
  "huggingface_hub[cli]>=0.34"

echo "== api service (leargas-api)"
umask 077
cat > /etc/leargas.env <<EOF
PATH=$VENV/bin:/usr/local/bin:/usr/bin:/bin
HOME=$HOME
HF_TOKEN=$HF_TOKEN
PORT=$PORT
LEARGAS_HOME=$HOME/leargas-data
MODEL_BASE_URL=${MODEL_BASE_URL:-http://127.0.0.1:8000/v1}
MODEL_API_KEY=${MODEL_API_KEY:-}
ELEVENLABS_API_KEY=${ELEVENLABS_API_KEY:-}
EOF
umask 022
cat > /etc/systemd/system/leargas-api.service <<EOF
[Unit]
Description=Leargas API
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$APP
EnvironmentFile=/etc/leargas.env
ExecStart=/bin/bash deploy/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q leargas-api
systemctl restart leargas-api

echo "== caddy (https://$LEARGAS_DOMAIN)"
command -v caddy >/dev/null || { apt-get update -qq; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy >/dev/null; }
cat > /etc/caddy/Caddyfile <<EOF
$LEARGAS_DOMAIN {
	encode gzip
	reverse_proxy localhost:$PORT
}
EOF
systemctl enable -q caddy
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo "waiting for the API (the first run downloads the dataset, ~10 min; log: journalctl -u leargas-api -f)"
until curl -sf "localhost:$PORT/health" >/dev/null; do
  sleep 5
  systemctl is-failed -q leargas-api && { journalctl -u leargas-api -n 30 --no-pager >&2; exit 1; }
done
echo
echo "API ready:  https://$LEARGAS_DOMAIN/health"
echo "On Vercel set  VITE_API_BASE=https://$LEARGAS_DOMAIN  and redeploy."
