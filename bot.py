import json
import os
import discord
from discord.ext import commands
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
load_dotenv()

# --- Settings ---
COMMANDS_FILE = os.getenv("COMMANDS_FILE", "commands.json")
PREFIX = os.getenv("BOT_PREFIX", "!")
OWNER_ID = os.getenv("OWNER_ID")  # optional, for reload protection (set to your Discord user ID)

intents = discord.Intents.default()
intents.message_content = True  # required for prefix commands
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# In-memory command map
command_map: Dict[str, str] = {}

def load_commands() -> None:
    global command_map
    path = Path(COMMANDS_FILE)
    if not path.exists():
        print(f"[WARN] {COMMANDS_FILE} not found. Creating a starter file.")
        path.write_text(json.dumps({"hello": "Hi!", "help": "This is the help text."}, indent=2))
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Normalize keys to lowercase for case-insensitive matching
    command_map = {str(k).strip().lower(): str(v) for k, v in data.items()}
    print(f"[OK] Loaded {len(command_map)} commands from {COMMANDS_FILE}")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    print(f"Prefix: {PREFIX}")
    load_commands()

def is_owner(ctx: commands.Context) -> bool:
    if OWNER_ID is None:
        return True  # if not set, allow anyone to use reload (you can tighten this)
    try:
        return int(OWNER_ID) == ctx.author.id
    except ValueError:
        return False

@bot.command(name="reload")
async def reload_cmd(ctx: commands.Context):
    """Reload commands.json without restarting the bot."""
    if not is_owner(ctx):
        return await ctx.reply("Sorry, only the owner can reload commands.")
    try:
        load_commands()
        await ctx.reply(f"✅ Reloaded `{COMMANDS_FILE}`.")
    except Exception as e:
        await ctx.reply(f"❌ Failed to reload: `{e}`")

@bot.event
async def on_message(message: discord.Message):
    # Ignore bot messages
    if message.author.bot:
        return

    content = message.content.strip()
    if not content.startswith(PREFIX):
        # Not a prefix command; nothing to do
        return

    # Remove prefix, normalize
    raw = content[len(PREFIX):].strip()
    lower_raw = raw.lower()
    first_word = lower_raw.split(" ", 1)[0]

    # If it's a *registered* command (like !reload), let discord.py handle it
    if first_word in bot.all_commands:
        await bot.process_commands(message)
        return

    # Otherwise serve from your external command map
    if lower_raw in command_map:
        await message.channel.send(command_map[lower_raw])
        return

    # Try matching just the first word (e.g., "!roll d20" -> "roll")
    if first_word in command_map:
        await message.channel.send(command_map[first_word])
        return

    # Optional: gentle fallback instead of silence
    # await message.channel.send("Unknown command. Try !help")

@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CommandNotFound):
        # We deliberately ignore unknown commands because most are handled by the JSON map.
        return
    # Re-raise other errors so you still see real problems
    raise error

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_TOKEN in your environment.")
    bot.run(token)