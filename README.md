# Discord Bot on Raspberry Pi 5

A lightweight, flexible Discord bot built with **Python** and **discord.py**, designed to run 24/7 on a Raspberry Pi 5.  
Supports **commands and keyword triggers from JSON**, **random responses**, **per-channel cooldowns**, and a full **dice roller with inline math**.

---

## ✨ Features

- **Configurable commands/keywords** via `commands.json`
  - Prefix commands (e.g. `!hello`)
  - Keyword triggers (e.g. reply whenever "war" or "bean" is mentioned)
  - Supports random replies if multiple strings are given

- **Dice Roller**
  - `!roll` supports:
    - Simple rolls: `!roll`, `!roll d20`, `!roll 1d20+5`
    - Advantage/Disadvantage: `!roll adv`, `!roll dis+2`
    - Keep highest/lowest: `!roll 2d20kh1`, `!roll 4d6kl3`
    - Inline math: `!roll 3d6 + 2d4 + 5`, `!roll adv + 1d4 - 2`
  - Breakdown shows all dice rolled and which were kept

- **Cooldowns**
  - Prevent spam by enforcing per-channel cooldowns for both commands and keyword triggers (configurable via `.env`)

- **Hot reload**
  - `!reload` reloads `commands.json` without restarting the bot

- **Environment-based config**
  - Safe and flexible via `.env` file (compatible with Windows, Linux, Raspberry Pi)

---

## 🛠 Requirements

- Python 3.9+
- Packages:
  ```bash
  pip install discord.py python-dotenv