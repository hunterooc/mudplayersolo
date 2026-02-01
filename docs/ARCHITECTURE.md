# MUD Agent Architecture and Workflow Summary

## Agents and Their Roles

### 1. MH — Memory Head

- **Model**: GPT-5-mini (API)
- **Purpose**: Maintains and updates the agent's internal game state and current room snapshot.

**Input:**

- New MUD output since last cycle
- Current versions of memory files (commands, current_location, mobs, session_summary)

**Prompt:**

MH updates memory files only (no monolithic state summary). **current_location.md** is the current room only (updated every time the room or our view of it changes): room name and short description, exits (directions or doors; do not list a direction if the MUD said "you cannot go that way"), what's on the ground, mobs/NPCs present. Also commands.md (discovered commands and effects), mobs.md (encountered enemies/NPCs), session_summary.md (the story so far, in narrative paragraph form to avoid overlap with list-style files), and **statbar.md** (HP, mana, movement points when visible in output).

**Output:**

- Updated memory files (commands, current_location, mobs, session_summary, inventory, equipment, statbar). There is no separate state summary file; agents receive granular .md files (and WM/VH receive a composed context built from current_location + session_summary + statbar for their single "game state" field).

---

### 2. PH — Policy Head

- **Model**: GPT-5-mini (API)
- **Purpose**: Proposes up to 7 next plausible player actions aligned with survive, explore, and gain experience; includes a combat option when a mob is present.

**Input:**

- Recent game buffer (context)
- Current versions of memory files: commands, current_location, mobs, session_summary, goals, inventory, equipment, statbar

**Prompt:**

PH is given explicit objectives: **Survive** (avoid death; when hurt or in danger, prefer healing, fleeing, or defensive actions); **Explore** (discover new areas and exits; try unseen directions or rooms when safe); **Gain experience** (engage in combat or quest-like actions when health/resources allow; gather items and information that might help later). PH also receives **goals.md** (long-term and immediate goals maintained by VH). Prefer actions that make progress toward current goals (especially immediate goals); if no goals are set, favor explore/survive/gain experience. Based on game state, recent events, and memory files, PH suggests up to 7 actions that mix these goals where possible. Include "wait and observe" if viable. All actions are short MUD-style commands. Prefer actions that use or extend known commands/locations from memory when that serves survival, exploration, or gaining experience.

**Output:**

- List of up to 7 possible action strings (including combat when mob present)

---

### 3. WM — World Model

- **Model**: Mistral-7B (local, fine-tunable)
- **Purpose**: Predicts outcome of each candidate action.
- **Mode**: Next-token completion (causal LM generate). For a chat-tuned model (e.g. Mistral-7B-Instruct) you would use the model's chat template instead.

**Input (per action):**

- MH state
- Action string

**Prompt:**

Predict what the MUD will display next. Output only the exact text the MUD would show (one short paragraph). Do not repeat the game state or use labels like "Expected output:". Then on the next line: Confidence: high (or medium or low).

**Output (per action):**

- `predicted_text`
- `confidence`

---

### 4. DH — Decision Head

- **Model**: GPT-5-mini (API)
- **Purpose**: Chooses best action from WM predictions using the full picture and defined criteria.

**Input:**

- Recent game buffer (full picture at decision time)
- List of actions + WM predictions + confidences
- Current versions of memory files (commands, current_location, mobs, session_summary, goals)

**Prompt:**

DH receives the full picture: current game state, recent MUD output, each option's predicted outcome, and **goals.md** (long-term and immediate goals). When choosing, prefer options that align with current goals when safety and feasibility allow. Use state and buffer to reject options that are impossible (e.g. eating when inventory is empty; using an object not in the current room). Criteria (in order of priority): **Safety** — avoid actions the prediction suggests could lead to death or heavy damage unless no safer option exists; if state suggests low HP or danger, strongly prefer healing, fleeing, or defensive actions. **Progress** — gaining experience or loot, entering new areas, learning new commands or mob behavior, or advancing toward a goal. **Learn or explore** — prefer options that reveal new information when confidence is at least medium and the outcome is not clearly lethal. **Priority rule:** When in doubt: survival first, then progress, then exploitation of already-known good options.

