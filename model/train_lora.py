"""M6 / M9: LoRA fine-tune of Gemma 4 E4B on the SFT JSONL (Unsloth), checkpoints to a PRIVATE HF repo.

UNTESTED: written Sat 03:00 without a GPU. Run the two checks first on the box (2 min):

  python -m model.train_lora --check-processor                     # image token count, chat markers
  python -m model.train_lora --data data/sft/run1.jsonl --run smoke --max-steps 5 --no-push

Run 1 (M6):
  python -m model.train_lora --data data/sft/run1.jsonl --run run1 --hub-repo leargas/bt-gemma4-e4b-run1
Serve it (M8):
  python -m model.train_lora --merge-only --run run1 --hub-repo leargas/bt-gemma4-e4b-run1   # -> ~/merged/run1
Run 2 (M9): same with --data data/sft/run2.jsonl --run run2 --points  (only the data changes)

Notes from the Unsloth Gemma 4 guide:
- E2B/E4B multimodal loss starting at 13-15 is normal. Watch the trend, not the value.
- E4B 16-bit LoRA needs ~17 GB; the box shares the GPU with vLLM at 35%, so there's plenty of room.
- Gemma 4 E-models need the KV cache at inference; after training we generate on 8 val rows and
  parse them with prompt.parse_output, to catch the known "garbage output" failure early.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from model.common import abs_path, load_jsonl  # noqa: E402
from model.prompt import MAX_SIDE, MAX_SOFT_TOKENS, build_train_messages, parse_output  # noqa: E402

DEFAULT_MODEL = "unsloth/gemma-4-E4B-it"


def set_image_budget(processor, soft_tokens: int) -> str:
    """Make the HF processor use the same visual token budget as vLLM (--mm-processor-kwargs max_soft_tokens)."""
    ip = getattr(processor, "image_processor", processor)
    done = []
    for attr in ("max_soft_tokens", "max_num_soft_tokens", "image_seq_length", "num_soft_tokens"):
        for obj in (ip, processor):
            if hasattr(obj, attr):
                setattr(obj, attr, soft_tokens)
                done.append(f"{type(obj).__name__}.{attr}")
    return ", ".join(done) or "!! no budget attribute found; check --check-processor output and set it by hand"


class SFTData:
    """Lazy dataset: loads and resizes each image when the collator asks for it (20k images won't fit in RAM)."""

    def __init__(self, rows: list[dict], with_points_prompt: bool):
        self.rows = rows
        self.with_points = with_points_prompt

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        return {"messages": build_train_messages(abs_path(r["image"]), r["question"], r["target"],
                                                 with_points=self.with_points, max_side=MAX_SIDE)}


def turn_markers(processor) -> tuple[str, str]:
    """Find the chat template's user-turn and model-turn prefixes by rendering, so the collator can
    mask everything except the assistant reply (train on responses only)."""
    tok = getattr(processor, "tokenizer", processor)
    user = [{"role": "user", "content": [{"type": "text", "text": "XQX"}]}]
    with_gen = processor.apply_chat_template(user, tokenize=False, add_generation_prompt=True)
    without = processor.apply_chat_template(user, tokenize=False, add_generation_prompt=False)
    response_part = with_gen[len(without):] if with_gen.startswith(without) else None
    pre = without.split("XQX")[0]
    bos = getattr(tok, "bos_token", "") or ""
    instruction_part = pre[len(bos):] if pre.startswith(bos) else pre
    return instruction_part, response_part


def check_processor(model_id: str, soft_tokens: int) -> None:
    from transformers import AutoProcessor

    proc = AutoProcessor.from_pretrained(model_id)
    print("budget set via:", set_image_budget(proc, soft_tokens))
    ins, resp = turn_markers(proc)
    print("instruction_part:", repr(ins), " response_part:", repr(resp))
    rows = load_jsonl(REPO / "data" / "sft" / "run1.jsonl")[:3]
    for r in rows:
        msgs = build_train_messages(abs_path(r["image"]), r["question"], r["target"])
        text = proc.apply_chat_template(msgs, tokenize=False)
        img = msgs[1]["content"][0]["image"]
        enc = proc(text=[text], images=[[img]], return_tensors="pt")
        n_img_tok = int((enc["input_ids"] == getattr(proc, "image_token_id", -1)).sum()) if hasattr(proc, "image_token_id") else "?"
        print(f"{r['image']}: input {img.size} -> pixel_values {tuple(enc['pixel_values'].shape)}, "
              f"image tokens {n_img_tok}, total tokens {enc['input_ids'].shape[1]}")
    print("rendered sample:")
    print(text[:600])


def train(a) -> None:
    from unsloth import FastVisionModel, get_chat_template  # noqa: I001  (unsloth must import first)
    from unsloth.trainer import UnslothVisionDataCollator
    from trl import SFTConfig, SFTTrainer

    rows = load_jsonl(Path(a.data))
    val_path = Path(a.data).with_name(Path(a.data).stem + "_val.jsonl")
    val_rows = load_jsonl(val_path) if val_path.exists() else []
    with_points = any(r.get("has_points") for r in rows) or a.points
    print(f"train rows {len(rows)}  val rows {len(val_rows)}  points prompt: {with_points}")

    model, processor = FastVisionModel.from_pretrained(a.model, load_in_4bit=a.load_in_4bit,
                                                       use_gradient_checkpointing="unsloth")
    processor = get_chat_template(processor, "gemma-4")  # non-thinking template
    print("image budget:", set_image_budget(processor, a.max_soft_tokens))
    model = FastVisionModel.get_peft_model(
        model,
        finetune_vision_layers=a.tune_vision, finetune_language_layers=True,
        finetune_attention_modules=True, finetune_mlp_modules=True,
        r=a.r, lora_alpha=a.r, lora_dropout=0, bias="none", random_state=3407,
        use_rslora=False, loftq_config=None, target_modules="all-linear",
    )
    FastVisionModel.for_training(model)

    ins, resp = turn_markers(processor)
    try:
        collator = UnslothVisionDataCollator(model, processor, train_on_responses_only=True,
                                             instruction_part=ins, response_part=resp)
        print(f"masking prompt tokens (instruction={ins!r}, response={resp!r})")
    except TypeError:
        collator = UnslothVisionDataCollator(model, processor)
        print("!! this Unsloth collator can't mask prompts; training on full sequences")

    out_dir = Path.home() / "runs" / a.run
    push = not a.no_push
    cfg = SFTConfig(
        output_dir=str(out_dir),
        per_device_train_batch_size=a.batch, gradient_accumulation_steps=a.grad_accum,
        num_train_epochs=a.epochs, max_steps=a.max_steps if a.max_steps else -1,
        learning_rate=a.lr, lr_scheduler_type="cosine", warmup_ratio=0.03, weight_decay=0.001,
        max_grad_norm=0.3, optim="adamw_8bit", seed=3407, bf16=True,
        logging_steps=10, save_steps=a.save_steps, save_total_limit=3,
        report_to="none", dataloader_num_workers=4,
        remove_unused_columns=False, dataset_text_field="", dataset_kwargs={"skip_prepare_dataset": True},
        max_length=a.max_length,
        push_to_hub=push, hub_model_id=a.hub_repo if push else None,
        hub_strategy="every_save", hub_private_repo=True,
    )
    trainer = SFTTrainer(model=model, train_dataset=SFTData(rows, with_points),
                         processing_class=processor.tokenizer, data_collator=collator, args=cfg)
    t0 = time.time()
    trainer.train(resume_from_checkpoint=a.resume or None)
    print(f"train done in {(time.time() - t0) / 60:.1f} min")

    model.save_pretrained(out_dir / "adapter")
    processor.save_pretrained(out_dir / "adapter")
    if push:
        model.push_to_hub(a.hub_repo, private=True)
        processor.push_to_hub(a.hub_repo, private=True)
        print(f"adapter pushed to {a.hub_repo} (private)")

    sanity_generate(model, processor, val_rows or rows, with_points)


def sanity_generate(model, processor, rows, with_points, n: int = 8) -> None:
    """Greedy-generate on a few rows and parse: catches broken outputs before serving."""
    from unsloth import FastVisionModel

    FastVisionModel.for_inference(model)
    ok = correct = 0
    for r in random.Random(0).sample(rows, min(n, len(rows))):
        msgs = build_train_messages(abs_path(r["image"]), r["question"], "", with_points=with_points)[:2]
        text = processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        enc = processor(text=[text], images=[[msgs[1]["content"][0]["image"]]], return_tensors="pt").to(model.device)
        out = model.generate(**enc, max_new_tokens=128, do_sample=False, use_cache=True)
        reply = getattr(processor, "tokenizer", processor).decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
        p = parse_output(reply)
        ok += p["ok"]
        correct += p["answer"] == r.get("answer")
        print(f"  gold={r.get('answer')!r:>8}  pred={p['answer']!r:>8}  reply={reply[:80]!r}")
    print(f"sanity: parsed {ok}/{n}, exact {correct}/{n}")


def merge(a) -> None:
    """Base + adapter -> 16-bit merged weights that vLLM serves as gemma-ft."""
    from unsloth import FastVisionModel

    local = Path.home() / "runs" / a.run / "adapter"
    # Prefer the local adapter (no download, and it's exactly what just finished); fall back to HF.
    src = a.adapter or (str(local) if local.exists() else None) or a.hub_repo
    if not src:
        sys.exit(f"no adapter: {local} missing and no --hub-repo/--adapter given")
    model, processor = FastVisionModel.from_pretrained(src, load_in_4bit=False)
    out = Path(a.merged_dir or Path.home() / "merged" / a.run)
    model.save_pretrained_merged(str(out), processor, save_method="merged_16bit")
    print(f"merged -> {out}")
    if a.push_merged:
        if not a.hub_repo:
            sys.exit("--push-merged needs --hub-repo (the merged repo is <hub-repo>-merged)")
        repo = f"{a.hub_repo}-merged"
        model.push_to_hub_merged(repo, processor, save_method="merged_16bit", private=True)
        print(f"merged pushed to {repo} (private)")
    json.dump({"adapter": src, "merged": str(out), "time": time.strftime("%F %T")},
              open(out / "bt_merge_info.json", "w"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(REPO / "data" / "sft" / "run1.jsonl"))
    ap.add_argument("--run", default="run1")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--hub-repo", default=None, help="PRIVATE HF model repo, e.g. leargas/bt-gemma4-e4b-run1")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--epochs", type=float, default=1)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--save-steps", type=int, default=500)
    ap.add_argument("--max-length", type=int, default=2048)
    ap.add_argument("--max-soft-tokens", type=int, default=MAX_SOFT_TOKENS)
    ap.add_argument("--tune-vision", action="store_true", help="also LoRA the vision tower (Unsloth: start without)")
    ap.add_argument("--load-in-4bit", action="store_true")
    ap.add_argument("--points", action="store_true", help="force the points prompt (auto-on if the data has points)")
    ap.add_argument("--resume", default="", help="checkpoint dir to resume from")
    ap.add_argument("--check-processor", action="store_true")
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--adapter", default=None, help="adapter dir or repo for --merge-only")
    ap.add_argument("--merged-dir", default=None)
    ap.add_argument("--push-merged", action="store_true")
    a = ap.parse_args()

    if a.check_processor:
        check_processor(a.model, a.max_soft_tokens)
    elif a.merge_only:
        merge(a)
    else:
        if not a.no_push and not a.hub_repo:
            sys.exit("--hub-repo is required (checkpoints must land on HF), or pass --no-push for smoke runs")
        if not a.no_push and not os.environ.get("HF_TOKEN"):
            sys.exit("HF_TOKEN not set")
        train(a)


if __name__ == "__main__":
    main()
