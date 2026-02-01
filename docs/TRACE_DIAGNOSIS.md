# Trace/Log Diagnosis — Most Recent Run

Based on `data/logs/orchestrator.log` and `data/logs/traces.jsonl` (3 steps, Temple of Midgaard).

**Implementation note:** The codebase has since been updated: MH now maintains `current_location.md` (current room, exits, ground, mobs present) instead of `locations.md`; DH receives full picture (mh_state + game_buffer); WM prompt tightened. PH grounding was not changed per request.

---

## Summary of What Happened

| Step | Action chosen | WM prediction (gist) | Actual MUD output | VH score |
|------|----------------|----------------------|-------------------|----------|
| 1 | east | "You see a sign..." (medium conf) | "Alas, you cannot go that way..." | 1 |
| 2 | drink water from fountain | Generic "Game state" + "Your response" (medium) | "You can't find it!" | 1 |
| 3 | eat food | "You eat a piece of food" (low conf) | "You don't seem to have a food." | 2 |

All three chosen actions failed. The agent stayed hungry/thirsty and gained no exploration or progress.

---

## Diagnosed Issues

### 1. No visibility into valid exits or room contents

- MH state says "Location: Temple of Midgaard, southern end of the temple hall" but **does not list exits** or visible objects.
- PH proposed "east" and "enter donation room" without knowing if east is a valid exit or if the donation room is reachable from here.
- **Root cause**: MH is not instructed to extract and keep **exits** and **visible objects** from the last `look` (or equivalent) in the game output. So PH/DH have no notion of "you can only go south" or "you see: fountain, donation room entrance".

**Evidence**: `locations.md` is still empty after 3 steps; MH never wrote the current room or its exits.

---

### 2. PH proposing infeasible actions given state

- MH state explicitly says **"Inventory: Currently carrying nothing"** and **"You are hungry and thirsty"**.
- PH still proposed: "eat rations", "eat food", "get all", "drink water from fountain".
- "Drink water from fountain" and "look in donation room" assume objects/rooms that were never stated as present in the current room.

**Root cause**: PH prompt does not require **grounding**: "Only suggest actions that are feasible right now (e.g. do not suggest 'eat X' if inventory is empty; do not suggest using an object that is not in the current room or inventory)."

---

### 3. WM output is prompt-leaky and often not MUD-style

- WM repeatedly outputs template text: "---", "Game state:", "Example:", "Your response:", "Correct response:", "Expected output:".
- WM sometimes just repeats the MH state instead of predicting the MUD’s next message.
- So DH often sees uninformative or misleading "predictions" and still has to pick an action.

**Root cause**: WM prompt is short and the base model (untrained Mistral) tends to complete the prompt format rather than a single, clean MUD-style paragraph. No few-shot example of desired output format.

---

### 4. DH has no direct view of game state

- DH only sees: (action, WM predicted text, confidence) + commands/locations/mobs.
- DH does **not** see: current MH state, inventory, or last game buffer.
- So when WM says "You eat a piece of food", DH cannot cross-check "inventory is empty" and reject that option.

**Root cause**: DH prompt (and `run_dh` in code) does not receive `mh_state` or recent MUD output. So DH cannot sanity-check WM predictions against state.

---

### 5. Survival objective not leading to feasible sequences

- Agent is hungry/thirsty; objectives say "when hurt or in danger, prefer healing..." and "gather items that might help".
- But PH never proposed a **sequence** like: look → go to donation room → get rations/water → eat/drink.
- PH proposed one-shot actions (eat food, drink from fountain) that aren’t feasible without first moving and getting items.

**Root cause**: PH is not instructed to prefer **immediately feasible** actions that address survival (e.g. "if hungry and inventory empty, prefer movement/look/get from current room first") or to avoid actions that are impossible in the current state.

---

### 6. locations.md never populated

