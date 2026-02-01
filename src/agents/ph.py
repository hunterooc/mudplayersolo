"""Policy Head: propose up to 5 next plausible actions (including combat when mob present)."""
import os
import re
from pathlib import Path
from typing import List

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


def run_ph(
    game_buffer: str,
    commands: str = "",
    spells: str = "",
    current_location: str = "",
    mobs: str = "",
    play_summary: str = "",
    session_summary: str = "",
    goals: str = "",
    inventory: str = "",
    equipment: str = "",
    statbar: str = "",
    client: OpenAI | None = None,
) -> List[str]:
    """Run PH: return list of up to 5 action strings (including combat when mob present). play_summary = commands sent this session; session_summary = what has happened this session; goals = current goals (goals.md); inventory/equipment = items carried and worn (inventory.md, equipment.md); statbar = HP, mana, movement (statbar.md)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-5-mini")
    template = _load_prompt("ph.txt")
    prompt = _fill(
        template,
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
        statbar=statbar,
    )
    temperature = cfg.get("openai", {}).get("temperature")
    if temperature is None:
        temperature = 0.5
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    text = (resp.choices[0].message.content or "").strip()
    # Parse lines as actions; skip numbering/bullets
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    actions = []
    for ln in lines:
        # Remove leading number, bullet, or dash
        ln = re.sub(r"^[\d\.\)\-\*]+\s*", "", ln).strip()
        if ln and len(ln) < 200:
            actions.append(ln)
    return actions[:5] if actions else ["look"]
