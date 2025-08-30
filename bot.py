# bot.py
import os
import json
import re
import time
import random
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Union

import discord
from discord.ext import commands
from discord.ext.commands import BucketType
from dotenv import load_dotenv

# ----------------------------
# Env & basic configuration
# ----------------------------
load_dotenv()  # Loads .env if present (DISCORD_TOKEN, BOT_PREFIX, etc.)

COMMANDS_FILE = os.getenv("COMMANDS_FILE", "commands.json")
PREFIX = os.getenv("BOT_PREFIX", "!")
OWNER_ID = os.getenv("OWNER_ID")  # optional (Discord user ID, as string)

# Cooldown in seconds (per-channel)
COOLDOWN_SEC = int(os.getenv("KEYWORD_COOLDOWN_SEC", "5"))

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")
for name in ("discord", "discord.client", "discord.gateway"):
    logging.getLogger(name).setLevel(logging.WARNING)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ----------------------------
# In-memory stores
# ----------------------------
# Values can be str OR List[str] for randomization
command_map: Dict[str, Union[str, List[str]]] = {}
keyword_map: Dict[str, Union[str, List[str]]] = {}

# Compiled patterns for keywords (regex, reply)
_keyword_patterns: List[Tuple[re.Pattern, Union[str, List[str]]]] = []

# Per-channel cooldown tracking
# Keyword: (channel_id, regex_pattern_str) -> last_hit_ts
_keyword_last_hit: Dict[Tuple[int, str], float] = {}
# Commands: (channel_id, command_key) -> last_hit_ts
_command_last_hit: Dict[Tuple[int, str], float] = {}


def pick_reply(v: Union[str, List[str]]) -> str:
    """Accepts a string or list; returns a single string."""
    if isinstance(v, list) and v:
        return random.choice(v)
    return str(v)


def _compile_keyword_patterns() -> None:
    """Compile whole-word, case-insensitive regex patterns. Longer phrases first."""
    global _keyword_patterns
    items = list(keyword_map.items())
    items.sort(key=lambda kv: len(kv[0]), reverse=True)
    patterns: List[Tuple[re.Pattern, Union[str, List[str]]]] = []
    for key, reply in items:
        pattern = re.compile(rf"\b{re.escape(key)}\b", re.IGNORECASE)
        patterns.append((pattern, reply))
    _keyword_patterns = patterns
    log.info(f"Compiled {len(_keyword_patterns)} keyword patterns")


def load_commands() -> None:
    """Load commands/keywords from JSON file."""
    global command_map, keyword_map

    path = Path(COMMANDS_FILE)
    if not path.exists():
        log.warning(f"{COMMANDS_FILE} not found. Creating a starter file.")
        starter = {
            "commands": {
                "hello": ["Hey there! 👋", "Hello!", "Yo!", "Hiya 👋"],
                "ping": "Pong!",
                "version": "Discord Bot on Raspberry Pi 5 — v1.0.0"
            },
            "keywords": {
                "bean": [
                    "Bean detected. Initiating chili protocol… 🌶️🫘",
                    "Mr. Bean is in the house! 🧥",
                    "It’s Bean time 🫘"
                ],
                "war": ["⚔️ War… war never changes.", "War? I prefer board games."]
            }
        }
        path.write_text(json.dumps(starter, indent=2, ensure_ascii=False), encoding="utf-8")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Keep values as str OR list[str]; normalize keys
    command_map = {str(k).strip().lower(): v for k, v in data.get("commands", {}).items()}
    keyword_map = {str(k).strip().lower(): v for k, v in data.get("keywords", {}).items()}

    _compile_keyword_patterns()
    log.info(f"Loaded {len(command_map)} commands and {len(keyword_map)} keywords from {COMMANDS_FILE}")


def _is_owner(user_id: int) -> bool:
    if not OWNER_ID:
        return True
    try:
        return int(OWNER_ID) == user_id
    except ValueError:
        return False


