"""Decision Head: choose next action from MH state + goals; update goals after outcome."""
import logging
import os
import re
from pathlib import Path
from typing import Optional

from openai import OpenAI

try:
    from src.config import load_config, PROJECT_ROOT
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    load_config = lambda: {}

logger = logging.getLogger(__name__)


def _load_prompt(name: str) -> str:
    cfg = load_config()
    prompts_dir = cfg.get("paths", {}).get("prompts_dir", "prompts")
    path = Path(prompts_dir) if Path(prompts_dir).is_absolute() else PROJECT_ROOT / prompts_dir
    with open(path / name) as f:
        return f.read()


def _fill(template: str, **kwargs: str) -> str:
    for k, v in kwargs.items():
        template = template.replace("{{" + k + "}}", (v or "").strip())
    return template


def _normalize_output_line(line: str) -> str:
    """Normalize model output lines for tolerant label parsing."""
    ln = line.strip()
    ln = re.sub(r"^`+|`+$", "", ln).strip()
    ln = re.sub(r"^[\d]+[\.\)]\s*", "", ln)  # 1. / 2)
    ln = re.sub(r"^[\-\*\u2022]\s*", "", ln)  # -, *, bullet
    return ln.strip()


def _parse_dh_response(text: str) -> tuple[str, str, bool, bool]:
    """
    Parse DH response robustly.
    Returns (reason, command, reason_from_label, command_from_label).
    """
    lines = [_normalize_output_line(ln) for ln in text.splitlines() if ln.strip()]

    reason = ""
    command = ""
    reason_from_label = False
    command_from_label = False

    # Prefer explicit labels.
    for ln in lines:
        m = re.match(r"^reason\s*:\s*(.+)$", ln, re.IGNORECASE)
        if m:
            reason = m.group(1).strip()
            reason_from_label = True
            break

    for ln in lines:
        m = re.match(r"^command\s*:\s*(.+)$", ln, re.IGNORECASE)
        if not m:
            continue
        candidate = m.group(1).strip()
        if candidate and len(candidate) <= 200 and re.match(r"^[\w\s\-']+$", candidate, re.IGNORECASE):
            command = candidate
            command_from_label = True
            break

    # Fallback command extraction for resilience.
    if not command:
        for ln in lines:
            cand = ln
            if ":" in cand:
                cand = cand.split(":", 1)[-1].strip()
            if not cand or cand in ("```", "`") or len(cand) > 200 or cand.endswith("."):
                continue
            if re.match(r"^[\w\s\-']+$", cand, re.IGNORECASE):
                command = cand
                break

    return reason, command, reason_from_label, command_from_label


def run_dh_action(
    game_buffer: str = "",
    commands: str = "",
    spells: str = "",
    current_location: str = "",
    mobs: str = "",
    session_summary: str = "",
    goals: str = "",
    inventory: str = "",
    equipment: str = "",
    statbar: str = "",
    play_summary: str = "",
    client: Optional[OpenAI] = None,
) -> tuple[str, str]:
    """
    Run DH action mode: given full MH state + goals, output the next MUD command.
    Returns (reason, command) tuple.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
    template = _load_prompt("dh.txt")
    prompt = _fill(
        template,
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
    temperature = cfg.get("openai", {}).get("temperature")
    if temperature is None:
        temperature = 0.2

    def _call_api(p: str):
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": p}],
            temperature=temperature,
        )

    try:
        resp = _call_api(prompt)
    except Exception as e:
        err_msg = str(e).lower() if e else ""
        if "context_length" in err_msg or "128000" in err_msg:
            logger.warning("DH context_length_exceeded; retrying with trimmed game_buffer and play_summary")
            trimmed_prompt = _fill(
                template,
                game_buffer=game_buffer[-2000:] if len(game_buffer) > 2000 else game_buffer,
                commands=commands,
                spells=spells,
                current_location=current_location,
                mobs=mobs,
                session_summary=(session_summary or "")[-800:] if len(session_summary or "") > 800 else session_summary,
                goals=goals,
                inventory=inventory,
                equipment=equipment,
                statbar=statbar,
                play_summary="(recent turns omitted due to context limit)",
            )
            resp = _call_api(trimmed_prompt)
        else:
            raise

    text = (resp.choices[0].message.content or "").strip()
    reason, command, reason_from_label, command_from_label = _parse_dh_response(text)

    if not command:
        logger.warning("DH parse fallback: no command found; defaulting to 'look'. Raw response: %r", text[:500])
        return (reason or "No reason provided by model.", "look")

    if not reason:
        reason = "No reason provided by model."

    if not reason_from_label or not command_from_label:
        logger.debug(
            "DH parsed with relaxed rules (reason_label=%s command_label=%s). Raw response: %r",
            reason_from_label,
            command_from_label,
            text[:500],
        )

    return (reason, command)


def run_dh_goals(
    mh_state: str,
    action: str,
    actual_output: str,
    goals: str = "",
    client: Optional[OpenAI] = None,
) -> str:
    """
    Run DH goals mode: given state at decision time, action taken, and actual MUD output,
    output updated goals.md content. Returns the GOALS.MD section text (to write to goals.md).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = client or OpenAI(api_key=api_key)
    cfg = load_config()
    model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
    template = _load_prompt("dh_goals.txt")
    prompt = _fill(
        template,
        mh_state=mh_state,
        action=action,
        actual_output=actual_output,
        goals=goals,
    )
    temperature = cfg.get("openai", {}).get("temperature")
    if temperature is None:
        temperature = 0.2
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    text = (resp.choices[0].message.content or "").strip()
    goals_section = re.search(
        r"=== GOALS(?:\.MD)? ===\s*(.+?)(?=\n===|\Z)",
        text,
        re.S | re.I,
    )
    if goals_section:
        return goals_section.group(1).strip()
    return goals  # keep previous if section missing
