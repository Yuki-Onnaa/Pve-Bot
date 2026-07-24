import json
import os
import re
from datetime import datetime, timezone

import discord
from discord.ext import commands

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_TOKEN")

# Where vouch data is stored. On Railway, mount a Volume and point this at it
# (e.g. "/data/vouches.json") so data survives redeploys.
DATA_FILE = os.environ.get("DATA_FILE", "/data/vouches.json")

# Each vouch category watches its own channel
PVE_CHANNEL_ID = 1529113596657799178
SECURITY_CHANNEL_ID = 1527834552150659103
SUPPORT_CHANNEL_ID = 1527834504658550924

CHANNEL_CATEGORY = {
    PVE_CHANNEL_ID: "pve",
    SECURITY_CHANNEL_ID: "security",
    SUPPORT_CHANNEL_ID: "support",
}

# ── PVE events (format: "vouch @user <event>") ──
PVE_EVENTS = {
    "Enmity": {"points": 1.5, "cooldown": 0},
    "Elder": {"points": 2, "cooldown": 0},
    "Titus": {"points": 3, "cooldown": 0},
    "Hellmode": {"points": 15, "cooldown": 0},
    "Deep Champion": {"points": 15, "cooldown": 0},
    "Diluvian W (25)": {"points": 3, "cooldown": 0},
    "Diluvian W (50)": {"points": 10, "cooldown": 0},
    "Parasol": {"points": 5, "cooldown": 0},
    "Layer 2 (1)": {"points": 3, "cooldown": 0},
    "Layer 2 (2)": {"points": 7, "cooldown": 0},
    "Other Bosses": {"points": 1, "cooldown": 0},
}

