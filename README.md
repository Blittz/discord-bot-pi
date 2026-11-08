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
* `/dadjoke` – Free family-friendly dad jokes from icanhazdadjoke.com, with a local fallback; no paid AI credits required
* `/sync` – Resync commands (owner only)

* **Audio Player**

* `/play` – Browse personal, voice-channel, and server audio libraries; play saved recordings or upload new audio
* `/stop` – Stop current playback
* `/volume` – Set playback volume from 1–100%
* `/importaudio` – Administrator-only import of SFTP-transferred audio files
* Supports MP3, WAV, OGG, FLAC, and M4A, with friendly artist/title names and Discord **Playing** activity
* Pause/Resume/Stop controls, secure scoped libraries, and administrator deletion
* SFTP imports support large recordings that exceed Discord upload limits

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

## ARK chat relay (disabled by default)

The optional chat relay is disabled unless both directions are enabled
explicitly in the private `.env` file:

```ini
ARK_CHANNEL_ID=1568775581313798345
ARK_CHAT_POLL_SECONDS=5
ARK_RELAY_TO_DISCORD=false
ARK_RELAY_TO_ARK=false
ARK_PLAYER_NOTIFICATIONS=false
ARK_PLAYER_POLL_SECONDS=10
ARK_RCON_HOST=192.168.1.10
ARK_RCON_PORT=27020
```

`ARK_RELAY_TO_DISCORD=true` polls `GetChat` every five seconds, establishes a
startup baseline, and forwards only new normalized messages to the exact text
channel identified by `ARK_CHANNEL_ID`. `ARK_RELAY_TO_ARK=true` forwards
ordinary messages from that channel through the fixed `ServerChat` operation;
it does not accept arbitrary RCON input. Mentions, formatting, control
characters, and oversized messages are sanitized. Per-user rate limits,
bounded queues, deduplication, reconnect backoff, and Discord mention
suppression are applied.

`ARK_PLAYER_NOTIFICATIONS=true` enables separate read-only `ListPlayers`
polling every ten seconds. The first successful snapshot establishes a
baseline, outages clear the baseline, and recovery establishes a new baseline
without generating false joins or leaves. Player platform identifiers are used
only internally when available and are never posted or logged. Notifications
are delivered only to `ARK_CHANNEL_ID`.

Retrieving the ARK chat buffer may affect other RCON consumers. Enable only one
chat-buffer consumer at a time until the server behavior is confirmed. To
rollback, set both relay flags to `false` and restart the bot through the normal
service procedure; no Discord command synchronization is required.

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

Keep the map outside Git and include it in a private backup. Existing flat
folders and version 1 mappings require an offline identity-verified migration;
see “Server/channel photo folders” below. Version 2 example, using fictitious IDs:

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

Never replace an existing map with this example. Server and channel IDs remain
the identity after renames. New identities receive separate numbered folders when
names collide; existing assigned folders retain their spelling. Store tokens,
server/channel IDs, real folder names, migration reports, media and backups privately.
No history replay is performed after an outage; any missed attachments require a
separately reviewed backfill. Duplicate IDs are skipped when their existing size
matches, and conflicting sizes are rejected without overwriting either file.

Run the isolated storage regression suite without Discord or a mounted share:

```bash
python -B -m unittest discover -s tests -v
```


### Age-restricted channels

Every image/video attachment passes a fresh Discord `GET /channels/{id}` check
before storage preparation or download. The `nsfw` boolean is Discord's
Age-Restricted flag. Restricted channels are skipped. Threads, including forum
and media posts, also require a fresh, explicitly unrestricted parent channel.
Missing flags, missing parents, unsupported channel types, permission errors,
and metadata/network failures skip the attachment; no cached unrestricted
assumption or local fallback is used. Logs contain only a channel ID and a short
reason for these skips, never message contents, tokens, or exception URLs.

`PhotoSaver.save_attachments` is the shared download entry point. Any future
history/backfill must call it rather than saving attachments directly, so the
same per-attachment policy, network mount checks, mapping and deduplication apply.
There is no automatic backfill. Existing media is never removed by this policy.
Fresh metadata requests add API traffic; Discord's HTTP client handles rate
limits. As with any remote permission check, a server-side flag change after the
check cannot be made atomic with a file download.


