import os
import random
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "150"))
OPENAI_TEMP = float(os.getenv("OPENAI_TEMP", "0.7"))

_semaphore = asyncio.Semaphore(2)

TOPICS = [
    "Dungeons & Dragons",
    "Online Gaming",
    "Dice",
    "World of Warcraft",
    "Video Games",
    "TV series Firefly",
    "Minecraft",
    "Dogs",
]


class DadJoke(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = bool(OPENAI_API_KEY)

    def cog_check(self, ctx: commands.Context):
        return self.enabled

    @app_commands.command(name="dadjoke", description="Get a random dad joke about games or dogs")
    @app_commands.checks.cooldown(3, 10.0)
    async def dadjoke(self, interaction: discord.Interaction):
        if not self.enabled:
            await interaction.response.send_message("🔒 ChatGPT not configured yet.", ephemeral=True)
            return

        topic = random.choice(TOPICS)
        prompt = f"Tell me a short, clean dad joke about {topic}."

        await interaction.response.defer(thinking=True)

        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        async with _semaphore:
            try:
                resp = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=OPENAI_MODEL,
                    temperature=OPENAI_TEMP,
                    max_tokens=OPENAI_MAX_TOKENS,
                    messages=[
                        {"role": "system", "content": "You tell short, groan-worthy dad jokes."},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = resp.choices[0].message.content.strip()
                await interaction.followup.send(content[:1900] or "…")
            except Exception as e:
                await interaction.followup.send(f"⚠️ AI error: {e}")


async def setup(bot):
    await bot.add_cog(DadJoke(bot))
