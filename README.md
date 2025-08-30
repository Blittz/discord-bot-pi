# discord-bot-pi
Discord bot running on Raspberry Pi 5.

## Commands
The bot uses a lookup dictionary to define simple text commands and their
responses. By default it supports:
- `!ping` → `Pong!`
- `!hello` → `Hello there!`

To add more commands, update the `COMMAND_RESPONSES` dictionary in `bot.py`.
