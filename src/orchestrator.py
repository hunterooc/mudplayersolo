"""Main loop: kickoff -> MH -> DH(action) -> execute -> DH(goals) -> debug log -> repeat."""
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from src.config import load_config, resolve_path, PROJECT_ROOT
from src.mud.client import MUDClient
from src.memory.store import MemoryStore
from src.agents.mh import run_mh
from src.agents.dh import run_dh_action, run_dh_goals


def _format_play_summary(commands_sent: list[str]) -> str:
    """Format list of commands sent this session for DH (Turn 1: X. Turn 2: Y. ...)."""
    if not commands_sent:
        return "None yet (this is the first turn)."
    return " ".join(f"Turn {i}: {cmd}." for i, cmd in enumerate(commands_sent, 1))


def _strip_login_menu_from_buffer(buffer: str, kickoff_commands: list[str]) -> str:
    """
    Remove the login/entry menu from the start of the buffer so MH never sees it.
    Keep only output from the first kickoff command onward (e.g. from "> look" onward).
    """
    if not buffer or not kickoff_commands:
        return buffer
    first_cmd = (kickoff_commands[0] or "look").strip()
    marker = "> " + first_cmd
    idx = buffer.find(marker)
    if idx >= 0:
        return buffer[idx:].strip()
    return buffer


