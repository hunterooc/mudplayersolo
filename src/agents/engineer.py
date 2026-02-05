"""Engineer agent: read critic diagnosis + DH prompt; output specific edit instructions (logged)."""
import json
import os
from pathlib import Path
from typing import Optional

from openai import OpenAI

try:
    from src.config import load_config, resolve_path, PROJECT_ROOT
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    load_config = lambda: {}
    def resolve_path(key: str, subpath: str = "") -> Path:
        cfg = load_config()
        base = cfg.get("paths", {}).get(key, "data/logs")
        p = Path(base) if isinstance(base, str) else Path(base)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p / subpath if subpath else p


def _load_prompt(name: str) -> str:
    cfg = load_config()
    prompts_dir = cfg.get("paths", {}).get("prompts_dir", "prompts")
    path = Path(prompts_dir) if Path(prompts_dir).is_absolute() else PROJECT_ROOT / prompts_dir
    with open(path / name, encoding="utf-8") as f:
        return f.read()


def run_engineer(
    diagnosis: str,
    dh_prompt: str,
    log_excerpt: Optional[str] = None,
    engineer_log_path: Optional[Path] = None,
    client: Optional[OpenAI] = None,
) -> str:
    """
    Run the engineer: given critic diagnosis and current DH prompt, output specific edit instructions.
    Appends the instructions to the engineer_changes log. Returns the edit instructions text.
    """
    cfg = load_config()
    engineer_log_path = engineer_log_path or resolve_path("engineer_changes_log")
    engineer_log_path.parent.mkdir(parents=True, exist_ok=True)

    template = _load_prompt("engineer.txt")
    prompt = template.replace("{{diagnosis}}", diagnosis).replace("{{dh_prompt}}", dh_prompt)
    if log_excerpt is not None and "{{log_excerpt}}" in template:
        prompt = prompt.replace("{{log_excerpt}}", log_excerpt)
    elif "{{log_excerpt}}" in template:
        prompt = prompt.replace("{{log_excerpt}}", "(Not provided)")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    model = cfg.get("openai", {}).get("model_engineer") or cfg.get("openai", {}).get("model", "gpt-4o")
    temperature = cfg.get("openai", {}).get("temperature")
    if temperature is None:
        temperature = 0.3

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    changes = (resp.choices[0].message.content or "").strip()

    log_entry = {"diagnosis_preview": diagnosis[:200], "changes": changes}
    with open(engineer_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    return changes
