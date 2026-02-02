# MUD Player Architecture (MH + DH)

## Agents and Their Roles

### 1. MH — Memory Head

- **Model**: GPT-5-mini (API)
- **Purpose**: Maintains and updates the agent's internal game state and current room snapshot (situational awareness).

**Input:**

- New MUD output since last cycle
- Current versions of memory files (commands, current_location, mobs, session_summary, inventory, equipment, statbar)

**Prompt:**

MH updates memory files only. **current_location.md** is the current room only: room name and short description, exits (directions or doors; do not list a direction if the MUD said "you cannot go that way"), what's on the ground, mobs/NPCs present. Also commands.md (discovered commands and effects), mobs.md (encountered enemies/NPCs), session_summary.md (the story so far, in narrative form), inventory.md, equipment.md, and **statbar.md** (HP, mana, movement points when visible).

**Output:**

- Updated memory files (commands, current_location, mobs, session_summary, inventory, equipment, statbar). DH receives this full situational context each turn.

---

### 2. DH — Decision Head

- **Model**: GPT-5-mini (API)
- **Purpose**: (1) Chooses the next MUD command from MH state + goals. (2) After each action, updates **goals.md** from the outcome.

**Two modes:**

1. **Action mode:** Given full MH state (current_location, session_summary, statbar, goals, inventory, equipment, commands, mobs, game_buffer, play_summary), output the single best next command. No candidate list—DH decides freely from state and goals.
2. **Goals mode:** Given game state at decision time, the action taken, and the actual MUD output, output updated goals.md content (mark completed, add immediate goals from outcome, keep or adjust long-term goals). Format: ## Long-Term Goals / ## Immediate Goals with bullet lists.

**Action criteria (in order of priority):** Safety (avoid death/heavy damage), Progress (XP, loot, new areas, goals), Learn or explore (new information when safe). Priority rule: survival first, then progress, then exploitation of known good options. Prefer actions that align with current goals when safety and feasibility allow.

**Output:**

- Action mode: one command string (e.g. "north", "get sword", "cast fireball goblin").
- Goals mode: the GOALS.MD section text (written to goals.md after each step).

---

## Runtime Flow

1. **Kickoff**: Sends commands like `look`, `score`, `inventory`, `equipment` to populate initial state.
2. **MH Update**: New MUD output → run_mh → updated memory files (commands, current_location, mobs, session_summary, inventory, equipment, statbar).
3. **DH Action**: Build context from memory + game_buffer + play_summary. Call run_dh_action → chosen command. (Manual override: user can type a command in the terminal to inject it instead.)
4. **Execute**: Send chosen command to MUD; wait for silence.
5. **DH Goals**: Call run_dh_goals(mh_state, action, actual_output, goals) → goals_update. Write goals_update to goals.md.
6. **Debug log**: Append one JSON object per step to `data/logs/gameplay.jsonl`: step, mh_context (what MH sent to DH), action, mud_output, goals_after. Use this to debug "what did DH see when it chose this action?"
7. **Repeat**: Next cycle starts with MH on the latest buffer.

---

## Debug Log Format

**Path:** `data/logs/gameplay.jsonl` (config: `paths.gameplay_log`).

**Per-line JSON fields:**

- `step`: int
- `mh_context`: object with keys current_location, session_summary, statbar, goals, inventory, equipment, commands, mobs, game_buffer (last ~4k chars)
- `action`: string (command sent)
- `mud_output`: string (MUD response after action)
- `goals_after`: string (goals.md content after this step)

This keeps debugging focused on situational awareness and outcomes without any world-model or training fields.

---

## Notes

- MH and DH are both prompt-driven API calls (OpenAI).
- Goals are maintained by DH (goals update call) and written to goals.md after each step; DH action sees them on the next turn.
- Memory files are cleared at startup (current_location, session_summary, goals, inventory, equipment, statbar) so each run starts fresh.
- Manual override: type a command in the orchestrator terminal and press Enter to send it as the next action instead of DH's choice.
