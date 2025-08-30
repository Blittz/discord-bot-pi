import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load token from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Set up bot with command prefix "!"
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Lookup of commands and their associated responses
COMMAND_RESPONSES = {
    "ping": "Pong!",
    "hello": "Hello there!",
}

# Dynamically create commands based on the lookup
for name, response in COMMAND_RESPONSES.items():
    async def command_fn(ctx, response=response):
        await ctx.send(response)
    bot.command(name=name)(command_fn)

@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")

# Run the bot
bot.run(TOKEN)
