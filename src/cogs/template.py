import discord
from discord.ext import commands
from discord import app_commands

# Optional: limit where commands can run (leave set() empty to allow everywhere)
ALLOWED_CHANNELS = set()  # e.g., {123456789012345678}

def _allowed_channel(interaction: discord.Interaction) -> bool:
    return (not ALLOWED_CHANNELS) or (interaction.channel_id in ALLOWED_CHANNELS)

class Template(commands.Cog):
    """Example cog: put your slash commands here."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Simple slash command
    @app_commands.check(_allowed_channel)
    @app_commands.command(name="hello", description="Say hi.")
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"👋 Hi, {interaction.user.mention}!")

    # An example subcommand group
    group = app_commands.Group(name="demo", description="Demo command group")

    @group.command(name="echo", description="Echo your message back.")
    @app_commands.describe(text="What should I echo?")
    @app_commands.check(_allowed_channel)
    @app_commands.checks.cooldown(1, 5.0)  # 1 use per 5s (per user)
    async def demo_echo(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message(text[:1900])

    # Basic per-cog error handler for app_commands
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.errors.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ Cooldown: try again in {error.retry_after:.1f}s.", ephemeral=True
            )
        elif isinstance(error, app_commands.errors.CheckFailure):
            await interaction.response.send_message("🔒 Not allowed in this channel.", ephemeral=True)
        else:
            # Log silently; show generic error
            try:
                await interaction.response.send_message("⚠️ Something went wrong.", ephemeral=True)
            except discord.InteractionResponded:
                await interaction.followup.send("⚠️ Something went wrong.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Template(bot))
