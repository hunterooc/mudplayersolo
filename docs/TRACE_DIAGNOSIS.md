# Gameplay Log / Debugging

The orchestrator writes a **debug log** to `data/logs/gameplay.jsonl` (one JSON object per line, one per step). Use it to see what situational awareness DH had when it chose each action and what the MUD returned.

## Log format

Each line is a JSON object with:

- **step**: Step number (1, 2, …).
- **mh_context**: What MH sent to DH (structured):
  - `current_location`, `session_summary`, `statbar`, `goals`, `inventory`, `equipment`, `commands`, `mobs`, `game_buffer` (last ~4k chars of recent MUD output).
- **action**: The command sent to the MUD.
- **mud_output**: The MUD’s response after that command.
- **goals_after**: The contents of goals.md after this step (after DH goals update).

## How to use it

1. **Why did DH choose this action?**  
   Inspect `mh_context` for that step: room, inventory, goals, and `game_buffer` show exactly what DH saw.

2. **Did the action succeed or fail?**  
   Compare `action` with `mud_output` (e.g. “You open the door.” vs “You don’t see that here.”).

3. **How did goals change?**  
   Compare `goals_after` across steps or with the previous step’s `mh_context.goals`.

4. **Reproduce a bad decision**  
   Use `mh_context` to see if DH was missing info (e.g. no exits in current_location, empty inventory but DH chose “eat food”). Adjust MH or DH prompts if needed.

Example (one line, pretty-printed):

```json
{
  "step": 2,
  "mh_context": {
    "current_location": "Temple of Midgaard, southern end...\nExits: south",
    "session_summary": "Entered temple...",
    "statbar": "20H 100M 83V",
    "goals": "## Immediate Goals\n- Explore north",
    "inventory": "",
    "equipment": "...",
    "commands": "look, north, south, ...",
    "mobs": "",
    "game_buffer": "> look\n..."
  },
  "action": "north",
  "mud_output": "Alas, you cannot go that way.",
  "goals_after": "## Immediate Goals\n- Find valid exit"
}
```

The orchestrator also logs per-step summaries to `data/logs/orchestrator.log` and stderr.
