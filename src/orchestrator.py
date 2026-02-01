"""Main loop: kickoff -> MH -> PH -> WM -> DH -> execute -> wait -> VH -> log -> repeat."""
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from src.config import load_config, resolve_path, PROJECT_ROOT
from src.mud.client import MUDClient
from src.memory.store import MemoryStore
from src.agents.mh import run_mh
from src.agents.ph import run_ph
from src.agents.wm import run_wm
from src.agents.dh import run_dh
from src.agents.vh import run_vh


def _format_play_summary(commands_sent: list[str]) -> str:
    """Format list of commands sent this session for PH/DH prompts (Turn 1: X. Turn 2: Y. ...)."""
    if not commands_sent:
        return "None yet (this is the first turn)."
    return " ".join(f"Turn {i}: {cmd}." for i, cmd in enumerate(commands_sent, 1))


def _strip_login_menu_from_buffer(buffer: str, kickoff_commands: list[str]) -> str:
    """
    Remove the login/entry menu from the start of the buffer so MH never sees it.
    The same menu ("1) Enter the game.", "Make your choice:") appears at login and after death;
    if we pass the full buffer to step 1 MH, it can wrongly infer death menu on later turns.
    Keep only output from the first kickoff command onward (e.g. from "> look" onward).
    """
    if not buffer or not kickoff_commands:
        return buffer
    # Find the first echo of a kickoff command (e.g. "> look" or "> look\r\n")
    first_cmd = (kickoff_commands[0] or "look").strip()
    marker = "> " + first_cmd
    idx = buffer.find(marker)
    if idx >= 0:
        return buffer[idx:].strip()
    return buffer


