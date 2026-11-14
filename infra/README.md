# infra/: the GPU server

One rented server runs the whole hosted app: the vision models, the model proxy and the backend.
It is a Verda instance with one A100 80 GB. The frontend runs separately on Vercel.

```
 browser ──► Vercel (frontend) ──► https://<server>.sslip.io ──► Caddy ──► backend :8100 (systemd)
                                                                              │
                                                     model proxy :8000 ◄──────┘
                                                        ├─► gemma-base   :8001  (vLLM, 0.35 of the GPU)
                                                        ├─► gemma-ft     :8002  (vLLM, 0.30)
                                                        └─► gemma-ft-cc  :8008  (vLLM, 0.25)
```

## Files

| File | What it does |
|---|---|
| `setup_box.sh` | First-time setup: the vLLM and training environments, model weights, the dataset, `~/.bt_env` |
| `serve.sh` | Starts one vLLM process per model in the tmux session `serve` (`base`, `ft <weights>`, `model <name> <port> <weights> [gpu share]`, `proxy`) |
| `model_proxy.py` | One address and one API key for all models; routes by the request's `model` field |
| `start_models.sh` | Starts any model or the proxy that is not answering. Installed as an `@reboot` cron job (`--install`), so the models come back after a reboot |
| `serve_backend.sh` | Installs or updates the backend from `main`, writes `/etc/leargas.env`, and runs the API and Caddy (https) as systemd services |
| `after_run1.sh`, `run2_chain.sh`, `spec_chain.sh`, `aug_chain.sh`, `soup_chain.sh`, `robust_chain.sh`, `super_robust_chain.sh` | Unattended experiments: train, merge, serve, score and calibrate, then restore the served models |
| `self_delete.py` | Deletes the instance through the Verda API (shutting down does not stop billing) |
| `verda.md` | The setup log and the original runbook |

## Common tasks

Deploy or update the backend (from a laptop, at the repository root):

```bash
ssh <server> "LEARGAS_DOMAIN=<server-ip-with-dashes>.sslip.io bash -s" < infra/serve_backend.sh
```

Check what is running (on the server):

```bash
tmux list-windows -t serve                 # the model windows and the proxy
systemctl status leargas-api caddy         # the backend and https
journalctl -u leargas-api -f               # backend log
bash ~/bt/infra/start_models.sh            # start anything that is down (safe to run at any time)
```

Swap the weights behind a served name (for example, back to run 1 as `gemma-ft`):

```bash
tmux kill-window -t serve:gemma-ft
FT_UTIL=0.30 bash ~/bt/infra/serve.sh ft ~/merged/run1
# then redeploy the backend with LEARGAS_GEMMA_FT_LABEL=gemma-ft so it uses run 1's calibration
```

Copy results to a laptop: `scp 'bt:bt/results/*.json' results/ && scp -r bt:bt/results/preds results/`.

## Things to know

- **Billing:** Verda bills a stopped instance. Only deleting it stops the charges. Delete it after judging.
- **Code on the server is copied, not pulled:** `~/bt` (models and experiments) is updated with `scp`. The backend
  in `~/leargas-app` is updated by `serve_backend.sh` from `main`.
- **tmux does not inherit your shell:** commands started in tmux get no venv and no exports. Always
  `source ~/.bt_env` and call `~/venv-train/bin/python` or `~/venv-vllm/bin/...` by full path.
- **Train and serve with the same image budget:** 560 image tokens (`SOFT_TOKENS` in `serve.sh`).
- **No secrets in git:** the API keys live in `~/.bt_env` and `/etc/leargas.env` on the server only.
