"""Persistent, privacy-preserving ARK survivor statistics."""

from __future__ import annotations

import os
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

STATS_ENABLED = os.getenv("ARK_STATS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
POLL_SECONDS = float(os.getenv("ARK_PLAYER_POLL_SECONDS", "10"))
MAX_GAP_SECONDS = max(30.0, POLL_SECONDS * 3)
DB_PATH = Path.home() / ".local/state/discord-bot/ark-stats.sqlite3"
SCHEMA_VERSION = "1"
log = logging.getLogger(__name__)
DEATH_TRACKING_ENABLED = os.getenv("ARK_DEATH_TRACKING_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
LOG_DIRECTORY = Path(os.getenv("ARK_LOG_DIRECTORY", "")) if os.getenv("ARK_LOG_DIRECTORY") else None
LOG_FILENAME = os.getenv("ARK_LOG_FILENAME", "ShooterGame.log")
DEATH_POLL_SECONDS = float(os.getenv("ARK_DEATH_POLL_SECONDS", "10"))
SERVER_START_LINE = re.compile(r'^\[\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}:\d{3}\]\[\s*\d+\]Server:\s+"([^"]{1,80})"\s+has successfully started!\s*$')
DEATH_LINE = re.compile(
    r"(?P<timestamp>\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2})\s*:\s*"
    r"(?P<victim>.+?)\s*-\s*Lvl\s+(?P<victim_level>\d+)\s*\([^)]*\)\s*"
    r"was killed(?: by (?:a|an)\s+(?P<killer>.+?)\s*-\s*Lvl\s+(?P<killer_level>\d+)\s*\([^)]*\))?!"
    r"(?:\s+\[KillerSID:\s*\d+\])?\s*$",
    re.IGNORECASE,
)
UNKNOWN_DEATH_LINE = re.compile(
    r"(?P<timestamp>\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2})\s*:\s*"
    r"(?P<victim>.+?)\s*-\s*Lvl\s+(?P<victim_level>\d+)\s*\([^)]*\)\s*was killed!"
    r"(?:\s+\[KillerSID:\s*\d+\])?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DeathEvent:
    event_id: str
    timestamp: str
    victim_name: str
    victim_level: int
    killer_name: str | None
    killer_level: int | None
    zombified: bool


@dataclass(frozen=True)
class RecordedDeath:
    event: DeathEvent
    player_key: str | None
    total_deaths: int | None


def parse_server_start_line(line: str) -> str | None:
    match = SERVER_START_LINE.match(line.strip())
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group(1)).strip()
    if not name or any(ord(char) < 32 for char in name):
        return None
    return name


def discover_server_name(path: str | Path, max_bytes: int = 65536) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - max_bytes))
        text = handle.read().decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        name = parse_server_start_line(line)
        if name:
            return name
    return None


