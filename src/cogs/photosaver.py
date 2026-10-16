import asyncio
import logging
import os
from pathlib import Path
from typing import Iterable

import discord
from discord.ext import commands
from src.photo_storage import NetworkPhotoStore, sanitize

log = logging.getLogger(__name__)
PHOTO_BASE_DIR = Path(os.getenv("PHOTO_SAVE_DIR", "~/discord-photos")).expanduser().absolute()
REQUIRED_MOUNT = os.getenv("PHOTO_REQUIRED_MOUNT", str(Path.home() / "server/Shared"))
STATE_FILE = Path(os.getenv("PHOTO_CHANNEL_MAP", "~/.local/state/discord-photo-saver/channels.json")).expanduser()
_sanitize_for_path = sanitize


def _iter_downloadable_attachments(attachments: Iterable[discord.Attachment]):
    for attachment in attachments:
        content_type = (attachment.content_type or "").lower()
        if any(content_type.startswith(prefix) for prefix in ("image/", "video/")):
            yield attachment
            continue

        # Fall back to basic extension check when Discord doesn't populate
        # ``content_type`` (for example when uploaded from some mobile apps).
        filename_lower = attachment.filename.lower()
        if any(
            filename_lower.endswith(ext)
            for ext in (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".bmp",
                ".mp4",
                ".mov",
                ".mkv",
                ".avi",
                ".webm",
            )
        ):
            yield attachment


class PhotoSaver(commands.Cog):
    """Save image attachments from channels the bot can see."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = NetworkPhotoStore(PHOTO_BASE_DIR, REQUIRED_MOUNT, STATE_FILE)
        self._storage_lock = asyncio.Lock()
        try:
            self.store.verify()
            log.info("PhotoSaver network storage verified")
        except OSError:
            log.warning("PhotoSaver network storage unavailable; downloads will fail closed")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.attachments or message.author.bot:
            return
        channel_id = message.channel.id
        channel_name = str(getattr(message.channel, "name", channel_id))
        for attachment in _iter_downloadable_attachments(message.attachments):
            pending = None
            async with self._storage_lock:
                try:
                    pending = await asyncio.to_thread(self.store.prepare, channel_id, channel_name,
                                                      attachment.id, attachment.filename, attachment.size)
                    if pending is None:
                        log.info("PhotoSaver duplicate skipped attachment=%s channel=%s", attachment.id, channel_id)
                        continue
                    await attachment.save(pending.file)
                    await asyncio.to_thread(pending.finish, attachment.size)
                    log.info("PhotoSaver saved attachment=%s channel=%s", attachment.id, channel_id)
                except Exception as error:
                    # Exception messages can contain signed CDN URLs; log the type only.
                    log.error("PhotoSaver download failed attachment=%s channel=%s reason=%s",
                              attachment.id, channel_id, type(error).__name__)
                finally:
                    if pending is not None:
                        await asyncio.to_thread(pending.close)


async def setup(bot: commands.Bot):
    await bot.add_cog(PhotoSaver(bot))
