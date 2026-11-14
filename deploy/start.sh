#!/usr/bin/env bash
# Container entrypoint: fetch the private dataset (first boot only), build the query templates, start the API.
# Secrets: HF_TOKEN (read access to leargas/junction-dataset), optional MODEL_BASE_URL, MODEL_API_KEY, ELEVENLABS_API_KEY.
set -euo pipefail
cd "$(dirname "$0")/.."

# /data is the persistent disk on a Space (if enabled). Without it the dataset is fetched on every restart.
if [ -z "${LEARGAS_HOME:-}" ]; then
  if [ -d /data ] && [ -w /data ]; then LEARGAS_HOME=/data; else LEARGAS_HOME="$HOME/leargas-data"; fi
fi
DATASET_REPO="${LEARGAS_DATASET_REPO:-leargas/junction-dataset}"
export LEARGAS_DATA_ROOT="${LEARGAS_DATA_ROOT:-$LEARGAS_HOME/junction-dataset}"
export JUNCTION_DATA="$LEARGAS_DATA_ROOT"
export LEARGAS_QUESTIONS="${LEARGAS_QUESTIONS:-$LEARGAS_DATA_ROOT/questions.jsonl}"
export LEARGAS_QUERY_TEMPLATES="${LEARGAS_QUERY_TEMPLATES:-$LEARGAS_HOME/query_templates.json}"
export LEARGAS_SHEET_CACHE="${LEARGAS_SHEET_CACHE:-$LEARGAS_HOME/sheet_cache}"
mkdir -p "$LEARGAS_DATA_ROOT" "$LEARGAS_SHEET_CACHE"

if [ ! -f "$LEARGAS_QUESTIONS" ]; then
  if [ -z "${HF_TOKEN:-}" ]; then
    echo "HF_TOKEN is not set: cannot download $DATASET_REPO" >&2
    exit 1
  fi
  echo "Downloading $DATASET_REPO to $LEARGAS_DATA_ROOT"
  # LEARGAS_DATASET_INCLUDE: space-separated patterns to fetch only part of the 12 GB dataset.
  INCLUDE=()
  [ -n "${LEARGAS_DATASET_INCLUDE:-}" ] && read -r -a INCLUDE <<< "$LEARGAS_DATASET_INCLUDE" && INCLUDE=(--include "${INCLUDE[@]}")
  hf download "$DATASET_REPO" --repo-type=dataset --local-dir "$LEARGAS_DATA_ROOT" "${INCLUDE[@]}"
fi

if [ ! -f "$LEARGAS_QUERY_TEMPLATES" ]; then
  (cd backend && python -m app.query.build_templates --questions "$LEARGAS_QUESTIONS" --out "$LEARGAS_QUERY_TEMPLATES")
fi

exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port "${PORT:-7860}"
