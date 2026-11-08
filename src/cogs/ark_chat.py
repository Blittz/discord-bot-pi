"""Disabled-by-default, channel-scoped ARK/Discord chat relay."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field

import discord
from discord.ext import commands, tasks

from src.ark_service import ArkRconService, shared_ark_service

log = logging.getLogger(__name__)
CHANNEL_ID = int(os.getenv("ARK_CHANNEL_ID", "0"))
POLL_SECONDS = float(os.getenv("ARK_CHAT_POLL_SECONDS", "5"))
RELAY_TO_DISCORD = os.getenv("ARK_RELAY_TO_DISCORD", "false").lower() in {"1", "true", "yes", "on"}
RELAY_TO_ARK = os.getenv("ARK_RELAY_TO_ARK", "false").lower() in {"1", "true", "yes", "on"}
MAX_CHAT_LENGTH = 180
DEDUP_TTL = 900.0
MAX_DEDUP_ENTRIES = 512
MAX_QUEUE = 50
INBOUND_MAX_RETRIES = 3
INBOUND_MAX_AGE = 120.0
INBOUND_RETRY_BASE = 1.0
INBOUND_RETRY_MAX = 15.0
OUTBOUND_PACING_SECONDS = float(os.getenv("ARK_RELAY_OUTBOUND_PACING_SECONDS", "1"))
USER_WINDOW_SECONDS = float(os.getenv("ARK_RELAY_USER_WINDOW_SECONDS", "10"))
USER_BURST_LIMIT = int(os.getenv("ARK_RELAY_USER_BURST_LIMIT", "5"))
USER_PENDING_LIMIT = int(os.getenv("ARK_RELAY_USER_PENDING_LIMIT", "5"))
FEEDBACK_COOLDOWN = 30.0


@dataclass
class RelayCounters:
    fetched: int = 0
    parsed: int = 0
    duplicate: int = 0
    queue_full: int = 0
    received: int = 0
    queued: int = 0
    sent: int = 0
    rejected: int = 0
    failed: int = 0
    reject_reasons: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejected += 1
        self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1


@dataclass(frozen=True)
class OutboundMessage:
    message: discord.Message
    text: str
    user_id: int


@dataclass(frozen=True)
class InboundMessage:
    key: str
    text: str
    created: float
    attempts: int = 0


def normalize_chat_line(line: str) -> str:
    line = unicodedata.normalize("NFKC", line).replace("\x00", " ")
    line = re.sub(r"\s+", " ", line).strip()
    return line[:MAX_CHAT_LENGTH]


def chat_fingerprint(line: str) -> str:
    return hashlib.sha256(normalize_chat_line(line).casefold().encode("utf-8")).hexdigest()


def chat_event_key(line: str) -> str:
    """Use a visible speaker prefix when ARK provides one; IDs are never used."""
    normalized = normalize_chat_line(line)
    match = re.match(r"^([^:]{1,80}):\s*(.*)$", normalized)
    if match:
        return chat_fingerprint(f"{match.group(1).casefold()}\0{match.group(2)}")
    return chat_fingerprint(normalized)


def sanitize_discord_text(line: str) -> str:
    line = normalize_chat_line(line)
    line = discord.utils.escape_mentions(line)
    line = re.sub(r"<@([!&]?)(\d+)>", lambda match: f"<@\u200b{match.group(1)}{match.group(2)}>", line)
    line = re.sub(r"[`*_~]", "", line)
    return line[:MAX_CHAT_LENGTH]


def parse_chat_lines(response: str) -> list[str]:
    return [line for line in (normalize_chat_line(x) for x in response.splitlines()) if line]


class ExpiringDedup:
    def __init__(self, ttl: float = DEDUP_TTL, limit: int = MAX_DEDUP_ENTRIES):
        self.ttl, self.limit = ttl, limit
        self._items: dict[str, float] = {}

    def _prune(self, now: float) -> None:
        for key, expires in list(self._items.items()):
            if expires <= now:
                self._items.pop(key, None)
        while len(self._items) > self.limit:
            self._items.pop(next(iter(self._items)))

    def add(self, line: str, now: float | None = None) -> bool:
        return self.add_key(chat_fingerprint(line), now)

    def add_key(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._prune(now)
        if key in self._items:
            return False
        self._items[key] = now + self.ttl
        return True

    def contains(self, line: str, now: float | None = None) -> bool:
        return self.contains_key(chat_fingerprint(line), now)

    def contains_key(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._prune(now)
        return key in self._items


class ArkChat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = shared_ark_service(bot)
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUE)
        self.inbound_queue: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=MAX_QUEUE)
        self.outbound_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=MAX_QUEUE)
        self.inbound_queued: set[str] = set()
        self.inbound_inflight: set[str] = set()
        self.inbound_delivered = ExpiringDedup()
        self.user_sends: dict[int, deque[float]] = {}
        self.user_pending: dict[int, int] = {}
        self.feedback_at: dict[tuple[int, str], float] = {}
        self.counters = RelayCounters()
        self.outbound_echoes: dict[str, float] = {}
        self.retry_after = 0.0
        self.retry_delay = POLL_SECONDS
        self._baseline_ready = False
        self._worker_task = asyncio.create_task(self._discord_worker())
        self._outbound_worker_task = asyncio.create_task(self._outbound_worker())
        self._poll_loop.start()

    def cog_unload(self):
        self._poll_loop.cancel()
        self._worker_task.cancel()
        self._outbound_worker_task.cancel()

    async def _channel(self):
        if not CHANNEL_ID:
            return None
        channel = self.bot.get_channel(CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(CHANNEL_ID)
            except (discord.DiscordException, discord.HTTPException):
                return None
        if not isinstance(channel, discord.TextChannel):
            return None
        return channel

    @tasks.loop(seconds=POLL_SECONDS)
    async def _poll_loop(self):
        if not RELAY_TO_DISCORD or time.monotonic() < self.retry_after:
            return
        try:
            response = await self.service.chat()
            self.counters.fetched += 1
            lines = parse_chat_lines(response)
            self.counters.parsed += len(lines)
            if not self._baseline_ready:
                for line in lines:
                    self.inbound_delivered.add_key(chat_event_key(line))
                self._baseline_ready = True
                return
            for line in lines:
                now = time.monotonic()
                self.outbound_echoes = {text: expires for text, expires in self.outbound_echoes.items() if expires > now}
                if any(text in line for text in self.outbound_echoes):
                    continue
                key = chat_event_key(line)
                if key in self.inbound_queued or key in self.inbound_inflight or self.inbound_delivered.contains_key(key):
                    self.counters.duplicate += 1
                    continue
                item = InboundMessage(key, line, time.monotonic())
                try:
                    self.inbound_queue.put_nowait(item)
                    self.inbound_queued.add(key)
                    self.counters.queued += 1
                except asyncio.QueueFull:
                    self.counters.queue_full += 1
                    log.warning("ARK inbound relay queue full; message retained only if GetChat returns it again")
            self.retry_delay = POLL_SECONDS
        except (TimeoutError, ConnectionError, OSError):
            self.retry_after = time.monotonic() + self.retry_delay
            self.retry_delay = min(self.retry_delay * 2, 60.0)
            log.warning("ARK chat polling unavailable; retrying", exc_info=False)
        except Exception:
            self.retry_after = time.monotonic() + self.retry_delay
            self.retry_delay = min(self.retry_delay * 2, 60.0)
            log.warning("ARK chat polling failed; retrying", exc_info=False)

    @_poll_loop.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()
        if RELAY_TO_DISCORD:
            try:
                response = await self.service.chat()
                for line in parse_chat_lines(response):
                    self.inbound_delivered.add_key(chat_event_key(line))
                self._baseline_ready = True
            except Exception:
                log.warning("ARK chat baseline unavailable; relay remains paused", exc_info=False)

    async def _discord_worker(self):
        while True:
            item = await self.inbound_queue.get()
            self.inbound_queued.discard(item.key)
            self.inbound_inflight.add(item.key)
            try:
                channel = await self._channel()
                if channel is None:
                    await self._retry_inbound(item, "channel-unavailable")
                else:
                    await channel.send(f"**ARK** {sanitize_discord_text(item.text)}", allowed_mentions=discord.AllowedMentions.none())
                    self.inbound_inflight.discard(item.key)
                    self.inbound_delivered.add_key(item.key)
                    self.counters.sent += 1
            except (discord.DiscordException, asyncio.TimeoutError, OSError):
                self.inbound_inflight.discard(item.key)
                self.counters.failed += 1
                log.warning("Could not deliver an ARK chat update; send result is uncertain and was not retried", exc_info=False)
            except Exception:
                self.inbound_inflight.discard(item.key)
                self.counters.failed += 1
                log.warning("Could not deliver an ARK chat update; send result is uncertain and was not retried", exc_info=False)
            finally:
                self.inbound_queue.task_done()

    async def _retry_inbound(self, item: InboundMessage, reason: str) -> None:
        age = time.monotonic() - item.created
        if item.attempts >= INBOUND_MAX_RETRIES or age >= INBOUND_MAX_AGE:
            self.inbound_inflight.discard(item.key)
            self.counters.failed += 1
            log.warning("ARK inbound relay expired after bounded retries reason=%s", reason)
            return
        delay = min(INBOUND_RETRY_BASE * (2 ** item.attempts), INBOUND_RETRY_MAX)
        await asyncio.sleep(delay)
        self.inbound_inflight.discard(item.key)
        try:
            self.inbound_queue.put_nowait(InboundMessage(item.key, item.text, item.created, item.attempts + 1))
            self.inbound_queued.add(item.key)
            self.counters.retried += 1
        except asyncio.QueueFull:
            self.counters.queue_full += 1
            log.warning("ARK inbound retry queue full reason=%s", reason)

    async def _feedback(self, message: discord.Message, reason: str, text: str) -> None:
        now = time.monotonic()
        key = (message.author.id, reason)
        if now - self.feedback_at.get(key, 0) < FEEDBACK_COOLDOWN:
            return
        self.feedback_at[key] = now
        try:
            await message.reply(text, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except discord.DiscordException:
            log.warning("Could not send ARK relay feedback", exc_info=False)

    async def _outbound_worker(self):
        while True:
            item = await self.outbound_queue.get()
            try:
                await self.service.server_chat(item.text)
                self.counters.sent += 1
                self.outbound_echoes[item.text] = time.monotonic() + DEDUP_TTL
            except (TimeoutError, ConnectionError, OSError, PermissionError):
                self.counters.failed += 1
                await self._feedback(item.message, "send-failed", "ARK chat delivery failed; it was not retried.")
                log.warning("Could not send a Discord chat message to ARK", exc_info=False)
            finally:
                self.user_pending[item.user_id] = max(0, self.user_pending.get(item.user_id, 1) - 1)
                self.outbound_queue.task_done()
            await asyncio.sleep(max(0.0, OUTBOUND_PACING_SECONDS))

    def _allow_user_message(self, user_id: int, now: float) -> bool:
        timestamps = self.user_sends.setdefault(user_id, deque())
        while timestamps and timestamps[0] <= now - USER_WINDOW_SECONDS:
            timestamps.popleft()
        if len(timestamps) >= USER_BURST_LIMIT:
            return False
        timestamps.append(now)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id == CHANNEL_ID and not message.author.bot and not message.webhook_id:
            self.counters.received += 1
        if not RELAY_TO_ARK or message.channel.id != CHANNEL_ID:
            return
        if message.author.bot or message.webhook_id:
            return
        now = time.monotonic()
        if not self._allow_user_message(message.author.id, now):
            self.counters.reject("rate-limit")
            await self._feedback(message, "rate-limit", "ARK relay rate limit reached; please wait before sending more messages.")
            return
        text = sanitize_discord_text(message.content)
        if not text or text.startswith("/"):
            self.counters.reject("invalid-message")
            await self._feedback(message, "invalid-message", "That message cannot be sent to ARK.")
            return
        try:
            if self.outbound_queue.full() or self.user_pending.get(message.author.id, 0) >= USER_PENDING_LIMIT:
                self.counters.reject("queue-full")
                await self._feedback(message, "queue-full", "ARK relay is busy; this message was not queued.")
                return
            self.outbound_queue.put_nowait(OutboundMessage(message, text, message.author.id))
            self.user_pending[message.author.id] = self.user_pending.get(message.author.id, 0) + 1
            self.counters.queued += 1
        except asyncio.QueueFull:
            self.counters.reject("queue-full")
            await self._feedback(message, "queue-full", "ARK relay is busy; this message was not queued.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ArkChat(bot))
