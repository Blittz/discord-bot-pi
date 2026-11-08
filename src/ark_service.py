"""Small, read-only ARK RCON service used by the Discord cog."""

from __future__ import annotations

import asyncio
import os
import re
import select
import socket
import struct
from dataclasses import dataclass


HOST_DEFAULT = "192.168.1.10"
PORT_DEFAULT = 27020
TIMEOUT_DEFAULT = 5.0
MAX_PACKET_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_PACKETS = 64
RESPONSE_IDLE_TIMEOUT = 0.5
_PLAYER_LINE = re.compile(r"^\s*(?:\d+\.)?\s*(.*?)\s*(?:,\s*.*)?$")
_PLAYER_ID = re.compile(r"^[A-Za-z0-9_-]{6,128}$")


class SourceRconClient:
    """Minimal dependency-free Source RCON client."""

    def __init__(self, host: str, port: int, password: str, timeout: float):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._next_id = 1
        self._authenticate(password)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_exact(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("RCON peer closed the connection")
            data.extend(chunk)
        return bytes(data)

    def _read_packet(self) -> tuple[int, int, str]:
        length = struct.unpack("<i", self._read_exact(4))[0]
        if length < 10 or length > MAX_PACKET_BYTES:
            raise ValueError("invalid RCON packet length")
        payload = self._read_exact(length)
        request_id, packet_type = struct.unpack("<ii", payload[:8])
        body = payload[8:].split(b"\0", 1)[0].decode("utf-8", errors="replace")
        return request_id, packet_type, body

    def _send_packet(self, packet_type: int, body: str) -> int:
        request_id = self._next_id
        self._next_id += 1
        payload = struct.pack("<ii", request_id, packet_type) + body.encode("utf-8") + b"\0\0"
        self.sock.sendall(struct.pack("<i", len(payload)) + payload)
        return request_id

    def _authenticate(self, password: str) -> None:
        request_id = self._send_packet(3, password)
        response_id, _packet_type, _body = self._read_packet()
        if response_id == -1:
            raise PermissionError("RCON authentication failed")
        if response_id != request_id:
            raise ConnectionError("unexpected RCON authentication response")

    def _response(self, command: str, *, allow_chat: bool = False) -> str:
        allowed = {"ListPlayers"} | ({"GetChat"} if allow_chat else set())
        is_server_chat = allow_chat and command.startswith("ServerChat ") and len(command) > len("ServerChat ")
        if command not in allowed and not is_server_chat:
            raise ValueError("command is not permitted by the service")
        request_id = self._send_packet(2, command)
        chunks = []
        total = 0
        original_timeout = self.sock.gettimeout()
        try:
            self.sock.settimeout(original_timeout)
            for packet_number in range(MAX_RESPONSE_PACKETS):
                response_id, _packet_type, body = self._read_packet()
                if response_id != request_id:
                    raise ConnectionError("unexpected RCON command response")
                total += len(body.encode("utf-8"))
                if total > MAX_RESPONSE_BYTES:
                    raise ValueError("RCON response exceeds size limit")
                chunks.append(body)
                ready, _, _ = select.select([self.sock], [], [], RESPONSE_IDLE_TIMEOUT)
                if not ready:
                    # Source RCON has no universal end-of-response marker for
                    # all ARK builds. An idle interval is the bounded framing
                    # fallback; partial packets are never accepted.
                    break
            else:
                raise ValueError("RCON response exceeds packet limit")
        finally:
            self.sock.settimeout(original_timeout)
        return "".join(chunks)

    def run(self, command: str) -> str:
        return self._response(command)

    def get_chat(self) -> str:
        return self._response("GetChat", allow_chat=True)

    def server_chat(self, text: str) -> None:
        self._response(f"ServerChat {text}", allow_chat=True)


def parse_players(response: str) -> list[str]:
    """Extract display names only; discard platform IDs and malformed rows."""
    players: list[str] = []
    for raw_line in response.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith(("no players", "list players")):
            continue
        match = _PLAYER_LINE.match(line)
        name = (match.group(1) if match else "").strip()
        if name and name not in players and len(name) <= 100:
            players.append(name)
    return players


@dataclass(frozen=True)
class ArkPlayer:
    key: str
    name: str


def parse_player_snapshot(response: str) -> dict[str, str]:
    """Return stable internal player keys mapped to display names."""
    snapshot: dict[str, str] = {}
    for raw_line in response.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith(("no players", "list players")):
            continue
        match = _PLAYER_LINE.match(line)
        if not match:
            continue
        name = match.group(1).strip()
        if not name or len(name) > 100:
            continue
        fields = [field.strip() for field in line.split(",")[1:]]
        stable_id = next((field for field in fields if _PLAYER_ID.fullmatch(field)), None)
        key = f"id:{stable_id}" if stable_id else f"name:{name.casefold()}"
        snapshot.setdefault(key, name)
    return snapshot


@dataclass(frozen=True)
class ArkStatus:
    reachable: bool
    authenticated: bool
    players: tuple[str, ...] = ()
    error: str | None = None


class ArkRconService:
    def __init__(self, host: str | None = None, port: int | None = None, timeout: float | None = None, password: str | None = None):
        self.host = host or os.getenv("ARK_RCON_HOST", HOST_DEFAULT)
        self.port = port or int(os.getenv("ARK_RCON_PORT", str(PORT_DEFAULT)))
        self.timeout = timeout or float(os.getenv("ARK_RCON_TIMEOUT", str(TIMEOUT_DEFAULT)))
        self.password = password if password is not None else os.getenv("ARK_RCON_PASSWORD", "")
        self._operation_lock = asyncio.Lock()

    def _players_sync(self) -> list[str]:
        if not self.password:
            raise PermissionError("RCON password is not configured")
        with SourceRconClient(self.host, self.port, self.password, self.timeout) as client:
            return parse_players(client.run("ListPlayers"))

    def _player_snapshot_sync(self) -> dict[str, str]:
        if not self.password:
            raise PermissionError("RCON password is not configured")
        with SourceRconClient(self.host, self.port, self.password, self.timeout) as client:
            return parse_player_snapshot(client.run("ListPlayers"))

    def _chat_sync(self) -> str:
        if not self.password:
            raise PermissionError("RCON password is not configured")
        with SourceRconClient(self.host, self.port, self.password, self.timeout) as client:
            return client.get_chat()

    def _server_chat_sync(self, text: str) -> None:
        if not self.password:
            raise PermissionError("RCON password is not configured")
        with SourceRconClient(self.host, self.port, self.password, self.timeout) as client:
            client.server_chat(text)

    async def players(self) -> list[str]:
        async with self._operation_lock:
            return await asyncio.to_thread(self._players_sync)

    async def player_snapshot(self) -> dict[str, str]:
        async with self._operation_lock:
            return await asyncio.to_thread(self._player_snapshot_sync)

    async def chat(self) -> str:
        async with self._operation_lock:
            return await asyncio.to_thread(self._chat_sync)

    async def server_chat(self, text: str) -> None:
        async with self._operation_lock:
            await asyncio.to_thread(self._server_chat_sync, text)

    async def status(self) -> ArkStatus:
        try:
            players = await self.players()
            return ArkStatus(True, True, tuple(players))
        except PermissionError:
            return ArkStatus(True, False, error="authentication failed or password is not configured")
        except (socket.timeout, TimeoutError):
            return ArkStatus(False, False, error="RCON request timed out")
        except (ConnectionError, OSError):
            return ArkStatus(False, False, error="RCON server unavailable")
        except Exception:
            return ArkStatus(False, False, error="RCON request failed")


def shared_ark_service(bot) -> ArkRconService:
    service = getattr(bot, "ark_rcon_service", None)
    if service is None:
        service = ArkRconService()
        bot.ark_rcon_service = service
    return service
