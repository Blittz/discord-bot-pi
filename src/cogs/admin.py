import os, discord
from discord.ext import commands
from discord import app_commands

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
class Admin(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="sync", description="Owner: synchronize slash commands globally")
    async def sync(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("🔒 Owner only.", ephemeral=True)
        await interaction.response.defer(thinking=True, ephemeral=True)
        synced = await self.bot.tree.sync()
        await interaction.followup.send(f"Synced {len(synced)} global commands.")

async def setup(bot): await bot.add_cog(Admin(bot))
