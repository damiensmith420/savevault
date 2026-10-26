"""
Local JSON config persistence for SaveVault.

Config file lives at ~/.savevault/config.json.
All writes are atomic: data is written to a temp file, then renamed.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".savevault"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class GameEntry:
    """Represents one tracked game save directory."""

    id: str
    name: str
    local_path: str
    drive_folder_id: str = ""
    last_sync: Optional[str] = None  # ISO-8601 UTC string or None

    @staticmethod
    def new(name: str, local_path: str) -> "GameEntry":
        """Create a brand-new GameEntry with a fresh UUID."""
        return GameEntry(
            id=str(uuid.uuid4()),
            name=name,
            local_path=local_path,
        )

    def last_sync_dt(self) -> Optional[datetime]:
        """Return last_sync as a timezone-aware datetime, or None."""
        if not self.last_sync:
            return None
        try:
            dt = datetime.fromisoformat(self.last_sync)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    def set_last_sync_now(self) -> None:
        """Stamp last_sync with the current UTC time."""
        self.last_sync = datetime.now(timezone.utc).isoformat()


@dataclass
class AppConfig:
    """Root config object."""

    games: list[GameEntry] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Serialisation helpers                                                #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Serialise to a plain dict suitable for json.dump."""
        return {"games": [asdict(g) for g in self.games]}

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        """Deserialise from a plain dict (as returned by json.load)."""
        games = [GameEntry(**g) for g in data.get("games", [])]
        return cls(games=games)


# ---------------------------------------------------------------------- #
# Public API                                                               #
# ---------------------------------------------------------------------- #

def load_config() -> AppConfig:
    """
    Load config from disk.

    Returns an empty AppConfig if the file does not exist or is corrupt.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        return AppConfig()
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return AppConfig.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        # Corrupt config — back it up and start fresh
        backup = CONFIG_FILE.with_suffix(".json.bak")
        try:
            CONFIG_FILE.replace(backup)
        except OSError:
            pass
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """
    Atomically persist config to disk.

    Writes to a temp file first, then renames to the real path so a
    crash mid-write can never corrupt the existing config.

    Raises:
        OSError: if the rename step fails.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)

    # Write to a temp file in the same directory (same filesystem → rename is atomic)
    fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def find_game_by_id(config: AppConfig, game_id: str) -> Optional[GameEntry]:
    """Return the GameEntry with the given id, or None."""
    for game in config.games:
        if game.id == game_id:
            return game
    return None


def upsert_game(config: AppConfig, entry: GameEntry) -> None:
    """Add or update a GameEntry in config (matched by id). Does not save to disk."""
    for i, g in enumerate(config.games):
        if g.id == entry.id:
            config.games[i] = entry
            return
    config.games.append(entry)


def remove_game(config: AppConfig, game_id: str) -> bool:
    """Remove a game by id. Returns True if it was found and removed."""
    before = len(config.games)
    config.games = [g for g in config.games if g.id != game_id]
    return len(config.games) < before