## Private scheduled-event feed for the photo viewer

The `events` cog reads scheduled events from **all servers the bot is already a
member of**. It fetches on ready/startup and every five minutes. Standard
`guild_scheduled_events` intent (already enabled by the installed library's
normal defaults) supplies create/update/delete notifications; channel and guild
changes also trigger a coalesced refresh. Polling covers missed/uncached gateway
updates. It never creates/edits events, RSVPs, fetches subscribers or sends messages.

For stage/voice events, Discord requires `VIEW_CHANNEL` to see the associated
channel. External events require membership but no extra event-management
permission. Do not grant `CREATE_EVENTS`, `MANAGE_EVENTS` or administrator just
for this feature. Existing attachment intents/permissions are unchanged.

The default shared file is `~/.local/state/discord-photo-viewer/events.json`.
Both applications currently run as the same OS user; its directory is 0700 and
atomic replacement files are 0600. This is a **local** state directory outside
all selected photo folders, separate from network photo storage. No mount or
system-service modifications are needed. For a deployment with different users,
provision a directory readable by the viewer and writable by the bot, and set
`SCHEDULED_EVENTS_FILE=/path/to/private-shared-state/events.json` in both launch
environments. Use an absolute path outside photo libraries; keep its contents
and all private configuration out of Git. Runtime code requires no elevation.

Schema version 1 includes refresh status, last attempted/successful UTC refresh,
server ID/name and per-server refresh status, plus event ID/server ID, title,
start/end UTC timestamps, status, external/channel kind and nullable channel ID.
Channel IDs are retained so old channel-associated records can be reverified on
fetch failures. Descriptions, creator details, attendee lists/counts, cover images,
external locations and links are not exported; invite URLs in titles are redacted.

Every channel-associated event uses the same fresh fail-closed restriction gate
as attachments, including parent checks if applicable. Restricted and unknown
channels are excluded. External events are represented without a channel or a
fabricated restriction flag. On partial/API failure, old external and freshly
reverified safe channel events can be retained, with `refresh_ok=false` and the
last successful time unchanged. **Never retain an unverifiable channel record**
just to preserve a stale preview. A successful refresh removes canceled/completed,
deleted or newly restricted events. Removed servers disappear from the feed.
The viewer also expires old snapshots, including when publication fails.

`os.replace` publishes one complete fsynced JSON file, never partial data. The
256 KiB size cap fails closed rather than truncating an oversized collection.
No event titles, descriptions or API exception bodies appear in exporter logs.
This feed does not alter attachment downloads, mount validation, channel maps,
deduplication, or any previously downloaded photo/video.


### Server/channel photo folders

PhotoSaver stores new media beneath `PHOTO_SAVE_DIR` as
`<server folder>/<channel folder>/<attachment ID>_<existing filename convention>`.
The private `PHOTO_CHANNEL_MAP` uses schema version 2: `servers` is keyed by
Discord server ID, and each server's `channels` is keyed by channel ID. Each
entry records its assigned `folder`; renaming a Discord server/channel does not
rename its storage. Keep this mapping outside Git and back it up with the media.

Folder names preserve readable Unicode, replace Windows forbidden/control
characters, strip trailing spaces/dots, and escape reserved device names.
Case/normalization collisions and existing unassigned directories receive an
explicit numbered suffix such as `notes (2)`; unrelated identities never share
an assigned folder. Attachment-ID deduplication scans the entire photo root,
including legacy directories that have not been migrated.

Legacy flat mappings require an offline migration before this version can load
PhotoSaver. Stop the bot, back up its private mapping, verify channel IDs and
their guild IDs against Discord, and inventory media before moving directories.
Only move directories with established identity; retain ambiguous directories.
Use no-replace moves on the verified network mount, verify filenames/sizes/hashes,
then atomically publish the new mapping before starting the bot. Never infer
legacy ownership from folder names alone. The viewer can continue selecting the
photo root recursively. Migration inventories and recovery records belong outside
Git alongside the private mapping backup.

