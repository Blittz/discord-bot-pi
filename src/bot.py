import os
import logging
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ALLOWED_CHANNELS = {int(x) for x in os.getenv("ALLOWED_CHANNEL_IDS", "").split(",") if x.strip().isdigit()}

# Discord Intents
intents = discord.Intents.default()
intents.guild_scheduled_events = True  # Standard, non-privileged read/update intent.
intents.message_content = True  # needed for some features; keep only if you use it

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("bot")

async def allowed_channel(interaction: discord.Interaction) -> bool:
    return (not ALLOWED_CHANNELS) or (interaction.channel_id in ALLOWED_CHANNELS)

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.tree_copy_lock = asyncio.Lock()

    async def allowed_channel(self, interaction: discord.Interaction) -> bool:
        return await allowed_channel(interaction)

    async def setup_hook(self):
        # Load cogs with error visibility
        for ext in (
            "cogs.core",
            "cogs.chat",
            "cogs.roll",
            "cogs.admin",
            "cogs.about",
            "cogs.dadjoke",
            "cogs.photosaver",
            "cogs.events",
            "cogs.audio",
            "cogs.ark",
            "cogs.ark_chat",
            "cogs.ark_players",
        ):
            try:
                await self.load_extension(ext)
                log.info(f"Loaded extension: {ext}")
            except Exception as e:
                log.exception(f"Error loading {ext}: {e}")

        # Slash-command synchronization is deliberately manual. Use /sync to
        # publish the current command tree globally after reviewing changes.

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (id={self.user.id})")
        # Set a presence tagline
        await self.change_presence(
            activity=discord.Game(name="👑🤖 “I am your AI overlord”")
        )

bot = MyBot()


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    """Global handler for app command errors."""
    if isinstance(error, app_commands.errors.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ Cooldown: try again in {error.retry_after:.1f}s.",
            ephemeral=True,
        )
    elif isinstance(error, app_commands.errors.CheckFailure):
        await interaction.response.send_message(
            "🔒 Not allowed in this channel.", ephemeral=True
        )
    else:
        log.exception("Command error:", exc_info=error)
        try:
            await interaction.response.send_message(
                "⚠️ Something went wrong. The logs have details.", ephemeral=True
            )
        except discord.InteractionResponded:
            await interaction.followup.send(
                "⚠️ Something went wrong. The logs have details.",
                ephemeral=True,
            )

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN missing in .env")
    bot.run(TOKEN)
