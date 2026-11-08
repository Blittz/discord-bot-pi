"""Disabled-by-default ARK player join/leave notifications."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import unicodedata
from dataclasses import dataclass

import discord
from discord.ext import commands, tasks

from src.ark_service import shared_ark_service
from src.ark_stats import STATS_ENABLED, shared_ark_stats_store

log = logging.getLogger(__name__)
CHANNEL_ID = int(os.getenv("ARK_CHANNEL_ID", "0"))
ENABLED = os.getenv("ARK_PLAYER_NOTIFICATIONS", "false").lower() in {"1", "true", "yes", "on"}
POLL_SECONDS = float(os.getenv("ARK_PLAYER_POLL_SECONDS", "10"))
MAX_QUEUE = 20
MAX_NAME_LENGTH = 80


def safe_player_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).replace("\x00", " ")
    name = re.sub(r"\s+", " ", name).strip()
    name = discord.utils.escape_mentions(name)
    name = re.sub(r"<@([!&]?)(\d+)>", lambda m: f"<@\u200b{m.group(1)}{m.group(2)}>", name)
    name = re.sub(r"[`*_~]", "", name)
    return name[:MAX_NAME_LENGTH] or "Unknown player"


@dataclass(frozen=True)
class PlayerAnnouncement:
    text: str


class ArkPlayers(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = shared_ark_service(bot)
        self.stats = shared_ark_stats_store(bot)
        self.snapshot: dict[str, str] | None = None
        self.queue: asyncio.Queue[PlayerAnnouncement] = asyncio.Queue(maxsize=MAX_QUEUE)
        self._worker = asyncio.create_task(self._delivery_worker())
        self._poll.start()

    def cog_unload(self):
        self._poll.cancel()
        self._worker.cancel()

    async def _channel(self):
        if not CHANNEL_ID:
            return None
        channel = self.bot.get_channel(CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(CHANNEL_ID)
            except discord.DiscordException:
                return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _sample(self) -> dict[str, str] | None:
        try:
            return await self.service.player_snapshot()
        except (TimeoutError, ConnectionError, OSError, PermissionError, ValueError):
            log.warning("ARK player snapshot unavailable; notifications paused", exc_info=False)
            return None
        except Exception:
            log.warning("ARK player snapshot failed; notifications paused", exc_info=False)
            return None

    async def _poll_once(self):
        current = await self._sample()
        if current is None:
            self.snapshot = None
            return
        if STATS_ENABLED:
            self.stats.record_snapshot(current)
        if self.snapshot is None:
            self.snapshot = current
            return
        previous = self.snapshot
        self.snapshot = current
        for key in current.keys() - previous.keys():
            await self._enqueue(f"🟢 {safe_player_name(current[key])} joined ARK! ({len(current)} players online)")
        for key in previous.keys() - current.keys():
            await self._enqueue(f"🔴 {safe_player_name(previous[key])} left ARK. ({len(current)} players online)")

    async def _enqueue(self, text: str):
        try:
            self.queue.put_nowait(PlayerAnnouncement(text))
        except asyncio.QueueFull:
            log.warning("ARK player notification queue full; announcement dropped")

    async def _delivery_worker(self):
        while True:
            announcement = await self.queue.get()
            try:
                channel = await self._channel()
                if channel is not None:
                    await channel.send(announcement.text, allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                log.warning("ARK player notification delivery failed", exc_info=False)
            finally:
                self.queue.task_done()

    @tasks.loop(seconds=POLL_SECONDS)
    async def _poll(self):
        if ENABLED or STATS_ENABLED:
            await self._poll_once()

    @_poll.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()
        if ENABLED or STATS_ENABLED:
            await self._poll_once()


async def setup(bot: commands.Bot):
    await bot.add_cog(ArkPlayers(bot))
