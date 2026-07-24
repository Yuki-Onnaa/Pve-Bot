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

# Only messages in this channel ID will be watched for vouches.
# Set to None to watch every channel the bot can see.
VOUCH_CHANNEL_ID = 1529113596657799178

# Where vouch data is stored. On Railway, mount a Volume and point this at it
# (e.g. "/data/vouches.json") so data survives redeploys — see README for setup.
DATA_FILE = os.environ.get("DATA_FILE", "/data/vouches.json")

# Canonical event names -> point values
EVENT_POINTS = {
    "Enmity": 1.5,
    "Elder": 2,
    "Titus": 3,
    "Hellmode": 15,
    "Deep Champion": 15,
    "Diluvian W (25)": 3,
    "Diluvian W (50)": 10,
    "Parasol": 5,
    "Layer 2 (1)": 3,
    "Layer 2 (2)": 7,
    "Other Bosses": 1,
}

ALL_EVENTS = list(EVENT_POINTS.keys())

# Aliases -> canonical name (all matched case-insensitively, whitespace-flexible)
EVENT_ALIASES = {
    "enmity": "Enmity",
    "elder": "Elder",
    "titus": "Titus",
    "hellmode": "Hellmode",
    "hell mode": "Hellmode",
    "deep champion": "Deep Champion",
    "deepchampion": "Deep Champion",
    "diluvian w 25": "Diluvian W (25)",
    "diluvian w (25)": "Diluvian W (25)",
    "diluvian 25": "Diluvian W (25)",
    "diluvian w 50": "Diluvian W (50)",
    "diluvian w (50)": "Diluvian W (50)",
    "diluvian 50": "Diluvian W (50)",
    "parasol": "Parasol",
    "layer 2 1": "Layer 2 (1)",
    "layer 2 (1)": "Layer 2 (1)",
    "layer2 1": "Layer 2 (1)",
    "layer 2 2": "Layer 2 (2)",
    "layer 2 (2)": "Layer 2 (2)",
    "layer2 2": "Layer 2 (2)",
    "other bosses": "Other Bosses",
    "other boss": "Other Bosses",
    "otherbosses": "Other Bosses",
}

# ─────────────────────────────────────────────────────────────
# STORAGE
# ─────────────────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_user_record(data, user_id):
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "total_points": 0,
            "total_vouches": 0,
            "events": {e: 0 for e in ALL_EVENTS},
            "log": [],
        }
    # Backfill any newly added event keys for existing users
    for e in ALL_EVENTS:
        data[uid]["events"].setdefault(e, 0)
    return data[uid]


# ─────────────────────────────────────────────────────────────
# PARSING
# ─────────────────────────────────────────────────────────────

# Matches: vouch @user1 @user2 ... <event text>
VOUCH_PATTERN = re.compile(r"^\s*vouch\s+((?:<@!?\d+>\s*)+)(.+)$", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"<@!?(\d+)>")


def normalize(text):
    # Collapse whitespace, strip punctuation-ish spacing, lowercase
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    return cleaned


def parse_event(text):
    """Return canonical event name if text matches a known event/alias, else None."""
    return EVENT_ALIASES.get(normalize(text))


# ─────────────────────────────────────────────────────────────
# BOT
# ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="?", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")


@bot.event
async def on_message(message):
    # Ignore the bot's own messages
    if message.author.bot:
        return

    # Optional channel restriction
    if VOUCH_CHANNEL_ID is not None:
        if message.channel.id != VOUCH_CHANNEL_ID:
            await bot.process_commands(message)
            return

    match = VOUCH_PATTERN.match(message.content)
    if match:
        mentions_block = match.group(1)
        event_text = match.group(2)
        target_ids = [int(uid) for uid in MENTION_PATTERN.findall(mentions_block)]

        event_name = parse_event(event_text)
        if event_name is None:
            await message.add_reaction("❌")
            return

        # Filter out self-vouch attempts; track if that removed everyone
        valid_targets = [uid for uid in target_ids if uid != message.author.id]
        if not valid_targets:
            await message.add_reaction("🚫")
            return

        points = EVENT_POINTS[event_name]
        data = load_data()

        for target_id in valid_targets:
            record = get_user_record(data, target_id)
            record["total_points"] += points
            record["total_vouches"] += 1
            record["events"][event_name] += 1
            record["log"].append({
                "by": message.author.id,
                "by_name": str(message.author),
                "event": event_name,
                "points": points,
                "time": datetime.now(timezone.utc).isoformat(),
            })

        save_data(data)

        # If some targets were dropped for being self-vouches, flag it alongside success
        if len(valid_targets) < len(target_ids):
            await message.add_reaction("🚫")
        await message.add_reaction("✅")
        return

    await bot.process_commands(message)


@bot.command(name="vouches")
async def vouches(ctx, member: discord.Member = None):
    """Check a user's vouch total and breakdown. Usage: !vouches @user"""
    member = member or ctx.author
    data = load_data()
    record = data.get(str(member.id))

    if not record:
        await ctx.send(f"{member.display_name} has no vouches yet.")
        return

    breakdown_lines = []
    for e in ALL_EVENTS:
        count = record["events"].get(e, 0)
        if count:
            breakdown_lines.append(f"  {e}: {count} × {EVENT_POINTS[e]} = {count * EVENT_POINTS[e]} pts")

    breakdown = "\n".join(breakdown_lines) if breakdown_lines else "  (no vouches yet)"
    await ctx.send(
        f"**{member.display_name}**\n"
        f"Total: {record['total_points']} pts across {record['total_vouches']} vouches\n"
        f"{breakdown}"
    )


