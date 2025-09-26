import logging
import os
from pathlib import Path
from typing import Iterable

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

_DEFAULT_PHOTO_BASE_DIR = Path("~/discord-photos").expanduser()

def _get_photo_base_dir() -> Path:

    raw_path = os.getenv("PHOTO_SAVE_DIR")
    if not raw_path:
        return _DEFAULT_PHOTO_BASE_DIR

    expanded = Path(raw_path).expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded

    return expanded


PHOTO_BASE_DIR = _get_photo_base_dir()


def _sanitize_for_path(value: str, fallback: str) -> str:
    """Return a filesystem-safe version of ``value``.

    Only keep alphanumeric characters, dashes and underscores. Collapses
    everything else into underscores so we avoid issues with odd characters
    Discord channel names might contain.
    """

    value = value.strip()
    if not value:
        return fallback

    safe = []
    for char in value:
        if char.isalnum() or char in {"-", "_","."}:
            safe.append(char)
        else:
            safe.append("_")

    sanitized = "".join(safe).strip("_")
    return sanitized or fallback


def _iter_image_attachments(attachments: Iterable[discord.Attachment]):
    for attachment in attachments:
        content_type = attachment.content_type or ""
        if content_type.startswith("image/"):
            yield attachment
            continue

        # Fall back to basic extension check when Discord doesn't populate
        # ``content_type`` (for example when uploaded from some mobile apps).
        filename_lower = attachment.filename.lower()
        if any(filename_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
            yield attachment


class PhotoSaver(commands.Cog):
    """Save image attachments from channels the bot can see."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        PHOTO_BASE_DIR.mkdir(parents=True, exist_ok=True)
        log.info("PhotoSaver storing attachments in %s", PHOTO_BASE_DIR)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.attachments:
            return

        if message.author.bot:
            return

        image_attachments = list(_iter_image_attachments(message.attachments))
        if not image_attachments:
            return

        channel_name = getattr(message.channel, "name", None) or getattr(message.channel, "id", "unknown")
        channel_dir_name = _sanitize_for_path(str(channel_name), "unknown")
        channel_dir = PHOTO_BASE_DIR / channel_dir_name
        channel_dir.mkdir(parents=True, exist_ok=True)

        for attachment in image_attachments:
            filename = _sanitize_for_path(attachment.filename, str(attachment.id))
            target_path = channel_dir / f"{attachment.id}_{filename}"

            try:
                await attachment.save(target_path)
            except Exception:
                log.exception("Failed to save attachment %s from channel %s", attachment.id, channel_name)
            else:
                log.info("Saved attachment %s to %s", attachment.id, target_path)


async def setup(bot: commands.Bot):
    await bot.add_cog(PhotoSaver(bot))
