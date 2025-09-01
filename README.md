# Discord Bot on Raspberry Pi 5

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.6.2-blueviolet?logo=discord&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Runs%20on-Raspberry%20Pi%205-red?logo=raspberrypi&logoColor=white)

A Discord bot built with **discord.py** and running on a **Raspberry Pi 5**.  
Version **2.0** introduces a clean **cog-based architecture** with **slash commands** and optional **ChatGPT integration**.

---

## ✨ Features

- **Slash commands (v2)**  
  - `/ping` – Health check  
  - `/help` – Lists all available commands (private/ephemeral)  
  - `/about` – Shows version, uptime, and owner  
  - `/roll` – Dice roller (XdY±Z)  
  - `/adv` – Roll with advantage (1dY±Z)  
  - `/dis` – Roll with disadvantage (1dY±Z)  
  - `/chat` – Ask ChatGPT (optional, requires API key)  
  - `/sync` – Resync commands (owner only)

- **Runs 24/7** via `systemd` on Raspberry Pi  
- **Automatic nightly updates** (via cron + update script)  
- **Configurable via `.env`** for tokens, keys, and IDs  
- **Extensible with cogs**: just drop a new file in `src/cogs/`  

---

## 🛠️ Setup

### 1. Clone the repo
```bash
git clone https://github.com/Blittz/discord-bot-pi.git
cd discord-bot-pi
2. Create virtual environment
bash
Copy code
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
3. Configure .env
Create a .env file with:

ini
Copy code
DISCORD_TOKEN=your_bot_token_here
OWNER_ID=your_user_id
GUILD_ID=your_guild_id
# Optional OpenAI integration
# OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini
OPENAI_MAX_TOKENS=500
OPENAI_TEMP=0.7
4. Run locally
bash
Copy code
python -m src.bot
🔧 Deployment on Raspberry Pi
Systemd Service
Configured in /etc/systemd/system/discord-bot.service:

ini
Copy code
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
Enable & start:

bash
Copy code
sudo systemctl daemon-reload
sudo systemctl enable discord-bot.service
sudo systemctl start discord-bot.service
Auto Update Script
A helper script update-discord-bot is installed at /usr/local/bin:

bash
Copy code
update-discord-bot
This pulls the latest code, installs dependencies, and restarts the bot.

Nightly cron job runs it at 2 AM automatically.

📂 Project Structure
bash
Copy code
discord-bot-pi/
├── src/
│   ├── bot.py         # Main entrypoint
│   └── cogs/          # Modular command cogs
│       ├── core.py    # /help, /ping
│       ├── about.py   # /about
│       ├── roll.py    # /roll, /adv, /dis
│       ├── chat.py    # /chat (ChatGPT integration)
│       └── admin.py   # /sync, owner tools
├── requirements.txt
├── .env (not committed)
└── README.md
🚀 Roadmap
 Add fun utility commands (/weather, /quote, etc.)

 Expand dice roller with advantage/disadvantage for pools

 Improve /chat with moderation guardrails

 GitHub Actions workflow for lint/test before push

📝 License
MIT License © 2025 Blittz