def _extract_first_mud_line(mud_output: str) -> str:
    """First substantive line of MUD output (excluding status bar / prompt). For WM training target next_line."""
    if not mud_output or not mud_output.strip():
        return ""
    # Strip ANSI codes
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    lines = [ansi.sub("", ln).strip() for ln in re.split(r"[\r\n]+", mud_output) if ln.strip()]
    # Skip status bar / prompt (e.g. "20H 100M 83V (news) (motd) >" or "> ")
    status_prompt = re.compile(r"^\d+H\s+\d+M\s+\d+V|>\s*$")
    for ln in lines:
        if not status_prompt.search(ln) and len(ln) > 1:
            return ln
    return lines[0] if lines else ""


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
) -> tuple[str, str, str, str, str, str, str, Optional[str], Optional[str], Optional[int], Optional[str], Optional[str]]:
    """
    One full cycle after we have MUD output in buffer: MH -> PH -> WM -> DH -> execute -> wait -> VH.
    When new_output_override is provided (e.g. full kickoff buffer for step 1), use it for MH instead of buffer_since_last_command.
    Returns (new_commands, new_current_location, new_mobs, new_session_summary, new_inventory, new_equipment, new_statbar, chosen_action, wm_prediction, vh_score, vh_summary, mud_output).
    """
    cfg = load_config()
    silence_timeout = cfg.get("mud", {}).get("silence_timeout_sec", 10.0)
    traces_path = resolve_path("traces_file")
    traces_path.parent.mkdir(parents=True, exist_ok=True)
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
    wm_context = (current_location or "").strip() + "\n\n" + (session_summary or "").strip() + "\n\n" + (statbar or "").strip()
    if log:
        log.info("step=%d MH (first 200 chars context): %s", step, (wm_context or "")[:200].replace("\n", " "))
    # PH/DH get recent game context: at least everything since last send, up to game_buffer_max_lines (so they see we already looked, etc.)
    since_last = client.get_buffer_since_last_command()
    full_buffer = client.get_full_buffer()
    max_lines = (cfg.get("orchestrator") or {}).get("game_buffer_max_lines", 100)
    full_lines = full_buffer.splitlines()
    since_last_line_count = len(since_last.splitlines())
    n = max(max_lines, since_last_line_count)
    game_buffer = "\n".join(full_lines[-n:]) if len(full_lines) > n else full_buffer
    if not game_buffer.strip():
        game_buffer = new_output

    # 2–4. If user injected a command (e.g. echo "north" > data/inject_command.txt), use it and skip PH/WM/DH
    if inject_command and inject_command.strip():
        chosen = inject_command.strip()
        options = [(chosen, "", "low")]
        wm_prediction = ""
        if log:
            log.info("step=%d using injected command: %s", step, chosen)
    else:
        # 2. PH (include play-so-far so PH can avoid repeating same command)
        commands_sent = commands_sent_this_session or []
        play_summary = _format_play_summary(commands_sent)
        actions = run_ph(
            game_buffer=game_buffer,
            commands=commands,
            spells=spells,
            current_location=current_location,
            mobs=mobs,
            play_summary=play_summary,
            session_summary=session_summary,
            goals=goals,
        )
        if not actions:
            actions = ["look"]
        if log:
            log.info("step=%d PH proposed: %s", step, actions)

        # 3. WM predictions (one call per PH action; options[i] = (actions[i], prediction_i, conf_i))
        # Pass last N lines of buffer so WM sees immediate screen context (helps next-line prediction).
        wm_buffer_lines = 25
        recent_buffer_wm = "\n".join(game_buffer.splitlines()[-wm_buffer_lines:]) if game_buffer else ""
        options = []
        for a in actions:
            pred_text, conf = run_wm(wm_context, a, recent_buffer=recent_buffer_wm)
            options.append((a, pred_text, conf))
        if log:
            for i, (a, p, c) in enumerate(options):
                snippet = (p or "").replace("\n", " ").strip()
                log.info("step=%d WM[%d] %r -> %s (conf=%s)", step, i, a, snippet[:400] + (" ..." if len(snippet) > 400 else "") if snippet else "(empty)", c)
            # Log digest of what we pass to DH (verify action–prediction pairing)
            options_digest = " | ".join(f"{a!r}:{(p or '')[:40].replace(chr(10),' ')}" for a, p, c in options)
            log.info("step=%d DH input digest: %s", step, options_digest[:500])

        # 3b. Re-drain socket and re-run MH on latest buffer so DH sees fresh state (e.g. mob left during WM)
        client.drain(timeout_sec=0.5)
        latest_since_last = client.get_buffer_since_last_command()
        if latest_since_last.strip():
            commands, current_location, mobs, session_summary, inventory, equipment, statbar = run_mh(
                new_output=latest_since_last,
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
            wm_context = (current_location or "").strip() + "\n\n" + (session_summary or "").strip() + "\n\n" + (statbar or "").strip()
            full_buffer = client.get_full_buffer()
            game_buffer = "\n".join(full_buffer.splitlines()[-n:]) if len(full_buffer.splitlines()) > n else full_buffer
            if log:
                log.info("step=%d MH re-run before DH (fresh state, %d chars buffer)", step, len(latest_since_last))

        # 4. DH (receives options, full state, play summary, session summary, goals, and recent buffer; chooses one action)
        chosen = run_dh(
            options=options,
            game_buffer=game_buffer,
            commands=commands,
            spells=spells,
            current_location=current_location,
            mobs=mobs,
            play_summary=play_summary,
            session_summary=session_summary,
            goals=goals,
        )
        wm_prediction = next((p for a, p, c in options if a == chosen), options[0][1] if options else "")
        if log:
            log.info("step=%d DH chose: %s (wm_pred len=%d)", step, chosen, len(wm_prediction or ""))

    # "wait and observe" = no command; wait for silence only, skip send/VH/trace
    if chosen and chosen.strip().lower() == "wait and observe":
        if log:
            log.info("step=%d wait and observe: no command sent, waiting %s s silence", step, silence_timeout)
        client.wait_silence(timeout_sec=silence_timeout)
        return commands, current_location, mobs, session_summary, inventory, equipment, "(wait)", None, None, None, None

    # 5. Execute (send() clears buffer and resets silence timer so we wait for MUD response)
    context_at_decision = (current_location or "").strip() + "\n\n" + (session_summary or "").strip() + "\n\n" + (statbar or "").strip()
    client.send(chosen)
    if log:
        log.info("step=%d sent: %s", step, chosen)

    # 6. Wait for MUD response then silence (client requires at least one chunk after send)
    client.wait_silence(timeout_sec=silence_timeout * 2)
    mud_output = client.get_buffer_since_last_command()
    if log and mud_output:
        # Log actual game text for diagnosis (single line, truncate if long)
        mud_one_line = mud_output.replace("\r", "").replace("\n", " | ").strip()
        mud_snippet = mud_one_line[:500] + (" ..." if len(mud_one_line) > 500 else "")
        log.info("step=%d game said: %s", step, mud_snippet)

    # 7. VH
    vh_score, vh_summary, goals_update = run_vh(
        mh_state=context_at_decision,
        action=chosen,
        wm_prediction=wm_prediction,
        actual_output=mud_output,
        goals=goals,
    )
    if log:
        # Log enough of VH summary to see full reasoning (e.g. "however ...")
        vh_summary_log = (vh_summary or "").replace("\n", " ").strip()
        log.info("step=%d VH score=%s summary=%s", step, vh_score, vh_summary_log[:600] + (" ..." if len(vh_summary_log) > 600 else ""))
    if goals_update and goals_update.strip():
        memory.write_goals(goals_update)
        if log:
            log.info("step=%d wrote goals.md (%d chars)", step, len(goals_update))
    elif log:
        log.info("step=%d VH returned no goals update; goals.md unchanged", step)

    # 8. Log trace (re-read buffer once more in case of trailing data)
    mud_output_for_trace = client.get_buffer_since_last_command()
    next_line = _extract_first_mud_line(mud_output_for_trace)
    # recent_buffer at decision time (last 25 lines DH/WM saw) for training parity with inference
    recent_buffer_trace = ""
    if game_buffer:
        recent_buffer_trace = "\n".join(game_buffer.splitlines()[-25:])
    trace = {
        "step": step,
        "mh_state": context_at_decision,
        "action": chosen,
        "recent_buffer": recent_buffer_trace,
        "wm_predicted_text": wm_prediction,
        "wm_confidence": next((c for a, p, c in options if a == chosen), "medium"),
        "mud_output": mud_output_for_trace,
        "next_line": next_line,
        "vh_score": vh_score,
        "vh_summary": vh_summary,
        "outcome_summary": vh_summary,
        "goals": goals,
        "timestamp": time.time(),
    }
    with open(traces_path, "a") as f:
        f.write(json.dumps(trace, ensure_ascii=False) + "\n")

    # 9. Update memory with the response we just got (so last step's output is in memory)
    commands, current_location, mobs, session_summary, inventory, equipment, statbar = run_mh(
        new_output=mud_output_for_trace,
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

    return commands, current_location, mobs, session_summary, inventory, equipment, statbar, chosen, wm_prediction, vh_score, vh_summary, mud_output


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
    traces_path = resolve_path("traces_file")
    # Clear logs and traces at start of each run (for easier debugging)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "orchestrator.log").write_text("")
    traces_path.parent.mkdir(parents=True, exist_ok=True)
    traces_path.write_text("")

    logger = _make_orchestrator_logger(logs_dir)
    logger.info("Starting orchestrator max_steps=%s host=%s port=%s", max_steps, host, port)

    memory_dir = resolve_path("memory_dir")
    memory_dir.mkdir(parents=True, exist_ok=True)
    # Clear memory files by direct write so goals and others definitely reset (no holdover from previous run)
    for name in ("current_location.md", "session_summary.md", "goals.md", "inventory.md", "equipment.md", "statbar.md"):
        (memory_dir / name).write_text("", encoding="utf-8")
    logger.info("Cleared memory files for fresh run: %s", memory_dir)
    memory = MemoryStore(memory_dir=memory_dir)
    client = MUDClient(host=host, port=port, silence_timeout_sec=silence_timeout)
    client.connect()
    client.set_stream(sys.stdout)  # stream MUD output so you can watch gameplay

    # Login if credentials are set (character name => password => enter => 1)
    if os.environ.get("MUD_CHARACTER") and os.environ.get("MUD_PASSWORD"):
        client.login(step_sleep_sec=1.0)
        time.sleep(1.0)

    commands = memory.read_commands()
    spells = memory.read_spells()
    # Start with empty current_location, mobs, session_summary, inventory, equipment, statbar so step 1 uses kickoff output only (avoids PH/DH seeing previous session's room/NPCs)
    current_location = ""
    mobs = ""  # mobs.md deprecated for now (like locations.md); don't load so no cross-run leakage
    session_summary = ""
    inventory = ""
    equipment = ""
    statbar = ""

    # Kickoff
    logger.info("Kickoff: %s", kickoff_commands)
    for cmd in kickoff_commands:
        client.send(cmd)
        client.drain(timeout_sec=1.0)
    client.wait_silence(timeout_sec=silence_timeout * 2)
    kickoff_buffer = client.get_buffer_since_last_command()
    if kickoff_buffer:
        buf_one_line = kickoff_buffer.replace("\r", "").replace("\n", " | ").strip()
        logger.info("After kickoff, game said: %s", buf_one_line[:500] + (" ..." if len(buf_one_line) > 500 else ""))
    # Full buffer includes output from all kickoff commands (look, score, inventory); step 1 MH needs it for room from "look"
    # Strip login/entry menu so step 1 MH never sees "1) Enter the game" and later turns don't infer death menu from it
    full_kickoff_buffer = _strip_login_menu_from_buffer(client.get_full_buffer(), kickoff_commands)

    step = 0
    commands_sent_this_session: list[str] = []
    # Manual override: type a line in this terminal and press Enter; it's sent as the next command.
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
            commands, current_location, mobs, session_summary, inventory, equipment, statbar, chosen, wm_pred, vh_score, vh_sum, mud_out = run_cycle(
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
                print(f"Step {step}: action={chosen!r} vh_score={vh_score}")
    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C).")
    finally:
        client.disconnect()
        logger.info("Stopped after %d step(s). Traces: %s", step, resolve_path("traces_file"))


if __name__ == "__main__":
    max_steps = 10  # default: 10 rounds then exit
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
            max_steps = None if n == 0 else n  # 0 = unlimited
        except ValueError:
            pass
    run(max_steps=max_steps)
