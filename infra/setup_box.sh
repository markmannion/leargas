#!/usr/bin/env bash
# M2: one-shot setup for a fresh Verda GPU box (Ubuntu + CUDA image).
#   scp -r infra model data/splits <box>:~/bt/   (or git clone the repo on the box)
#   ssh <box> 'cd ~/bt && HF_TOKEN=hf_xxx bash infra/setup_box.sh'
#
# vLLM and Unsloth each pin their own torch, so they get SEPARATE venvs:
#   ~/venv-vllm   -> serving (vllm serve ...), the model proxy
#   ~/venv-train  -> unsloth / trl training, build_sft
set -euo pipefail

: "${HF_TOKEN:?export HF_TOKEN (read access to the leargas org; write for checkpoint pushes)}"
WORK=${WORK:-$HOME/bt}
DATA=${JUNCTION_DATA:-$HOME/junction-dataset}
MODEL_ID=${MODEL_ID:-google/gemma-4-E4B-it}

sudo apt-get update -qq && sudo apt-get install -y -qq tmux htop nvtop git-lfs jq >/dev/null || true
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv

echo "== venv-vllm"
[ -d ~/venv-vllm ] || uv venv ~/venv-vllm --python 3.12
uv pip install --python ~/venv-vllm/bin/python -U vllm "huggingface_hub[hf_transfer]" fastapi uvicorn httpx openai pillow
~/venv-vllm/bin/python -c "import vllm; print('vllm', vllm.__version__)"
# Gemma 4 needs a vLLM release with Gemma4ForConditionalGeneration. If the import below fails,
# install the nightly:  uv pip install --python ~/venv-vllm/bin/python -U vllm --pre --extra-index-url https://wheels.vllm.ai/nightly/cu129
~/venv-vllm/bin/python - <<'EOF'
from vllm import ModelRegistry
archs = ModelRegistry.get_supported_archs()
ok = any("Gemma4" in a for a in archs)
print("Gemma4 supported by this vLLM:", ok)
if not ok:
    raise SystemExit("!! vLLM too old for Gemma 4: install nightly (see comment above) or fall back to google/gemma-3-12b-it")
EOF

if [ "${SKIP_TRAIN:-0}" != "1" ]; then  # SKIP_TRAIN=1 on serving-only boxes (L40S, sweep)
  echo "== venv-train"
  [ -d ~/venv-train ] || uv venv ~/venv-train --python 3.12
  uv pip install --python ~/venv-train/bin/python -U unsloth trl datasets "huggingface_hub[hf_transfer]" pillow verda
  ~/venv-train/bin/python -c "import unsloth, trl, transformers; print('unsloth', unsloth.__version__, 'trl', trl.__version__, 'transformers', transformers.__version__)"
fi
uv pip install --python ~/venv-vllm/bin/python verda   # for infra/self_delete.py

echo "== HF login + downloads"
export HF_HUB_ENABLE_HF_TRANSFER=1
export HF_TOKEN  # the hf CLI, huggingface_hub and push_to_hub all read HF_TOKEN from the environment
~/venv-vllm/bin/hf download "$MODEL_ID" &
# Only the raster sources are needed on the box (CubiCasa PNGs + swiss PNGs), ~ a few GB, not the full 12 GB.
~/venv-vllm/bin/hf download leargas/junction-dataset --repo-type=dataset --local-dir "$DATA" \
  --include "questions.jsonl" "README.md" "data/cubicasa5k/*" "data/swiss_dwellings/*.png" &
wait
# ~/.bt_env is what tmux jobs source (they don't get your shell's exports, and Ubuntu's .bashrc
# exits early when non-interactive). Interactive shells load it too via .bashrc.
grep -q JUNCTION_DATA ~/.bt_env 2>/dev/null || printf 'export JUNCTION_DATA=%s\nexport HF_TOKEN=%s\nexport HF_HUB_ENABLE_HF_TRANSFER=1\n' "$DATA" "$HF_TOKEN" >> ~/.bt_env
chmod 600 ~/.bt_env
grep -q bt_env ~/.bashrc || echo '[ -f ~/.bt_env ] && . ~/.bt_env' >> ~/.bashrc
du -sh "$DATA"

if [ "${CUBICASA:-0}" = "1" ]; then
  # Only if Stoa said yes at kickoff. Zenodo record of CubiCasa5k (cubicasa5k.zip, ~5.4 GB).
  mkdir -p ~/cubicasa && (cd ~/cubicasa && nohup wget -q -c "https://zenodo.org/records/2613548/files/cubicasa5k.zip" -O cubicasa5k.zip && unzip -q cubicasa5k.zip) > ~/cubicasa/dl.log 2>&1 &
  echo "CubiCasa5k download started in background (~/cubicasa/dl.log)"
fi

echo "setup done. Next: bash infra/serve.sh base"
