import os
import asyncio
import re
import discord
from discord.ext import commands
from discord import app_commands

# Optional dependency
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "500"))
OPENAI_TEMP = float(os.getenv("OPENAI_TEMP", "0.7"))

# simple concurrency guard
_semaphore = asyncio.Semaphore(2)  # at most 2 concurrent requests

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = bool(OPENAI_API_KEY)

    def cog_check(self, ctx: commands.Context):
        return self.enabled

    @app_commands.command(name="ai", description="Ask ChatGPT (guardrails on).")
    @app_commands.describe(prompt="Your question or prompt")
    async def ai(self, interaction: discord.Interaction, prompt: str):
        if not self.enabled:
            await interaction.response.send_message("🔒 ChatGPT not configured yet.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        # lazy import to avoid hard dep if disabled
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        # cost & rate guardrails
        if len(prompt) > 2000:
            await interaction.followup.send("❌ Prompt too long (max 2000 chars).")
            return

        async with _semaphore:
            try:
                # Create a concise, safe answer without blocking the event loop
                resp = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=OPENAI_MODEL,
                    temperature=OPENAI_TEMP,
                    max_tokens=OPENAI_MAX_TOKENS,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful, concise assistant for a Discord server.",
                        },
                        {"role": "user", "content": prompt.strip()},
                    ],
                )
                content = resp.choices[0].message.content.strip()
                content = content[:1900]  # Discord message headroom
                await interaction.followup.send(content or "…")
            except Exception as e:
                await interaction.followup.send(f"⚠️ AI error: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if self.bot.user and self.bot.user.mentioned_in(message) and not message.mention_everyone:
            if not self.enabled:
                return

            prompt = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
            if not prompt:
                return
            if len(prompt) > 2000:
                await message.reply("❌ Prompt too long (max 2000 chars).")
                return

            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)

            async with message.channel.typing():
                async with _semaphore:
                    try:
                        resp = await asyncio.to_thread(
                            client.chat.completions.create,
                            model=OPENAI_MODEL,
                            temperature=OPENAI_TEMP,
                            max_tokens=OPENAI_MAX_TOKENS,
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are a helpful, concise assistant for a Discord server.",
                                },
                                {"role": "user", "content": prompt},
                            ],
                        )
                        content = resp.choices[0].message.content.strip()
                        content = content[:1900]
                        await message.reply(content or "…")
                    except Exception as e:
                        await message.reply(f"⚠️ AI error: {e}")

async def setup(bot):
    cog = Chat(bot)
    await bot.add_cog(cog)
