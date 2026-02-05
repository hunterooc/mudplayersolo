"""Editor agent: apply engineer's specific changes to DH prompt; output new full prompt."""
import os
from pathlib import Path
from typing import Optional

from openai import OpenAI

try:
    from src.config import load_config, PROJECT_ROOT
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    load_config = lambda: {}


def _load_prompt(name: str) -> str:
    cfg = load_config()
    prompts_dir = cfg.get("paths", {}).get("prompts_dir", "prompts")
    path = Path(prompts_dir) if Path(prompts_dir).is_absolute() else PROJECT_ROOT / prompts_dir
    with open(path / name, encoding="utf-8") as f:
        return f.read()


def run_editor(
    specific_changes: str,
    current_dh_prompt: str,
    client: Optional[OpenAI] = None,
) -> str:
    """
    Run the editor: given engineer's edit instructions and current DH prompt,
    output the complete new prompt text (to be written to prompts/dh.txt).
    """
    if not specific_changes.strip() or "no changes needed" in specific_changes.strip().lower()[:50]:
        return current_dh_prompt

    cfg = load_config()
    template = _load_prompt("editor.txt")
    prompt = template.replace("{{specific_changes}}", specific_changes).replace(
        "{{current_dh_prompt}}", current_dh_prompt
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    model = cfg.get("openai", {}).get("model_editor") or cfg.get("openai", {}).get("model", "gpt-4o-mini")
    temperature = cfg.get("openai", {}).get("temperature")
    if temperature is None:
        temperature = 0.2

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()