**Output:**

- Chosen action (or ranked list)

---

### 5. VH — Value Head

- **Model**: GPT-5-mini (API)
- **Purpose**: Grades WM's prediction, summarizes actual outcome, and updates **goals.md** (long-term and immediate goals).

**Input:**

- MH state at decision time
- Chosen action
- WM's predicted outcome
- Actual MUD output since action
- Current goals (goals.md)

**Prompt:**

VH evaluates how well the world model predicted the outcome, summarizes what actually happened in 1–3 bullet points, and outputs an updated **goals.md**: mark completed or remove goals that were achieved, add new immediate goals if the outcome suggests one (e.g. found a new area → "Explore north"), and add or keep long-term goals as appropriate. Format: ## Long-Term Goals / ## Immediate Goals with bullet lists. If no goals exist yet, VH may add initial goals based on the outcome.

**Output:**

- `vh_score`: integer 1–5
- `vh_summary`: brief text summary of what occurred
- `goals_update`: updated goals.md content (written to disk after VH; PH and DH see it on the next step)

---

## Runtime Flow

1. **Kickoff**: Triggered via start command or completion of previous VH step. Sends commands like `look`, `score`, `inventory` to populate initial state.
2. **MH Update**: Triggered by 10s silence or kickoff. Updates memory files using new MUD output (commands, current_location, mobs, session_summary, inventory, equipment, statbar).
3. **PH Action Proposal**: Generates up to 7 plausible actions using memory files (including combat when mob present).
4. **WM Prediction**: Predicts outcome and confidence for each action.
5. **DH Selection**: Chooses best action from WM predictions and memory-informed context.
6. **Execute Action**: Sends command to MUD.
7. **VH Evaluation**: After next 10s of silence, compares WM prediction to actual result. Outputs score, consequence summary, and updated **goals.md**. Goals are written to disk immediately after VH (so step N+1 PH/DH see them).
8. **Logging**: Store full trace: MH state, action, WM prediction, VH score, VH summary, goals (at decision time), MUD output.
9. **Repeat**: Return to MH on next 10s silence.

---

## WM Training Tuple Format

Each trace written after a step includes:

**Input:**

```json
{
  "mh_state": "...",
  "action": "cast fireball goblin"
}
```

(The "mh_state" key in traces holds the composed game context at decision time: current_location + session_summary + statbar, so train.py continues to build the "Game state:" block from it.)

**Targets (both logged for training):**

- **next_line**: First substantive line of MUD output after the action (status bar / prompt excluded). Extracted at trace time so WM can be trained to predict the immediate next line.
- **outcome_summary**: VH's summary of what actually happened (same as vh_summary). VH produces this when scoring; it summarizes the consequence of the action in 1–3 bullet points so WM can be trained to predict outcome, not just raw tokens.

**VH Score**: 1–5, used to filter or weight training samples.

**Training Modes** (train.py):

- **next_line**: LM loss on next_line (first non-status MUD line). Keeps WM grounded in surface text.
- **outcome_summary**: Instruction tuning on outcome_summary (VH summary). Teaches WM causal/consequence understanding.
- Filter or weigh loss by `vh_score`.

---

## Notes

- WM is the only trainable component initially.
- MH, PH, DH, VH are all prompt-driven GPT-5-mini calls.
- Action loop triggered on prompt or timer (10s MUD silence).
- VH generates both a score and a consequence summary to serve as supervision signal for WM.
- MH maintains persistent memory files (commands, current_location, mobs, session_summary, inventory, equipment, **statbar**) which PH consumes each turn (DH receives all except statbar). There is no monolithic state summary file; WM and VH receive a single "game state" string built by composing current_location + session_summary + statbar at decision time (stored in trace["mh_state"] for training). **statbar.md** holds HP, mana, and movement points; PH and VH (and WM via composed context) receive it; DH does not. **goals.md** is maintained by VH after each action evaluation (long-term and immediate goals); it is cleared at startup so each run starts with no goals. PH and DH receive goals so they can propose and select goal-aligned actions; if VH omits the GOALS section or returns empty, previous goals are kept (not overwritten).
