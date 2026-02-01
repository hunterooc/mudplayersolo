"""World Model: Mistral-7B local, predicts outcome of (state, action) and confidence.

Uses next-token completion (causal LM generate). For a chat-tuned model (e.g. Mistral-7B-Instruct)
you would use the model's chat template and pass messages instead of a single prompt.
"""
import os
import re
from pathlib import Path
from typing import Tuple, Optional

try:
    from src.config import load_config, PROJECT_ROOT
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    load_config = lambda: {}


def _load_prompt(name: str) -> str:
    cfg = load_config()
    prompts_dir = cfg.get("paths", {}).get("prompts_dir", "prompts")
    path = Path(prompts_dir) if Path(prompts_dir).is_absolute() else PROJECT_ROOT / prompts_dir
    with open(path / name) as f:
        return f.read()


def _fill(template: str, **kwargs: str) -> str:
    for k, v in kwargs.items():
        template = template.replace("{{" + k + "}}", (v or "").strip())
    return template


# Lazy load model/tokenizer to avoid import-time GPU use
_model = None
_tokenizer = None


def _get_model():
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    cfg = load_config()
    wm_cfg = cfg.get("wm", {})
    base_name = wm_cfg.get("model_name", "mistralai/Mistral-7B-v0.1")
    use_4bit = wm_cfg.get("use_4bit", False)
    paths = cfg.get("paths", {})
    checkpoint_dir = paths.get("checkpoints_dir", "data/checkpoints/wm")
    if not Path(checkpoint_dir).is_absolute():
        checkpoint_dir = str(PROJECT_ROOT / checkpoint_dir)
    has_adapter = Path(checkpoint_dir).exists() and any(Path(checkpoint_dir).iterdir())
    # Tokenizer: from checkpoint if we have a fine-tuned adapter, else base model
    tokenizer_path = checkpoint_dir if has_adapter else base_name
    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_path,
        trust_remote_code=True,
    )
    model_kwargs = {"trust_remote_code": True}
    if use_4bit:
        from transformers import BitsAndBytesConfig
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
    else:
        model_kwargs["dtype"] = torch.float16
    model = AutoModelForCausalLM.from_pretrained(base_name, **model_kwargs)
    if has_adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, checkpoint_dir)
    if torch.cuda.is_available():
        model = model.cuda()
    model.eval()
    _model, _tokenizer = model, tokenizer
    return _model, _tokenizer


def run_wm(mh_state: str, action: str, recent_buffer: str = "") -> Tuple[str, str]:
    """
    Run WM: predict (predicted_text, confidence).
    confidence is one of: high, medium, low.
    recent_buffer: last N lines of MUD output before the action (optional; helps next-line prediction).
    """
    template = _load_prompt("wm.txt")
    prompt = _fill(
        template,
        mh_state=mh_state,
        action=action,
        recent_buffer=(recent_buffer or "(none)").strip(),
    )
    model, tokenizer = _get_model()
    cfg = load_config()
    wm_cfg = cfg.get("wm", {})
    max_new_tokens = wm_cfg.get("max_new_tokens", 256)
    temperature = wm_cfg.get("temperature", 0.3)
    import torch
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
    if next(model.parameters()).is_cuda:
        inputs = {k: v.cuda() for k, v in inputs.items()}
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=temperature > 0,
            pad_token_id=tokenizer.eos_token_id,
        )
    full = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    # Parse: predicted paragraph then "Confidence: high|medium|low"
    confidence = "medium"
    predicted_text = full
    conf_m = re.search(r"Confidence:\s*(high|medium|low)", full, re.I)
    if conf_m:
        confidence = conf_m.group(1).lower()
        predicted_text = full[: conf_m.start()].strip()
    return predicted_text, confidence


def reset_wm_cache() -> None:
    """Clear cached model/tokenizer (e.g. after training)."""
    global _model, _tokenizer
    _model = _tokenizer = None
