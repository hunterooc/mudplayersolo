#!/usr/bin/env python3
"""
Train WM on traces: load traces.jsonl, build (input, target) from mh_state, action, mud_output, vh_summary.
Filter/weight by vh_score. Fine-tune Mistral-7B with LoRA.
Modes: next_line (LM loss on MUD snippet) or outcome_summary (instruction tuning with vh_summary).
Uses a small validation split (eval_fraction) and early stopping when eval loss does not improve for
early_stopping_patience consecutive epochs. Set eval_fraction to 0 to disable.
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from src.config import load_config, resolve_path, PROJECT_ROOT


def load_traces(glob_pattern: str = None):
    cfg = load_config()
    pattern = glob_pattern or cfg.get("training", {}).get("trace_glob", "data/logs/traces*.jsonl")
    if not Path(pattern).is_absolute():
        pattern = str(PROJECT_ROOT / pattern)
    files = glob.glob(pattern)
    traces = []
    for f in files:
        with open(f) as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return traces


def build_dataset(traces, mode: str = "outcome_summary", vh_score_min: int = 1, weight_by_vh_score: bool = True):
    """Yield (input_text, target_text, weight). Matches WM prompt: mh_state, recent_buffer, action.

    vh_score rates *prediction* accuracy (1–5), not outcome quality. For WM training we learn
    (state, action) -> actual outcome; traces where the prediction was poor but the outcome was
    fine (e.g. WM blank, VH score=1) are high-value. Use vh_score_min=1 so those are kept and
    downweighted via weight_by_vh_score; vh_score_min>=2 drops them and hurts cold WM learning.
    """
    for t in traces:
        vh_score = t.get("vh_score", 3)
        if vh_score < vh_score_min:
            continue
        mh_state = t.get("mh_state", "")
        action = t.get("action", "")
        recent_buffer = t.get("recent_buffer", "") or "(none)"
        mud_output = t.get("mud_output", "")
        next_line = t.get("next_line", "")
        outcome_summary = t.get("outcome_summary", t.get("vh_summary", ""))
        weight = float(vh_score) / 5.0 if weight_by_vh_score else 1.0
        buf_block = f"\n\nRecent MUD output (last lines before action; if none, \"(none)\"):\n{recent_buffer}"
        if mode == "next_line":
            # Predict first substantive line of MUD output (use trace next_line when present)
            if not next_line and mud_output.strip():
                first_line = mud_output.strip().split("\n")[0].strip()
                next_line = first_line or mud_output[:500]
            target = (next_line or mud_output[:500] or "").strip()
            if not target:
                continue  # skip empty targets to avoid all-masked labels and NaN loss
            input_text = f"Game state:\n{mh_state}{buf_block}\n\nAction: {action}\n\nPredicted MUD output:"
        else:
            # outcome_summary: predict VH's summary of what actually happened
            target = (outcome_summary or "").strip()
            if not target:
                continue  # skip empty targets to avoid all-masked labels and NaN loss
            input_text = f"Game state:\n{mh_state}{buf_block}\n\nAction: {action}\n\nActual outcome summary:"
        yield input_text, target, weight


def run_training(
    trace_glob: str = None,
    mode: str = "outcome_summary",
    vh_score_min: int = 1,
    weight_by_vh_score: bool = True,
    output_dir: str = None,
    num_epochs: int = None,
    per_device_train_batch_size: int = 1,
    gradient_accumulation_steps: int = None,
    learning_rate: float = None,
    lora_r: int = 8,
    lora_alpha: int = 16,
    early_stopping_patience: int = None,
    eval_fraction: float = None,
    max_length: int = None,
    use_semantic_loss: bool = None,
    semantic_loss_weight: float = None,
    semantic_only: bool = None,
    semantic_encoder: str = None,
):
    import torch
    import torch.nn.functional as F
    from torch.utils.data import WeightedRandomSampler
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer, EarlyStoppingCallback
    from transformers.modeling_outputs import CausalLMOutputWithPast
    from peft import LoraConfig, get_peft_model, TaskType

    class WeightedTrainer(Trainer):
        """Trainer that oversamples by vh_score when sample_weights is provided."""
        def __init__(self, sample_weights=None, **kwargs):
            super().__init__(**kwargs)
            self._sample_weights = sample_weights

        def _get_train_sampler(self, train_dataset=None):
            if train_dataset is None:
                train_dataset = self.train_dataset
            if self._sample_weights is not None and len(self._sample_weights) == len(train_dataset):
                return WeightedRandomSampler(
                    self._sample_weights,
                    num_samples=len(train_dataset),
                    replacement=True,
                )
            return super()._get_train_sampler(train_dataset)

    class WMWithSemanticLoss(torch.nn.Module):
        """Wraps the LM and adds semantic loss: match mean-pooled target hidden states to reference embedding (cosine)."""
        def __init__(self, model, projection_head, sentence_encoder, semantic_loss_weight: float, semantic_only: bool):
            super().__init__()
            self.model = model
            self.projection_head = projection_head
            self.sentence_encoder = sentence_encoder
            self.semantic_loss_weight = float(semantic_loss_weight)
            self.semantic_only = bool(semantic_only)
            for p in self.sentence_encoder.parameters():
                p.requires_grad = False

        def forward(self, input_ids=None, attention_mask=None, labels=None, target_text=None, **kwargs):
            if target_text is None or (not self.semantic_only and self.semantic_loss_weight == 0):
                return self.model(input_ids=input_ids, attention_mask=attention_mask, labels=labels, **kwargs)
            kwargs.pop("target_text", None)
            outputs = self.model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels,
                output_hidden_states=True,
                **kwargs,
            )
            last_hidden = outputs.hidden_states[-1]
            mask = (labels != -100)
            if mask.any():
                pooled = (last_hidden * mask.unsqueeze(-1).float()).sum(1) / mask.sum(1).clamp(min=1).unsqueeze(-1)
                projected = self.projection_head(pooled.float())
                projected = F.normalize(projected, dim=1)
                with torch.no_grad():
                    ref_emb = self.sentence_encoder.encode(
                        target_text, convert_to_tensor=True, device=projected.device
                    )
                    ref_emb = F.normalize(ref_emb.float(), dim=1)
                L_sem = (1 - (projected * ref_emb).sum(dim=1)).mean()
                if self.semantic_only:
                    loss = L_sem
                else:
                    loss = outputs.loss + self.semantic_loss_weight * L_sem
            else:
                loss = outputs.loss
            return CausalLMOutputWithPast(
                loss=loss,
                logits=outputs.logits,
                past_key_values=outputs.past_key_values,
                hidden_states=outputs.hidden_states,
                attentions=outputs.attentions,
            )

        def save_pretrained(self, save_directory, **kwargs):
            self.model.save_pretrained(save_directory, **kwargs)
            torch.save(self.projection_head.state_dict(), Path(save_directory) / "projection_head.pt")

    cfg = load_config()
    train_cfg = cfg.get("training", {})
    trace_glob = trace_glob or train_cfg.get("trace_glob")
    mode = mode or train_cfg.get("mode", "outcome_summary")
    vh_score_min = vh_score_min if vh_score_min is not None else train_cfg.get("vh_score_min", 1)
    weight_by_vh_score = weight_by_vh_score if weight_by_vh_score is not None else train_cfg.get("weight_by_vh_score", True)
    output_dir = output_dir or str(resolve_path("checkpoints_dir"))
    num_epochs = num_epochs or train_cfg.get("num_epochs", 3)
    per_device_train_batch_size = per_device_train_batch_size or train_cfg.get("per_device_train_batch_size", 1)
    gradient_accumulation_steps = gradient_accumulation_steps if gradient_accumulation_steps is not None else train_cfg.get("gradient_accumulation_steps", 4)
    learning_rate = learning_rate or train_cfg.get("learning_rate", 2.0e-5)
    lora_r = lora_r or train_cfg.get("lora_r", 8)
    lora_alpha = lora_alpha or train_cfg.get("lora_alpha", 16)
    early_stopping_patience = early_stopping_patience if early_stopping_patience is not None else train_cfg.get("early_stopping_patience", 2)
    eval_fraction = eval_fraction if eval_fraction is not None else train_cfg.get("eval_fraction", 0.1)
    max_length = max_length if max_length is not None else train_cfg.get("max_length", 2048)
    use_semantic_loss = use_semantic_loss if use_semantic_loss is not None else train_cfg.get("use_semantic_loss", False)
    semantic_loss_weight = semantic_loss_weight if semantic_loss_weight is not None else train_cfg.get("semantic_loss_weight", 0.5)
    semantic_only = semantic_only if semantic_only is not None else train_cfg.get("semantic_only", False)
    semantic_encoder_name = semantic_encoder or train_cfg.get("semantic_encoder", "sentence-transformers/all-MiniLM-L6-v2")

    traces = load_traces(trace_glob)
    if not traces:
        raise SystemExit("No traces found. Run the orchestrator to generate data/logs/traces.jsonl.")

    rows = list(build_dataset(traces, mode=mode, vh_score_min=vh_score_min, weight_by_vh_score=weight_by_vh_score))
    if not rows:
        raise SystemExit("No traces passed vh_score_min filter.")
    input_texts = [inp for inp, _, _ in rows]
    target_texts = [tgt for _, tgt, _ in rows]
    weights = [w for _, _, w in rows]

    model_name = cfg.get("wm", {}).get("model_name", "mistralai/Mistral-7B-v0.1")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id

    min_target_tokens = 64  # reserve space so target (outcome summary) is never fully truncated (avoids all -100 labels and NaN loss)
    pad_id = tokenizer.pad_token_id

    def tokenize_with_labels(examples):
        """Tokenize prompt + target; build labels with -100 on prompt so loss is only on target."""
        input_ids_list = []
        attention_mask_list = []
        labels_list = []
        for inp, tgt in zip(examples["input_text"], examples["target_text"]):
            full_text = inp + " " + tgt
            enc_full = tokenizer(
                full_text,
                truncation=True,
                max_length=max_length,
                padding="max_length",
                return_tensors=None,
            )
            # Use shorter max for prompt so we always have room for target tokens (avoids NaN when prompt fills max_length)
            enc_prompt = tokenizer(inp, truncation=True, max_length=max_length - min_target_tokens)
            num_full = len(enc_full["input_ids"])
            prompt_len = min(len(enc_prompt["input_ids"]), num_full - min_target_tokens)
            input_ids = enc_full["input_ids"]
            attention_mask = enc_full["attention_mask"]
            labels = [-100] * prompt_len + [input_ids[i] if attention_mask[i] and input_ids[i] != pad_id else -100 for i in range(prompt_len, len(input_ids))]
            input_ids_list.append(input_ids)
            attention_mask_list.append(attention_mask)
            labels_list.append(labels)
        return {
            "input_ids": input_ids_list,
            "attention_mask": attention_mask_list,
            "labels": labels_list,
        }

    dataset = Dataset.from_dict({
        "input_text": input_texts,
        "target_text": target_texts,
        "idx": list(range(len(rows))),
    })
    remove_cols = ["input_text"]
    if not use_semantic_loss:
        remove_cols.append("target_text")
    tokenized = dataset.map(
        tokenize_with_labels,
        batched=True,
        remove_columns=remove_cols,
    )
    tokenized.set_format("torch")

    # Train/validation split for early stopping (eval loss)
    eval_dataset = None
    train_dataset = tokenized
    train_weights = None
    if eval_fraction and eval_fraction > 0 and len(tokenized) >= 2:
        split = tokenized.train_test_split(test_size=eval_fraction, seed=42)
        train_dataset = split["train"]
        eval_dataset = split["test"]
        # Weights for oversampling: high vh_score traces seen more often
        if weight_by_vh_score and weights:
            train_weights = torch.tensor([weights[i] for i in train_dataset["idx"]], dtype=torch.float32)
        train_dataset = train_dataset.remove_columns(["idx"])
        eval_dataset = eval_dataset.remove_columns(["idx"])
    else:
        if "idx" in train_dataset.column_names:
            train_dataset = train_dataset.remove_columns(["idx"])
        if weight_by_vh_score and weights:
            train_weights = torch.tensor(weights, dtype=torch.float32)

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        trust_remote_code=True,
    )
    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"],
    )
    model = get_peft_model(model, peft_config)

    if use_semantic_loss and mode == "outcome_summary":
        from sentence_transformers import SentenceTransformer
        encoder = SentenceTransformer(semantic_encoder_name)
        encoder_dim = encoder.get_sentence_embedding_dimension()
        hidden_size = getattr(model.config, "hidden_size", model.config.text_config.hidden_size if hasattr(model.config, "text_config") else 4096)
        projection_head = torch.nn.Linear(hidden_size, encoder_dim)
        device = next(model.parameters()).device
        encoder = encoder.to(device)
        projection_head = projection_head.to(device)
        model = WMWithSemanticLoss(
            model, projection_head, encoder, semantic_loss_weight, semantic_only
        )

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=per_device_train_batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=learning_rate,
        logging_steps=5,
        save_strategy="best" if eval_dataset else "no",  # when eval: save only when eval improves; else save only at end
        save_total_limit=1 if eval_dataset else None,   # when eval: keep only best checkpoint (delete previous when new best saved)
        fp16=torch.cuda.is_available(),
        eval_strategy="epoch" if eval_dataset else "no",
        metric_for_best_model="loss",
        load_best_model_at_end=bool(eval_dataset),
        greater_is_better=False,
    )
    callbacks = [EarlyStoppingCallback(early_stopping_patience=early_stopping_patience)] if eval_dataset else []
    trainer_cls = WeightedTrainer if train_weights is not None else Trainer
    trainer_kw = dict(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        callbacks=callbacks,
    )
    if trainer_cls is WeightedTrainer:
        trainer_kw["sample_weights"] = train_weights
    trainer = trainer_cls(**trainer_kw)
    trainer.train()
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print("Saved checkpoint to", output_dir)


def main():
    p = argparse.ArgumentParser(description="Train WM on traces")
    p.add_argument("--trace-glob", default=None, help="Glob for trace files")
    p.add_argument("--mode", choices=["next_line", "outcome_summary"], default=None)
    p.add_argument("--vh-score-min", type=int, default=None)
    p.add_argument("--output-dir", default=None)
    p.add_argument("--epochs", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=None, help="Per-device train batch size (default from config)")
    p.add_argument("--gradient-accumulation-steps", type=int, default=None, help="Effective batch = batch_size * this * num_gpus")
    p.add_argument("--max-length", type=int, default=None, help="Max sequence length (context + target). Larger = more mh_state + buffer; Mistral supports 8192.")
    p.add_argument("--no-semantic-loss", action="store_true", help="Disable semantic loss (use token CE only)")
    p.add_argument("--semantic-loss-weight", type=float, default=None)
    p.add_argument("--semantic-only", action="store_true", help="Use only semantic loss (no CE on target tokens)")
    p.add_argument("--semantic-encoder", type=str, default=None)
    p.add_argument("--lr", type=float, default=None)
    args = p.parse_args()
    run_training(
        trace_glob=args.trace_glob,
        mode=args.mode,
        vh_score_min=args.vh_score_min,
        output_dir=args.output_dir,
        num_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        max_length=args.max_length,
        use_semantic_loss=False if args.no_semantic_loss else None,
        semantic_loss_weight=args.semantic_loss_weight,
        semantic_only=args.semantic_only or None,
        semantic_encoder=args.semantic_encoder,
        learning_rate=args.lr,
    )


if __name__ == "__main__":
    main()