PVE_ALIASES = {
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

# ── Security events (format: "<event> @user", 1hr cooldown unless noted) ──
SECURITY_EVENTS = {
    "Security Vouch": {"points": 1, "cooldown": 3600},
    "Depths Vouch": {"points": 1.5, "cooldown": 3600},
    "Defense Vouch": {"points": 1, "cooldown": 0},
    "Depths Defense Vouch": {"points": 1.5, "cooldown": 0},
}

# ── Support events (format: "<event> @user", 1hr cooldown) ──
SUPPORT_EVENTS = {
    "Support Vouch": {"points": 1, "cooldown": 3600},
    "Backup Vouch": {"points": 2, "cooldown": 3600},
    "Depths Safe Vouch": {"points": 5, "cooldown": 3600},
}

CATEGORY_EVENTS = {
    "pve": PVE_EVENTS,
    "security": SECURITY_EVENTS,
    "support": SUPPORT_EVENTS,
}

# Phrase -> (category, canonical event name), for the "<event> @user" style commands
PHRASE_ALIASES = {
    "security vouch": ("security", "Security Vouch"),
    "depths vouch": ("security", "Depths Vouch"),
    "defense vouch": ("security", "Defense Vouch"),
    "depths defense vouch": ("security", "Depths Defense Vouch"),
    "support vouch": ("support", "Support Vouch"),
    "backup vouch": ("support", "Backup Vouch"),
    "depths safe vouch": ("support", "Depths Safe Vouch"),
}
# Sort longest-phrase-first so "depths defense vouch" matches before "depths vouch"
_SORTED_PHRASES = sorted(PHRASE_ALIASES.keys(), key=len, reverse=True)
_PHRASE_PATTERN = "|".join(re.escape(p) for p in _SORTED_PHRASES)
PHRASE_VOUCH_PATTERN = re.compile(
    rf"^\s*({_PHRASE_PATTERN})\s+((?:<@!?\d+>\s*)+)$", re.IGNORECASE
)

PVE_VOUCH_PATTERN = re.compile(r"^\s*vouch\s+((?:<@!?\d+>\s*)+)(.+)$", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"<@!?(\d+)>")

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


def get_user_record(data, user_id, category):
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    if category not in data[uid]:
        data[uid][category] = {
            "total_points": 0,
            "total_vouches": 0,
            "events": {e: 0 for e in CATEGORY_EVENTS[category]},
            "cooldowns": {},
            "log": [],
        }
    # Backfill any newly added event keys
    for e in CATEGORY_EVENTS[category]:
        data[uid][category]["events"].setdefault(e, 0)
    return data[uid][category]


def combined_total(user_data):
    return sum(user_data.get(cat, {}).get("total_points", 0) for cat in CATEGORY_EVENTS)


# ─────────────────────────────────────────────────────────────
# PARSING HELPERS
# ─────────────────────────────────────────────────────────────

def normalize(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def parse_pve_event(text):
    return PVE_ALIASES.get(normalize(text))


# ─────────────────────────────────────────────────────────────
# CORE VOUCH RECORDING (shared by live messages + sync + backfill)
# ─────────────────────────────────────────────────────────────

def record_vouch(data, target_ids, author_id, category, event_name, when=None):
    """
    Records a vouch for each target (skipping the author and anyone on cooldown).
    Returns (recorded_count, cooldown_count, self_dropped_count).
    """
    when = when or datetime.now(timezone.utc)
    cfg = CATEGORY_EVENTS[category][event_name]
    points = cfg["points"]
    cooldown = cfg["cooldown"]

    valid_targets = [uid for uid in target_ids if uid != author_id]
    self_dropped = len(target_ids) - len(valid_targets)

    recorded = 0
    cooldown_hit = 0

    for target_id in valid_targets:
        record = get_user_record(data, target_id, category)

        if cooldown > 0:
            last = record["cooldowns"].get(event_name)
            if last:
                last_dt = datetime.fromisoformat(last)
                if (when - last_dt).total_seconds() < cooldown:
                    cooldown_hit += 1
                    continue

        record["total_points"] += points
        record["total_vouches"] += 1
        record["events"][event_name] += 1
        record["cooldowns"][event_name] = when.isoformat()
        record["log"].append({
            "by": author_id,
            "event": event_name,
            "points": points,
            "time": when.isoformat(),
        })
        recorded += 1

    return recorded, cooldown_hit, self_dropped


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
    if message.author.bot:
        return

    category = CHANNEL_CATEGORY.get(message.channel.id)
    if category is None:
        await bot.process_commands(message)
        return

    data = load_data()
    recorded = cooldown_hit = self_dropped = 0
    handled = False

    if category == "pve":
        match = PVE_VOUCH_PATTERN.match(message.content)
        if match:
            handled = True
            mentions_block = match.group(1)
            event_text = match.group(2)
            target_ids = [int(uid) for uid in MENTION_PATTERN.findall(mentions_block)]
            event_name = parse_pve_event(event_text)
            if event_name is None:
                await message.add_reaction("❌")
                return
            recorded, cooldown_hit, self_dropped = record_vouch(
                data, target_ids, message.author.id, "pve", event_name
            )
    else:
        match = PHRASE_VOUCH_PATTERN.match(message.content)
        if match:
            handled = True
            phrase = normalize(match.group(1))
            mentions_block = match.group(2)
            evt_category, event_name = PHRASE_ALIASES[phrase]
            target_ids = [int(uid) for uid in MENTION_PATTERN.findall(mentions_block)]
            recorded, cooldown_hit, self_dropped = record_vouch(
                data, target_ids, message.author.id, evt_category, event_name
            )

    if handled:
        save_data(data)
        if self_dropped and recorded == 0 and cooldown_hit == 0:
            await message.add_reaction("🚫")
            return
        if self_dropped:
            await message.add_reaction("🚫")
        if cooldown_hit:
            await message.add_reaction("⏳")
        if recorded:
            await message.add_reaction("✅")
        return

    await bot.process_commands(message)


# ─────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────

CATEGORY_NAMES = {"pve": "PVE", "security": "Security", "support": "Support"}


@bot.command(name="vouches")
async def vouches(ctx, member: discord.Member = None, category: str = None):
    """Usage: ?vouches @user [pve|security|support]"""
    member = member or ctx.author
    data = load_data()
    user_data = data.get(str(member.id), {})

    if category:
        category = category.lower()
        if category not in CATEGORY_EVENTS:
            await ctx.send("⚠️ Category must be one of: pve, security, support")
            return
        record = user_data.get(category)
        if not record or record["total_vouches"] == 0:
            await ctx.send(f"{member.display_name} has no {CATEGORY_NAMES[category]} vouches yet.")
            return
        lines = [
            f"  {e}: {c} × {CATEGORY_EVENTS[category][e]['points']} = {c * CATEGORY_EVENTS[category][e]['points']} pts"
            for e, c in record["events"].items() if c
        ]
        await ctx.send(
            f"**{member.display_name}** — {CATEGORY_NAMES[category]}\n"
            f"Total: {record['total_points']} pts across {record['total_vouches']} vouches\n"
            + "\n".join(lines)
        )
        return

    # No category given: show summary across all three
    total = combined_total(user_data)
    if total == 0:
        await ctx.send(f"{member.display_name} has no vouches yet.")
        return

    lines = [f"**{member.display_name}** — {total} pts total\n"]
    for cat in CATEGORY_EVENTS:
        record = user_data.get(cat)
        if record and record["total_vouches"]:
            lines.append(f"**{CATEGORY_NAMES[cat]}**: {record['total_points']} pts ({record['total_vouches']} vouches)")
    await ctx.send("\n".join(lines))


@bot.command(name="leaderboard")
async def leaderboard(ctx, *args):
    """Usage: ?leaderboard [pve|security|support] [n]"""
    category = None
    top_n = 10
    for a in args:
        if a.lower() in CATEGORY_EVENTS:
            category = a.lower()
        elif a.isdigit():
            top_n = int(a)

    data = load_data()
    if not data:
        await ctx.send("No vouches recorded yet.")
        return

    if category:
        ranked = sorted(
            data.items(),
            key=lambda kv: kv[1].get(category, {}).get("total_points", 0),
            reverse=True,
        )
        ranked = [(uid, rec) for uid, rec in ranked if rec.get(category, {}).get("total_points", 0) > 0][:top_n]
        title = f"🏆 {CATEGORY_NAMES[category]} Leaderboard"
        lines = []
        for i, (uid, rec) in enumerate(ranked, start=1):
            member = ctx.guild.get_member(int(uid)) if ctx.guild else None
            name = member.display_name if member else f"<@{uid}>"
            pts = rec.get(category, {}).get("total_points", 0)
            n = rec.get(category, {}).get("total_vouches", 0)
            lines.append(f"{i}. {name} — {pts} pts ({n} vouches)")
    else:
        ranked = sorted(data.items(), key=lambda kv: combined_total(kv[1]), reverse=True)
        ranked = [(uid, rec) for uid, rec in ranked if combined_total(rec) > 0][:top_n]
        title = "🏆 Overall Vouch Leaderboard"
        lines = []
        for i, (uid, rec) in enumerate(ranked, start=1):
            member = ctx.guild.get_member(int(uid)) if ctx.guild else None
            name = member.display_name if member else f"<@{uid}>"
            lines.append(f"{i}. {name} — {combined_total(rec)} pts")

    if not lines:
        await ctx.send("No vouches recorded yet.")
        return
    await ctx.send(f"**{title}**\n" + "\n".join(lines))


@bot.command(name="addvouch", aliases=["backfill"])
@commands.has_permissions(manage_guild=True)
async def addvouch(ctx, category: str, member: discord.Member, *, event_and_count: str):
    """
    Manually record old vouches. Usage: ?addvouch <pve|security|support> @user <event> [count]
    Example: ?addvouch security "Security Vouch" 3
    """
    category = category.lower()
    if category not in CATEGORY_EVENTS:
        await ctx.send("⚠️ Category must be one of: pve, security, support")
        return

    parts = event_and_count.strip().rsplit(" ", 1)
    count = 1
    event_text = event_and_count.strip()
    if len(parts) == 2 and parts[1].isdigit():
        event_text = parts[0]
        count = int(parts[1])

    if category == "pve":
        event_name = parse_pve_event(event_text)
    else:
        match_name = normalize(event_text)
        event_name = None
        for canonical in CATEGORY_EVENTS[category]:
            if normalize(canonical) == match_name:
                event_name = canonical
                break

    if event_name is None:
        valid_list = ", ".join(CATEGORY_EVENTS[category].keys())
        await ctx.send(f"⚠️ Couldn't recognize event `{event_text}`. Valid: {valid_list}")
        return

    if count < 1:
        await ctx.send("⚠️ Count must be at least 1.")
        return

    points = CATEGORY_EVENTS[category][event_name]["points"]
    data = load_data()
    record = get_user_record(data, member.id, category)
    record["total_points"] += points * count
    record["total_vouches"] += count
    record["events"][event_name] += count
    record["log"].append({
        "by": ctx.author.id, "event": event_name, "points": points * count,
        "count": count, "backfilled": True,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    save_data(data)

    await ctx.send(
        f"✅ Backfilled **{count}x {event_name}** ({CATEGORY_NAMES[category]}) for {member.display_name} "
        f"(+{points * count} pts, new total: {record['total_points']} pts)"
    )


@addvouch.error
async def addvouch_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to backfill vouches.")
    else:
        await ctx.send("⚠️ Usage: `?addvouch <pve|security|support> @user <event> [count]`")


@bot.command(name="syncvouches", aliases=["scanhistory"])
@commands.has_permissions(manage_guild=True)
async def syncvouches(ctx):
    """Scan all three vouch channels' full history and rebuild all vouch data."""
    channels = {
        "pve": ctx.guild.get_channel(PVE_CHANNEL_ID),
        "security": ctx.guild.get_channel(SECURITY_CHANNEL_ID),
        "support": ctx.guild.get_channel(SUPPORT_CHANNEL_ID),
    }

    status = await ctx.send("🔄 Scanning all vouch channels for history... this may take a bit.")

    new_data = {}
    scanned = 0
    recorded_total = 0

    for cat, channel in channels.items():
        if channel is None:
            continue
        async for msg in channel.history(limit=None, oldest_first=True):
            scanned += 1
            if msg.author.bot:
                continue

            when = msg.created_at.replace(tzinfo=timezone.utc)

            if cat == "pve":
                match = PVE_VOUCH_PATTERN.match(msg.content)
                if not match:
                    continue
                target_ids = [int(uid) for uid in MENTION_PATTERN.findall(match.group(1))]
                event_name = parse_pve_event(match.group(2))
                if event_name is None:
                    continue
                r, _, _ = record_vouch(new_data, target_ids, msg.author.id, "pve", event_name, when)
                recorded_total += r
            else:
                match = PHRASE_VOUCH_PATTERN.match(msg.content)
                if not match:
                    continue
                phrase = normalize(match.group(1))
                evt_category, event_name = PHRASE_ALIASES[phrase]
                target_ids = [int(uid) for uid in MENTION_PATTERN.findall(match.group(2))]
                r, _, _ = record_vouch(new_data, target_ids, msg.author.id, evt_category, event_name, when)
                recorded_total += r

    save_data(new_data)
    await status.edit(
        content=f"✅ Sync complete. Scanned {scanned} messages, recorded {recorded_total} vouches across {len(new_data)} users."
    )


@syncvouches.error
async def syncvouches_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to sync vouch history.")
    else:
        await ctx.send(f"⚠️ Sync failed: {error}")


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("No token found. Set the DISCORD_TOKEN environment variable before running.")
    bot.run(TOKEN)
