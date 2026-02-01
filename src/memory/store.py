"""Read/write memory files: commands.md, spells.md, current_location.md, mobs.md, session_summary.md, goals.md, inventory.md, equipment.md, statbar.md."""
from pathlib import Path
from typing import Optional

try:
    from src.config import load_config, resolve_path, PROJECT_ROOT
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    load_config = lambda: {}
    def resolve_path(key: str, subpath: str = "") -> Path:
        cfg = load_config()
        base = cfg.get("paths", {}).get(key, "data")
        p = Path(base) if isinstance(base, str) else Path(base)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p / subpath if subpath else p


MEMORY_FILES = ("commands.md", "spells.md", "current_location.md", "mobs.md", "session_summary.md", "goals.md", "inventory.md", "equipment.md", "statbar.md")


def get_memory_paths(memory_dir: Optional[Path] = None) -> dict[str, Path]:
    """Return paths for commands.md, spells.md, current_location.md, mobs.md, session_summary.md, goals.md, inventory.md, equipment.md, statbar.md."""
    base = memory_dir or resolve_path("memory_dir")
    base.mkdir(parents=True, exist_ok=True)
    return {name: base / name for name in MEMORY_FILES}


class MemoryStore:
    """Read and write memory files as markdown strings."""

    def __init__(self, memory_dir: Optional[Path] = None):
        self._paths = get_memory_paths(memory_dir)
        for p in self._paths.values():
            p.parent.mkdir(parents=True, exist_ok=True)

    def read_commands(self) -> str:
        return self._read("commands.md")

    def read_spells(self) -> str:
        return self._read("spells.md")

    def read_current_location(self) -> str:
        return self._read("current_location.md")

    def read_mobs(self) -> str:
        return self._read("mobs.md")

    def read_session_summary(self) -> str:
        return self._read("session_summary.md")

    def read_goals(self) -> str:
        return self._read("goals.md")

    def read_inventory(self) -> str:
        return self._read("inventory.md")

    def read_equipment(self) -> str:
        return self._read("equipment.md")

    def read_statbar(self) -> str:
        return self._read("statbar.md")

    def _read(self, name: str) -> str:
        p = self._paths.get(name) or (self._paths["commands.md"].parent / name)
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    def read_all(self) -> dict[str, str]:
        """Return dict keys: commands, spells, current_location, mobs, session_summary, goals, inventory, equipment, statbar (content strings)."""
        return {
            "commands": self.read_commands(),
            "spells": self.read_spells(),
            "current_location": self.read_current_location(),
            "mobs": self.read_mobs(),
            "session_summary": self.read_session_summary(),
            "goals": self.read_goals(),
            "inventory": self.read_inventory(),
            "equipment": self.read_equipment(),
            "statbar": self.read_statbar(),
        }

    def write_commands(self, content: str) -> None:
        self._write("commands.md", content)

    def write_spells(self, content: str) -> None:
        self._write("spells.md", content)

    def write_current_location(self, content: str) -> None:
        self._write("current_location.md", content)

    def write_mobs(self, content: str) -> None:
        self._write("mobs.md", content)

    def write_session_summary(self, content: str) -> None:
        self._write("session_summary.md", content)

    def write_goals(self, content: str) -> None:
        self._write("goals.md", content)

    def write_inventory(self, content: str) -> None:
        self._write("inventory.md", content)

    def write_equipment(self, content: str) -> None:
        self._write("equipment.md", content)

    def write_statbar(self, content: str) -> None:
        self._write("statbar.md", content)

    def _write(self, name: str, content: str) -> None:
        p = self._paths.get(name) or (self._paths["commands.md"].parent / name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def write_all(
        self,
        commands: str = "",
        spells: str = "",
        current_location: str = "",
        mobs: str = "",
        session_summary: str = "",
        goals: str = "",
        inventory: str = "",
        equipment: str = "",
        statbar: str = "",
    ) -> None:
        """Write one or more files; omit or empty string to leave unchanged."""
        if commands is not None and commands != "":
            self.write_commands(commands)
        if spells is not None and spells != "":
            self.write_spells(spells)
        if current_location is not None and current_location != "":
            self.write_current_location(current_location)
        if mobs is not None and mobs != "":
            self.write_mobs(mobs)
        if session_summary is not None and session_summary != "":
            self.write_session_summary(session_summary)
        if goals is not None and goals != "":
            self.write_goals(goals)
        if inventory is not None and inventory != "":
            self.write_inventory(inventory)
        if equipment is not None and equipment != "":
            self.write_equipment(equipment)
        if statbar is not None and statbar != "":
            self.write_statbar(statbar)
