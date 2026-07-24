import json
import os
import re
import uuid
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

# Channel where the 3 live, auto-updating leaderboards get posted
LIVE_LEADERBOARD_CHANNEL_ID = 1530286316628217906

# Channel where every vouch / backfill / sync gets logged
AUDIT_LOG_CHANNEL_ID = 1530317395669815438

CHANNEL_CATEGORY = {
    PVE_CHANNEL_ID: "pve",
    SECURITY_CHANNEL_ID: "security",
    SUPPORT_CHANNEL_ID: "support",
}

CATEGORY_NAMES = {"pve": "Host", "security": "Security", "support": "Support"}

# ── PVE / Host events (format: "vouch @user <event>") ──
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

# ── Role ladders (ascending by threshold). Role names must match exactly
#    the roles already created in your Discord server. ──
ROLE_THRESHOLDS = {
    "pve": [
        (0, "Apprentice Hoster"),
        (150, "Skilled Hoster"),
        (350, "Master Hoster"),
        (750, "Divine Hoster"),
        (1250, "Godlike Hoster"),
        (2000, "True Hoster"),
        (3500, "No Life Hoster"),
        (5000, "Absolute Being"),
    ],
    "support": [
        (0, "Guardian Link"),
        (15, "Vigor Warden"),
        (45, "Soul Reliefer"),
        (100, "Graceful Commander"),
        (200, "Hero Of Events"),
    ],
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
    for e in CATEGORY_EVENTS[category]:
        data[uid][category]["events"].setdefault(e, 0)
    return data[uid][category]


def combined_total(user_data):
    return sum(user_data.get(cat, {}).get("total_points", 0) for cat in CATEGORY_EVENTS)


def user_records(data):
    """Yield only real user records, skipping internal bookkeeping keys."""
    for uid, rec in data.items():
        if uid.isdigit():
            yield uid, rec


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
    Returns (recorded_target_ids, cooldown_target_ids, self_dropped_count).
    """
    when = when or datetime.now(timezone.utc)
    cfg = CATEGORY_EVENTS[category][event_name]
    points = cfg["points"]
    cooldown = cfg["cooldown"]

    valid_targets = [uid for uid in target_ids if uid != author_id]
    self_dropped = len(target_ids) - len(valid_targets)

    recorded_ids = []
    cooldown_ids = []

    for target_id in valid_targets:
        record = get_user_record(data, target_id, category)

        if cooldown > 0:
            last = record["cooldowns"].get(event_name)
            if last:
                last_dt = datetime.fromisoformat(last)
                if (when - last_dt).total_seconds() < cooldown:
                    cooldown_ids.append(target_id)
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
        recorded_ids.append(target_id)

    return recorded_ids, cooldown_ids, self_dropped


# ─────────────────────────────────────────────────────────────
# LIVE LEADERBOARDS
# ─────────────────────────────────────────────────────────────

def build_leaderboard_lines(data, category, n=10):
    ranked = sorted(
        user_records(data),
        key=lambda kv: kv[1].get(category, {}).get("total_points", 0),
        reverse=True,
    )
    ranked = [(uid, rec) for uid, rec in ranked if rec.get(category, {}).get("total_points", 0) > 0][:n]
    lines = []
    for i, (uid, rec) in enumerate(ranked, start=1):
        pts = rec[category]["total_points"]
        cnt = rec[category]["total_vouches"]
        lines.append(f"**{i}.** <@{uid}> — {pts} pts ({cnt} vouches)")
    return lines


async def refresh_live_leaderboards():
    channel = bot.get_channel(LIVE_LEADERBOARD_CHANNEL_ID)
    if channel is None:
        return

    data = load_data()
    meta = data.get("_live_messages", {})
    changed = False

    for cat in CATEGORY_EVENTS:
        lines = build_leaderboard_lines(data, cat, 10)
        embed = discord.Embed(
            title=f"🏆 {CATEGORY_NAMES[cat]} Leaderboard",
            description="\n".join(lines) if lines else "No vouches yet.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

        msg_id = meta.get(cat)
        msg = None
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                msg = None

        if msg:
            try:
                await msg.edit(embed=embed)
            except discord.HTTPException:
                msg = None

        if not msg:
            new_msg = await channel.send(embed=embed)
            meta[cat] = new_msg.id
            changed = True

    if changed:
        data["_live_messages"] = meta
        save_data(data)


# ─────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────

async def log_audit(text):
    channel = bot.get_channel(AUDIT_LOG_CHANNEL_ID)
    if channel is None:
        return
    try:
        await channel.send(text)
    except discord.HTTPException:
        pass


# ─────────────────────────────────────────────────────────────
# ROLE LADDER
# ─────────────────────────────────────────────────────────────

async def update_role_for_user(guild, user_id, category):
    """Assigns the correct rank role for a user in a category with a role ladder."""
    if guild is None or category not in ROLE_THRESHOLDS:
        return

    data = load_data()
    record = data.get(str(user_id), {}).get(category)
    points = record["total_points"] if record else 0

    thresholds = ROLE_THRESHOLDS[category]
    achieved_role_name = thresholds[0][1]
    for threshold, role_name in thresholds:
        if points >= threshold:
            achieved_role_name = role_name

    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return
        except discord.HTTPException:
            return

    category_role_names = {name for _, name in thresholds}
    roles_to_remove = [r for r in member.roles if r.name in category_role_names and r.name != achieved_role_name]
    role_to_add = discord.utils.get(guild.roles, name=achieved_role_name)

    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Vouch rank update")
        if role_to_add and role_to_add not in member.roles:
            await member.add_roles(role_to_add, reason="Vouch rank update")
    except discord.Forbidden:
        await log_audit(
            f"⚠️ Couldn't update rank role for <@{user_id}> — check the bot's role is above "
            f"the `{achieved_role_name}` role and has Manage Roles permission."
        )
    except discord.HTTPException:
        pass


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
    await refresh_live_leaderboards()


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    category = CHANNEL_CATEGORY.get(message.channel.id)
    if category is None:
        await bot.process_commands(message)
        return

    data = load_data()
    recorded_ids, cooldown_ids, self_dropped = [], [], 0
    handled = False
    event_name = None

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
            recorded_ids, cooldown_ids, self_dropped = record_vouch(
                data, target_ids, message.author.id, "pve", event_name
            )
    else:
        match = PHRASE_VOUCH_PATTERN.match(message.content)
        if match:
            handled = True
            phrase = normalize(match.group(1))
            mentions_block = match.group(2)
            category, event_name = PHRASE_ALIASES[phrase]
            target_ids = [int(uid) for uid in MENTION_PATTERN.findall(mentions_block)]
            recorded_ids, cooldown_ids, self_dropped = record_vouch(
                data, target_ids, message.author.id, category, event_name
            )

    if handled:
        save_data(data)

        if self_dropped and not recorded_ids and not cooldown_ids:
            await message.add_reaction("🚫")
            return
        if self_dropped:
            await message.add_reaction("🚫")
        if cooldown_ids:
            await message.add_reaction("⏳")

        if recorded_ids:
            await message.add_reaction("✅")
            points = CATEGORY_EVENTS[category][event_name]["points"]
            targets_str = " ".join(f"<@{t}>" for t in recorded_ids)
            await log_audit(
                f"✅ **{CATEGORY_NAMES[category]} — {event_name}** (+{points} pts each)\n"
                f"By: <@{message.author.id}> → {targets_str}"
            )
            await refresh_live_leaderboards()
            for target_id in recorded_ids:
                await update_role_for_user(message.guild, target_id, category)
        return

    await bot.process_commands(message)


# ─────────────────────────────────────────────────────────────
# RANK PROGRESS HELPERS
# ─────────────────────────────────────────────────────────────

def get_rank_progress(points, thresholds):
    """Returns (current_role, current_threshold, next_role, next_threshold)."""
    current_role, current_threshold = thresholds[0][1], thresholds[0][0]
    next_role, next_threshold = None, None
    for i, (threshold, role_name) in enumerate(thresholds):
        if points >= threshold:
            current_role, current_threshold = role_name, threshold
            if i + 1 < len(thresholds):
                next_threshold, next_role = thresholds[i + 1]
            else:
                next_threshold, next_role = None, None
        else:
            break
    return current_role, current_threshold, next_role, next_threshold


def progress_bar(points, current_threshold, next_threshold, length=10):
    if next_threshold is None:
        return "█" * length
    span = next_threshold - current_threshold
    progressed = points - current_threshold
    frac = max(0, min(1, progressed / span)) if span > 0 else 1
    filled = round(frac * length)
    return "█" * filled + "░" * (length - filled)


# ─────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────

async def send_leaderboard(ctx, category, top_n=10):
    data = load_data()
    ranked = sorted(
        user_records(data),
        key=lambda kv: kv[1].get(category, {}).get("total_points", 0),
        reverse=True,
    )
    ranked = [(uid, rec) for uid, rec in ranked if rec.get(category, {}).get("total_points", 0) > 0][:top_n]

    if not ranked:
        await ctx.send(f"No {CATEGORY_NAMES[category]} vouches recorded yet.")
        return

    lines = []
    for i, (uid, rec) in enumerate(ranked, start=1):
        member = ctx.guild.get_member(int(uid)) if ctx.guild else None
        name = member.display_name if member else f"<@{uid}>"
        pts = rec[category]["total_points"]
        cnt = rec[category]["total_vouches"]
        lines.append(f"{i}. {name} — {pts} pts ({cnt} vouches)")

    await ctx.send(f"**🏆 {CATEGORY_NAMES[category]} Leaderboard**\n" + "\n".join(lines))


def make_progress_bar(current, low, high, length=10):
    if high <= low:
        filled = length
    else:
        frac = max(0, min(1, (current - low) / (high - low)))
        filled = round(frac * length)
    return "▰" * filled + "▱" * (length - filled)


@bot.command(name="profile")
async def profile(ctx, member: discord.Member = None):
    """Shows a combined profile card: rank, points, and progress to next rank. Usage: ?profile [@user]"""
    member = member or ctx.author
    data = load_data()
    user_data = data.get(str(member.id), {})

    embed = discord.Embed(title=f"{member.display_name}'s Vouch Profile", color=discord.Color.gold())
    embed.set_thumbnail(url=member.display_avatar.url)

    for cat in CATEGORY_EVENTS:
        record = user_data.get(cat)
        points = record["total_points"] if record else 0
        vouch_count = record["total_vouches"] if record else 0

        if cat in ROLE_THRESHOLDS:
            thresholds = ROLE_THRESHOLDS[cat]
            achieved_idx = 0
            for i, (thresh, _) in enumerate(thresholds):
                if points >= thresh:
                    achieved_idx = i
            current_role = thresholds[achieved_idx][1]

            if achieved_idx + 1 < len(thresholds):
                low = thresholds[achieved_idx][0]
                next_thresh, next_role = thresholds[achieved_idx + 1]
                bar = make_progress_bar(points, low, next_thresh)
                remaining = next_thresh - points
                value = (
                    f"**{current_role}**\n"
                    f"{points} pts ({vouch_count} vouches)\n"
                    f"{bar}\n"
                    f"{remaining} pts to **{next_role}**"
                )
            else:
                value = f"**{current_role}** 👑 (max rank)\n{points} pts ({vouch_count} vouches)"
        else:
            value = f"{points} pts ({vouch_count} vouches)"

        embed.add_field(name=CATEGORY_NAMES[cat], value=value, inline=False)

    total = combined_total(user_data)
    embed.set_footer(text=f"{total} pts combined across all categories")

    await ctx.send(embed=embed)


@bot.command(name="profile")
async def profile(ctx, member: discord.Member = None):
    """Shows a combined profile card with points, rank, and progress to next rank. Usage: ?profile [@user]"""
    member = member or ctx.author
    data = load_data()
    user_data = data.get(str(member.id), {})

    total = combined_total(user_data)
    embed = discord.Embed(
        title=f"{member.display_name}'s Vouch Profile",
        description=f"**{total} total points**",
        color=discord.Color.gold(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    for cat in CATEGORY_EVENTS:
        record = user_data.get(cat, {})
        pts = record.get("total_points", 0)
        cnt = record.get("total_vouches", 0)

        if cat in ROLE_THRESHOLDS:
            thresholds = ROLE_THRESHOLDS[cat]
            current_role, current_threshold, next_role, next_threshold = get_rank_progress(pts, thresholds)
            bar = progress_bar(pts, current_threshold, next_threshold)
            if next_role:
                remaining = next_threshold - pts
                progress_line = f"{bar}\n{pts}/{next_threshold} pts — {remaining} to **{next_role}**"
            else:
                progress_line = f"{bar}\nMax rank reached! 🎉"
            value = f"**Rank:** {current_role}\n**Points:** {pts} ({cnt} vouches)\n{progress_line}"
        else:
            value = f"**Points:** {pts} ({cnt} vouches)"

        embed.add_field(name=CATEGORY_NAMES[cat], value=value, inline=False)

    await ctx.send(embed=embed)


@bot.command(name="leaderboard")
async def leaderboard(ctx, top_n: int = 10):
    """Host/PVE leaderboard. Usage: ?leaderboard [n]"""
    await send_leaderboard(ctx, "pve", top_n)


@bot.command(name="sleaderboard")
async def sleaderboard(ctx, top_n: int = 10):
    """Security leaderboard. Usage: ?sleaderboard [n]"""
    await send_leaderboard(ctx, "security", top_n)


@bot.command(name="suleaderboard")
async def suleaderboard(ctx, top_n: int = 10):
    """Support leaderboard. Usage: ?suleaderboard [n]"""
    await send_leaderboard(ctx, "support", top_n)


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


@bot.command(name="addvouch", aliases=["backfill"])
@commands.has_permissions(manage_guild=True)
async def addvouch(ctx, category: str, member: discord.Member, *, event_and_count: str):
    """Usage: ?addvouch <pve|security|support> @user <event> [count]"""
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
        "id": uuid.uuid4().hex[:8],
        "by": ctx.author.id, "event": event_name, "points": points * count,
        "count": count, "backfilled": True,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    save_data(data)
    await refresh_live_leaderboards()
    await update_role_for_user(ctx.guild, member.id, category)

    await log_audit(
        f"🛠️ **Backfill** — {count}x {event_name} ({CATEGORY_NAMES[category]}) for <@{member.id}> "
        f"(+{points * count} pts) by <@{ctx.author.id}>"
    )

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


@bot.command(name="backfillhistory")
@commands.has_permissions(manage_guild=True)
async def backfillhistory(ctx, category: str, member: discord.Member):
    """List recent backfills for a user so you can find the ID to revert. Usage: ?backfillhistory <pve|security|support> @user"""
    category = category.lower()
    if category not in CATEGORY_EVENTS:
        await ctx.send("⚠️ Category must be one of: pve, security, support")
        return

    data = load_data()
    record = data.get(str(member.id), {}).get(category)
    entries = [e for e in (record["log"] if record else []) if e.get("backfilled")]

    if not entries:
        await ctx.send(f"{member.display_name} has no {CATEGORY_NAMES[category]} backfill entries.")
        return

    lines = []
    for idx, e in list(enumerate(record["log"]))[-15:][::-1]:
        if not e.get("backfilled"):
            continue
        ref = e.get("id") or f"idx{idx}"
        ts = e["time"][:16].replace("T", " ")
        lines.append(f"`{ref}` — {e.get('count', 1)}x {e['event']} (+{e['points']} pts) by <@{e['by']}> · {ts}")

    if not lines:
        await ctx.send(f"{member.display_name} has no {CATEGORY_NAMES[category]} backfill entries.")
        return

    await ctx.send(
        f"**Recent {CATEGORY_NAMES[category]} backfills for {member.display_name}**\n" + "\n".join(lines)
    )


@backfillhistory.error
async def backfillhistory_error(ctx, error):
    await ctx.send("⚠️ Usage: `?backfillhistory <pve|security|support> @user`")


@bot.command(name="revertbackfill", aliases=["undobackfill"])
@commands.has_permissions(manage_guild=True)
async def revertbackfill(ctx, category: str, member: discord.Member, log_id: str = None):
    """
    Undo a backfilled vouch. Usage: ?revertbackfill <pve|security|support> @user [log_id]
    Omit log_id to revert the most recent backfill for that user/category.
    Use ?backfillhistory to look up log IDs.
    """
    category = category.lower()
    if category not in CATEGORY_EVENTS:
        await ctx.send("⚠️ Category must be one of: pve, security, support")
        return

    data = load_data()
    record = data.get(str(member.id), {}).get(category)
    if not record or not record["log"]:
        await ctx.send(f"{member.display_name} has no {CATEGORY_NAMES[category]} vouch history to revert.")
        return

    entry = None
    entry_index = None

    if log_id:
        for i, e in enumerate(record["log"]):
            ref = e.get("id") or f"idx{i}"
            if ref == log_id:
                entry = e
                entry_index = i
                break
        if entry is None:
            await ctx.send(f"⚠️ Couldn't find a log entry with id `{log_id}` for {member.display_name}.")
            return
        if not entry.get("backfilled"):
            await ctx.send("⚠️ That entry wasn't a backfill — only backfilled entries can be reverted with this command.")
            return
    else:
        for i in range(len(record["log"]) - 1, -1, -1):
            if record["log"][i].get("backfilled"):
                entry = record["log"][i]
                entry_index = i
                break
        if entry is None:
            await ctx.send(f"⚠️ {member.display_name} has no backfilled entries to revert.")
            return

    points = entry["points"]
    count = entry.get("count", 1)
    event_name = entry["event"]

    record["total_points"] -= points
    record["total_vouches"] -= count
    record["events"][event_name] = max(0, record["events"].get(event_name, 0) - count)
    del record["log"][entry_index]

    save_data(data)
    await refresh_live_leaderboards()
    await update_role_for_user(ctx.guild, member.id, category)

    await log_audit(
        f"↩️ **Reverted backfill** — {count}x {event_name} ({CATEGORY_NAMES[category]}) for <@{member.id}> "
        f"(-{points} pts) by <@{ctx.author.id}>"
    )

    await ctx.send(
        f"✅ Reverted **{count}x {event_name}** ({CATEGORY_NAMES[category]}) for {member.display_name} "
        f"(-{points} pts, new total: {record['total_points']} pts)"
    )


@revertbackfill.error
async def revertbackfill_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to revert backfills.")
    else:
        await ctx.send("⚠️ Usage: `?revertbackfill <pve|security|support> @user [log_id]`")


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
                recorded_ids, _, _ = record_vouch(new_data, target_ids, msg.author.id, "pve", event_name, when)
                recorded_total += len(recorded_ids)
            else:
                match = PHRASE_VOUCH_PATTERN.match(msg.content)
                if not match:
                    continue
                phrase = normalize(match.group(1))
                evt_category, event_name = PHRASE_ALIASES[phrase]
                target_ids = [int(uid) for uid in MENTION_PATTERN.findall(match.group(2))]
                recorded_ids, _, _ = record_vouch(new_data, target_ids, msg.author.id, evt_category, event_name, when)
                recorded_total += len(recorded_ids)

    save_data(new_data)
    await refresh_live_leaderboards()

    for uid, rec in new_data.items():
        if not uid.isdigit():
            continue
        for cat in ROLE_THRESHOLDS:
            if cat in rec:
                await update_role_for_user(ctx.guild, int(uid), cat)

    await log_audit(
        f"🔄 **Sync** — scanned {scanned} messages, recorded {recorded_total} vouches "
        f"across {len(new_data)} users, run by <@{ctx.author.id}>"
    )

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
