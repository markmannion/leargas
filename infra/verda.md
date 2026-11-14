# Verda runbook (M2, M6, M9, M10, M11b)

Fill in the blanks (`____`) as you go: the plan asks for the instance type, region and launch commands here.

## M2 first check: done in advance (Sat 02:00, from docs)

| Question | Answer | Source |
|---|---|---|
| Gemma 4 model IDs | `google/gemma-4-E2B-it`, `google/gemma-4-E4B-it`, `google/gemma-4-26B-A4B-it`, `google/gemma-4-31B-it` (base: drop `-it`). Unsloth mirrors: `unsloth/gemma-4-E4B-it` etc. | HF model card, vLLM recipe |
| vLLM supports it? | **Yes**, day-0 (`Gemma4ForConditionalGeneration`). `setup_box.sh` asserts it; if the stable wheel is too old, use the nightly (command in the script). | vLLM blog + recipes |
| Unsloth supports it? | **Yes**, vision LoRA via `FastVisionModel`. E4B LoRA 16-bit is about 17 GB VRAM. | unsloth.ai/docs/models/gemma-4/train |
| Image budget | `max_soft_tokens` ∈ {70, 140, 280 (default), 560, 1120}. vLLM: `--mm-processor-kwargs '{"max_soft_tokens": 560}'`. **Train and serve with the same value** (default here: 560). | vLLM Gemma 4 recipe |
| Thinking | Off unless the system prompt starts with `<|think|>`. We never send it: answers stay short and fast. | model card |
| Pointing | Native detection output is JSON `{"box_2d": [y1, x1, y2, x2], "label": ...}` on a 0–1000 grid (y first!). `prompt.py` asks for `points` as `[y, x]` in 0–1000 (Gemma's native order) and `parse_output` converts them to C2's 0–1 `[x, y]`. | ai.google.dev Gemma vision docs |
| Expected training loss | Unsloth says E2B/E4B multimodal loss of **13–15 at the start is normal**, so don't panic on step 1. Watch the trend. | Unsloth guide |
| Known Unsloth gotcha | E2B/E4B produce garbage with `use_cache=False` (KV-shared layers) in older Unsloth; fixed upstream. Update Unsloth and sanity-generate after training. | Unsloth guide |
| Fallback | If either check fails: `google/gemma-3-12b-it` (`MODEL_ID=... bash infra/setup_box.sh`) and note it here. | plan |

## ⚠ Billing gotcha: shutdown ≠ stopped

Verda docs: **a shut-down instance keeps billing; only *delete* stops compute charges.** Block volumes you keep are billed per GB even after delete.
So run 2's "automatic instance shutdown" must **delete** the instance. Use `infra/self_delete.py` (Verda Python SDK, `pip install verda`, needs `VERDA_CLIENT_ID`/`VERDA_CLIENT_SECRET` from the dashboard). Put the keys in `~/.bt_env` and dry-run it once at setup, **through tmux the same way M9 will call it**:
```bash
printf 'export VERDA_CLIENT_ID=%s\nexport VERDA_CLIENT_SECRET=%s\n' '<id>' '<secret>' >> ~/.bt_env
tmux new -s deltest "bash -c 'source ~/.bt_env; cd ~/bt; ~/venv-train/bin/python infra/self_delete.py --dry-run; sleep 30'"
```

**Why `~/.bt_env` and absolute venv paths everywhere:** a command started with `tmux new '...'` doesn't inherit your shell's activated venv or `export`s (it gets the tmux *server's* environment, frozen when `serve.sh` first started tmux), and Ubuntu's `~/.bashrc` returns early for non-interactive shells. So inside tmux, bare `python` is the system Python (no unsloth, no verda), and `VERDA_*` are unset. Every tmux command below sources `~/.bt_env` and calls `~/venv-train/bin/python` directly.

Prices: the plan uses $2.81/h (RTX PRO 6000) and $2.00/h (L40S). Verda's pricing page showed different numbers when checked (≈$1.89–3.00/h and ≈$1.37–2.13/h depending on the page and on spot vs on-demand). **Read the actual rate off the dashboard when you launch and write it here**, since H7's cost-per-1,000 numbers use it.

Hostnames, instance IDs and IPs go in `infra/verda.local.md` (gitignored), not here: this repo is public.

| Box | GPU | Rate seen | Region | Hostname | IP | Launched | Deleted |
|---|---|---|---|---|---|---|---|
| dev (base serve + run 1 + run 2) | **A100 80GB** (RTX PRO 6000 out of stock everywhere) | €2.159/h compute (€2.208/h incl. 200 GiB OS vol) | FIN-03 | ____ | ____ | Sat 14 Nov 11:22 | ____ |
| serving | L40S 48GB | ____ | ____ | ____ | ____ | ____ | ____ |
| sweep | RTX PRO 6000 96GB | ____ | ____ | ____ | ____ | ____ | ____ |

## M2: dev box, 09:30

1. Dashboard → Deploy instance → **1× RTX PRO 6000 96GB, on-demand**, Ubuntu + CUDA image, EU region (Finland/Iceland), your SSH key, OS disk ≥ 200 GB.
2. Copy the code over (or `git clone` + checkout `mark`):
   ```bash
   scp -r infra model data <box>:~/bt/
   ```
3. Setup (vLLM and Unsloth go in separate venvs because they pin different torch versions). It downloads Gemma 4 E4B plus only the raster part of the dataset:
   ```bash
   ssh <box>
   cd ~/bt && HF_TOKEN=hf_xxx CUBICASA=0 bash infra/setup_box.sh     # CUBICASA=1 only if Stoa said yes
   ```
4. Serve base + proxy:
   ```bash
   export MODEL_API_KEY=$(openssl rand -hex 24); echo "export MODEL_API_KEY=$MODEL_API_KEY" >> ~/.bt_env
   bash infra/serve.sh base     # gemma-base on :8001 at 35% GPU, leaving ~60 GB for training
   bash infra/serve.sh proxy    # one URL on :8000, routes by "model"
   ```
5. Give Harry `.env` (from `.env.example`): `MODEL_BASE_URL=http://<box-ip>:8000/v1`, `MODEL_API_KEY=...`.
   Open port 8000 in the Verda firewall if needed, or have Harry use `ssh -L 8000:localhost:8000 <box>`.
6. **Done-when check** (from your laptop):
   ```bash
   python -m model.smoke_test --image datasets/junction-dataset/data/cubicasa5k/colorful-10052.png \
       --question "How many windows are shown on this floor plan?" --model gemma-base
   ```
   That prints the parsed answer and confidence (expected 7). It also appends the raw output to `data/model_outputs/raw.jsonl`, which feeds M3's "round-trips 20 real outputs" check.

## M6: run 1 (same box, 14:00)
`data/sft/run1.jsonl` was already built on the laptop and copied over with `data/` (re-run `~/venv-train/bin/python -m model.build_sft --out data/sft/run1.jsonl --n 20000` only if the split changed; `build_sft` has no `--max-soft-tokens` flag, the budget is set in `train_lora`).
```bash
cd ~/bt && source ~/.bt_env
~/venv-train/bin/python -m model.train_lora --check-processor                                   # image tokens ≈ 560?
~/venv-train/bin/python -m model.train_lora --data data/sft/run1.jsonl --run smoke --max-steps 5 --no-push
tmux new -s train "bash -c 'source ~/.bt_env; cd ~/bt; ~/venv-train/bin/python -m model.train_lora --data data/sft/run1.jsonl --run run1 --hub-repo leargas/bt-gemma4-e4b-run1 2>&1 | tee ~/train-run1.log; exec bash'"
```
(`exec bash` keeps the tmux window open after training so you can read the end of the log.)

## M8: serve run 1 as gemma-ft (17:00)
```bash
~/venv-train/bin/python -m model.train_lora --merge-only --run run1 --hub-repo leargas/bt-gemma4-e4b-run1 --push-merged
# writes ~/merged/run1 (16-bit) AND pushes leargas/bt-gemma4-e4b-run1-merged, which M10's L40S pulls
FT_UTIL=0.30 bash infra/serve.sh ft ~/merged/run1
```

## M9: run 2 overnight, self-deleting (18:00)
Build the data first (needs Harry's C4 at `data/points/swiss_points.jsonl`, plus `cubicasa_points.jsonl` if M4b ran):
```bash
~/venv-train/bin/python -m model.build_sft --points --out data/sft/run2.jsonl --n 60000
```
Then:
```bash
tmux new -s train2 "bash -c 'source ~/.bt_env; cd ~/bt; \
  { ~/venv-train/bin/python -m model.train_lora --data data/sft/run2.jsonl --run run2 --hub-repo leargas/bt-gemma4-e4b-run2 \
    && ~/venv-train/bin/python -m model.train_lora --merge-only --run run2 --hub-repo leargas/bt-gemma4-e4b-run2 --push-merged; } 2>&1 | tee ~/train-run2.log; \
  ~/venv-train/bin/hf upload leargas/bt-gemma4-e4b-run2 ~/train-run2.log logs/train-run2.log; \
  ~/venv-train/bin/python infra/self_delete.py --yes'"
```
The `;` before `self_delete` means it deletes even if training crashes. Checkpoints are already on HF, and the training log is uploaded to the run 2 repo first, because the box (and its disk) is gone in the morning.

## M10: L40S serving box (19:00)
Same as M2 steps 1–3 but with `SKIP_TRAIN=1 bash infra/setup_box.sh` (no Unsloth venv), then:
```bash
GPU_UTIL=0.42 bash infra/serve.sh base
FT_UTIL=0.42 bash infra/serve.sh ft leargas/bt-gemma4-e4b-run1-merged
bash infra/serve.sh proxy
```
Two E4B copies at ~16 GB of weights each fit in 48 GB with `MAXLEN=4096`. Update `MODEL_BASE_URL` in `.env` and tell Harry.

## M11b: sweep box (22:00, ~2.5 h, then DELETE it)
```bash
bash infra/serve.sh sweep      # gemma-e2b :8003 (0.18), gemma-26b :8004 (0.72)
ROUTES='gemma-e2b=http://localhost:8003,gemma-26b=http://localhost:8004' bash infra/serve.sh proxy
```
Setup with `SKIP_TRAIN=1`. Then run Harry's `eval/run_eval.py --model gemma-e2b|gemma-26b ...` against it, `python -m model.throughput` for $/1k, then `~/venv-vllm/bin/python infra/self_delete.py --yes` on the sweep box (a `SKIP_TRAIN=1` box has no venv-train; add the `VERDA_*` keys to its `~/.bt_env` first).

## Sunday: tear-down checklist
- [ ] every instance **deleted** (not shut down) in the dashboard
- [ ] every block volume holding dataset copies deleted
- [ ] every HF repo still **private**
