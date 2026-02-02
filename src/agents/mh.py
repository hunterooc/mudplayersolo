"""Memory Head: maintain game state and update memory files (current_location, session_summary, inventory, equipment, statbar, spells at kickoff). commands.md is read-only (user-populated). mobs.md is deprecated. Uses parallel API calls per file."""
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
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

logger = logging.getLogger(__name__)


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


def _run_mh_current_location(new_output: str, current_location: str, client: Optional[OpenAI] = None) -> str:
    template = _load_prompt("mh_current_location.txt")
    prompt = _fill(template, new_output=new_output, current_location=current_location)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
    temperature = cfg.get("openai", {}).get("temperature") or 0.3
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature)
    return (resp.choices[0].message.content or "").strip()


def _run_mh_session_summary(new_output: str, session_summary: str, client: Optional[OpenAI] = None) -> str:
    template = _load_prompt("mh_session_summary.txt")
    prompt = _fill(template, new_output=new_output, session_summary=session_summary)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
    temperature = cfg.get("openai", {}).get("temperature") or 0.3
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature)
    return (resp.choices[0].message.content or "").strip()


def _run_mh_inventory(new_output: str, inventory: str, client: Optional[OpenAI] = None) -> str:
    template = _load_prompt("mh_inventory.txt")
    prompt = _fill(template, new_output=new_output, inventory=inventory)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
    temperature = cfg.get("openai", {}).get("temperature") or 0.3
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature)
    return (resp.choices[0].message.content or "").strip()


def _run_mh_equipment(new_output: str, equipment: str, client: Optional[OpenAI] = None) -> str:
    template = _load_prompt("mh_equipment.txt")
    prompt = _fill(template, new_output=new_output, equipment=equipment)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
    temperature = cfg.get("openai", {}).get("temperature") or 0.3
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature)
    return (resp.choices[0].message.content or "").strip()


def _run_mh_statbar(new_output: str, statbar: str, client: Optional[OpenAI] = None) -> str:
    template = _load_prompt("mh_statbar.txt")
    prompt = _fill(template, new_output=new_output, statbar=statbar)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
    temperature = cfg.get("openai", {}).get("temperature") or 0.3
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature)
    return (resp.choices[0].message.content or "").strip()


def _run_mh_spells(new_output: str, spells: str, client: Optional[OpenAI] = None) -> str:
    template = _load_prompt("mh_spells.txt")
    prompt = _fill(template, new_output=new_output, spells=spells)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
    temperature = cfg.get("openai", {}).get("temperature") or 0.3
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature)
    return (resp.choices[0].message.content or "").strip()


def run_mh_parallel(
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
    max_workers: int = 6,
) -> tuple[str, str, str, str, str, str, str, str]:
    """
    Run six MH updates in parallel (one API call per file). Returns same 8-tuple as run_mh.
    On partial failure: keep previous value for that file and log a warning.
    """
    new_current_location = current_location
    new_session_summary = session_summary
    new_inventory = inventory
    new_equipment = equipment
    new_statbar = statbar
    new_spells = spells

    def run_current_location():
        return _run_mh_current_location(new_output, current_location, client)

    def run_session_summary():
        return _run_mh_session_summary(new_output, session_summary, client)

    def run_inventory():
        return _run_mh_inventory(new_output, inventory, client)

    def run_equipment():
        return _run_mh_equipment(new_output, equipment, client)

    def run_statbar():
        return _run_mh_statbar(new_output, statbar, client)

    def run_spells():
        return _run_mh_spells(new_output, spells, client)

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {
            executor.submit(run_current_location): "current_location",
            executor.submit(run_session_summary): "session_summary",
            executor.submit(run_inventory): "inventory",
            executor.submit(run_equipment): "equipment",
            executor.submit(run_statbar): "statbar",
            executor.submit(run_spells): "spells",
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                logger.warning("MH parallel call failed for %s: %s; keeping previous value.", name, e)
                prev = {"current_location": current_location, "session_summary": session_summary, "inventory": inventory, "equipment": equipment, "statbar": statbar, "spells": spells}
                results[name] = prev[name]

    new_current_location = results.get("current_location", current_location)
    new_session_summary = results.get("session_summary", session_summary)
    new_inventory = results.get("inventory", inventory)
    new_equipment = results.get("equipment", equipment)
    new_statbar = results.get("statbar", statbar)
    new_spells = results.get("spells", spells)

    if memory_store:
        memory_store.write_all(
            current_location=new_current_location,
            session_summary=new_session_summary,
            inventory=new_inventory,
            equipment=new_equipment,
            statbar=new_statbar,
        )
    return commands, new_current_location, mobs, new_session_summary, new_inventory, new_equipment, new_statbar, new_spells
