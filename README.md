# MUD Player (LLM)

An autonomous MUD player using LLM agents for situational awareness and decision-making, with an auto-prompt-engineering loop that improves gameplay over time.

**Disclaimer:** This project was vibecoded. No guarantees or warranties. Use at your own risk.

## Testing

All testing was done on [tbaMUD](https://github.com/tbamud/tbamud), which is based on CircleMUD and DikuMUD. The command syntax and game mechanics assume a DikuMUD-style MUD.

## Architecture Overview

- **MH (Memory Head):** 6 parallel API calls updating situational awareness (location, inventory, equipment, stats, spells, session summary)
- **DH (Decision Head):** Chooses the next action based on game state and goals; updates goals after each action
- **Critic/Engineer/Editor loop:** Every N steps, reviews gameplay and automatically improves the DH prompt

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set OPENAI_API_KEY, MUD_HOST, MUD_PORT
# Optionally set MUD_CHARACTER and MUD_PASSWORD for auto-login
```

## Config

- `.env`: `OPENAI_API_KEY`, `MUD_HOST`, `MUD_PORT`, `MUD_CHARACTER`, `MUD_PASSWORD`
- `config.yaml`: timeouts, paths, model names (including separate models for critic/engineer/editor), orchestrator options

Key config options:
- `orchestrator.critic_interval`: Run the auto-prompt-engineering loop every N steps (default: 20, set to `null` to disable)
- `openai.model_critic` / `model_engineer`: Smarter model (e.g. gpt-4o) for analysis
- `openai.model_editor`: Cheaper model (e.g. gpt-4o-mini) for applying edits

## Run

- **Orchestrator** (main loop): `python main.py [max_steps]` — defaults to 10 rounds then exits; pass `0` for unlimited.
- **Interrupt**: Press **Ctrl+C** to stop gracefully.
- **Manual override**: While running in a TTY, type a command and press **Enter** to inject it as the next action instead of DH's choice.

## Prompt Reset / Rollback

- Baseline prompt copies live in `prompts/baselines/` (`dh.txt`, `engineer.txt`, `editor.txt`).
- Reset DH prompt only: `python scripts/reset_prompts.py`
- Reset all editable prompts: `python scripts/reset_prompts.py --all`
- Preview without writing: `python scripts/reset_prompts.py --dry-run`

## Logs

- `data/logs/orchestrator.log` — high-level orchestrator events
- `data/logs/gameplay.jsonl` — per-step debug log (MH context, action, MUD output, goals)
- `data/logs/critic.jsonl` — critic diagnoses (what's going well / not going well)
- `data/logs/engineer_changes.jsonl` — specific prompt changes suggested by the engineer

All logs are reset at the start of each run.

## Tests

- `python scripts/test_memory.py` — memory read/write (no deps)
- `python scripts/test_mud_client.py` — telnet connect (needs MUD_HOST)
- `python scripts/test_agents_api.py` — MH, DH action, DH goals (needs OPENAI_API_KEY)

## Layout

- `src/mud/` — telnet client, buffer, silence detection
- `src/agents/` — MH, DH, Critic, Engineer, Editor
- `src/memory/` — memory file read/write
- `src/orchestrator.py` — main loop including auto-prompt-engineering
- `prompts/` — prompt templates (mh_*.txt, dh.txt, dh_goals.txt, critic.txt, engineer.txt, editor.txt)
- `prompts/baselines/` — immutable prompt rollback copies used by `scripts/reset_prompts.py`
- `data/` — memory files (.md), logs under `data/logs/`

## Memory Files

- `commands.md` — persistent, user-populated command reference (never cleared)
- `spells.md` — updated from kickoff only (e.g. after `practice`)
- `current_location.md`, `session_summary.md`, `goals.md`, `inventory.md`, `equipment.md`, `statbar.md` — cleared each run, updated by MH/DH