def _hit_recently(store: dict, key: tuple, now: float, cooldown: int) -> bool:
    """Return True if still in cooldown; else record now and return False."""
    last = store.get(key, 0.0)
    if now - last < cooldown:
        return True
    store[key] = now
    return False


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (id: {bot.user.id})")
    log.info(f"Prefix: {PREFIX}")
    load_commands()


# ----------------------------
# Dice utilities (single term + inline expressions)
# ----------------------------
DICE_SINGLE_RE = re.compile(
    r"""
    ^\s*
    (?:
        (?P<adv>adv|dis)
        (?:\s*(?P<adv_mod>[+\-]\d+))?
      |
        (?P<n>\d*)d(?P<sides>\d+)
        (?:
            (?P<keep>(kh|kl))(?P<knum>\d+)
        )?
        (?P<mod>(?:[+\-]\d+)*)
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE
)

TOKEN_RE = re.compile(
    r"""
    (?P<sign>[+\-]?)
    (?:
        (?P<dice>(?P<n>\d*)d(?P<sides>\d+)(?:(?P<keep>kh|kl)(?P<knum>\d+))?)
      | (?P<advdis>adv|dis)
      | (?P<num>\d+)
    )
    """,
    re.IGNORECASE | re.VERBOSE
)


def _sum_modifiers(mod_str: str) -> int:
    if not mod_str:
        return 0
    total = 0
    for part in re.findall(r"[+\-]\d+", mod_str):
        total += int(part)
    return total


def _roll_once(n: int, sides: int) -> List[int]:
    return [random.randint(1, sides) for _ in range(max(1, n))]


def _format_roll(rolls: List[int], kept_idx: set = None) -> str:
    if not rolls:
        return "—"
    kept_idx = kept_idx or set()
    parts = []
    for i, r in enumerate(rolls):
        parts.append(f"**{r}**" if i in kept_idx else str(r))
    return "[" + ", ".join(parts) + "]"


def roll_single(expr: str) -> Tuple[int, str]:
    m = DICE_SINGLE_RE.match(expr or "")
    if not m:
        raise ValueError("Unrecognized roll syntax.")

    if m.group("adv"):
        adv = m.group("adv").lower()
        bonus = _sum_modifiers(m.group("adv_mod") or "")
        rolls = _roll_once(2, 20)
        if adv == "adv":
            kept_idx = {0 if rolls[0] >= rolls[1] else 1}
            kept = max(rolls)
            kind = "Advantage"
        else:
            kept_idx = {0 if rolls[0] <= rolls[1] else 1}
            kept = min(rolls)
            kind = "Disadvantage"
        total = kept + bonus
        text = f"{kind}: {_format_roll(rolls, kept_idx)} {'+' if bonus>=0 else ''}{bonus} = **{total}**"
        return total, text

    n = int(m.group("n") or "1")
    sides = int(m.group("sides"))
    keep = m.group("keep")
    knum = int(m.group("knum") or "0")
    bonus = _sum_modifiers(m.group("mod") or "")

    rolls = _roll_once(n, sides)

    kept_idx = set(range(len(rolls)))
    if keep:
        if knum <= 0 or knum > len(rolls):
            raise ValueError("Invalid keep count.")
        if keep == "kh":
            sorted_idx = sorted(range(len(rolls)), key=lambda i: rolls[i], reverse=True)
            kept_idx = set(sorted_idx[:knum])
            label = f"{n}d{sides}kh{knum}"
        else:
            sorted_idx = sorted(range(len(rolls)), key=lambda i: rolls[i])
            kept_idx = set(sorted_idx[:knum])
            label = f"{n}d{sides}kl{knum}"
        kept_values = [rolls[i] for i in kept_idx]
        subtotal = sum(kept_values)
    else:
        label = f"{n}d{sides}"
        subtotal = sum(rolls)

    total = subtotal + bonus
    pretty_mod = f" {'+' if bonus>=0 else ''}{bonus}" if bonus else ""
    text = f"{label}: {_format_roll(rolls, kept_idx)}{pretty_mod} = **{total}**"
    return total, text


def roll_expression(expr: str) -> Tuple[int, str]:
    """
    Parse and evaluate inline math:
      '3d6+2d4+5', '2d20kh1 + 1d6 - 2', 'adv + 3 + 1d4', 'dis - 1'
    No precedence; left-to-right sum of signed terms.
    """
    if not expr or not expr.strip():
        return roll_single("d20")

    s = expr.replace(" ", "").lower()
    tokens = []
    i = 0
    while i < len(s):
        m = TOKEN_RE.match(s, i)
        if not m:
            if i == 0:
                return roll_single(s)
            raise ValueError(f"Unrecognized token at: {s[i:]}")
        sign = -1 if m.group("sign") == "-" else 1
        if m.group("dice"):
            n = int(m.group("n") or "1")
            sides = int(m.group("sides"))
            keep = m.group("keep")
            knum = int(m.group("knum") or "0")
            tokens.append(("dice", sign, n, sides, keep, knum))
        elif m.group("advdis"):
            tokens.append(("advdis", sign, m.group("advdis").lower()))
        else:
            tokens.append(("num", sign, int(m.group("num"))))
        i = m.end()

    if not tokens:
        return roll_single("d20")

    parts_text = []
    total = 0

    for tok in tokens:
        if tok[0] == "dice":
            _, sign, n, sides, keep, knum = tok
            rolls = _roll_once(n, sides)
            kept_idx = set(range(len(rolls)))
            label = f"{n}d{sides}"

            if keep:
                if knum <= 0 or knum > len(rolls):
                    raise ValueError("Invalid keep count.")
                if keep == "kh":
                    sorted_idx = sorted(range(len(rolls)), key=lambda i: rolls[i], reverse=True)
                    kept_idx = set(sorted_idx[:knum])
                    label += f"kh{knum}"
                else:
                    sorted_idx = sorted(range(len(rolls)), key=lambda i: rolls[i])
                    kept_idx = set(sorted_idx[:knum])
                    label += f"kl{knum}"
                kept_vals = [rolls[i] for i in kept_idx]
                subtotal = sum(kept_vals)
            else:
                subtotal = sum(rolls)

            total += sign * subtotal
            sign_str = "+" if sign >= 0 else "-"
            parts_text.append(f"{sign_str} {label} {_format_roll(rolls, kept_idx)} → {sign_str}**{subtotal}**")

        elif tok[0] == "advdis":
            _, sign, kind = tok
            rolls = _roll_once(2, 20)
            if kind == "adv":
                kept_idx = {0 if rolls[0] >= rolls[1] else 1}
                kept = max(rolls)
                label = "adv"
            else:
                kept_idx = {0 if rolls[0] <= rolls[1] else 1}
                kept = min(rolls)
                label = "dis"
            total += sign * kept
            sign_str = "+" if sign >= 0 else "-"
            parts_text.append(f"{sign_str} {label} {_format_roll(rolls, kept_idx)} → {sign_str}**{kept}**")

        else:  # num
            _, sign, val = tok
            total += sign * val
            sign_str = "+" if sign >= 0 else "-"
            parts_text.append(f"{sign_str} **{val}**")

    if parts_text and parts_text[0].startswith("+ "):
        parts_text[0] = parts_text[0][2:]
    breakdown = " ".join(parts_text)
    return total, f"{breakdown} = **{total}**"


# ----------------------------
# Commands
# ----------------------------
@bot.command(name="reload")
async def reload_cmd(ctx: commands.Context):
    """Reload commands.json without restarting the bot."""
    if not _is_owner(ctx.author.id):
        return await ctx.reply("Sorry, only the owner can reload commands.")
    try:
        load_commands()
        await ctx.reply(f"✅ Reloaded `{COMMANDS_FILE}`.")
    except Exception as e:
        log.exception("Failed to reload commands")
        await ctx.reply(f"❌ Failed to reload: `{e}`")


@bot.command(name="roll")
@commands.cooldown(1, COOLDOWN_SEC, BucketType.channel)
async def roll_cmd(ctx: commands.Context, *, arg: str = "d20"):
    """Roll dice with inline expressions (e.g., 3d6+2d4+5, adv+1)."""
    try:
        _, text = roll_expression(arg)
        await ctx.reply(text)
    except Exception:
        await ctx.reply(
            "❌ Invalid roll. Try examples like:\n"
            "`!roll 3d6 + 2d4 + 5` • `!roll 2d20kh1 + 1d6 - 2` • `!roll adv + 3` • `!roll d20`"
        )


@roll_cmd.error
async def roll_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(f"⏳ Roll is on cooldown here. Try again in {error.retry_after:.1f}s.")
        return
    raise error


@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    """Show available commands and keywords dynamically."""
    # JSON commands (prefix-based)
    json_commands = sorted(command_map.keys())

    # Registered commands (exclude JSON names to avoid duplicates)
    built_ins = sorted([name for name in bot.all_commands.keys() if name not in json_commands])

    # Keywords (no prefix required)
    keywords = sorted(keyword_map.keys())

    lines = [
        f"**Prefix:** `{PREFIX}`",
        "",
        "**Built-in commands:** " + (", ".join(f"`{PREFIX}{c}`" for c in built_ins) if built_ins else "_none_"),
        "**JSON commands:** " + (", ".join(f"`{PREFIX}{c}`" for c in json_commands) if json_commands else "_none_"),
        "**Keyword triggers (no prefix):** " + (", ".join(f"`{k}`" for k in keywords) if keywords else "_none_"),
        "",
        "• Dice help: try `!roll 1d20+5`, `!roll adv+2`, or `!roll 3d6 + 2d4 + 5`",
    ]
    await ctx.reply("\n".join(lines))


# ----------------------------
# Error handling
# ----------------------------
@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CommandNotFound):
        return
    raise error


# ----------------------------
# Message handling
# ----------------------------
@bot.event
async def on_message(message: discord.Message):
    # Ignore bots
    if message.author.bot:
        return

    content = message.content
    lower_content = content.lower().strip()

    # ---- 1) Prefix commands (registered or JSON) ----
    if lower_content.startswith(PREFIX.lower()):
        raw = lower_content[len(PREFIX):].strip()
        first_word = raw.split(" ", 1)[0]

        # Registered @bot.command (e.g., help, reload, roll)
        if first_word in bot.all_commands:
            await bot.process_commands(message)
            return

        now = time.time()

        # JSON exact match (full content after prefix)
        if raw in command_map:
            key = (message.channel.id, f"cmd:{raw}")
            if _hit_recently(_command_last_hit, key, now, COOLDOWN_SEC):
                return
            await message.channel.send(pick_reply(command_map[raw]))
            return

        # JSON token fallback (e.g., "!hello there" -> "hello")
        if first_word in command_map:
            key = (message.channel.id, f"cmd:{first_word}")
            if _hit_recently(_command_last_hit, key, now, COOLDOWN_SEC):
                return
            await message.channel.send(pick_reply(command_map[first_word]))
            return

        # No match; don't call process_commands to avoid CommandNotFound spam
        return  # and don't run keyword triggers on prefixed text

    # ---- 2) Keyword triggers (whole-word) with per-channel cooldown ----
    now = time.time()
    for pattern, reply in _keyword_patterns:
        if pattern.search(content):
            key = (message.channel.id, pattern.pattern)
            if _hit_recently(_keyword_last_hit, key, now, COOLDOWN_SEC):
                return
            await message.channel.send(pick_reply(reply))
            return  # stop after first match


# ----------------------------
# Entrypoint
# ----------------------------
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN not set. Create a .env file with DISCORD_TOKEN=your-bot-token "
            "or set it in your environment."
        )
    bot.run(token)