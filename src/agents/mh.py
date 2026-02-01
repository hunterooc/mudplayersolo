"""Memory Head: maintain game state and update memory files (commands, current_location). mobs.md is deprecated."""
import os
import re
from pathlib import Path
from typing import Optional

from openai import OpenAI

try:
    from src.config import load_config, PROJECT_ROOT
    from src.memory.store import MemoryStore
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    load_config = lambda: {}
    MemoryStore = None


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


def run_mh(
    new_output: str,
    commands: str = "",
    spells: str = "",
    current_location: str = "",
    mobs: str = "",
    session_summary: str = "",
    inventory: str = "",
    equipment: str = "",
    statbar: str = "",
    memory_store: Optional[MemoryStore] = None,
    client: Optional[OpenAI] = None,
) -> tuple[str, str, str, str, str, str, str]:
    """
    Run MH: update memory files (no monolithic state).
    Returns (updated_commands, updated_current_location, updated_mobs, updated_session_summary, updated_inventory, updated_equipment, updated_statbar).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-5-mini")
    template = _load_prompt("mh.txt")
    prompt = _fill(
        template,
        new_output=new_output,
        commands=commands,
        spells=spells,
        current_location=current_location,
        session_summary=session_summary,
        inventory=inventory,
        equipment=equipment,
        statbar=statbar,
    )
    temperature = cfg.get("openai", {}).get("temperature")
    if temperature is None:
        temperature = 0.3
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    text = (resp.choices[0].message.content or "").strip()
    # Parse COMMANDS.MD, CURRENT_LOCATION(.MD)?, SESSION_SUMMARY(.MD)?, INVENTORY.MD, EQUIPMENT.MD, STATBAR.MD (mobs.md deprecated; not parsed or written)
    new_commands = commands
    new_current_location = current_location
    new_session_summary = session_summary  # keep previous if section missing
    new_inventory = inventory
    new_equipment = equipment
    new_statbar = statbar
    section = re.compile(
        r"=== (COMMANDS\.MD|CURRENT[\s_]?LOCATION(?:\.MD)?|SESSION[\s_]?SUMMARY(?:\.MD)?|INVENTORY\.MD|EQUIPMENT\.MD|STATBAR\.MD) ===\s*",
        re.I,
    )
    parts = section.split(text)
    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break
        name, content = parts[i].strip().upper().replace(" ", "_"), parts[i + 1].strip()
        if "COMMANDS" in name:
            new_commands = content
        elif "CURRENT_LOCATION" in name:
            new_current_location = content
        elif "SESSION_SUMMARY" in name:
            new_session_summary = content
        elif "INVENTORY" in name:
            new_inventory = content
        elif "EQUIPMENT" in name:
            new_equipment = content
        elif "STATBAR" in name:
            new_statbar = content
    if memory_store:
        memory_store.write_all(
            commands=new_commands,
            current_location=new_current_location,
            session_summary=new_session_summary,
            inventory=new_inventory,
            equipment=new_equipment,
            statbar=new_statbar,
        )
    return new_commands, new_current_location, mobs, new_session_summary, new_inventory, new_equipment, new_statbar
