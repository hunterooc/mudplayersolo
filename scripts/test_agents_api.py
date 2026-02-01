#!/usr/bin/env python3
"""Test API agents MH, PH, DH, VH with dummy inputs. Requires OPENAI_API_KEY in env."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env if present (without requiring python-dotenv)
project_root = Path(__file__).resolve().parents[1]
env_file = project_root / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

from src.agents.mh import run_mh
from src.agents.ph import run_ph
from src.agents.dh import run_dh
from src.agents.vh import run_vh
from src.memory.store import MemoryStore


def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY in .env to run this test.")
        sys.exit(0)
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(memory_dir=Path(tmp))
        # MH (returns 7 values: commands, current_location, mobs, session_summary, inventory, equipment, statbar)
        cmd, current_loc, mob, session_summary, inventory, equipment, statbar = run_mh(
            new_output="You are in a dusty tavern. A goblin eyes you from the corner.",
            memory_store=store,
        )
        assert current_loc or session_summary, "MH should return location or session summary"
        print("MH current_location length:", len(current_loc), "session_summary length:", len(session_summary))
        # Composed context for WM/VH (current_location + session_summary + statbar)
        composed_context = (current_loc or "").strip() + "\n\n" + (session_summary or "").strip() + "\n\n" + (statbar or "").strip()
        # PH
        actions = run_ph(
            game_buffer="You are in a dusty tavern.",
            commands=cmd,
            current_location=current_loc,
            mobs=mob,
            session_summary=session_summary,
            goals="",
            inventory=inventory,
            equipment=equipment,
            statbar=statbar,
        )
        assert 1 <= len(actions) <= 7, "PH should return 1–7 actions"
        print("PH actions:", actions)
        # DH (dummy WM predictions; DH now gets full picture)
        options = [
            ("look", "You see a tavern.", "high"),
            ("attack goblin", "You swing and miss.", "medium"),
        ]
        chosen = run_dh(
            options=options,
            game_buffer="You are in a dusty tavern.",
            commands=cmd,
            current_location=current_loc,
            mobs=mob,
            session_summary=session_summary,
            goals="",
            inventory=inventory,
            equipment=equipment,
        )
        assert chosen in [o[0] for o in options] or chosen, "DH should return an action"
        print("DH chosen:", chosen)
        # VH (receives composed context: current_location + session_summary)
        score, summary, goals_update = run_vh(
            mh_state=composed_context,
            action="look",
            wm_prediction="You see a dusty tavern.",
            actual_output="You see a dusty tavern. A goblin is here.",
            goals="",
        )
        assert 1 <= score <= 5, "VH score should be 1–5"
        assert summary, "VH should return summary"
        assert isinstance(goals_update, str), "VH should return goals_update (str)"
        print("VH score:", score, "summary:", summary[:80])
    print("test_agents_api: OK")


if __name__ == "__main__":
    main()
