import json
import os
import re
from datetime import datetime, timezone

import discord
from discord.ext import commands

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

# Put your bot token in an environment variable called DISCORD_TOKEN
# (Never hardcode your token in the file, especially if you share/upload it anywhere.)
TOKEN = os.environ.get("DISCORD_TOKEN")

# Only messages in these channel names will be watched for vouches.
# Set to None to watch every channel the bot can see.
VOUCH_CHANNEL_NAMES = None  # e.g. {"vouches", "vouch-log"}

DATA_FILE = "vouches.json"

# Canonical event names + accepted aliases (all matched case-insensitively)
EVENT_ALIASES = {
    "elder": "Elder",
    "prima": "Prima",
    "primadon": "Prima",
    "enmity": "Enmity",
    "hell mode": "Hell Mode",
    "hellmode": "Hell Mode",
    "titus": "Titus",
}

ALL_EVENTS = ["Elder", "Prima", "Enmity", "Hell Mode", "Titus"]

# ─────────────────────────────────────────────────────────────
# STORAGE
# ─────────────────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_user_record(data, user_id):
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"total": 0, "events": {e: 0 for e in ALL_EVENTS}, "log": []}
    return data[uid]


# ─────────────────────────────────────────────────────────────
# PARSING
# ─────────────────────────────────────────────────────────────

# Matches: vouch @user <event text>
VOUCH_PATTERN = re.compile(r"^\s*vouch\s+<@!?(\d+)>\s+(.+)$", re.IGNORECASE)


def parse_event(text):
    """Return canonical event name if text matches a known event/alias, else None."""
    cleaned = text.strip().lower()
    return EVENT_ALIASES.get(cleaned)


# ─────────────────────────────────────────────────────────────
# BOT
# ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")


@bot.event
async def on_message(message):
    # Ignore the bot's own messages
    if message.author.bot:
        return

    # Optional channel restriction
    if VOUCH_CHANNEL_NAMES is not None:
        if getattr(message.channel, "name", None) not in VOUCH_CHANNEL_NAMES:
            await bot.process_commands(message)
            return

    match = VOUCH_PATTERN.match(message.content)
    if match:
        target_id = int(match.group(1))
        event_text = match.group(2)
        event_name = parse_event(event_text)

        if event_name is None:
            valid_list = ", ".join(ALL_EVENTS)
            await message.channel.send(
                f"⚠️ Couldn't recognize event type `{event_text.strip()}`. "
                f"Valid events: {valid_list}"
            )
            return

        # Prevent self-vouching (optional — remove this block if not wanted)
        if target_id == message.author.id:
            await message.channel.send("⚠️ You can't vouch for yourself.")
            return

        data = load_data()
        record = get_user_record(data, target_id)
        record["total"] += 1
        record["events"][event_name] += 1
        record["log"].append({
            "by": message.author.id,
            "by_name": str(message.author),
            "event": event_name,
            "time": datetime.now(timezone.utc).isoformat(),
        })
        save_data(data)

        target_member = message.guild.get_member(target_id) if message.guild else None
        target_name = target_member.display_name if target_member else f"<@{target_id}>"

        await message.channel.send(
            f"✅ Vouch recorded for **{target_name}** — {event_name} "
            f"(total: {record['total']})"
        )
        return

    await bot.process_commands(message)


@bot.command(name="vouches")
async def vouches(ctx, member: discord.Member = None):
    """Check a user's vouch count. Usage: !vouches @user"""
    member = member or ctx.author
    data = load_data()
    record = data.get(str(member.id))

    if not record:
        await ctx.send(f"{member.display_name} has no vouches yet.")
        return

    breakdown = "\n".join(
        f"  {e}: {record['events'].get(e, 0)}" for e in ALL_EVENTS
    )
    await ctx.send(
        f"**{member.display_name}**'s vouches (total: {record['total']})\n{breakdown}"
    )


@bot.command(name="leaderboard")
async def leaderboard(ctx, top_n: int = 10):
    """Show the top vouched users. Usage: !leaderboard [n]"""
    data = load_data()
    if not data:
        await ctx.send("No vouches recorded yet.")
        return

    ranked = sorted(data.items(), key=lambda kv: kv[1]["total"], reverse=True)[:top_n]

    lines = []
    for i, (uid, record) in enumerate(ranked, start=1):
        member = ctx.guild.get_member(int(uid)) if ctx.guild else None
        name = member.display_name if member else f"<@{uid}>"
        lines.append(f"{i}. {name} — {record['total']}")

    await ctx.send("**🏆 Vouch Leaderboard**\n" + "\n".join(lines))


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "No token found. Set the DISCORD_TOKEN environment variable before running."
        )
    bot.run(TOKEN)
