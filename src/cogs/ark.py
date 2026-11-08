"""Read-only ARK: Survival Ascended monitoring commands."""

import discord
from discord import app_commands
from discord.ext import commands

from src.ark_service import ArkRconService, shared_ark_service


class Ark(commands.GroupCog, group_name="ark", group_description="Read-only ARK server monitoring"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = shared_ark_service(bot)

    @app_commands.command(name="players", description="List currently connected ARK players")
    async def players(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            players = await self.service.players()
        except PermissionError:
            return await interaction.followup.send("ARK RCON authentication failed or is not configured.", ephemeral=True)
        except (TimeoutError, ConnectionError, OSError):
            return await interaction.followup.send("ARK RCON is currently unavailable.", ephemeral=True)
        except Exception:
            return await interaction.followup.send("ARK player status could not be retrieved.", ephemeral=True)
        if not players:
            return await interaction.followup.send("No players are currently connected.", ephemeral=True)
        await interaction.followup.send("Connected players:\n" + "\n".join(f"• {name}" for name in players), ephemeral=True)

    @app_commands.command(name="status", description="Show read-only ARK RCON status")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        result = await self.service.status()
        if not result.reachable:
            return await interaction.followup.send(f"ARK RCON: unavailable ({result.error}).", ephemeral=True)
        if not result.authenticated:
            return await interaction.followup.send("ARK RCON: reachable, but authentication failed or is not configured.", ephemeral=True)
        await interaction.followup.send(
            f"ARK RCON: reachable and authenticated. Connected players: {len(result.players)}.\n"
            "This verifies the RCON endpoint only; it does not verify all game services.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Ark(bot))
