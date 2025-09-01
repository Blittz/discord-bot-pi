# Discord Bot on Raspberry Pi 5

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