@bot.command(name="addvouch", aliases=["backfill"])
@commands.has_permissions(manage_guild=True)
async def addvouch(ctx, member: discord.Member, *, event_and_count: str):
    """
    Record old/historical vouches for a user without needing the original messages.
    Usage: ?addvouch @user <event> [count]
    Examples:
      ?addvouch @user Elder
      ?addvouch @user Hellmode 3
    Requires Manage Server permission.
    """
    parts = event_and_count.strip().rsplit(" ", 1)
    count = 1
    event_text = event_and_count.strip()

    # Check if the last word is a number (a count was provided)
    if len(parts) == 2 and parts[1].isdigit():
        event_text = parts[0]
        count = int(parts[1])

    event_name = parse_event(event_text)
    if event_name is None:
        valid_list = ", ".join(ALL_EVENTS)
        await ctx.send(
            f"⚠️ Couldn't recognize event type `{event_text}`. Valid events: {valid_list}"
        )
        return

    if count < 1:
        await ctx.send("⚠️ Count must be at least 1.")
        return

    points = EVENT_POINTS[event_name]
    data = load_data()
    record = get_user_record(data, member.id)
    record["total_points"] += points * count
    record["total_vouches"] += count
    record["events"][event_name] += count
    record["log"].append({
        "by": ctx.author.id,
        "by_name": str(ctx.author),
        "event": event_name,
        "points": points * count,
        "count": count,
        "backfilled": True,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    save_data(data)

    await ctx.send(
        f"✅ Backfilled **{count}x {event_name}** for {member.display_name} "
        f"(+{points * count} pts, new total: {record['total_points']} pts)"
    )


@addvouch.error
async def addvouch_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to backfill vouches.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("⚠️ Couldn't find that member.")
    else:
        await ctx.send(f"⚠️ Usage: `?addvouch @user <event> [count]`")


@bot.command(name="syncvouches", aliases=["scanhistory"])
@commands.has_permissions(manage_guild=True)
async def syncvouches(ctx):
    """
    Scan the vouch channel's full message history and rebuild vouch data
    from every valid 'vouch @user(s) <event>' message ever sent.
    This OVERWRITES current data with what's found in the channel history.
    Requires Manage Server permission.
    """
    channel = ctx.guild.get_channel(VOUCH_CHANNEL_ID) if VOUCH_CHANNEL_ID else ctx.channel
    if channel is None:
        await ctx.send("⚠️ Couldn't find the configured vouch channel.")
        return

    status = await ctx.send(f"🔄 Scanning #{channel.name} for past vouches... this may take a bit.")

    new_data = {}
    scanned = 0
    recorded = 0

    async for msg in channel.history(limit=None, oldest_first=True):
        scanned += 1
        if msg.author.bot:
            continue

        match = VOUCH_PATTERN.match(msg.content)
        if not match:
            continue

        mentions_block = match.group(1)
        event_text = match.group(2)
        target_ids = [int(uid) for uid in MENTION_PATTERN.findall(mentions_block)]

        event_name = parse_event(event_text)
        if event_name is None:
            continue

        valid_targets = [uid for uid in target_ids if uid != msg.author.id]
        if not valid_targets:
            continue

        points = EVENT_POINTS[event_name]

        for target_id in valid_targets:
            record = get_user_record(new_data, target_id)
            record["total_points"] += points
            record["total_vouches"] += 1
            record["events"][event_name] += 1
            record["log"].append({
                "by": msg.author.id,
                "by_name": str(msg.author),
                "event": event_name,
                "points": points,
                "time": msg.created_at.replace(tzinfo=timezone.utc).isoformat(),
                "message_id": msg.id,
            })
            recorded += 1

    save_data(new_data)

    await status.edit(
        content=(
            f"✅ Sync complete. Scanned {scanned} messages, "
            f"found {recorded} valid vouches across {len(new_data)} users."
        )
    )


@syncvouches.error
async def syncvouches_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to sync vouch history.")
    else:
        await ctx.send(f"⚠️ Sync failed: {error}")


@bot.command(name="leaderboard")
async def leaderboard(ctx, top_n: int = 10):
    """Show the top vouched users by points. Usage: !leaderboard [n]"""
    data = load_data()
    if not data:
        await ctx.send("No vouches recorded yet.")
        return

    ranked = sorted(data.items(), key=lambda kv: kv[1]["total_points"], reverse=True)[:top_n]

    lines = []
    for i, (uid, record) in enumerate(ranked, start=1):
        member = ctx.guild.get_member(int(uid)) if ctx.guild else None
        name = member.display_name if member else f"<@{uid}>"
        lines.append(f"{i}. {name} — {record['total_points']} pts ({record['total_vouches']} vouches)")

    await ctx.send("**🏆 Vouch Leaderboard**\n" + "\n".join(lines))


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "No token found. Set the DISCORD_TOKEN environment variable before running."
        )
    bot.run(TOKEN)
