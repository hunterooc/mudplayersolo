#!/usr/bin/env python3
"""Test memory layer: write sample content, read back, assert PH/DH can receive as string."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.memory.store import MemoryStore, get_memory_paths


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(memory_dir=Path(tmp))
        store.write_commands("# Commands\n- look: see room\n- north: go north")
        store.write_current_location("# Current room\n- Town Square: central area, exits: north, south")
        store.write_mobs("# Mobs\n- Goblin: weak, drops gold")
        paths = get_memory_paths(Path(tmp))
        assert paths["commands.md"].exists()
        assert paths["current_location.md"].exists()
        assert paths["mobs.md"].exists()
        all_ = store.read_all()
        assert "look" in all_["commands"]
        assert "Town Square" in all_["current_location"]
        assert "Goblin" in all_["mobs"]
        # PH/DH consume as string
        combined = "\n\n".join([f"## {k}\n{v}" for k, v in all_.items()])
        assert "look" in combined and "Goblin" in combined
    print("test_memory: OK")


if __name__ == "__main__":
    main()
