<div align="center">

# 🤖 BlittzBot

### A home-grown Discord bot for tabletop nights, a shared ARK server, and a very busy Raspberry Pi

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.7.1-blueviolet?logo=discord&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Runs%20on-Raspberry%20Pi%205-red?logo=raspberrypi&logoColor=white)
![Version](https://img.shields.io/badge/version-2.1.0-success)
[![Tests](https://github.com/Blittz/discord-bot-pi/actions/workflows/tests.yml/badge.svg)](https://github.com/Blittz/discord-bot-pi/actions/workflows/tests.yml)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

</div>

BlittzBot is a cog-based **discord.py** bot that runs 24/7 under `systemd` on a Raspberry Pi 5.
It plays narrated D&D session recaps in voice channels, bridges Discord and an ARK: Survival Ascended
server in both directions, announces who joins, leaves and dies, rolls dice, tells dad jokes, backs up
shared photos to network storage, and feeds server events to a companion photo-viewer app.

Everything risky is **opt-in, fail-closed and sanitized**: features that cost money or touch the game
server are off until you switch them on in `.env`.

---

## 📑 Contents

- [Highlights](#-highlights)
- [Command reference](#-command-reference)
- [ARK ⇄ Discord chat relay](#-ark--discord-chat-relay)
- [ARK player, outage and death announcements](#-ark-player-outage-and-death-announcements)
- [ARK survivor statistics](#-ark-survivor-statistics)
- [Audio player and libraries](#-audio-player-and-libraries)
- [Dice and dad jokes](#-dice-and-dad-jokes)
- [PhotoSaver](#-photosaver)
- [Scheduled-event feed](#-scheduled-event-feed)
- [Optional ChatGPT integration](#-optional-chatgpt-integration)
- [Configuration](#-configuration)
- [Setup and deployment](#-setup-and-deployment)
- [Project structure](#-project-structure)
- [Development and testing](#-development-and-testing)
- [Roadmap](#-roadmap)

---

## ✨ Highlights

| | Feature | What it does |
|---|---|---|
| 💬 | **ARK chat relay** | Two-way chat between one Discord channel and the in-game ARK chat. In-game text is posted as `**ARK** …`; Discord text reaches the game as `Name (Discord): message`. |
| 🦖 | **ARK monitoring** | Live player list, RCON status, join/leave posts, outage/recovery alerts, death announcements and playtime leaderboards. |
| 🎧 | **Audio player** | Plays long D&D recap recordings in voice channels with Pause/Resume/Stop/Volume buttons and scoped personal, channel and server libraries. |
| 🎲 | **Dice roller** | `XdY±Z` with advantage and disadvantage. |
| 😂 | **Dad jokes** | Free, family-friendly jokes with a D&D collection, 😂/🙄 voting and a monthly leaderboard. |
| 📷 | **PhotoSaver** | Saves image and video attachments to a mounted network share, safely and without duplicates. |
| 📅 | **Event feed** | Exports Discord scheduled events to a private JSON file for the Pi photo viewer. |
| 🧠 | **ChatGPT (off by default)** | `/ai` and @mention replies, behind a cost-control switch. |

---

## 🎮 Command reference

Commands are Discord **slash commands**. They are published by an owner-run `/sync`, not automatically.
Use `/help` in Discord for the live list (it reads the registered commands, so it is always current).

### General

| Command | Description | Access |
|---|---|---|
| `/help` | Lists every available command (private reply). | Everyone |
| `/about` | Version, latency, uptime and owner. | Everyone |
| `/sync` | Publishes the current command set globally. Run it after any change to command definitions. | Owner (hidden from non-admins) |

### Dice and fun

| Command | Description | Access |
|---|---|---|
| `/roll dice:<XdY±Z> [mode]` | Rolls dice such as `1d20` or `3d6+2`. `mode` is `normal`, `advantage` or `disadvantage`. Limits: 1-100 dice, 2-1000 sides, modifier ±10000, 3 uses per 10 s per user. | Everyone |
| `/adv dice:<1dY±Z>` | Shortcut for a roll with advantage. Single die only. | Everyone |
| `/dis dice:<1dY±Z>` | Shortcut for a roll with disadvantage. Single die only. | Everyone |
| `/dadjoke [topic]` | A free dad joke; add a topic like `halloween`, `cats` or `dnd`. Has 😂 Funny and 🙄 Groan voting buttons. | Everyone |
| `/dadjoke-leaderboard [visibility]` | Top five groan-worthy jokes plus monthly usage. `visibility` is `private` (default) or `public`. | Everyone |

### Audio

| Command | Description | Access |
|---|---|---|
| `/play [audio]` | Opens your private audio library browser, or plays an uploaded `audio` attachment. You must be in a voice channel. | Everyone (library actions are permission-checked each time) |
| `/stop` | Stops playback in this server. | Everyone |
| `/volume <1-100>` | Sets playback volume in whole percent. | Everyone |
| `/importaudio` | Imports a file placed in the SFTP import folder into My, Channel or Server audio. | Administrators |

### ARK server

| Command | Description | Access |
|---|---|---|
| `/ark players` | Lists connected survivors (private reply). | Everyone |
| `/ark status` | Checks that the RCON endpoint is reachable and authenticated. | Everyone |
| `/ark stats show [player]` | Playtime, last seen and death summary, for everyone or one survivor. | Everyone |
| `/ark stats leaderboard` | Playtime ranking. | Everyone |
| `/ark stats reset [confirm]` | Erases all survivor statistics. Needs a repeat with `confirm:true` within 60 seconds. | Owner |

### Optional (off by default)

| Command | Description |
|---|---|
| `/ai` | Ask ChatGPT. Only registered when `AI_ENABLED=true`. See [Optional ChatGPT integration](#-optional-chatgpt-integration). |

### Background features (no commands)

The ARK chat relay, ARK announcements, PhotoSaver and the scheduled-event feed all run automatically
from `.env` settings and have no slash commands.

---

## 💬 ARK ⇄ Discord chat relay

One Discord text channel (`ARK_CHANNEL_ID`) is linked to the in-game chat. Each direction is switched on
separately.

```text
In ARK        Survivor: anyone up for a boss fight?
In Discord    ARK Survivor: anyone up for a boss fight?

In Discord    Blittz: Hey all
In ARK        Blittz (Discord): Hey all
```

**ARK → Discord** (`ARK_RELAY_TO_DISCORD=true`)
- Polls the game chat buffer every 5 seconds and posts only *new* lines, prefixed with **ARK**.
- Takes a baseline at startup, so old chat is never replayed after a restart.
- Filters admin-command log lines and the bot's own `SERVER:` echoes, so nothing loops back.
- Deduplicates, backs off on RCON errors (up to 60 s) and retries channel failures a bounded number of times.

**Discord → ARK** (`ARK_RELAY_TO_ARK=true`)
- Messages from people in the channel are sent as `Name (Discord): text` using the sender's server display name.
- The label is always kept; if a message is too long, only the message body is trimmed (180 characters total).
- Messages beginning with `/` and empty messages are refused, and bot or webhook messages are ignored.
- Uses only the fixed `ServerChat` operation. It never accepts arbitrary RCON commands.
- Per-user rate limit (5 messages per 10 s) and pending-message cap, plus a bounded FIFO queue sent at one message per second.
- Failed deliveries are *not* retried, to avoid duplicate or flooded game chat. The sender gets a rate-limited notice.

**Safety for both directions**: mentions are neutralised (`@everyone`, `<@id>`), markdown and control characters are stripped, and
outgoing Discord text containing internal markers (`AdminCmd:`, `ArkID:`, `PlatformID:`) is dropped.

> **Heads-up:** reading the ARK chat buffer can affect other RCON consumers. Run only one chat-buffer reader at a time.
> **Rollback:** set both relay flags to `false` and restart the service. No `/sync` is needed.

---

## 🦖 ARK player, outage and death announcements

Enabled with `ARK_PLAYER_NOTIFICATIONS=true`; posts go only to `ARK_CHANNEL_ID`.

- 🟢 **Joined** and 🔴 **left** messages with a running "N players online" count.
- **Outage detection:** three consecutive failed `ListPlayers` polls post one 🔴 *offline* notice, and the first success afterwards
  posts one 🟢 *back online* notice. The outage marker is saved to disk, so a bot restart never repeats the notice.
- **Quiet start:** the first snapshot is a baseline, and recovery re-baselines, so restarts and outages never cause fake joins or leaves.
- **Deaths** (`ARK_DEATH_TRACKING_ENABLED=true`): new entries from the configured read-only `ShooterGame.log` are announced with a
  running death total. A death is announced with no personal total when the player cannot be reliably identified.
- A failed Discord send is never replayed later, which prevents floods after reconnects.
- Player platform IDs are used internally only. They are never posted or logged.

## 📊 ARK survivor statistics

With `ARK_STATS_ENABLED=true` the bot records accumulated playtime and last-seen time per survivor in a local SQLite file.
Failed polls pause the clock, so an outage is never credited as playtime. Use `/ark stats show` and `/ark stats leaderboard`;
death counts, zombified deaths and the last cause are included when death tracking is on.

---

## 🎧 Audio player and libraries

Built for long session recordings. Join a voice channel and run `/play`.

- **Formats:** MP3, WAV, OGG, FLAC and M4A, validated with FFprobe/FFmpeg before storage.
- **Three scoped libraries** under `AUDIO_DIR`: **My Audio** (personal), **Channel Audio** and **Server Audio**.
  Layout: `servers/<guild-id>/personal/<user-id>`, `channel/<channel-id>`, `server/shared`.
- **Controls:** one Pause/Resume button, Stop and Volume. `/stop` and `/volume` also work as commands.
- **Now Playing:** the bot's own Discord status shows the recording (`⏸ Paused: …` when paused) and resets when idle.
- **Message reuse:** playback updates edit one player message per channel instead of spamming new ones.
- **Uploads:** attach a file to `/play`; uploads are size-limited and checked.
- **Large files:** copy recordings by SFTP into the import folder, then an administrator runs `/importaudio`, picks the file and a
  destination, and confirms. Files are validated and quota-checked, then removed from the import folder only after a successful commit.
  The folder is never scanned automatically, and sub-folders and symlinks are ignored.
- **Safe by design:** generated file names, permissions re-checked on every action, and deletion needs confirmation and is limited to the
  requester or an administrator.
- **Quotas and limits** (all configurable): 125 MB per upload, 2 hours per recording, 250 MB personal quota, 2 GB server quota.

---

## 🎲 Dice and dad jokes

- **Dice** accept `XdY` or `XdY±Z`. Advantage/disadvantage rolls two dice and keeps the higher or lower, then applies the modifier.
- **Dad jokes** come from icanhazdadjoke.com with a local fallback if the API is down. Topics are searched live, with seasonal fallbacks
  (Halloween, Christmas). `dnd`, `d&d` and `dungeons and dragons` use a curated local collection of family-friendly D&D jokes.
- **Voting:** every joke has 😂 Funny and 🙄 Groan buttons with persistent per-server ratings.
- **Leaderboard:** top five groan-worthy jokes, plus monthly (UTC) totals for the server, the current channel and the top five requesters.
  Stored in `~/.local/state/discord-bot/joke-ratings.sqlite3`.

---

## 📷 PhotoSaver

Saves image and video attachments to a mounted network share. It prefers losing nothing over saving everything: if anything is
uncertain, it skips the file rather than guess.

- **Mount-aware:** `PHOTO_SAVE_DIR` must sit inside the CIFS mount named by `PHOTO_REQUIRED_MOUNT`. Mount identity is verified before
  opening the destination and again before publishing, so an unmounted share can never fall through to a local folder.
- **Atomic writes:** hidden `.partial` files, expected-size checks, SHA-256 readback, then `renameat2(RENAME_NOREPLACE)`. Existing files are never replaced.
- **Deduplication:** by attachment ID across the whole photo root, including legacy folders.
- **Folder layout:** `<server folder>/<channel folder>/<attachment ID>_<filename>`. A private map (`PHOTO_CHANNEL_MAP`, schema v2) pins each server
  and channel ID to its folder, so renaming things in Discord never moves files. Colliding names get numbered suffixes (`notes (2)`).
- **Age-restricted channels are never saved.** Every attachment triggers a fresh Discord channel check, and threads require an
  explicitly unrestricted parent. Missing flags, permission errors and network failures all skip the file.
- **No history replay.** Anything missed during an outage needs a separately reviewed backfill that goes through the same safety checks.

<details>
<summary><b>Private storage configuration and legacy migration</b></summary>

Set these in the ignored `.env` (examples only):

```ini
PHOTO_SAVE_DIR=/mnt/example-share/Photos/Discord
PHOTO_REQUIRED_MOUNT=/mnt/example-share
PHOTO_CHANNEL_MAP=/var/lib/example-bot/photo-channel-map.json
```

Provision the destination only while the share is mounted. The service user needs write access to it and to the map's parent
directory. Configure the actual mount root, not a folder inside the share. Linux `/proc/self/mountinfo`, directory-descriptor
operations and `renameat2(RENAME_NOREPLACE)` support are required; unsupported systems fail closed.

Keep the channel map outside Git and back it up with the media. Version 2 format, with fictitious IDs:

```json
{
  "schema_version": 2,
  "servers": {
    "1": {
      "folder": "Example server",
      "channels": {"10": {"folder": "example-channel"}}
    }
  }
}
```

Never replace an existing map with this example.

**Legacy flat mappings** need an offline migration before this version can load PhotoSaver: stop the bot, back up the map, verify channel
and guild IDs against Discord, inventory the media, then use no-replace moves on the verified mount and check names, sizes and hashes.
Retain any folder whose identity is ambiguous; never infer ownership from folder names alone. Unverifiable assignments can be kept in
`unresolved_legacy_channels`, and saving for those IDs fails closed until they are reviewed. A folder with confirmed server ownership but
unknown channel provenance may be relocated intact under that server as a separate legacy folder, never merged into a live channel's folder.
Keep migration inventories and evidence outside Git.

Folder names keep readable Unicode, replace Windows-forbidden characters, strip trailing spaces and dots, and escape reserved device names.
</details>

---

## 📅 Scheduled-event feed

The `events` cog exports Discord scheduled events from every server the bot is in to a private JSON file for the photo viewer.
It is strictly read-only: it never creates or edits events, RSVPs, reads subscribers or sends messages.

- Refreshes at startup, every five minutes, and on event or channel changes.
- Default file: `~/.local/state/discord-photo-viewer/events.json` (directory `0700`, file `0600`). Override with `SCHEDULED_EVENTS_FILE`.
- Exports only IDs, titles, UTC times, status and event type. Descriptions, creators, attendees, images, links and locations are **not** exported,
  and invite URLs in titles are redacted.
- Events tied to age-restricted or unverifiable channels are excluded, using the same fail-closed check as PhotoSaver.
- Writes are atomic and fsynced, capped at 256 KiB, and never partially published. On partial API failure only verifiable events are kept,
  with `refresh_ok=false` and the last successful time unchanged.
- No extra Discord permissions are needed. Do not grant `MANAGE_EVENTS` or administrator for this feature.

---

## 🧠 Optional ChatGPT integration

`/ai` and @mention replies are **off by default** because they spend OpenAI credits. To enable: set `AI_ENABLED=true` and
`OPENAI_API_KEY`, restart the service, then run `/sync`.

Guardrails: per-user cooldown (`AI_COOLDOWN_SECONDS`, default 10), at most 2 requests at once, prompt and reply length caps, optional channel
allow-list (`ALLOWED_CHANNEL_IDS`), mentions suppressed in replies, and errors logged rather than shown to users.

---

## 🧩 Configuration

All settings live in a private `.env` file (never committed). Use plain values with no quotes and no inline comments.
`OWNER_ID` is a number only.

### Core

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | required | Bot token. |
| `OWNER_ID` | `0` | Your Discord user ID. Gates `/sync` and `/ark stats reset`. |
| `ALLOWED_CHANNEL_IDS` | all | Comma-separated channel allow-list for slash commands and AI. |

### ARK

| Variable | Default | Purpose |
|---|---|---|
| `ARK_RCON_HOST` / `ARK_RCON_PORT` / `ARK_RCON_PASSWORD` | | RCON connection. The password is never printed or logged. |
| `ARK_RCON_TIMEOUT` | built-in | RCON socket timeout. |
| `ARK_CHANNEL_ID` | `0` | The one channel used for relay and announcements. |
| `ARK_RELAY_TO_DISCORD` | `false` | ARK chat → Discord. |
| `ARK_RELAY_TO_ARK` | `false` | Discord → ARK chat. |
| `ARK_CHAT_POLL_SECONDS` | `5` | Chat polling interval. |
| `ARK_RELAY_OUTBOUND_PACING_SECONDS` | `1` | Delay between messages sent to the game. |
| `ARK_RELAY_USER_BURST_LIMIT` / `_WINDOW_SECONDS` / `_PENDING_LIMIT` | `5` / `10` / `5` | Per-user rate limits. |
| `ARK_PLAYER_NOTIFICATIONS` | `false` | Join, leave and outage posts. |
| `ARK_PLAYER_POLL_SECONDS` | `10` | Player polling interval. |
| `ARK_DEATH_TRACKING_ENABLED` | `false` | Death announcements and counts. |
| `ARK_DEATH_POLL_SECONDS` | `10` | Death-log polling interval. |
| `ARK_LOG_DIRECTORY` / `ARK_LOG_FILENAME` | `ShooterGame.log` | Read-only game log location. |
| `ARK_STATS_ENABLED` | `false` | Playtime statistics. |

### Audio

| Variable | Default | Purpose |
|---|---|---|
| `AUDIO_DIR` | `~/discord-audio` | Library root. |
| `AUDIO_IMPORT_DIR` | `~/discord-audio-import` | SFTP drop folder for `/importaudio`. |
| `AUDIO_MAX_UPLOAD_MB` | `125` | Per-file size limit. |
| `AUDIO_MAX_DURATION_SECONDS` | `7200` | Per-file length limit. |
| `AUDIO_PERSONAL_QUOTA_MB` | `250` | Quota per user. |
| `AUDIO_SERVER_QUOTA_GB` | `2` | Quota per server. |

### Storage, events and AI

| Variable | Default | Purpose |
|---|---|---|
| `PHOTO_SAVE_DIR` | `~/discord-photos` | Photo destination (must be inside the required mount). |
| `PHOTO_REQUIRED_MOUNT` | | Mounted share the destination must live on. |
| `PHOTO_CHANNEL_MAP` | `~/.local/state/discord-photo-saver/channels.json` | Private server/channel folder map. |
| `SCHEDULED_EVENTS_FILE` | `~/.local/state/discord-photo-viewer/events.json` | Event feed output. |
| `AI_ENABLED` | `false` | Turns on `/ai` and @mention replies. |
| `OPENAI_API_KEY` | | Needed only when AI is enabled. |
| `OPENAI_MODEL` / `OPENAI_MAX_TOKENS` / `OPENAI_TEMP` | `gpt-4o-mini` / `500` / `0.7` | Model settings. |
| `AI_COOLDOWN_SECONDS` | `10` | Per-user AI cooldown. |

---

## 🔧 Setup and deployment

### 1. Prerequisites (Raspberry Pi OS)

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3 python3-venv python3-pip ffmpeg libsodium23
```

`ffmpeg` and `libsodium23` are needed for voice playback and audio validation.

### 2. Clone and install

```bash
git clone https://github.com/Blittz/discord-bot-pi.git
cd discord-bot-pi
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure

Create `.env` (see [Configuration](#-configuration)); the minimum is:

```ini
DISCORD_TOKEN=your_bot_token_here
OWNER_ID=your_user_id
```

### 4. Run it

```bash
python -m src.bot
```

Then run `/sync` once in Discord to publish the slash commands.

### 5. Run it 24/7 with systemd

`/etc/systemd/system/discord-bot.service`:

```ini
[Unit]
Description=Discord Bot (discord-bot-pi)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=blittz
Group=blittz
WorkingDirectory=/home/blittz/apps/discord-bot-pi
Environment=PYTHONPATH=/home/blittz/apps/discord-bot-pi/src
EnvironmentFile=/home/blittz/apps/discord-bot-pi/.env
ExecStart=/home/blittz/apps/discord-bot-pi/.venv/bin/python -m src.bot
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now discord-bot.service
```

Useful commands:

```bash
systemctl status discord-bot.service
journalctl -u discord-bot.service -f
sudo systemctl restart discord-bot.service
```

> Python reads the code once at startup, so **any code change only takes effect after a restart**.

### 6. Updates

`tools/update-bot.sh` is the safe updater. `/usr/local/bin/update-discord-bot` is a symlink to it, and a cron job runs it every
night at **2 AM**, logging to `~/update-bot.log`.

```bash
update-discord-bot           # update only if origin/main has new commits
update-discord-bot --force   # restart and health-check even with nothing new
```

What it does, in order:

1. Refuses to run (and changes nothing) if the repo is not on `main`, if tracked files have local edits, or if another update is running.
2. Fetches, then fast-forwards only. Diverged history is never merged or rebased.
3. If there is nothing new it stops, so the bot is **not** restarted needlessly.
4. Installs dependencies only when `requirements.txt` changed.
5. Runs the full test suite. If any test fails, the new commits are rolled back and the bot is left running untouched.
6. Restarts the service and waits up to 45 seconds for the bot to log in and stay up for 5 more seconds.
7. If the bot does not come up healthy, it rolls back to the previous commit, restarts again and verifies that too.

The script exits non-zero on any failure or rollback, and every step is time-stamped in the log.
Its behavior (good update, failing tests, unhealthy deploy, wrong branch, dirty tree) is covered by `tests/test_update_script.py`,
which uses throwaway git repos and a stubbed `systemctl`, so the real bot is never touched.

### Changing the bot

1. Branch (`git checkout -b feat/my-change`), edit, and add tests.
2. Run the suite (below). Open a pull request and merge to `main`.
3. On the Pi: `git checkout main && git pull`, then restart the service.
4. If you changed any command definition, run `/sync` in Discord.

---

## 📂 Project structure

```text
discord-bot-pi/
├── src/
│   ├── bot.py                # Entry point, intents, cog loading
│   ├── cogs/
│   │   ├── core.py           # /help
│   │   ├── about.py          # /about
│   │   ├── admin.py          # /sync
│   │   ├── roll.py           # /roll, /adv, /dis
│   │   ├── dadjoke.py        # /dadjoke, /dadjoke-leaderboard
│   │   ├── audio.py          # /play, /stop, /volume, /importaudio
│   │   ├── ark.py            # /ark players, status, stats
│   │   ├── ark_chat.py       # ARK <-> Discord chat relay
│   │   ├── ark_players.py    # Join/leave, outage and death announcements
│   │   ├── photosaver.py     # Attachment saver
│   │   ├── events.py         # Scheduled-event feed
│   │   ├── chat.py           # /ai + @mention (only loaded when AI_ENABLED)
│   │   └── template.py       # Starting point for new cogs
│   ├── ark_service.py        # ARK RCON client (fixed, allow-listed commands)
│   ├── ark_stats.py          # Playtime and death statistics (SQLite)
│   ├── audio_storage.py      # Scoped audio libraries and quotas
│   ├── photo_storage.py      # Fail-closed network photo storage
│   ├── attachment_policy.py  # Age-restricted channel gate
│   ├── scheduled_events.py   # Event feed exporter
│   ├── joke_ratings.py       # Dad-joke votes (SQLite)
│   └── dnd_jokes.py          # Curated D&D jokes
├── tests/                    # unittest suite
├── tools/
│   ├── update-bot.sh         # Safe updater with tests, health check and rollback
│   └── ark_rcon_diagnostic.py  # ARK RCON diagnostics
├── requirements.txt
└── README.md
```

New features are one file: copy `src/cogs/template.py`, then add the cog to `CORE_EXTENSIONS` in `src/bot.py`.

---

## 🧪 Development and testing

```bash
python -B -m unittest discover -s tests -v
```

The suite (110 tests) runs without Discord, an ARK server or a mounted network share. Please add tests with every behavior change.

GitHub Actions (`.github/workflows/tests.yml`) runs the same command on Python 3.11 for every pull request and every push to `main`,
so a failing test shows up as a red check on the PR before anything is merged. The Pi's updater runs the suite again before it restarts the bot.

## 🚀 Roadmap

- [x] Checked-in update script with tests and automatic rollback
- [x] GitHub Actions workflow runs the tests on every pull request and push to `main`
- [ ] More utility commands (`/weather`, `/quote`)
- [ ] Moderation guardrails for `/ai`

---

## 📝 License

MIT License © 2025 Blittz
