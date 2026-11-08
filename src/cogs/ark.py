"""ARK: Survival Ascended monitoring and survivor statistics commands."""

import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from src.ark_service import ArkRconService, shared_ark_service
from src.ark_stats import STATS_ENABLED, discord_timestamp, format_duration, shared_ark_stats_store
from src.cogs.ark_players import safe_player_name

OWNER_ID = int(os.getenv("OWNER_ID", "0"))


class Ark(commands.GroupCog, group_name="ark", group_description="Read-only ARK server monitoring"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = shared_ark_service(bot)
        self.stats_store = shared_ark_stats_store(bot)
        self._reset_confirmations: dict[int, float] = {}

    stats_group = app_commands.Group(name="stats", description="ARK survivor statistics")

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

    @stats_group.command(name="show", description="Show accumulated ARK playtime")
    @app_commands.describe(player="Optional exact survivor name")
    async def stats_show(self, interaction: discord.Interaction, player: str | None = None):
        if not STATS_ENABLED:
            return await interaction.response.send_message("ARK survivor statistics are disabled.", ephemeral=True)
        if player:
            match = self.stats_store.find_by_name(player)
            if not match:
                return await interaction.response.send_message("No tracked survivor matched that name.", ephemeral=True)
            rows = [match]
        else:
            rows = self.stats_store.stats()
        if not rows:
            return await interaction.response.send_message("No survivor statistics are available yet.", ephemeral=True)
        started = discord_timestamp(self.stats_store.tracking_started()) or "Never"
        embed = discord.Embed(title="ARK Survivor Statistics", colour=discord.Colour.blurple())
        embed.add_field(name="Tracking started", value=started, inline=False)
        for _key, name, seconds, last_played in rows:
            safe_name = safe_player_name(name)
            last = discord_timestamp(last_played) or "Never"
            embed.add_field(
                name=safe_name,
                value=f"**Playtime:** {format_duration(seconds)}\n**Last played:** {last}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @stats_group.command(name="leaderboard", description="Show the ARK playtime leaderboard")
    async def stats_leaderboard(self, interaction: discord.Interaction):
        if not STATS_ENABLED:
            return await interaction.response.send_message("ARK survivor statistics are disabled.", ephemeral=True)
        rows = self.stats_store.stats()
        if not rows:
            return await interaction.response.send_message("No survivor statistics are available yet.", ephemeral=True)
        lines = [f"{index}. {safe_player_name(name)} — {format_duration(seconds)}" for index, (_key, name, seconds, _last) in enumerate(rows, 1)]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @stats_group.command(name="reset", description="Reset ARK survivor statistics (owner only)")
    @app_commands.describe(confirm="Set true, then repeat within 60 seconds to confirm")
    async def stats_reset(self, interaction: discord.Interaction, confirm: bool = False):
        if interaction.user.id != OWNER_ID or not OWNER_ID:
            return await interaction.response.send_message("Only the bot owner can reset ARK statistics.", ephemeral=True)
        now = time.monotonic()
        if not confirm:
            self._reset_confirmations[interaction.user.id] = now + 60
            return await interaction.response.send_message("This will erase accumulated ARK statistics. Repeat `/ark stats reset confirm:true` within 60 seconds.", ephemeral=True)
        if self._reset_confirmations.get(interaction.user.id, 0) < now:
            return await interaction.response.send_message("Reset confirmation expired. Run the reset command once without confirmation first.", ephemeral=True)
        self.stats_store.reset()
        self._reset_confirmations.pop(interaction.user.id, None)
        await interaction.response.send_message("ARK survivor statistics reset.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ark(bot))
