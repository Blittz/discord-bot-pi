import discord
from discord.ext import commands

class Core(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="help", description="Show available commands")
    async def help_slash(self, interaction: discord.Interaction):
        text = (
            "**Commands**\n"
            "/help — show this help\n"
            "/ping — health check\n"
            "/chat — (optional) ask ChatGPT (enable later)\n"
        )
        await interaction.response.send_message(text, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Core(bot))
