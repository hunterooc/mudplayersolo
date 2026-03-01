"""Load config from config.yaml and env."""
from pathlib import Path
import os

import yaml

# Project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


def load_config():
    path = PROJECT_ROOT / "config.yaml"
    if not path.exists():
        return _default_config()
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return _deep_merge(_default_config(), cfg)


def _default_config():
    return {
        "mud": {
            "silence_timeout_sec": 10,
            "reconnect_delay_sec": 2,
            "max_reconnect_attempts": 5,
        },
        "paths": {
            "data_dir": "data",
            "memory_dir": "data",
            "logs_dir": "data/logs",
            "gameplay_log": "data/logs/gameplay.jsonl",
            "prompts_dir": "prompts",
            "critic_log": "data/logs/critic.jsonl",
            "engineer_changes_log": "data/logs/engineer_changes.jsonl",
        },
        "openai": {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "model_critic": os.getenv("OPENAI_MODEL_CRITIC", "gpt-5-mini"),
            "model_engineer": os.getenv("OPENAI_MODEL_ENGINEER", "gpt-5-mini"),
            "model_editor": os.getenv("OPENAI_MODEL_EDITOR", "gpt-5-nano"),
        },
        "orchestrator": {
            "kickoff_commands": ["look", "score", "inventory", "equipment"],
            "max_steps": None,
            "game_buffer_max_lines": 80,
            "game_buffer_max_chars_for_dh": 4000,
            "play_summary_max_turns": 10,
            "statbar_refresh_interval": None,
            "critic_interval": 20,
            "game_buffer_max_chars_for_critic": 16000,
        },
    }


def _deep_merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve_path(key: str, subpath: str = "") -> Path:
    """Resolve a path from config paths section; subpath is joined if given."""
    cfg = load_config()
    base = cfg["paths"].get(key, key)
    p = Path(base)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if subpath:
        p = p / subpath
    return p
