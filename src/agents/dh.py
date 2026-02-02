"""Decision Head: choose next action from MH state + goals; update goals after outcome."""
import os
import re
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
    with open(path / name) as f:
        return f.read()


def _fill(template: str, **kwargs: str) -> str:
    for k, v in kwargs.items():
        template = template.replace("{{" + k + "}}", (v or "").strip())
    return template


def run_dh_action(
    game_buffer: str = "",
    commands: str = "",
    spells: str = "",
    current_location: str = "",
    mobs: str = "",
    session_summary: str = "",
    goals: str = "",
    inventory: str = "",
    equipment: str = "",
    statbar: str = "",
    play_summary: str = "",
    client: Optional[OpenAI] = None,
) -> str:
    """
    Run DH action mode: given full MH state + goals, output the next MUD command.
    Returns chosen action string.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-5-mini")
    template = _load_prompt("dh.txt")
    prompt = _fill(
        template,
        game_buffer=game_buffer,
        commands=commands,
        spells=spells,
        current_location=current_location,
        mobs=mobs,
        session_summary=session_summary,
        goals=goals,
        inventory=inventory,
        equipment=equipment,
        statbar=statbar,
        play_summary=play_summary,
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
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        ln = re.sub(r"^[\d\.\)\-\*]+\s*", "", ln).strip()
        ln = re.sub(r"^`+|`+$", "", ln).strip()
        if ":" in ln:
            ln = ln.split(":")[-1].strip()
        if not ln or ln in ("```", "`") or len(ln) > 200 or ln.endswith("."):
            continue
        if re.match(r"^[\w\s\-']+$", ln, re.IGNORECASE):
            return ln
    return "look"


def run_dh_goals(
    mh_state: str,
    action: str,
    actual_output: str,
    goals: str = "",
    client: Optional[OpenAI] = None,
) -> str:
    """
    Run DH goals mode: given state at decision time, action taken, and actual MUD output,
    output updated goals.md content. Returns the GOALS.MD section text (to write to goals.md).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-5-mini")
    template = _load_prompt("dh_goals.txt")
    prompt = _fill(
        template,
        mh_state=mh_state,
        action=action,
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
    goals_section = re.search(
        r"=== GOALS(?:\.MD)? ===\s*(.+?)(?=\n===|\Z)",
        text,
        re.S | re.I,
    )
    if goals_section:
        return goals_section.group(1).strip()
    return goals  # keep previous if section missing
