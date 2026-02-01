"""Decision Head: choose best action from WM predictions."""
import os
import re
from pathlib import Path
from typing import List, Tuple

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


def run_dh(
    options: List[Tuple[str, str, str]],
    game_buffer: str = "",
    commands: str = "",
    spells: str = "",
    current_location: str = "",
    mobs: str = "",
    play_summary: str = "",
    session_summary: str = "",
    goals: str = "",
    inventory: str = "",
    equipment: str = "",
    client: OpenAI | None = None,
) -> str:
    """
    Run DH: options is list of (action, predicted_text, confidence).
    Receives full picture: game_buffer, play_summary, and memory files (including inventory, equipment).
    Returns chosen action string.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-5-mini")
    options_text = "\n\n".join(
        f"Action: {a}\nPredicted: {p}\nConfidence: {c}" for a, p, c in options
    )
    template = _load_prompt("dh.txt")
    prompt = _fill(
        template,
        options_text=options_text,
        game_buffer=game_buffer,
        commands=commands,
        spells=spells,
        current_location=current_location,
        mobs=mobs,
        play_summary=play_summary,
        session_summary=session_summary,
        goals=goals,
        inventory=inventory,
        equipment=equipment,
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
    # First non-empty line that looks like a command (short, no punctuation at end)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        ln = re.sub(r"^[\d\.\)\-\*]+\s*", "", ln).strip()
        # Reject markdown/code artifacts: backticks, code blocks, empty
        ln = re.sub(r"^`+|`+$", "", ln).strip()
        # If line is "Action: look", take the part after the last colon
        if ":" in ln:
            ln = ln.split(":")[-1].strip()
        if not ln or ln in ("```", "`") or len(ln) > 200 or ln.endswith("."):
            continue
        # Prefer an action that was one of PH's options
        if options and any(a.strip().lower() == ln.lower() for a, _, _ in options):
            return ln
        # Otherwise accept any reasonable-looking command (letters, spaces, digits)
        if re.match(r"^[\w\s\-']+$", ln, re.IGNORECASE):
            return ln
    return options[0][0] if options else "look"