def parse_death_line(line: str) -> DeathEvent | None:
    match = DEATH_LINE.search(line.strip()) or UNKNOWN_DEATH_LINE.search(line.strip())
    if not match:
        return None
    timestamp = match.group("timestamp")
    victim = re.sub(r"\s+", " ", match.group("victim")).strip()
    killer = match.groupdict().get("killer")
    killer = re.sub(r"\s+", " ", killer).strip() if killer else None
    fingerprint = hashlib.sha256(line.strip().encode("utf-8")).hexdigest()
    return DeathEvent(
        fingerprint,
        timestamp,
        victim,
        int(match.group("victim_level")),
        killer,
        int(match.group("killer_level")) if match.groupdict().get("killer_level") else None,
        bool(killer and killer.casefold().startswith("zombified ")),
    )


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
                zombified_deaths INTEGER NOT NULL DEFAULT 0,
                killer_counts TEXT NOT NULL DEFAULT '{}',
                tracking_epoch INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS death_events (
                event_id TEXT PRIMARY KEY,
                event_timestamp TEXT NOT NULL,
                victim_name TEXT NOT NULL,
                victim_level INTEGER NOT NULL,
                player_key TEXT,
                killer_name TEXT,
                killer_level INTEGER,
                zombified INTEGER NOT NULL DEFAULT 0,
                blood_moon INTEGER,
                tracking_epoch INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_offset INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS players_playtime_idx
                ON players(total_seconds DESC, display_name COLLATE NOCASE);
            """
        )
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(players)")}
        if "zombified_deaths" not in columns:
            self.db.execute("ALTER TABLE players ADD COLUMN zombified_deaths INTEGER NOT NULL DEFAULT 0")
        if "killer_counts" not in columns:
            self.db.execute("ALTER TABLE players ADD COLUMN killer_counts TEXT NOT NULL DEFAULT '{}'")
        self.db.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('schema_version', ?)", (SCHEMA_VERSION,))
        self.db.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('tracking_epoch', '1')")
        self.db.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('tracking_started', ?)", (utc_now(),))
        self.db.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('death_tracking_started', ?)", (utc_now(),))
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
                self._set_metadata("playtime_interrupted", "0")
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
            self._set_metadata("playtime_interrupted", "0")

    def interrupt_snapshot(self) -> None:
        with self.lock:
            self._active = None
            self._last_mono = None
            self._set_metadata("playtime_interrupted", "1")
            self.db.commit()

    def playtime_interrupted(self) -> bool:
        with self.lock:
            return self._metadata("playtime_interrupted") == "1"

    def set_server_outage(self, value: bool) -> None:
        with self.lock:
            self._set_metadata("server_outage_confirmed", "1" if value else "0")
            self.db.commit()

    def server_outage(self) -> bool:
        with self.lock:
            return self._metadata("server_outage_confirmed") == "1"

    def set_server_name(self, name: str) -> None:
        with self.lock:
            self._set_metadata("server_name", name)
            self.db.commit()

    def server_name(self) -> str | None:
        with self.lock:
            return self._metadata("server_name")

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
            self.db.execute("UPDATE players SET total_seconds=0, total_deaths=0, zombified_deaths=0, killer_counts='{}', last_played=NULL, last_death_cause=NULL, tracking_epoch=tracking_epoch + 1")
            self.db.execute("UPDATE metadata SET value=? WHERE key='tracking_epoch'", (str(self._epoch() + 1),))
            self.db.execute("UPDATE metadata SET value=? WHERE key='tracking_started'", (started,))
            self.db.execute("UPDATE metadata SET value=? WHERE key='death_tracking_started'", (started,))
            self.db.execute("DELETE FROM death_events")
            self.db.execute("DELETE FROM metadata WHERE key='death_file_state'")
            self.db.commit()
            self._active = None
            self._last_mono = None
        return started

    def collect_log(self, path: str | Path, player_snapshot: dict[str, str], return_events: bool = False) -> int | list[RecordedDeath]:
        """Read only new complete lines; return the number of inserted deaths."""
        path = Path(path)
        with self.lock:
            state = self._metadata("death_file_state")
            if not path.is_file():
                return [] if return_events else 0
            size = path.stat().st_size
            head_hash = self._head_hash(path)
            if not state:
                stat = path.stat()
                self._set_metadata("death_file_state", json.dumps({"name": str(path), "offset": size, "partial": "", "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino, "head_hash": head_hash}))
                self.db.commit()
                return [] if return_events else 0
            saved = json.loads(state)
            offset = int(saved.get("offset", 0))
            stat = path.stat()
            rotated = saved.get("name") == str(path) and saved.get("inode") not in (None, stat.st_ino)
            read_path = path
            final_offset = offset
            if rotated:
                candidates = [candidate for candidate in path.parent.glob(f"{path.stem}-backup-*.log") if candidate.is_file()]
                inode_matches = [candidate for candidate in candidates if candidate.stat().st_ino == saved.get("inode")]
                content_matches = [candidate for candidate in candidates if candidate.stat().st_size >= offset and self._prefix_hash(candidate, min(offset, 256)) == saved.get("head_hash")]
                matches = inode_matches if len(inode_matches) == 1 else content_matches if len(content_matches) == 1 else []
                if matches:
                    read_path = max(matches, key=lambda candidate: candidate.stat().st_mtime_ns)
                    final_offset = 0
                else:
                    self._set_metadata("death_coverage_gap", f"rotation-unmatched:{utc_now()}")
                    reason = "ambiguous" if len(inode_matches) > 1 or len(content_matches) > 1 else "unmatched"
                    log.warning("ARK death log rotation %s; coverage gap recorded", reason)
                    offset = 0
                    final_offset = 0
            elif saved.get("name") != str(path) or size < offset or (size == offset and saved.get("head_hash") != head_hash):
                offset = 0
                final_offset = 0
            with read_path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read()
                new_offset = handle.tell()
            text = saved.get("partial", "") + data.decode("utf-8", errors="replace")
            complete, separator, partial = text.rpartition("\n")
            if not separator:
                partial = text
                complete = ""
            epoch = self._epoch()
            inserted = 0
            recorded: list[RecordedDeath] = []
            for line in complete.splitlines():
                event = parse_death_line(line)
                if not event:
                    continue
                key = self._match_player(event.victim_name, player_snapshot)
                cursor = new_offset - len(partial.encode("utf-8"))
                row = (event.event_id, event.timestamp, event.victim_name, event.victim_level, key, event.killer_name, event.killer_level, int(event.zombified), None, epoch, str(read_path), cursor)
                result = self.db.execute("INSERT OR IGNORE INTO death_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", row)
                if result.rowcount:
                    inserted += 1
                    if key:
                        self.db.execute("INSERT OR IGNORE INTO players(player_key, display_name, tracking_epoch) VALUES(?,?,?)", (key, event.victim_name, epoch))
                        row = self.db.execute("SELECT killer_counts FROM players WHERE player_key=?", (key,)).fetchone()
                        counts = json.loads(row[0] or "{}")
                        if event.killer_name:
                            counts[event.killer_name] = counts.get(event.killer_name, 0) + 1
                        self.db.execute("UPDATE players SET total_deaths=COALESCE(total_deaths,0)+1, zombified_deaths=zombified_deaths+?, killer_counts=?, last_death_cause=? WHERE player_key=?", (int(event.zombified), json.dumps(counts, sort_keys=True), event.killer_name or "Unknown", key))
                        total = self.db.execute("SELECT total_deaths FROM players WHERE player_key=?", (key,)).fetchone()[0]
                    else:
                        total = None
                    recorded.append(RecordedDeath(event, key, total))
            next_offset = final_offset if read_path != path else new_offset
            next_partial = partial if read_path != path else partial
            self._set_metadata("death_file_state", json.dumps({"name": str(path), "offset": next_offset, "partial": next_partial, "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino, "head_hash": head_hash}))
            self.db.commit()
            return recorded if return_events else inserted

    def _metadata(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _head_hash(path: Path) -> str:
        return ArkStatsStore._prefix_hash(path, 256)

    @staticmethod
    def _prefix_hash(path: Path, length: int) -> str:
        with path.open("rb") as handle:
            return hashlib.sha256(handle.read(length)).hexdigest()

    def _set_metadata(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", (key, value))

    def _match_player(self, victim: str, snapshot: dict[str, str]) -> str | None:
        matches = [key for key, name in snapshot.items() if name.casefold() == victim.casefold()]
        return matches[0] if len(matches) == 1 else None

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

    def death_summary(self, player_key: str):
        with self.lock:
            return self.db.execute(
                "SELECT COALESCE(total_deaths,0), COALESCE(zombified_deaths,0), last_death_cause, killer_counts FROM players WHERE player_key=?", (player_key,)
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
