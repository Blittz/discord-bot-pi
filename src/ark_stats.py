"""Persistent, privacy-preserving ARK survivor statistics."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

STATS_ENABLED = os.getenv("ARK_STATS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
POLL_SECONDS = float(os.getenv("ARK_PLAYER_POLL_SECONDS", "10"))
MAX_GAP_SECONDS = max(30.0, POLL_SECONDS * 3)
DB_PATH = Path.home() / ".local/state/discord-bot/ark-stats.sqlite3"
SCHEMA_VERSION = "1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " ".join(parts)


def discord_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return f"<t:{int(parsed.timestamp())}:f>"


class ArkStatsStore:
    def __init__(self, path: str | Path = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS players (
                player_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                total_seconds REAL NOT NULL DEFAULT 0,
                last_played TEXT,
                total_deaths INTEGER,
                last_death_cause TEXT,
                tracking_epoch INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS players_playtime_idx
                ON players(total_seconds DESC, display_name COLLATE NOCASE);
            """
        )
        self.db.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('schema_version', ?)", (SCHEMA_VERSION,))
        self.db.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('tracking_epoch', '1')")
        self.db.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('tracking_started', ?)", (utc_now(),))
        self.db.commit()
        self._last_mono: float | None = None
        self._active: dict[str, str] | None = None

    def record_snapshot(self, snapshot: dict[str, str], now_mono: float | None = None, now_wall: str | None = None) -> None:
        now_mono = time.monotonic() if now_mono is None else now_mono
        now_wall = utc_now() if now_wall is None else now_wall
        with self.lock:
            if self._last_mono is None or self._active is None:
                self._active = dict(snapshot)
                self._last_mono = now_mono
                self._upsert_names(snapshot)
                self.db.commit()
                return
            elapsed = min(max(0.0, now_mono - self._last_mono), MAX_GAP_SECONDS)
            epoch = int(self.db.execute("SELECT value FROM metadata WHERE key='tracking_epoch'").fetchone()[0])
            for key, name in self._active.items():
                if key not in snapshot:
                    continue
                self.db.execute(
                    """INSERT INTO players(player_key, display_name, total_seconds, last_played, tracking_epoch)
                       VALUES(?, ?, ?, ?, ?)
                       ON CONFLICT(player_key) DO UPDATE SET
                         display_name=excluded.display_name,
                         total_seconds=players.total_seconds + excluded.total_seconds,
                         last_played=excluded.last_played,
                         tracking_epoch=excluded.tracking_epoch""",
                    (key, name, elapsed, now_wall, epoch),
                )
            self._upsert_names(snapshot)
            self.db.commit()
            self._active = dict(snapshot)
            self._last_mono = now_mono

    def _upsert_names(self, snapshot: dict[str, str]) -> None:
        epoch = int(self.db.execute("SELECT value FROM metadata WHERE key='tracking_epoch'").fetchone()[0])
        for key, name in snapshot.items():
            self.db.execute(
                """INSERT INTO players(player_key, display_name, tracking_epoch)
                   VALUES(?, ?, ?)
                   ON CONFLICT(player_key) DO UPDATE SET display_name=excluded.display_name""",
                (key, name, epoch),
            )

    def reset(self) -> str:
        started = utc_now()
        with self.lock:
            self.db.execute("UPDATE players SET total_seconds=0, last_played=NULL, tracking_epoch=tracking_epoch + 1")
            self.db.execute("UPDATE metadata SET value=? WHERE key='tracking_epoch'", (str(self._epoch() + 1),))
            self.db.execute("UPDATE metadata SET value=? WHERE key='tracking_started'", (started,))
            self.db.commit()
            self._active = None
            self._last_mono = None
        return started

    def _epoch(self) -> int:
        return int(self.db.execute("SELECT value FROM metadata WHERE key='tracking_epoch'").fetchone()[0])

    def tracking_started(self) -> str:
        with self.lock:
            return self.db.execute("SELECT value FROM metadata WHERE key='tracking_started'").fetchone()[0]

    def stats(self, player_key: str | None = None):
        with self.lock:
            if player_key:
                return self.db.execute(
                    "SELECT player_key, display_name, total_seconds, last_played FROM players WHERE player_key=?", (player_key,)
                ).fetchone()
            return self.db.execute(
                "SELECT player_key, display_name, total_seconds, last_played FROM players ORDER BY total_seconds DESC, display_name COLLATE NOCASE LIMIT 10"
            ).fetchall()

    def find_by_name(self, name: str):
        with self.lock:
            return self.db.execute(
                "SELECT player_key, display_name, total_seconds, last_played FROM players WHERE display_name=? COLLATE NOCASE ORDER BY total_seconds DESC LIMIT 1",
                (name,),
            ).fetchone()

    def close(self) -> None:
        with self.lock:
            self.db.close()


def shared_ark_stats_store(bot) -> ArkStatsStore:
    store = getattr(bot, "ark_stats_store", None)
    if store is None:
        store = ArkStatsStore()
        bot.ark_stats_store = store
    return store
