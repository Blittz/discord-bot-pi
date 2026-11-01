"""Free dad-joke command backed by icanhazdadjoke.com with local fallback."""
import asyncio, random, re
from urllib.parse import quote_plus
import aiohttp
import discord
from src.dnd_jokes import DND_JOKES
from discord.ext import commands
from discord import app_commands
API_URL = "https://icanhazdadjoke.com/"
SEARCH_URL = "https://icanhazdadjoke.com/search?term={}"
USER_AGENT = "Blittz Raspberry Pi Discord Bot (https://github.com/Blittz/discord-bot-pi)"
FALLBACK_JOKES = ("I only know 25 letters of the alphabet. I don't know y.", "I used to hate facial hair, but then it grew on me.", "Why did the scarecrow win an award? Because he was outstanding in his field.", "I am reading a book about anti-gravity. It is impossible to put down.", "What do you call cheese that is not yours? Nacho cheese.", "I told my computer I needed a break, and now it will not stop sending me vacation ads.")
THEMED_FALLBACKS = {
 "halloween": ("Why did the vampire read the newspaper? He heard it had great circulation.", "I dressed up as a skeleton for Halloween, but I had no body to go with."),
 "christmas": ("What do snowmen eat for breakfast? Frosted Flakes.", "Why was the Christmas tree bad at knitting? It kept dropping its needles."),
}
ALIASES = {"haloween": "halloween", "hallowen": "halloween", "xmas": "christmas", "dnd": "dnd", "d&d": "dnd", "dungeons and dragons": "dnd", "dungeons & dragons": "dnd"}
def clean_joke(text):
    return re.sub(r"<@!?\d+>", "@\u200b", str(text)).replace("`", "'").strip()[:1900] or "I forgot the punchline, but it was hilarious in rehearsal."
def normalize_topic(topic):
    value = " ".join(str(topic).strip().lower().split())
    return ALIASES.get(value, value)
async def _session():
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8), headers={"Accept":"application/json", "User-Agent":USER_AGENT})
async def fetch_dad_joke(session=None):
    own = session is None
    if own: session = await _session()
    try:
        async with session.get(API_URL) as response:
            if response.status != 200: raise RuntimeError(f"HTTP {response.status}")
            joke = (await response.json(content_type=None)).get("joke")
            if not isinstance(joke, str) or not joke.strip(): raise ValueError("missing joke")
            return clean_joke(joke)
    finally:
        if own: await session.close()
async def search_dad_joke(topic, session=None):
    own = session is None
    if own: session = await _session()
    try:
        first = None
        for page in range(1, 4):
            async with session.get(SEARCH_URL.format(quote_plus(topic)) + f"&page={page}") as response:
                if response.status != 200: raise RuntimeError(f"HTTP {response.status}")
                payload = await response.json(content_type=None)
                if not isinstance(payload, dict): raise ValueError("invalid response")
                first = payload if first is None else first
                results = [r.get("joke") for r in payload.get("results", []) if isinstance(r, dict) and isinstance(r.get("joke"), str)]
                if results and (page >= min(int(payload.get("total_pages", page)), 3)): return clean_joke(random.choice(results))
                if page >= min(int(payload.get("total_pages", page)), 3): break
        if first is not None and first.get("results"):
            results = [r.get("joke") for r in first["results"] if isinstance(r, dict) and isinstance(r.get("joke"), str)]
            if results: return clean_joke(random.choice(results))
        return None
    finally:
        if own: await session.close()
class DadJoke(commands.Cog):
    def __init__(self, bot): self.bot, self.last_joke, self.lock = bot, None, asyncio.Lock()
    @app_commands.command(name="dadjoke", description="Get a free, family-friendly dad joke")
    @app_commands.describe(topic="Optional topic, such as cats, Halloween, or Christmas")
    @app_commands.checks.cooldown(3, 10.0)
    async def dadjoke(self, interaction, topic: str | None = None):
        await interaction.response.defer(thinking=True)
        async with self.lock:
            normalized = normalize_topic(topic) if topic else None
            if normalized == "dnd":
                choices = [j for j in DND_JOKES if j != self.last_joke] or DND_JOKES
                joke = random.choice(choices)
            else:
                joke = None
            if joke is None:
                try:
                    joke = await (search_dad_joke(normalized) if normalized else fetch_dad_joke())
                except Exception:
                    joke = None
            if not joke and normalized in THEMED_FALLBACKS:
                choices = [j for j in THEMED_FALLBACKS[normalized] if j != self.last_joke] or THEMED_FALLBACKS[normalized]; joke = random.choice(choices)
            if not joke and normalized: joke = f"I couldn't find a dad joke about {clean_joke(normalized)}. Try another topic."
            if not joke: joke = random.choice([j for j in FALLBACK_JOKES if j != self.last_joke] or FALLBACK_JOKES)
            self.last_joke = joke
        await interaction.followup.send(joke)
async def setup(bot): await bot.add_cog(DadJoke(bot))
