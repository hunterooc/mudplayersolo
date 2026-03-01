# MUD Player Architecture

## Overview

An autonomous MUD player with three main components:

1. **MH (Memory Head):** Maintains situational awareness via parallel API calls
2. **DH (Decision Head):** Chooses actions and updates goals
3. **Auto-Prompt-Engineering Loop (Critic → Engineer → Editor):** Periodically reviews gameplay and improves the DH prompt

All testing was done on [tbaMUD](https://github.com/tbamud/tbamud) (based on CircleMUD/DikuMUD).

---

## Agents and Their Roles

### 1. MH — Memory Head (parallel)

- **Model**: Configurable (default: gpt-4o-mini)
- **Purpose**: Maintains the agent's internal game state (situational awareness). Runs **six API calls in parallel**, one per file.

**Per-file prompts** (under `prompts/`): mh_current_location.txt, mh_session_summary.txt, mh_inventory.txt, mh_equipment.txt, mh_statbar.txt, mh_spells.txt.

**Input (per call):** New MUD output + previous content for that file.

**Output:** Updated memory files (current_location, session_summary, inventory, equipment, statbar, spells). On partial failure, that file keeps its previous value and a warning is logged.

---

### 2. DH — Decision Head

- **Model**: Configurable (default: gpt-4o-mini)
- **Purpose**: (1) Chooses the next MUD command. (2) Updates goals based on outcomes.

**Two modes:**

1. **Action mode:** Given full MH state + goals + game buffer, output the single best command. Also outputs a reason/rationale for the choice.
2. **Goals mode:** Given state, action taken, and MUD output, update goals.md (mark completed, add new goals).

**Action criteria (priority order):** Survival → Progress → Exploration. Respects inventory/spell constraints (won't try to eat food not in inventory or cast unknown spells).

**Output format (action mode):**
```
Reason: <rationale>
Command: <command>
```

---

### 3. Auto-Prompt-Engineering Loop

Every N steps (configurable via `orchestrator.critic_interval`), three agents run in sequence to improve the DH prompt:

#### Critic
- **Model**: Smarter model (e.g. gpt-4o)
- **Input**: All gameplay log entries since last critic run
- **Output**: Structured diagnosis — what's going well (2-4 bullets), what's not going well (2-4 bullets)
- **Logs to**: `data/logs/critic.jsonl`

#### Engineer
- **Model**: Smarter model (e.g. gpt-4o)
- **Input**: Critic's diagnosis + current DH prompt (prompts/dh.txt)
- **Output**: Strict, bounded edit instructions (max 2 one-sentence instructions) or `No changes needed.`
- **Logs to**: `data/logs/engineer_changes.jsonl`

#### Editor
- **Model**: Cheaper model (e.g. gpt-4o-mini)
- **Input**: Engineer's edit instructions + current DH prompt
- **Output**: Complete new DH prompt (written to prompts/dh.txt), or unchanged prompt if instructions are malformed/invalid

This loop allows the agent to learn from mistakes (e.g. repeating failed commands) and improve its decision-making prompt automatically.

Guardrails currently in prompts:
- Engineer is constrained to tiny, deduplicated edits and must avoid metadata output like `Reason:`/`Command:`.
- Editor applies patch-style instructions only, preserves placeholders/section order, and falls back to unchanged prompt when instructions are invalid.

---

## Runtime Flow

1. **Kickoff**: Send commands like `look`, `score`, `inventory`, `equipment`, `practice` to populate initial state.

2. **Main Loop** (each step):
   - **MH Update**: New MUD output → 6 parallel API calls → updated memory files
   - **DH Action**: Build context → run_dh_action → (reason, command)
   - **Execute**: Send command to MUD; wait for silence
   - **DH Goals**: run_dh_goals(state, action, output) → update goals.md
   - **Debug log**: Append to gameplay.jsonl

3. **Auto-Prompt-Engineering** (every N steps):
   - Run Critic on gameplay log since last run
   - Run Engineer with diagnosis + current DH prompt
   - Run Editor to apply changes → write new prompts/dh.txt

4. **Repeat** until max_steps or disconnect.

Rollback workflow:
1. Restore baseline prompts from `prompts/baselines/` with `python scripts/reset_prompts.py` (or `--all`).
2. Start orchestrator.
3. If edits become repetitive/noisy again, reset prompts and continue.

---

## Debug Log Format

**Path:** `data/logs/gameplay.jsonl`

**Per-line JSON fields:**
- `step`: int
- `mh_context`: object with current_location, session_summary, statbar, goals, inventory, equipment, commands, spells, mobs, game_buffer
- `action`: string (command sent)
- `mud_output`: string (MUD response)
- `goals_after`: string (goals.md after this step)

---

## Config Reference

Key settings in `config.yaml`:

```yaml
orchestrator:
  critic_interval: 20        # Run critic/engineer/editor every N steps (null = disabled)
  game_buffer_max_lines: 100
  game_buffer_max_chars_for_critic: 16000

openai:
  model: gpt-4o-mini         # Default model (MH, DH)
  model_critic: gpt-4o       # Smarter model for critic
  model_engineer: gpt-4o     # Smarter model for engineer
  model_editor: gpt-4o-mini  # Cheaper model for editor

paths:
  gameplay_log: data/logs/gameplay.jsonl
  critic_log: data/logs/critic.jsonl
  engineer_changes_log: data/logs/engineer_changes.jsonl
```

---

## Notes

- All agents are prompt-driven API calls (OpenAI).
- Memory files (except commands.md) are cleared at startup for a fresh run.
- Log files (gameplay, critic, engineer_changes) are also cleared at startup.
- Manual override: type a command in the orchestrator terminal to inject it instead of DH's choice.
- The DH prompt (prompts/dh.txt) may be modified by the auto-prompt-engineering loop during a run.
- Prompt baselines are stored in `prompts/baselines/` and can be restored with `scripts/reset_prompts.py`.
