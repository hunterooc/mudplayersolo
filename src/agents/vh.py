"""Value Head: grade WM prediction and summarize actual outcome."""
import os
import re
from pathlib import Path
from typing import Tuple

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
    with open(path / name) as f:
        return f.read()


def _fill(template: str, **kwargs: str) -> str:
    for k, v in kwargs.items():
        template = template.replace("{{" + k + "}}", (v or "").strip())
    return template


def run_vh(
    mh_state: str,
    action: str,
    wm_prediction: str,
    actual_output: str,
    goals: str = "",
    client: OpenAI | None = None,
) -> Tuple[int, str, str]:
    """Run VH: return (vh_score 1–5, vh_summary, goals_update). If GOALS.MD section missing, goals_update = goals (keep previous)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-5-mini")
    template = _load_prompt("vh.txt")
    prompt = _fill(
        template,
        mh_state=mh_state,
        action=action,
        wm_prediction=wm_prediction,
        actual_output=actual_output,
        goals=goals,
    )
    temperature = cfg.get("openai", {}).get("temperature")
    if temperature is None:
        temperature = 0.2
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    text = (resp.choices[0].message.content or "").strip()
    score = 3
    summary = text
    goals_update = goals  # keep previous if section missing
    m = re.search(r"vh_score:\s*(\d)", text, re.I)
    if m:
        score = max(1, min(5, int(m.group(1))))
    summary_m = re.search(r"vh_summary:\s*(.+?)(?=\n\n===|\n\nWhere|\Z)", text, re.S | re.I)
    if summary_m:
        summary = summary_m.group(1).strip()
    # Accept "=== GOALS.MD ===" or "=== GOALS ===" (model may drop .MD)
    goals_section = re.search(r"=== GOALS(?:\.MD)? ===\s*(.+?)(?=\n===|\Z)", text, re.S | re.I)
    if goals_section:
        goals_update = goals_section.group(1).strip()
    return score, summary, goals_update
