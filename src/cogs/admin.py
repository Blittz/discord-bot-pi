import os, discord
from discord.ext import commands
from discord import app_commands

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

class Admin(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="sync", description="Owner: resync slash commands (guild or global)")
    @app_commands.describe(scope="guild or global")
    async def sync(self, interaction: discord.Interaction, scope: str = "guild"):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("🔒 Owner only.", ephemeral=True)
        await interaction.response.defer(thinking=True, ephemeral=True)
        if scope.lower() == "global":
            synced = await self.bot.tree.sync()
            return await interaction.followup.send(f"Synced {len(synced)} global commands.")
        guild = interaction.guild or (discord.Object(id=GUILD_ID) if GUILD_ID else None)
        if not guild:
            return await interaction.followup.send("No guild context/ID set.")
        self.bot.tree.copy_global_to(guild=guild)
        synced = await self.bot.tree.sync(guild=guild if isinstance(guild, discord.Guild) else guild)
        await interaction.followup.send(f"Synced {len(synced)} guild commands.")

async def setup(bot): await bot.add_cog(Admin(bot))
