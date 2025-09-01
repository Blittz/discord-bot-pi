import os
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

# Optional dependency
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "500"))
OPENAI_TEMP = float(os.getenv("OPENAI_TEMP", "0.7"))

# simple concurrency guard
_semaphore = asyncio.Semaphore(2)  # at most 2 concurrent chats

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = bool(OPENAI_API_KEY)

    def cog_check(self, ctx: commands.Context):
        return self.enabled

    @app_commands.command(name="chat", description="Ask ChatGPT (guardrails on).")
    @app_commands.describe(prompt="Your question or prompt")
    async def chat(self, interaction: discord.Interaction, prompt: str):
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
                # Create a concise, safe answer
                resp = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    temperature=OPENAI_TEMP,
                    max_tokens=OPENAI_MAX_TOKENS,
                    messages=[
                        {"role": "system", "content": "You are a helpful, concise assistant for a Discord server."},
                        {"role": "user", "content": prompt.strip()},
                    ],
                )
                content = resp.choices[0].message.content.strip()
                content = content[:1900]  # Discord message headroom
                await interaction.followup.send(content or "…")
            except Exception as e:
                await interaction.followup.send(f"⚠️ Chat error: {e}")

async def setup(bot):
    cog = Chat(bot)
    await bot.add_cog(cog)
