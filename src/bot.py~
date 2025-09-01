import os
import logging
import asyncio
import discord
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

class Guard(commands.Cog):
    """Global checks & error handling."""
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx, exc):
        if isinstance(exc, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ Cooldown: try again in {exc.retry_after:.1f}s.", ephemeral=True if hasattr(ctx, "response") else False)
        else:
            log.exception("Command error:", exc_info=exc)
            try:
                await ctx.reply("⚠️ Something went wrong. The logs have details.")
            except Exception:
                pass

async def allowed_channel(interaction: discord.Interaction) -> bool:
    return (not ALLOWED_CHANNELS) or (interaction.channel_id in ALLOWED_CHANNELS)

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.tree_copy_lock = asyncio.Lock()

# near top of file
import logging
log = logging.getLogger("bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ensure these are read
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # ok if you need it
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Load cogs with error visibility
        for ext in ("cogs.core", "cogs.chat", "cogs.roll", "cogs.admin", "cogs.about"):
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

bot = MyBot()

@bot.tree.command(name="ping", description="Check if the bot is alive.")
@discord.app_commands.check(allowed_channel)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 pong")

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN missing in .env")
    bot.run(TOKEN)
