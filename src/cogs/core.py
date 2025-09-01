import os
import discord
from discord.ext import commands
from discord import app_commands

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

class Core(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show available commands")
    async def help_slash(self, interaction: discord.Interaction):
        lines = []
        for cmd in self.bot.tree.get_commands(guild=interaction.guild):
            # Skip hidden or disabled
            if cmd.name.startswith("_"):
                continue
            # Check if owner-only
            owner_only = False
            checks = getattr(cmd, "checks", [])
            for chk in checks:
                if getattr(chk, "__qualname__", "").startswith("is_owner") or "OWNER" in chk.__qualname__:
                    owner_only = True
            if cmd.name == "sync":  # hardcode since we know it's owner only
                owner_only = True

            desc = cmd.description or ""
            flag = " 🔒 (Owner only)" if owner_only else ""
            lines.append(f"/{cmd.name} — {desc}{flag}")

        text = "**Available Commands**\n" + "\n".join(sorted(lines))
        await interaction.response.send_message(text, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Core(bot))
