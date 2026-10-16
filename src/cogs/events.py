"""Read-only scheduled events feed for the local photo viewer."""
import asyncio
import logging
import os
from pathlib import Path
from discord.ext import commands
from src.scheduled_events import EventExporter, DEFAULT_EVENTS_FILE

log=logging.getLogger(__name__)


class ScheduledEvents(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        self.exporter=EventExporter(bot.http,Path(os.getenv('SCHEDULED_EVENTS_FILE',str(DEFAULT_EVENTS_FILE))).expanduser())
        self.wakeup=asyncio.Event()
        self.task=asyncio.create_task(self.run())
        self.last_status=None

    def cog_unload(self):
        self.task.cancel()

    async def run(self):
        await self.bot.wait_until_ready()
        while True:
            self.wakeup.clear()
            try:
                status=await self.exporter.refresh(list(self.bot.guilds))
                if status!=self.last_status:
                    log.info('Scheduled event feed status: %s',status)
                    self.last_status=status
            except Exception:
                if self.last_status!='write-failed':
                    log.warning('Scheduled event feed update failed; last snapshot retained')
                    self.last_status='write-failed'
            try:await asyncio.wait_for(self.wakeup.wait(),300)
            except asyncio.TimeoutError:pass
            # Coalesce gateway bursts without delaying startup or blocking the bot.
            if self.wakeup.is_set():await asyncio.sleep(2)

    @commands.Cog.listener()
    async def on_scheduled_event_create(self,event):self.wakeup.set()

    @commands.Cog.listener()
    async def on_scheduled_event_update(self,before,after):self.wakeup.set()

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self,event):self.wakeup.set()

    @commands.Cog.listener()
    async def on_guild_channel_update(self,before,after):self.wakeup.set()

    @commands.Cog.listener()
    async def on_guild_join(self,guild):self.wakeup.set()

    @commands.Cog.listener()
    async def on_guild_remove(self,guild):self.wakeup.set()


async def setup(bot):
    await bot.add_cog(ScheduledEvents(bot))
