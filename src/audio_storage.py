"""ID-scoped audio storage with atomic writes and quota checks."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

SCOPES = {"personal", "channel", "server"}
MAX_USER_BYTES = int(os.getenv("AUDIO_PERSONAL_QUOTA_MB", "250")) * 1024 * 1024
MAX_SERVER_BYTES = int(os.getenv("AUDIO_SERVER_QUOTA_GB", "2")) * 1024 * 1024 * 1024

class AudioStorage:
    def __init__(self, root: Path): self.root = root.expanduser().resolve()
    def scope_dir(self, guild_id: int, scope: str, owner_id: int | None = None, channel_id: int | None = None) -> Path:
        if scope not in SCOPES: raise ValueError("invalid audio scope")
        if scope == "personal" and owner_id is None: raise ValueError("personal owner required")
        if scope == "channel" and channel_id is None: raise ValueError("channel required")
        suffix = str(owner_id) if scope == "personal" else str(channel_id) if scope == "channel" else "shared"
        path = (self.root / "servers" / str(int(guild_id)) / scope / suffix).resolve()
        if self.root not in path.parents: raise ValueError("storage path escaped root")
        path.mkdir(parents=True, exist_ok=True); return path
    def metadata_path(self, path: Path) -> Path: return path.with_suffix(path.suffix + ".json")
    def list_files(self, guild_id: int, scope: str, owner_id=None, channel_id=None) -> list[Path]:
        directory = self.scope_dir(guild_id, scope, owner_id, channel_id)
        return sorted((p for p in directory.iterdir() if p.is_file() and not p.is_symlink() and not p.name.endswith(".json")), key=lambda p: p.name.lower())
    def server_bytes(self, guild_id: int) -> int:
        directory = (self.root / "servers" / str(int(guild_id))).resolve()
        if self.root not in directory.parents or not directory.exists(): return 0
        return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file() and not p.is_symlink() and not p.name.endswith(".json"))
    def personal_bytes(self, guild_id: int, owner_id: int) -> int:
        return sum(p.stat().st_size for p in self.list_files(guild_id, "personal", owner_id=owner_id))
    def reserve_path(self, guild_id: int, scope: str, display_name: str, owner_id=None, channel_id=None) -> tuple[Path, Path]:
        directory = self.scope_dir(guild_id, scope, owner_id, channel_id)
        suffix = Path(display_name).suffix.lower()
        if suffix not in {".mp3", ".wav", ".ogg", ".flac", ".m4a"}: raise ValueError("unsupported audio format")
        path = directory / f"{uuid.uuid4().hex}{suffix}"
        return path, self.metadata_path(path)
    def write_metadata(self, path: Path, display_name: str, owner_id: int, scope: str, channel_id=None):
        self.metadata_path(path).write_text(json.dumps({"display_name": display_name[:200], "owner_id": int(owner_id), "scope": scope, "channel_id": channel_id}), encoding="utf-8")

    def save_file(self, source: Path, guild_id: int, scope: str, display_name: str, owner_id: int, channel_id=None, personal_quota=MAX_USER_BYTES, server_quota=MAX_SERVER_BYTES) -> Path:
        size = source.stat().st_size
        if size > server_quota or self.server_bytes(guild_id) + size > server_quota:
            raise ValueError("This server's audio storage quota would be exceeded.")
        if scope == "personal" and self.personal_bytes(guild_id, owner_id) + size > personal_quota:
            raise ValueError("Your personal audio storage quota would be exceeded.")
        destination, metadata = self.reserve_path(guild_id, scope, display_name, owner_id, channel_id)
        partial = destination.with_suffix(destination.suffix + ".partial")
        try:
            partial.write_bytes(source.read_bytes())
            partial.replace(destination)
            self.write_metadata(destination, display_name, owner_id, scope, channel_id)
            return destination
        except Exception:
            partial.unlink(missing_ok=True); destination.unlink(missing_ok=True); metadata.unlink(missing_ok=True); raise

    def delete_file(self, path: Path, guild_id: int) -> None:
        path = path.absolute(); root = (self.root / "servers" / str(int(guild_id))).resolve()
        if root not in path.resolve().parents or path.is_symlink() or not path.is_file(): raise ValueError("Invalid managed audio file.")
        path.unlink(); self.metadata_path(path).unlink(missing_ok=True)
