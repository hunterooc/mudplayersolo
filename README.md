# MUD World Model

Five-agent MUD world model: MH, PH, WM, DH, VH. WM (Mistral-7B) is local and trainable; MH/PH/DH/VH use GPT-5-mini (API). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full spec.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set OPENAI_API_KEY, MUD_HOST, MUD_PORT
```

## Config

- `.env`: `OPENAI_API_KEY`, `MUD_HOST`, `MUD_PORT`
- `config.yaml`: timeouts, paths, model names, training options

## Run

- **Orchestrator** (main loop): `python main.py [max_steps]` — defaults to 10 rounds then exits; pass `0` for unlimited. Logs to `data/logs/orchestrator.log` and stderr (MH/PH/WM/DH/VH per step).
- **Interrupt**: Press **Ctrl+C** to stop gracefully; the client disconnects and the final step count is logged (no traceback).
- **Manual override**: While the orchestrator is running in a TTY, type a command in the same terminal and press **Enter**. That line is sent to the MUD on the next cycle instead of DH’s choice.
- **Train WM** on logs: `python train.py [--trace-glob ...] [--mode outcome_summary|next_line] [--output-dir ...]`

## Tests

- `python scripts/test_memory.py` — memory read/write (no deps)
- `python scripts/test_mud_client.py` — telnet connect (needs MUD_HOST)
- `python scripts/test_agents_api.py` — MH, PH, DH, VH (needs OPENAI_API_KEY)
- `python scripts/test_wm.py` — WM inference (needs GPU/model)
- `python scripts/test_train.py` — training pipeline (needs GPU + transformers/datasets/peft; otherwise skips)

## Layout

- `src/mud/` — telnet client, buffer, silence detection
- `src/agents/` — MH, PH, WM, DH, VH
- `src/memory/` — commands.md, current_location.md, mobs.md
- `src/orchestrator.py` — main loop
- `prompts/` — prompt templates
- `data/` — memory files, `data/logs/traces.jsonl`, `data/checkpoints/wm`
