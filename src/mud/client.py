"""Telnet MUD client with buffer and silence detection."""
import os
import socket
import time
import threading
from pathlib import Path

try:
    from src.config import load_config
except ImportError:
    load_config = lambda: {}


class MUDClient:
    """Connect to a MUD via telnet; buffer output; detect 10s silence."""

    def __init__(
        self,
        host: str = None,
        port: int = None,
        silence_timeout_sec: float = 10.0,
        reconnect_delay_sec: float = 2.0,
        max_reconnect_attempts: int = 5,
    ):
        cfg = load_config().get("mud", {})
        self.host = host or os.environ.get("MUD_HOST") or cfg.get("host", "")
        self.port = int(port) if port is not None else int(os.environ.get("MUD_PORT", "23") or cfg.get("port", 23))
        self.silence_timeout_sec = silence_timeout_sec or cfg.get("silence_timeout_sec", 10.0)
        self.reconnect_delay_sec = reconnect_delay_sec or cfg.get("reconnect_delay_sec", 2.0)
        self.max_reconnect_attempts = max_reconnect_attempts or cfg.get("max_reconnect_attempts", 5)

        self._sock: socket.socket | None = None
        self._buffer: list[str] = []
        self._buffer_since_last_command: list[str] = []
        self._last_recv_time: float = 0.0
        self._lock = threading.Lock()
        self._connected = False
        self._stream = None  # If set, incoming data is written here as it arrives (e.g. sys.stdout)

    def connect(self) -> None:
        """Connect to MUD host:port (telnet = raw TCP)."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(5.0)
        try:
            self._sock.connect((self.host, self.port))
        except Exception as e:
            self._sock.close()
            self._sock = None
            raise ConnectionError(f"Failed to connect to {self.host}:{self.port}: {e}") from e
        self._sock.setblocking(False)
        self._connected = True
        self._last_recv_time = time.monotonic()
        self._buffer.clear()
        self._buffer_since_last_command.clear()

    def set_stream(self, stream) -> None:
        """If set, incoming MUD data is written to this file-like object as it arrives (e.g. sys.stdout)."""
        self._stream = stream

    def disconnect(self) -> None:
        """Close the connection."""
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            self._connected = False

    def _try_receive(self) -> str:
        """Read available data from socket; update buffer and last_recv_time. Returns new text."""
        if not self._sock:
            return ""
        try:
            data = self._sock.recv(4096)
        except BlockingIOError:
            return ""
        except OSError:
            self._connected = False
            return ""
        if not data:
            self._connected = False
            return ""
        text = data.decode("utf-8", errors="replace")
        with self._lock:
            self._last_recv_time = time.monotonic()
            self._buffer.append(text)
            self._buffer_since_last_command.append(text)
        if self._stream:
            try:
                self._stream.write(text)
                self._stream.flush()
            except Exception:
                pass
        return text

    def send(self, command: str) -> None:
        """Send a single command (e.g. 'look'); clear buffer_since_last_command after send.
        Empty string sends a single newline (e.g. for 'press return' prompts)."""
        cmd = command.strip()
        if not self._sock or not self._connected:
            raise ConnectionError("Not connected")
        with self._lock:
            self._buffer_since_last_command.clear()
            self._last_recv_time = 0  # force wait_silence to wait for response before considering silence
        line = "\r\n" if not cmd else (cmd if cmd.endswith("\r\n") else cmd + "\r\n")
        self._sock.sendall(line.encode("utf-8"))
        if self._stream:
            try:
                self._stream.write("> " + (cmd or "(return)") + "\n")
                self._stream.flush()
            except Exception:
                pass
        echo_line = "> " + (cmd or "(return)") + "\n"
        with self._lock:
            self._buffer.append(echo_line)
            self._buffer_since_last_command.append(echo_line)

    def drain(self, timeout_sec: float = 2.0) -> None:
        """Read socket until no data for timeout_sec (allows prompt to arrive)."""
        deadline = time.monotonic() + timeout_sec
        last_data = time.monotonic()
        while time.monotonic() < deadline:
            self._try_receive()
            with self._lock:
                t = self._last_recv_time
            if t > last_data:
                last_data = t
                deadline = min(deadline, time.monotonic() + timeout_sec)
            time.sleep(0.05)

    def get_buffer_since_last_command(self) -> str:
        """Return all output accumulated since the last send()."""
        self._try_receive()
        with self._lock:
            return "".join(self._buffer_since_last_command)

    def get_full_buffer(self) -> str:
        """Return all output since connection (or last clear)."""
        self._try_receive()
        with self._lock:
            return "".join(self._buffer)

    def clear_buffer_since_last_command(self) -> None:
        """Clear only the 'since last command' buffer (e.g. after MH consumes it)."""
        with self._lock:
            self._buffer_since_last_command.clear()

    def wait_silence(self, timeout_sec: float = None) -> bool:
        """
        Block until no data has been received for silence_timeout_sec.
        Returns True if silence was reached, False if timeout_sec (or default) expired without silence.
        """
        silence = timeout_sec if timeout_sec is not None else self.silence_timeout_sec
        deadline = time.monotonic() + silence + self.silence_timeout_sec  # max wait
        last_recv = self._last_recv_time
        while time.monotonic() < deadline:
            self._try_receive()
            with self._lock:
                t = self._last_recv_time
            if t > last_recv:
                last_recv = t
            # Don't return until we've received at least one chunk (t > 0) and then silence
            if last_recv > 0 and time.monotonic() - last_recv >= self.silence_timeout_sec:
                return True
            time.sleep(0.2)
        return False

    def _wait_for_text(self, text: str, timeout_sec: float = 15.0, poll_interval: float = 0.5) -> bool:
        """Wait until the full buffer contains the given text; return True if seen, False on timeout."""
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            self._try_receive()
            with self._lock:
                buf = "".join(self._buffer)
            if text in buf:
                return True
            time.sleep(poll_interval)
        return False

    def login(
        self,
        character_name: str = None,
        password: str = None,
        step_sleep_sec: float = 1.0,
    ) -> None:
        """
        Send MUD login sequence: wait for each prompt, then send response. Name => password => enter => 1.
        Credentials from MUD_CHARACTER, MUD_PASSWORD. Uses step_sleep_sec for name/password; shorter
        delays after PRESS RETURN and for menu choice so we respond before MUD timeouts.
        """
        name = character_name or os.environ.get("MUD_CHARACTER", "").strip()
        pwd = password or os.environ.get("MUD_PASSWORD", "").strip()
        if not name or not pwd:
            return
        # 1. Wait for name prompt, then send character name
        self._wait_for_text("By what name do you wish to be known?", timeout_sec=15.0)
        time.sleep(step_sleep_sec)
        self.send(name)
        time.sleep(step_sleep_sec)
        self.drain(timeout_sec=1.0)
        time.sleep(step_sleep_sec)
        # 2. Wait for password prompt, then send password
        self._wait_for_text("Password:", timeout_sec=15.0)
        time.sleep(step_sleep_sec)
        self.send(pwd)
        time.sleep(step_sleep_sec)
        self.drain(timeout_sec=1.0)
        time.sleep(step_sleep_sec)
        # 3. Wait for PRESS RETURN, then send enter (newline)
        self._wait_for_text("PRESS RETURN", timeout_sec=15.0)
        time.sleep(0.3)
        self.send("")  # sends \r\n so MUD receives "press return"
        time.sleep(0.5)
        self.drain(timeout_sec=1.5)
        time.sleep(0.3)
        # 4. Wait for menu "Make your choice:", then send 1 quickly (avoid MUD timeout)
        self._wait_for_text("Make your choice:", timeout_sec=15.0)
        time.sleep(0.4)
        self.send("1")
        time.sleep(step_sleep_sec)
        self.drain(timeout_sec=2.0)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._sock is not None
