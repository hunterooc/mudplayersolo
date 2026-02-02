#!/usr/bin/env python3
"""Test API agents MH and DH (action + goals) with dummy inputs. Requires OPENAI_API_KEY in env."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

project_root = Path(__file__).resolve().parents[1]
env_file = project_root / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

from src.agents.mh import run_mh
from src.agents.dh import run_dh_action, run_dh_goals
from src.memory.store import MemoryStore


def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY in .env to run this test.")
        sys.exit(0)
    with __import__("tempfile").TemporaryDirectory() as tmp:
        store = MemoryStore(memory_dir=Path(tmp))
        # MH
        cmd, current_loc, mob, session_summary, inventory, equipment, statbar = run_mh(
            new_output="You are in a dusty tavern. A goblin eyes you from the corner.",
            memory_store=store,
        )
        assert current_loc or session_summary, "MH should return location or session summary"
        print("MH current_location length:", len(current_loc), "session_summary length:", len(session_summary))
        # DH action: full state + goals -> one command
        chosen = run_dh_action(
            game_buffer="You are in a dusty tavern.",
            commands=cmd,
            spells="",
            current_location=current_loc,
            mobs=mob,
            session_summary=session_summary,
            goals="",
            inventory=inventory,
            equipment=equipment,
            statbar=statbar,
            play_summary="None yet (this is the first turn).",
        )
        assert chosen and len(chosen) < 200, "DH action should return a short command"
        print("DH action chosen:", chosen)
        # DH goals: state + action + outcome -> goals_update
        composed_context = (current_loc or "").strip() + "\n\n" + (session_summary or "").strip() + "\n\n" + (statbar or "").strip()
        goals_update = run_dh_goals(
            mh_state=composed_context,
            action="look",
            actual_output="You see a dusty tavern. A goblin is here.",
            goals="",
        )
        assert isinstance(goals_update, str), "DH goals should return goals_update (str)"
        print("DH goals_update length:", len(goals_update))
    print("test_agents_api: OK")


if __name__ == "__main__":
    main()
