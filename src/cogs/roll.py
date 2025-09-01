import random
import re
import discord
from discord.ext import commands
from discord import app_commands

# same v1-style regex: XdY or XdY±Z
DICE_RE = re.compile(r"^\s*(\d{1,3})d(\d{1,3})(?:\s*([+-]\s*\d{1,4}))?\s*$")

class Roll(commands.Cog):
    """/roll dice like 1d20, 3d6+2, with optional advantage/disadvantage."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roll", description="Roll dice (e.g., 1d20, 3d6+2)")
    @app_commands.describe(
        dice="Format: XdY or XdY+Z (e.g., 1d20, 3d6+2)",
        mode="normal (default), advantage, or disadvantage"
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="normal", value="normal"),
            app_commands.Choice(name="advantage", value="advantage"),
            app_commands.Choice(name="disadvantage", value="disadvantage"),
        ]
    )
    @app_commands.checks.cooldown(3, 10.0)  # per-user: 3 uses per 10s
    async def roll(self, interaction: discord.Interaction, dice: str, mode: app_commands.Choice[str] = None):
        m = DICE_RE.match(dice)
        if not m:
            await interaction.response.send_message("❌ Use formats like `1d20` or `3d6+2`.", ephemeral=True)
            return

        count, sides = int(m.group(1)), int(m.group(2))
        mod_str = m.group(3)
        bonus = int(mod_str.replace(" ", "")) if mod_str else 0
        mode_val = (mode.value if mode else "normal").lower()

        if not (1 <= count <= 100 and 2 <= sides <= 1000 and -10000 <= bonus <= 10000):
            await interaction.response.send_message("❌ Dice expression is out of bounds.", ephemeral=True)
            return

        # Advantage/Disadvantage: only meaningful for single-die rolls (XdY where X=1)
        if mode_val != "normal" and count != 1:
            await interaction.response.send_message(
                "⚠️ Advantage/disadvantage only works with a single die (e.g., `1d20+5`).",
                ephemeral=True
            )
            return

        if mode_val == "normal":
            rolls = [random.randint(1, sides) for _ in range(count)]
            total = sum(rolls) + bonus
            detail = " + ".join(map(str, rolls))
            if bonus:
                detail += f" {'+' if bonus > 0 else ''}{bonus}"
            await interaction.response.send_message(f"🎲 {dice.strip()} → **{total}**  ({detail})")
            return

        # adv/dis with single die
        r1 = random.randint(1, sides)
        r2 = random.randint(1, sides)
        chosen = max(r1, r2) if mode_val == "advantage" else min(r1, r2)
        total = chosen + bonus

        chosen_label = "kept" if bonus == 0 else f"kept + {'+' if bonus > 0 else ''}{bonus}"
        await interaction.response.send_message(
            f"🎲 {dice.strip()} [{mode_val}] → rolls: {r1}, {r2} → **{total}** ({chosen} {chosen_label})"
        )

    # Convenience commands: /adv and /dis
    @app_commands.command(name="adv", description="Roll with advantage (e.g., 1d20+5)")
    @app_commands.describe(dice="Format: 1dY or 1dY+Z (e.g., 1d20+5)")
    @app_commands.checks.cooldown(3, 10.0)
    async def adv(self, interaction: discord.Interaction, dice: str):
        # delegate to /roll with mode=advantage
        choice = app_commands.Choice(name="advantage", value="advantage")
        await self.roll.callback(self, interaction, dice, choice)  # type: ignore

    @app_commands.command(name="dis", description="Roll with disadvantage (e.g., 1d20+5)")
    @app_commands.describe(dice="Format: 1dY or 1dY+Z (e.g., 1d20+5)")
    @app_commands.checks.cooldown(3, 10.0)
    async def dis(self, interaction: discord.Interaction, dice: str):
        # delegate to /roll with mode=disadvantage
        choice = app_commands.Choice(name="disadvantage", value="disadvantage")
        await self.roll.callback(self, interaction, dice, choice)  # type: ignore

async def setup(bot):
    await bot.add_cog(Roll(bot))
