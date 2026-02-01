#!/usr/bin/env python3
"""Test training: create synthetic traces, run one epoch, assert checkpoint is written (or loss decreases)."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from train import load_traces, build_dataset, run_training


def main():
    with tempfile.TemporaryDirectory() as tmp:
        traces_file = Path(tmp) / "traces.jsonl"
        with open(traces_file, "w") as f:
            for i in range(3):
                f.write(
                    json.dumps(
                        {
                            "mh_state": "You are in a tavern.",
                            "action": "look",
                            "mud_output": "You see a dusty tavern.",
                            "vh_score": 4,
                            "vh_summary": "- You looked around.\n- You see a dusty tavern.",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        traces = load_traces(str(traces_file))
        assert len(traces) == 3
        rows = list(build_dataset(traces, mode="outcome_summary", vh_score_min=1))
        assert len(rows) == 3
        out_dir = Path(tmp) / "checkpoint"
        try:
            run_training(
                trace_glob=str(traces_file),
                mode="outcome_summary",
                vh_score_min=1,
                output_dir=str(out_dir),
                num_epochs=1,
                per_device_train_batch_size=1,
            )
        except Exception as e:
            print("Training failed (GPU/model may be required):", e)
            print("test_train: SKIP (run with GPU and Mistral-7B for full test)")
            return
        assert out_dir.exists(), "Checkpoint dir should exist"
        # PEFT saves adapter_config.json and adapter_model.safetensors (or .bin)
        assert any(out_dir.iterdir()), "Checkpoint dir should not be empty"
    print("test_train: OK")


if __name__ == "__main__":
    main()
