"""Critic agent: review gameplay log since last run and output diagnosis (what's working / not)."""
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


def _build_excerpt(gameplay_log_path: Path, since_step: int, current_step: int) -> str:
    """Read gameplay.jsonl and build a text excerpt for steps in (since_step, current_step]."""
    if not gameplay_log_path.exists():
        return "(No log entries in this window.)"
    lines = []
    with open(gameplay_log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            step = entry.get("step")
            if step is None or not (since_step < step <= current_step):
                continue
            action = entry.get("action", "")
            mud_output = (entry.get("mud_output") or "")[:2000].strip()  # cap for readability
            mh = entry.get("mh_context") or {}
            loc = (mh.get("current_location") or "")[:500].strip()
            inv = (mh.get("inventory") or "")[:300].strip()
            goals = (mh.get("goals") or "")[:400].strip()
            lines.append(
                f"--- Step {step} ---\n"
                f"Action: {action}\n"
                f"Room: {loc}\n"
                f"Inventory: {inv}\n"
                f"Goals: {goals}\n"
                f"MUD output: {mud_output}\n"
            )
    return "\n".join(lines) if lines else "(No log entries in this window.)"


def run_critic(
    gameplay_log_path: Optional[Path] = None,
    since_step: int = 0,
    current_step: int = 0,
    critic_log_path: Optional[Path] = None,
    client: Optional[OpenAI] = None,
) -> str:
    """
    Run the critic on gameplay log entries from (since_step, current_step].
    Returns the diagnosis text and appends it to the critic log.
    """
    cfg = load_config()
    gameplay_log_path = gameplay_log_path or resolve_path("gameplay_log")
    critic_log_path = critic_log_path or resolve_path("critic_log")
    critic_log_path.parent.mkdir(parents=True, exist_ok=True)

    excerpt = _build_excerpt(gameplay_log_path, since_step, current_step)
    template = _load_prompt("critic.txt")
    prompt = template.replace("{{gameplay_excerpt}}", excerpt)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    model = cfg.get("openai", {}).get("model_critic") or cfg.get("openai", {}).get("model", "gpt-4o")
    temperature = cfg.get("openai", {}).get("temperature")
    if temperature is None:
        temperature = 0.3

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    diagnosis = (resp.choices[0].message.content or "").strip()

    log_entry = {"step": current_step, "since_step": since_step, "diagnosis": diagnosis}
    with open(critic_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    return diagnosis
