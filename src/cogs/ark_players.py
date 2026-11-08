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
from src.ark_stats import (
    DEATH_POLL_SECONDS,
    DEATH_TRACKING_ENABLED,
    LOG_DIRECTORY,
    LOG_FILENAME,
    discover_server_name,
    STATS_ENABLED,
    shared_ark_stats_store,
)

log = logging.getLogger(__name__)
CHANNEL_ID = int(os.getenv("ARK_CHANNEL_ID", "0"))
RELAY_TO_DISCORD = os.getenv("ARK_RELAY_TO_DISCORD", "false").lower() in {"1", "true", "yes", "on"}
ENABLED = os.getenv("ARK_PLAYER_NOTIFICATIONS", "false").lower() in {"1", "true", "yes", "on"}
POLL_SECONDS = float(os.getenv("ARK_PLAYER_POLL_SECONDS", "10"))
MAX_QUEUE = 20
MAX_NAME_LENGTH = 80
RCON_FAILURE_THRESHOLD = 3


def safe_player_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).replace("\x00", " ")
    name = re.sub(r"\s+", " ", name).strip()
    name = discord.utils.escape_mentions(name)
    name = re.sub(r"<@([!&]?)(\d+)>", lambda m: f"<@\u200b{m.group(1)}{m.group(2)}>", name)
    name = re.sub(r"[`*_~]", "", name)
    return name[:MAX_NAME_LENGTH] or "Unknown player"


def online_count_label(count: int) -> str:
    return f"{count} player{'s' if count != 1 else ''} online"


def death_count_label(count: int) -> str:
    return f"{count} {'death' if count == 1 else 'deaths'} total"


@dataclass(frozen=True)
class PlayerAnnouncement:
    text: str


class ArkPlayers(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = shared_ark_service(bot)
        self.stats = shared_ark_stats_store(bot)
        self.snapshot: dict[str, str] | None = None
        self.latest_snapshot: dict[str, str] = {}
        self._availability_initialized = False
        self._rcon_failures = 0
        self._outage_announced = self.stats.server_outage()
        self.queue: asyncio.Queue[PlayerAnnouncement] = asyncio.Queue(maxsize=MAX_QUEUE)
        self._worker = asyncio.create_task(self._delivery_worker())
        self._death_task = asyncio.create_task(self._death_collector())
        self._server_name_task = asyncio.create_task(self._server_name_collector())
        self._poll.start()

    def cog_unload(self):
        self._poll.cancel()
        self._worker.cancel()
        self._death_task.cancel()
        self._server_name_task.cancel()

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
            self._rcon_failures += 1
            self.stats.interrupt_snapshot()
            self.snapshot = None
            if self._availability_initialized and self._rcon_failures == RCON_FAILURE_THRESHOLD and not self._outage_announced:
                self._outage_announced = True
                self.stats.set_server_outage(True)
                if RELAY_TO_DISCORD:
                    await self._enqueue(f"🔴 **{safe_player_name(self.stats.server_name() or 'ARK server')} is offline.**")
            return
        recovered = self._availability_initialized and self._outage_announced
        self._availability_initialized = True
        self._rcon_failures = 0
        self._outage_announced = False
        self.stats.set_server_outage(False)
        self.latest_snapshot = dict(current)
        if STATS_ENABLED:
            self.stats.record_snapshot(current)
        if recovered and RELAY_TO_DISCORD:
            await self._enqueue(f"🟢 **{safe_player_name(self.stats.server_name() or 'ARK server')} is back online!**")
        if self.snapshot is None:
            self.snapshot = current
            return
        previous = self.snapshot
        self.snapshot = current
        server_name = self.stats.server_name()
        server_suffix = f" {safe_player_name(server_name)}" if server_name else " ARK"
        leave_punctuation = "!" if server_name else "."
        for key in current.keys() - previous.keys():
            await self._enqueue(f"🟢 {safe_player_name(current[key])} joined{server_suffix}! ({online_count_label(len(current))})")
        for key in previous.keys() - current.keys():
            await self._enqueue(f"🔴 {safe_player_name(previous[key])} left{server_suffix}{leave_punctuation} ({online_count_label(len(current))})")

    async def _enqueue(self, text: str):
        try:
            self.queue.put_nowait(PlayerAnnouncement(text))
        except asyncio.QueueFull:
            log.warning("ARK player notification queue full; announcement dropped")

    async def _enqueue_death(self, death):
        event = death.event
        victim = safe_player_name(event.victim_name)
        if event.killer_name:
            killer = safe_player_name(event.killer_name)
            level = f"level {event.killer_level} " if event.killer_level is not None else ""
            text = f"{'🧟' if event.zombified else '💀'} **{victim}** was killed by a {level}{killer}"
        else:
            text = f"💀 **{victim}** died under mysterious circumstances"
        if death.total_deaths is not None:
            text += f" ({death_count_label(death.total_deaths)})"
        await self._enqueue(text)

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

    async def _death_collector(self):
        if not DEATH_TRACKING_ENABLED or LOG_DIRECTORY is None:
            return
        await self.bot.wait_until_ready()
        await asyncio.sleep(DEATH_POLL_SECONDS)
        path = LOG_DIRECTORY / LOG_FILENAME
        while True:
            try:
                deaths = await asyncio.to_thread(self.stats.collect_log, path, dict(self.latest_snapshot), True)
                if RELAY_TO_DISCORD:
                    for death in deaths:
                        await self._enqueue_death(death)
            except Exception:
                log.warning("ARK death log collection failed; continuing player monitoring", exc_info=False)
            await asyncio.sleep(DEATH_POLL_SECONDS)

    async def _server_name_collector(self):
        if LOG_DIRECTORY is None:
            return
        path = LOG_DIRECTORY / LOG_FILENAME
        while True:
            try:
                name = await asyncio.to_thread(discover_server_name, path)
                if name:
                    self.stats.set_server_name(name)
            except Exception:
                log.warning("ARK server-name discovery failed; using cached/fallback name", exc_info=False)
            await asyncio.sleep(DEATH_POLL_SECONDS)

    @_poll.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()
        if ENABLED or STATS_ENABLED:
            await self._poll_once()


async def setup(bot: commands.Bot):
    await bot.add_cog(ArkPlayers(bot))
