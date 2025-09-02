import os
import time
import platform
import discord
from discord.ext import commands
from discord import app_commands

START_TIME = time.time()
VERSION = "2.1.0"

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

class About(commands.Cog):
    """Bot info and uptime."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="about", description="Show info about the bot")
    async def about(self, interaction: discord.Interaction):
        uptime = time.time() - START_TIME
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)

        owner = f"<@{OWNER_ID}>" if OWNER_ID else "Unknown"

        embed = discord.Embed(
            title="🤖 Campaign Bot",
            description="Discord bot running on Raspberry Pi 5",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Version", value=VERSION, inline=True)
        embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s", inline=True)
        embed.add_field(name="Owner", value=owner, inline=True)
        embed.set_footer(text=f"Python {platform.python_version()} • discord.py {discord.__version__}")

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(About(bot))