- After 3 steps, `locations.md` is still empty.
- So "known locations" never includes "Temple of Midgaard – southern end, exits: south (?), donation room (?)", etc.
- PH and DH therefore have no memory of where we are or where we can go.

**Root cause**: Either MH is not extracting location/exits from MUD output, or the instruction to update locations.md is not strong enough (e.g. "always add current room and its exits when we see new room text").

---

## Suggested Improvements

### A. MH: Extract exits and room contents

- In **prompts/mh.txt**, add an explicit instruction:
  - "From the game output, always extract: (1) current room name and description, (2) **exits or directions** mentioned (e.g. north, south, east, donation room), (3) **visible objects** (e.g. fountain, chest, NPCs). Include these in the state summary and in locations.md (current room + exits)."
- Optionally add: "If the MUD says 'You cannot go that way', record that the attempted direction is not an exit from the current room."

This gives PH/DH a notion of "valid exits" and "visible objects".

---

### B. PH: Ground actions in current state

- In **prompts/ph.txt**, add:
  - "Only suggest actions that are **feasible right now**: do not suggest 'eat X' or 'drink X' if the player has no such item in inventory; do not suggest using an object (e.g. fountain) unless it appears in the current room description or state; prefer movement/look/get when you lack information about the room or need to obtain items."
  - "If the player is hungry/thirsty and inventory is empty, prefer actions that might lead to food/water (e.g. look, move to a room that might have donations/items, get all) rather than direct 'eat'/'drink' with no item."

This reduces impossible actions and aligns with survival.

---

### C. DH: Pass MH state (and optionally last MUD line) to DH

- In **src/orchestrator.py**, pass `mh_state` into `run_dh` (and add a parameter to `run_dh`).
- In **prompts/dh.txt**, add a section:
  - "Current game state summary: {{mh_state}}"
  - "Use this to reject options that are impossible (e.g. eating when inventory is empty; using an object not in the room)."
- In **src/agents/dh.py**, load the DH template and add `mh_state` to the template variables when calling the API.

This lets DH override bad WM predictions when they contradict state.

---

### D. WM: Reduce prompt leakage and clarify output format

- In **prompts/wm.txt**:
  - Ask for exactly one short paragraph: "Output only the exact text the MUD would display after this action (one short paragraph). Do not repeat the game state. Do not output labels like 'Expected output:' or 'Your response:'."
  - Then: "On the next line write only: Confidence: high|medium|low."
- Consider adding one **few-shot example**: one (state, action) pair and the desired "MUD line" + "Confidence: medium" so the model sees the desired format.

This should reduce template repetition and make WM output more useful for DH.

---

### E. locations.md: Stronger MH instruction

- In **prompts/mh.txt**, add:
  - "Update locations.md every time the game output describes a new room or new exits. At minimum, keep an entry for the **current room** with its name, short description, and **list of exits or directions** we have seen (from 'look' or from attempted movement)."

This should prevent locations.md from staying empty when the agent has seen room text.

---

### F. Optional: Exits in game buffer for PH

- Ensure the **game_buffer** passed to PH includes the output of the last `look` (or equivalent) so that "recent game buffer" actually contains room description and exits when PH suggests moves. Currently the buffer is "since last command"; if the last command was "east" and the MUD replied "You cannot go that way", PH still gets that—but if the previous cycle had run "look", that output might be in an earlier buffer. So the flow is OK as long as MH summarizes "exits" from that look; the main fix is (A) and (E).

---

## Priority Order

1. **A + E** — MH extracts and records exits/room contents and updates locations.md. Highest impact so PH/DH know what’s possible.
2. **B** — PH grounds actions (no eat/drink without item; prefer feasible survival steps).
3. **C** — DH gets mh_state so it can reject impossible options.
4. **D** — WM prompt tightened and optional few-shot to improve prediction quality.

Implementing 1–3 should already reduce impossible actions and make survival/exploration behavior more coherent; 4 improves the quality of DH’s choices over time.
