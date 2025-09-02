# Discord Bot on Raspberry Pi 5

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python\&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.6.2-blueviolet?logo=discord\&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Runs%20on-Raspberry%20Pi%205-red?logo=raspberrypi\&logoColor=white)

A Discord bot built with **discord.py** and running on a **Raspberry Pi 5**.
Version **2.1.0** introduces a clean **cog-based architecture** with **slash commands** and optional **ChatGPT integration**.

---

## ✨ Features

* **Slash commands (v2)**

  * `/ping` – Health check
  * `/help` – Lists all available commands (private/ephemeral)
  * `/about` – Shows version, uptime, and owner
  * `/roll` – Dice roller (XdY±Z)
  * `/adv` – Roll with advantage (1dY±Z)
  * `/dis` – Roll with disadvantage (1dY±Z)
  * `/ai` – Ask ChatGPT (optional, requires API key)
  * `/dadjoke` – Random dad joke about gaming or dogs (ChatGPT)
  * `/sync` – Resync commands (owner only)

* **Runs 24/7** via `systemd` on Raspberry Pi

* **Automatic nightly updates** (via cron + update script)

* **Configurable via `.env`** for tokens, keys, and IDs

* **Extensible with cogs**: just drop a new file in `src/cogs/`

---

## 🛠️ Setup

### 0. Prerequisites (Raspberry Pi OS Bookworm)

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3 python3-venv python3-pip
# Optional (voice features later)
sudo apt install -y ffmpeg libsodium23
```

> **Note:** Use plain values in `.env` (no quotes, no inline comments). `OWNER_ID` and `GUILD_ID` must be numbers only.

### 1. Clone the repo

```bash
git clone https://github.com/Blittz/discord-bot-pi.git
cd discord-bot-pi
```

### 2. Create a virtual environment & install deps

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure `.env`

Create a `.env` file with:

```ini
DISCORD_TOKEN=your_bot_token_here
OWNER_ID=your_user_id
GUILD_ID=your_guild_id
# Optional OpenAI integration
# OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini
OPENAI_MAX_TOKENS=500
OPENAI_TEMP=0.7
```

### 4. Run locally

```bash
python -m src.bot
```

### 5. (Optional) Set a presence/tagline

Edit `src/bot.py` and add inside `on_ready`:

```python
await self.change_presence(activity=discord.Game(name="Rolling dice & keeping watch"))
```

---

## 🔧 Deployment on Raspberry Pi

### Systemd Service

Configured in `/etc/systemd/system/discord-bot.service`:

```
[Unit]
Description=Discord Bot (discord-bot-pi)
After=network-online.target

[Service]
Type=simple
User=blittz
Group=blittz
WorkingDirectory=/home/blittz/discord-bot-pi
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=/home/blittz/discord-bot-pi/src
EnvironmentFile=/home/blittz/discord-bot-pi/.env
ExecStart=/home/blittz/discord-bot-pi/.venv/bin/python -m src.bot
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable & start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable discord-bot.service
sudo systemctl start discord-bot.service
```

### Auto Update Script

A helper script `update-discord-bot` is installed at `/usr/local/bin`:

```bash
update-discord-bot
```

This pulls the latest code, installs dependencies, and restarts the bot.

Nightly cron job runs it at **2 AM** automatically.

---

## 📂 Project Structure

```
discord-bot-pi/
├── src/
│   ├── bot.py         # Main entrypoint
│   └── cogs/          # Modular command cogs
│       ├── core.py    # /help, /ping
│       ├── about.py   # /about
│       ├── roll.py    # /roll, /adv, /dis
│       ├── chat.py    # /ai (ChatGPT integration)
│       └── admin.py   # /sync, owner tools
├── requirements.txt
├── .env (not committed)
└── README.md
```

---

## 🚀 Roadmap

* [ ] Add fun utility commands (`/weather`, `/quote`, etc.)
* [ ] Expand dice roller with advantage/disadvantage for pools
* [ ] Improve `/ai` with moderation guardrails
* [ ] GitHub Actions workflow for lint/test before push

---

## 📝 License

MIT License © 2025 Blittz
