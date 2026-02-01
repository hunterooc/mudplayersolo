#!/usr/bin/env python3
"""Entry point: run MUD world model orchestrator. Set MUD_HOST, MUD_PORT, OPENAI_API_KEY in .env."""
import os
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from src.orchestrator import run


def main():
    # Default 10 rounds then graceful exit; pass 0 for unlimited
    max_steps = 10
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
            max_steps = None if n == 0 else n
        except ValueError:
            pass
    run(max_steps=max_steps)


if __name__ == "__main__":
    main()
