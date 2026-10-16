# Discord Bot on Raspberry Pi 5

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python\&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.6.2-blueviolet?logo=discord\&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Runs%20on-Raspberry%20Pi%205-red?logo=raspberrypi\&logoColor=white)

A Discord bot built with **discord.py** and running on a **Raspberry Pi 5**.
Version **2.1.0** introduces a clean **cog-based architecture** with **slash commands** and optional **ChatGPT integration**.

---

## ✨ Features

* **Slash commands (v2)**

* `/help` – Lists all available commands (private/ephemeral)
* `/about` – Shows version, latency, uptime, and owner
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
# Network photo storage: configure all three values as described below
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
User=photobot
Group=photobot
WorkingDirectory=/home/photobot/discord-bot-pi
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=/home/photobot/discord-bot-pi/src
EnvironmentFile=/home/photobot/discord-bot-pi/.env
ExecStart=/home/photobot/discord-bot-pi/.venv/bin/python -m src.bot
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
│       ├── core.py    # /help
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


## PhotoSaver network storage

PhotoSaver requires the configured `PHOTO_SAVE_DIR` to be inside the mounted
CIFS filesystem named by `PHOTO_REQUIRED_MOUNT`. It validates mount identity
before opening the destination and again before publishing. All creates and
renames are relative to held directory descriptors, so an unmounted share cannot
fall through to its underlying local directory. Unavailable storage is logged;
there is no automatic local fallback or history backfill.

`PHOTO_CHANNEL_MAP` points to a private JSON map keyed by Discord channel ID.
It preserves existing sanitized folder names, including decorative Unicode
letters, across channel renames. New colliding or unassigned existing folder
names fail closed for manual review; existing folders are never renamed.

Attachments are deduplicated by attachment ID across the entire destination.
Downloads use hidden `.partial` files, expected-size checks, SHA-256 readback,
and atomic `renameat2(RENAME_NOREPLACE)` publication. Existing destinations are
never replaced. A signed CDN URL or message contents are not logged on failure.
Private configuration and migration reports belong outside the repository.


### Private storage configuration

Set these in the ignored `.env`, substituting your own paths (examples only):

```ini
PHOTO_SAVE_DIR=/mnt/example-share/Photos/Discord
PHOTO_REQUIRED_MOUNT=/mnt/example-share
PHOTO_CHANNEL_MAP=/var/lib/example-bot/photo-channel-map.json
```

Provision the destination only while the CIFS share is mounted. The service user
must have write access to it and to the local channel-map parent directory.
Linux `/proc/self/mountinfo`, directory-descriptor operations, and filesystem
support for `renameat2(RENAME_NOREPLACE)` are required; unsupported operations
fail closed. Configure the actual mount root, not a directory inside the share.
The systemd user and home paths above are examples too.

Keep the map outside Git and include it in a private backup. For existing folders,
seed it with the real channel IDs and their **exact existing** folder names before
running the bot. Example schema, using a fictitious channel ID:

```json
{"123456789012345678": {"folder": "example-channel"}}
```

Never replace an existing map with this example. IDs remain the identity when a
channel is renamed; Unicode letters are preserved. Review collisions manually
instead of renaming existing directories or creating a second tree. Store tokens,
channel IDs, real folder names, migration reports, media and backups privately.
No history replay is performed after an outage; any missed attachments require a
separately reviewed backfill. Duplicate IDs are skipped when their existing size
matches, and conflicting sizes are rejected without overwriting either file.

Run the isolated storage regression suite without Discord or a mounted share:

```bash
python -B -m unittest discover -s tests -v
```
