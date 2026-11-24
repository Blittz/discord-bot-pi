import os
import asyncio
import logging
import re
import time

import discord
from discord.ext import commands
from discord import app_commands

log = logging.getLogger(__name__)

# Optional dependency
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "500"))
OPENAI_TEMP = float(os.getenv("OPENAI_TEMP", "0.7"))

# Per-user cooldown shared by /ai and @mention requests (cost guardrail).
AI_COOLDOWN_SECONDS = float(os.getenv("AI_COOLDOWN_SECONDS", "10"))

# Same optional channel allow-list that bot.py applies to slash commands.
ALLOWED_CHANNELS = {
    int(x) for x in os.getenv("ALLOWED_CHANNEL_IDS", "").split(",") if x.strip().isdigit()
}

SYSTEM_PROMPT = "You are a helpful, concise assistant for a Discord server."
MAX_PROMPT_CHARS = 2000
MAX_REPLY_CHARS = 1900  # Discord message headroom
GENERIC_ERROR = "⚠️ The AI request failed. Please try again in a bit."
NO_MENTIONS = discord.AllowedMentions.none()

# simple concurrency guard
_semaphore = asyncio.Semaphore(2)  # at most 2 concurrent requests


def channel_allowed(channel_id) -> bool:
    """True when no allow-list is configured or the channel is on it."""
    return (not ALLOWED_CHANNELS) or (channel_id in ALLOWED_CHANNELS)


class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = bool(OPENAI_API_KEY)
        self._client = None
        self._last_request = {}  # user id -> time.monotonic() of last accepted request

    def _take_cooldown(self, user_id: int) -> float:
        """Return seconds the user must still wait, or 0.0 and start a new cooldown."""
        now = time.monotonic()
        last = self._last_request.get(user_id)
        if last is not None and now - last < AI_COOLDOWN_SECONDS:
            return AI_COOLDOWN_SECONDS - (now - last)
        self._last_request[user_id] = now
        if len(self._last_request) > 1024:  # keep the dict bounded
            cutoff = now - AI_COOLDOWN_SECONDS
            self._last_request = {u: t for u, t in self._last_request.items() if t > cutoff}
        return 0.0

    def _get_client(self):
        if self._client is None:
            # lazy import to avoid hard dep if disabled
            from openai import OpenAI
            self._client = OpenAI(api_key=OPENAI_API_KEY)
        return self._client

    def _complete(self, prompt: str) -> str:
        resp = self._get_client().chat.completions.create(
            model=OPENAI_MODEL,
            temperature=OPENAI_TEMP,
            max_tokens=OPENAI_MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    async def _answer(self, prompt: str) -> str:
        """Ask the model without blocking the event loop; never leaks error details."""
        async with _semaphore:
            try:
                content = await asyncio.to_thread(self._complete, prompt)
            except Exception:
                log.exception("OpenAI request failed")
                return GENERIC_ERROR
        return content[:MAX_REPLY_CHARS] or "…"

    @app_commands.command(name="ai", description="Ask ChatGPT (guardrails on).")
    @app_commands.describe(prompt="Your question or prompt")
    async def ai(self, interaction: discord.Interaction, prompt: str):
        if not self.enabled:
            await interaction.response.send_message("🔒 ChatGPT not configured yet.", ephemeral=True)
            return
        if not channel_allowed(interaction.channel_id):
            await interaction.response.send_message("🔒 Not allowed in this channel.", ephemeral=True)
            return

        prompt = prompt.strip()
        if len(prompt) > MAX_PROMPT_CHARS:
            await interaction.response.send_message(
                f"❌ Prompt too long (max {MAX_PROMPT_CHARS} chars).", ephemeral=True
            )
            return

        wait = self._take_cooldown(interaction.user.id)
        if wait > 0:
            await interaction.response.send_message(
                f"⏳ Cooldown: try again in {wait:.0f}s.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        answer = await self._answer(prompt)
        await interaction.followup.send(answer, allowed_mentions=NO_MENTIONS)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.enabled:
            return
        if not (self.bot.user and self.bot.user.mentioned_in(message)) or message.mention_everyone:
            return
        if not channel_allowed(message.channel.id):
            return

        prompt = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        if not prompt:
            return
        if len(prompt) > MAX_PROMPT_CHARS:
            await message.reply(
                f"❌ Prompt too long (max {MAX_PROMPT_CHARS} chars).",
                allowed_mentions=NO_MENTIONS,
            )
            return

        wait = self._take_cooldown(message.author.id)
        if wait > 0:
            await message.reply(
                f"⏳ Cooldown: try again in {wait:.0f}s.",
                allowed_mentions=NO_MENTIONS,
                delete_after=10,
            )
            return

        async with message.channel.typing():
            answer = await self._answer(prompt)
        await message.reply(answer, allowed_mentions=NO_MENTIONS)


async def setup(bot):
    cog = Chat(bot)
    await bot.add_cog(cog)
