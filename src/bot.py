import os
import logging
import asyncio
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
ALLOWED_CHANNELS = {int(x) for x in os.getenv("ALLOWED_CHANNEL_IDS", "").split(",") if x.strip().isdigit()}

# Discord Intents
intents = discord.Intents.default()
intents.message_content = True  # needed for some features; keep only if you use it

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("bot")

async def allowed_channel(interaction: discord.Interaction) -> bool:
    return (not ALLOWED_CHANNELS) or (interaction.channel_id in ALLOWED_CHANNELS)


def _format_timedelta(delta: datetime.timedelta) -> str:
    total = int(delta.total_seconds())
    days, total = divmod(total, 86400)
    hours, total = divmod(total, 3600)
    minutes, seconds = divmod(total, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.tree_copy_lock = asyncio.Lock()
        self.start_time = discord.utils.utcnow()

    async def setup_hook(self):
        # Load cogs with error visibility
        for ext in (
            "cogs.core",
            "cogs.chat",
            "cogs.roll",
            "cogs.admin",
            "cogs.about",
            "cogs.dadjoke",
        ):
            try:
                await self.load_extension(ext)
                log.info(f"Loaded extension: {ext}")
            except Exception as e:
                log.exception(f"Error loading {ext}: {e}")

        # Force GUILD sync (instant) if GUILD_ID present, else global
        try:
            if GUILD_ID:
                guild = discord.Object(id=GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info(f"Synced {len(synced)} commands to guild {GUILD_ID}: {[c.name for c in synced]}")
            else:
                synced = await self.tree.sync()
                log.info(f"Synced {len(synced)} global commands: {[c.name for c in synced]}")
        except Exception as e:
            log.exception(f"Slash command sync failed: {e}")

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

@bot.tree.command(name="ping", description="Check if the bot is alive.")
@discord.app_commands.check(allowed_channel)
async def ping(interaction: discord.Interaction):
    latency_ms = bot.latency * 1000
    uptime = discord.utils.utcnow() - bot.start_time
    uptime_str = _format_timedelta(uptime)
    await interaction.response.send_message(
        f"🏓 Pong! Latency: {latency_ms:.0f} ms | Uptime: {uptime_str}"
    )

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN missing in .env")
    bot.run(TOKEN)
