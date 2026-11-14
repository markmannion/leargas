#!/usr/bin/env bash
# Upload the committed backend code to a Hugging Face Docker Space.
# Usage: deploy/push_space.sh <owner>/<space-name>   (needs `hf auth login` with write access)
# The Space README (with the Space config header) is generated here, so the repo keeps one README.
set -euo pipefail
SPACE="${1:?usage: deploy/push_space.sh <owner>/<space-name>}"
cd "$(git rev-parse --show-toplevel)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git archive HEAD Dockerfile .dockerignore backend model contracts deploy | tar -x -C "$TMP"
cat > "$TMP/README.md" <<'EOF'
---
title: Leargas API
emoji: 📐
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

Backend API for Léargas (Junction 2026, Stoa track).
EOF

hf upload "$SPACE" "$TMP" . --repo-type=space --delete="*" --commit-message "Deploy $(git rev-parse --short HEAD)"
echo "Pushed to https://huggingface.co/spaces/$SPACE"
