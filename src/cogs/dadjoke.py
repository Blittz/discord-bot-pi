"""Free dad-joke command backed by icanhazdadjoke.com with local fallback."""
import asyncio
import random
import re
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

API_URL = "https://icanhazdadjoke.com/"
USER_AGENT = "Blittz Raspberry Pi Discord Bot (https://github.com/Blittz/discord-bot-pi)"
FALLBACK_JOKES = (
    "I only know 25 letters of the alphabet. I don't know y.",
    "I used to hate facial hair, but then it grew on me.",
    "Why did the scarecrow win an award? Because he was outstanding in his field.",
    "I am reading a book about anti-gravity. It is impossible to put down.",
    "What do you call cheese that is not yours? Nacho cheese.",
    "I told my computer I needed a break, and now it will not stop sending me vacation ads.",
)

def clean_joke(text: str) -> str:
    text = re.sub(r"<@!?\d+>", "@\u200b", str(text))
    text = text.replace("`", "'").strip()
    return text[:1900] or "I forgot the punchline, but it was hilarious in rehearsal."

async def fetch_dad_joke(session=None) -> str:
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8), headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        async with session.get(API_URL) as response:
            if response.status != 200: raise RuntimeError(f"HTTP {response.status}")
            payload = await response.json(content_type=None)
            joke = payload.get("joke") if isinstance(payload, dict) else None
            if not isinstance(joke, str) or not joke.strip(): raise ValueError("missing joke")
            return clean_joke(joke)
    finally:
        if own_session: await session.close()

class DadJoke(commands.Cog):
    def __init__(self, bot):
        self.bot, self.last_joke, self.lock = bot, None, asyncio.Lock()

    @app_commands.command(name="dadjoke", description="Get a free, family-friendly dad joke")
    @app_commands.checks.cooldown(3, 10.0)
    async def dadjoke(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        async with self.lock:
            try: joke = await fetch_dad_joke()
            except Exception: joke = random.choice([j for j in FALLBACK_JOKES if j != self.last_joke] or FALLBACK_JOKES)
            self.last_joke = joke
        await interaction.followup.send(joke)

async def setup(bot):
    await bot.add_cog(DadJoke(bot))
