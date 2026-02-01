#!/usr/bin/env python3
"""Test MUD telnet client: connect, send command, assert buffer gets output. Requires MUD_HOST and MUD_PORT in env."""
import os
import sys
from pathlib import Path

# Run from project root
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

# Load .env if present (without requiring python-dotenv)
env_file = project_root / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

from src.mud.client import MUDClient


def main():
    host = os.environ.get("MUD_HOST")
    port = os.environ.get("MUD_PORT", "23")
    if not host:
        print("Set MUD_HOST (and optionally MUD_PORT) in .env to run this test.")
        sys.exit(0)
    port = int(port)
    client = MUDClient(host=host, port=port, silence_timeout_sec=3.0)
    # Stream incoming MUD output to stdout as it arrives (easier to track)
    client.set_stream(sys.stdout)
    try:
        client.connect()
        print("Connected to", host, port, file=sys.stderr)
        # Login if credentials set (name => password => enter => 1)
        if os.environ.get("MUD_CHARACTER") and os.environ.get("MUD_PASSWORD"):
            ch = os.environ.get("MUD_CHARACTER", "")
            pw = os.environ.get("MUD_PASSWORD", "")
            pw_masked = (pw[0] + "*" * (len(pw) - 1)) if len(pw) > 1 else ("*" if pw else "(empty)")
            print("Login debug: MUD_CHARACTER =", repr(ch), "| MUD_PASSWORD =", repr(pw_masked), file=sys.stderr)
            print("(We will send: 1=name, 2=password, 3=enter, 4=1)", file=sys.stderr)
            client.login(step_sleep_sec=2.0)
            import time
            time.sleep(2.0)
            # Full buffer is cumulative (never cleared); duplications = MUD sent them (e.g. after "Reconnecting.")
            full = client.get_full_buffer()
            print("\n--- Full buffer after login (length", len(full), ") ---", file=sys.stderr)
        else:
            print("Skipping login (MUD_CHARACTER or MUD_PASSWORD not set in .env). Send 'look' at name prompt.", file=sys.stderr)
        client.send("look")
        client.drain(timeout_sec=2.0)
        out = client.get_buffer_since_last_command()
        assert out, "Expected some output after 'look'"
        print("\n--- Buffer since last command (length", len(out), ") ---", file=sys.stderr)
        print("test_mud_client: OK", file=sys.stderr)
    except ConnectionError as e:
        print("Connection failed:", e)
        sys.exit(1)
    except Exception as e:
        print("Error:", e)
        raise
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
