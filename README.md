# MUD Player (LLM)

Two-agent MUD player: MH (situational awareness) and DH (goals + next move). Both use OpenAI API. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the spec.

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
- `config.yaml`: timeouts, paths, model name, orchestrator options

## Run

- **Orchestrator** (main loop): `python main.py [max_steps]` — defaults to 10 rounds then exits; pass `0` for unlimited. Logs to `data/logs/orchestrator.log` and stderr (MH/DH per step). Debug log (what MH sent to DH each step) is written to `data/logs/gameplay.jsonl`.
- **Interrupt**: Press **Ctrl+C** to stop gracefully; the client disconnects and the final step count is logged (no traceback).
- **Manual override**: While the orchestrator is running in a TTY, type a command in the same terminal and press **Enter**. That line is sent to the MUD on the next cycle instead of DH's choice.

## Tests

- `python scripts/test_memory.py` — memory read/write (no deps)
- `python scripts/test_mud_client.py` — telnet connect (needs MUD_HOST)
- `python scripts/test_agents_api.py` — MH, DH action, DH goals (needs OPENAI_API_KEY)

## Layout

- `src/mud/` — telnet client, buffer, silence detection
- `src/agents/` — MH, DH (action + goals)
- `src/memory/` — **commands.md** (persistent, user-populated; never cleared or updated by the app), **spells.md** (updated from kickoff e.g. after `practice` only), current_location.md, session_summary.md, goals.md, inventory.md, equipment.md, statbar.md
- `src/orchestrator.py` — main loop
- `prompts/` — prompt templates (mh.txt, dh.txt, dh_goals.txt)
- `data/` — memory files, `data/logs/orchestrator.log`, `data/logs/gameplay.jsonl`