Unverifiable legacy channel assignments can be retained privately in
`unresolved_legacy_channels`. Saving for those IDs fails closed until an offline
identity review resolves the entry; the original mapping backup remains available.

If a legacy folder's server ownership is explicitly confirmed but its channel-ID
provenance is unavailable, it may be relocated intact beneath that server as a
separate unassigned legacy folder. Verify hashes before and after a no-replace
move while downloads are paused. Do not merge it into a live channel's assigned
folder or invent a channel mapping; recursive viewing and root-wide deduplication
still include the relocated legacy files. Keep the ownership evidence and
verification records private, outside Git.

### Audio playback

Use `/play` while connected to a voice channel. Saved files are read from
`AUDIO_DIR` (default `~/discord-audio`); create that directory and copy in
MP3, WAV, OGG, FLAC, M4A, AAC, WebM, or Opus files. The bot joins your
current voice channel, plays the file through FFmpeg, and disconnects when
finished. An uploaded file can be supplied through `/play`'s optional
`audio` attachment field; uploads are size-limited by `AUDIO_MAX_UPLOAD_MB`
(default 25 MB), validated, and removed after playback.

### Playback controls

The private Now Playing and playback status responses provide a single Pause or Resume button, Stop, and Volume controls. `/volume` accepts any whole-number percentage from 1% through 100% (default 100%). `/stop` remains available if a component message is unavailable.

### Managed audio libraries

Audio storage is scoped by numeric Discord IDs under `AUDIO_DIR` (default `~/discord-audio`): `servers/<guild-id>/personal/<user-id>`, `channel/<channel-id>`, and `server/shared`. Upload validation accepts MP3, WAV, OGG, FLAC, and M4A, verifies an audio stream with FFprobe/FFmpeg, limits uploads to `AUDIO_MAX_UPLOAD_MB` (125 MB by default) and `AUDIO_MAX_DURATION_SECONDS` (2 hours by default), and uses generated filenames. Personal quota defaults to 500 MB (`AUDIO_PERSONAL_QUOTA_MB`); server quota defaults to 2 GB (`AUDIO_SERVER_QUOTA_GB`). `/play` provides private library scope selection, upload choices, and deletion confirmation; permissions are checked again for each operation.

### Playback activity

While audio is playing, the bot profile shows a Discord **Playing** activity using the recording's friendly artist/title or filename. Paused playback is shown as `⏸ Paused: <name>`; when playback ends or all active servers are idle, the default bot activity is restored.

### SFTP audio import

For files too large to upload through Discord, copy them by SFTP into `/home/blittz/discord-audio-import/` (for example: `sftp user@pi:/home/blittz/discord-audio-import/`). An administrator can run `/importaudio`, choose a direct MP3/WAV/OGG/FLAC/M4A file, select My Audio, Channel Audio, or Server Audio, and confirm the import. Files are FFprobe/FFmpeg validated, quota checked, copied into generated scoped storage names, and removed from the import directory only after a successful commit. The import directory is never scanned automatically and subdirectories/symlinks are ignored.

### Player message reuse

Playback controls reuse the bot's current player message in each text channel when Discord permits editing it. Start, pause/resume, volume, stop, and natural completion update that message; private library, upload, and deletion workflows remain ephemeral. If a message is stale or deleted, the bot falls back to a new response.

`/dadjoke` also accepts an optional topic, for example `/dadjoke topic:halloween` or `/dadjoke topic:cats`; topic searches use the free API with local seasonal fallbacks.
For tabletop gaming, `/dadjoke topic:dnd` (also `d&d` or `dungeons and dragons`) uses a curated local collection of family-friendly D&D jokes.
Dad jokes include persistent per-server 😂 Funny and 🙄 Groan voting buttons; `/dadjoke-leaderboard` shows the top five groan-worthy jokes plus current-month usage (UTC). It defaults to private; use `/dadjoke-leaderboard visibility:public` to post it in the channel. Ratings and usage are stored locally in `~/.local/state/discord-bot/joke-ratings.sqlite3`; ratings remain all-time while usage starts tracking after deployment each calendar month.
The leaderboard also shows current-channel totals and the top five requesting users for the current UTC month. Older usage rows remain in server totals but have no invented channel assignment.