def _make_orchestrator_logger(logs_dir: Path) -> logging.Logger:
    """Logger to data/logs/orchestrator.log and stderr for debugging."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "orchestrator.log"
    log = logging.getLogger("orchestrator")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(asctime)s [orch] %(message)s"))
    log.addHandler(sh)
    return log


def run_cycle(
    client: MUDClient,
    memory: MemoryStore,
    commands: str,
    spells: str,
    current_location: str,
    mobs: str,
    session_summary: str,
    inventory: str,
    equipment: str,
    statbar: str,
    step: int,
    log: Optional[logging.Logger] = None,
    new_output_override: Optional[str] = None,
    commands_sent_this_session: Optional[list[str]] = None,
    inject_command: Optional[str] = None,
) -> tuple[str, str, str, str, str, str, str, Optional[str], Optional[str], Optional[str]]:
    """
    One full cycle: MH -> DH(action) -> execute -> DH(goals) -> debug log.
    Returns (commands, current_location, mobs, session_summary, inventory, equipment, statbar, chosen_action, goals_after, mud_output).
    """
    cfg = load_config()
    silence_timeout = cfg.get("mud", {}).get("silence_timeout_sec", 10.0)
    gameplay_log_path = resolve_path("gameplay_log")
    gameplay_log_path.parent.mkdir(parents=True, exist_ok=True)
    goals = memory.read_goals()

    # 1. MH update (use override for step 1 so MH sees full kickoff output including room from "look")
    new_output = new_output_override if new_output_override is not None else client.get_buffer_since_last_command()
    commands, current_location, mobs, session_summary, inventory, equipment, statbar = run_mh(
        new_output=new_output,
        commands=commands,
        spells=spells,
        current_location=current_location,
        mobs=mobs,
        session_summary=session_summary,
        inventory=inventory,
        equipment=equipment,
        statbar=statbar,
        memory_store=memory,
    )
    context_at_decision = (current_location or "").strip() + "\n\n" + (session_summary or "").strip() + "\n\n" + (statbar or "").strip()
    if log:
        log.info("step=%d MH (first 200 chars context): %s", step, (context_at_decision or "")[:200].replace("\n", " "))

    # Build game buffer for DH
    full_buffer = client.get_full_buffer()
    max_lines = (cfg.get("orchestrator") or {}).get("game_buffer_max_lines", 100)
    full_lines = full_buffer.splitlines()
    n = max(max_lines, len(full_buffer.splitlines()))
    game_buffer = "\n".join(full_lines[-n:]) if len(full_lines) > n else full_buffer
    if not game_buffer.strip():
        game_buffer = new_output

    commands_sent = commands_sent_this_session or []
    play_summary = _format_play_summary(commands_sent)

    # 2. If user injected a command, use it; else DH action
    if inject_command and inject_command.strip():
        chosen = inject_command.strip()
        if log:
            log.info("step=%d using injected command: %s", step, chosen)
    else:
        chosen = run_dh_action(
            game_buffer=game_buffer,
            commands=commands,
            spells=spells,
            current_location=current_location,
            mobs=mobs,
            session_summary=session_summary,
            goals=goals,
            inventory=inventory,
            equipment=equipment,
            statbar=statbar,
            play_summary=play_summary,
        )
        if log:
            log.info("step=%d DH chose: %s", step, chosen)

    # "wait and observe" = no command; wait for silence only, skip send/goals/log
    if chosen and chosen.strip().lower() == "wait and observe":
        if log:
            log.info("step=%d wait and observe: no command sent", step)
        client.wait_silence(timeout_sec=silence_timeout)
        return commands, current_location, mobs, session_summary, inventory, equipment, statbar, "(wait)", goals, None

    # 3. Execute
    client.send(chosen)
    if log:
        log.info("step=%d sent: %s", step, chosen)

    # 4. Wait for MUD response
    client.wait_silence(timeout_sec=silence_timeout * 2)
    mud_output = client.get_buffer_since_last_command()
    if log and mud_output:
        mud_one_line = mud_output.replace("\r", "").replace("\n", " | ").strip()
        log.info("step=%d game said: %s", step, mud_one_line[:500] + (" ..." if len(mud_one_line) > 500 else ""))

    # 5. DH goals update
    goals_update = run_dh_goals(
        mh_state=context_at_decision,
        action=chosen,
        actual_output=mud_output,
        goals=goals,
    )
    if goals_update and goals_update.strip():
        memory.write_goals(goals_update)
        goals_after = goals_update
        if log:
            log.info("step=%d wrote goals.md (%d chars)", step, len(goals_update))
    else:
        goals_after = goals
        if log:
            log.info("step=%d DH goals returned no update; goals.md unchanged", step)

    # 6. Debug log: what MH sent to DH, action, outcome, goals_after
    mh_context = {
        "current_location": (current_location or "").strip(),
        "session_summary": (session_summary or "").strip(),
        "statbar": (statbar or "").strip(),
        "goals": (goals or "").strip(),
        "inventory": (inventory or "").strip(),
        "equipment": (equipment or "").strip(),
        "commands": (commands or "").strip(),
        "mobs": (mobs or "").strip(),
        "game_buffer": game_buffer[-4000:] if game_buffer else "",  # last 4k chars for inspection
    }
    debug_entry = {
        "step": step,
        "mh_context": mh_context,
        "action": chosen,
        "mud_output": mud_output,
        "goals_after": goals_after,
    }
    with open(gameplay_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(debug_entry, ensure_ascii=False) + "\n")

    # 7. Update memory with the response we just got (so next cycle has it)
    mud_output_final = client.get_buffer_since_last_command()
    commands, current_location, mobs, session_summary, inventory, equipment, statbar = run_mh(
        new_output=mud_output_final,
        commands=commands,
        spells=spells,
        current_location=current_location,
        mobs=mobs,
        session_summary=session_summary,
        inventory=inventory,
        equipment=equipment,
        statbar=statbar,
        memory_store=memory,
    )

    return commands, current_location, mobs, session_summary, inventory, equipment, statbar, chosen, goals_after, mud_output


def run(
    max_steps: Optional[int] = None,
    mud_host: Optional[str] = None,
    mud_port: Optional[int] = None,
) -> None:
    """Run the main loop until max_steps or disconnect."""
    cfg = load_config()
    mud_cfg = cfg.get("mud", {})
    orch_cfg = cfg.get("orchestrator", {})
    host = mud_host or os.environ.get("MUD_HOST")
    port = mud_port or int(os.environ.get("MUD_PORT", "23"))
    if not host:
        raise ValueError("MUD_HOST not set (env or config)")
    silence_timeout = mud_cfg.get("silence_timeout_sec", 10.0)
    kickoff_commands = orch_cfg.get("kickoff_commands", ["look", "score", "inventory", "equipment"])
    max_steps = max_steps if max_steps is not None else orch_cfg.get("max_steps")

    logs_dir = resolve_path("logs_dir")
    gameplay_log_path = resolve_path("gameplay_log")
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "orchestrator.log").write_text("")
    gameplay_log_path.parent.mkdir(parents=True, exist_ok=True)
    gameplay_log_path.write_text("")

    logger = _make_orchestrator_logger(logs_dir)
    logger.info("Starting orchestrator max_steps=%s host=%s port=%s", max_steps, host, port)

    memory_dir = resolve_path("memory_dir")
    memory_dir.mkdir(parents=True, exist_ok=True)
    for name in ("current_location.md", "session_summary.md", "goals.md", "inventory.md", "equipment.md", "statbar.md"):
        (memory_dir / name).write_text("", encoding="utf-8")
    logger.info("Cleared memory files for fresh run: %s", memory_dir)
    memory = MemoryStore(memory_dir=memory_dir)
    client = MUDClient(host=host, port=port, silence_timeout_sec=silence_timeout)
    client.connect()
    client.set_stream(sys.stdout)

    if os.environ.get("MUD_CHARACTER") and os.environ.get("MUD_PASSWORD"):
        client.login(step_sleep_sec=1.0)
        time.sleep(1.0)

    commands = memory.read_commands()
    spells = memory.read_spells()
    current_location = ""
    mobs = ""
    session_summary = ""
    inventory = ""
    equipment = ""
    statbar = ""

    logger.info("Kickoff: %s", kickoff_commands)
    for cmd in kickoff_commands:
        client.send(cmd)
        client.drain(timeout_sec=1.0)
    client.wait_silence(timeout_sec=silence_timeout * 2)
    kickoff_buffer = client.get_buffer_since_last_command()
    if kickoff_buffer:
        buf_one_line = kickoff_buffer.replace("\r", "").replace("\n", " | ").strip()
        logger.info("After kickoff, game said: %s", buf_one_line[:500] + (" ..." if len(buf_one_line) > 500 else ""))
    full_kickoff_buffer = _strip_login_menu_from_buffer(client.get_full_buffer(), kickoff_commands)

    step = 0
    commands_sent_this_session: list[str] = []
    stdin_inject_lock = threading.Lock()
    pending_stdin_inject: Optional[str] = None

    def _stdin_reader() -> None:
        nonlocal pending_stdin_inject
        while True:
            try:
                line = sys.stdin.readline()
            except (EOFError, OSError):
                break
            if not line:
                break
            line = line.strip()
            if line:
                with stdin_inject_lock:
                    pending_stdin_inject = line

    if sys.stdin.isatty():
        stdin_thread = threading.Thread(target=_stdin_reader, daemon=True)
        stdin_thread.start()
        logger.info("Manual override: type a command in this terminal and press Enter to send it as the next action.")

    try:
        while True:
            step += 1
            if max_steps is not None and step > max_steps:
                logger.info("Reached max_steps=%d; graceful exit.", max_steps)
                break
            if not client.is_connected:
                logger.warning("Disconnected after %d steps.", step - 1)
                break
            inject_command: Optional[str] = None
            with stdin_inject_lock:
                if pending_stdin_inject is not None:
                    inject_command = pending_stdin_inject
                    pending_stdin_inject = None
            if inject_command:
                logger.info("Injecting command: %s", inject_command)
            commands, current_location, mobs, session_summary, inventory, equipment, statbar, chosen, goals_after, mud_out = run_cycle(
                client=client,
                memory=memory,
                commands=commands,
                spells=spells,
                current_location=current_location,
                mobs=mobs,
                session_summary=session_summary,
                inventory=inventory,
                equipment=equipment,
                statbar=statbar,
                step=step,
                log=logger,
                new_output_override=full_kickoff_buffer if step == 1 else None,
                commands_sent_this_session=commands_sent_this_session,
                inject_command=inject_command,
            )
            if chosen == "(wait)":
                print(f"Step {step}: wait and observe (no command sent)")
            else:
                commands_sent_this_session.append(chosen)
                print(f"Step {step}: action={chosen!r}")
    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C).")
    finally:
        client.disconnect()
        logger.info("Stopped after %d step(s). Debug log: %s", step, gameplay_log_path)


if __name__ == "__main__":
    max_steps = 10
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
            max_steps = None if n == 0 else n
        except ValueError:
            pass
    run(max_steps=max_steps)
