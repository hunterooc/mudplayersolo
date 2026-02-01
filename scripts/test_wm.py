#!/usr/bin/env python3
"""Test WM: one inference (state, action) -> (predicted_text, confidence). Needs GPU/model or will be slow on CPU."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env if present (HF_TOKEN for model download)
project_root = Path(__file__).resolve().parents[1]
env_file = project_root / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

from src.agents.wm import run_wm


def main():
    state = "You are in a dusty tavern. A goblin is in the corner. Your health is full."
    action = "look"
    print("Running WM (state, action) -> (predicted_text, confidence)...")
    try:
        predicted_text, confidence = run_wm(state, action)
    except Exception as e:
        print("WM test failed (missing GPU or model download):", e)
        print("Install transformers, torch, and run again when ready.")
        sys.exit(1)
    assert isinstance(predicted_text, str), "predicted_text should be str"
    assert confidence in ("high", "medium", "low"), "confidence should be high/medium/low"
    print("predicted_text (first 200 chars):", repr(predicted_text[:200]))
    print("confidence:", confidence)
    print("test_wm: OK")


if __name__ == "__main__":
    main()
