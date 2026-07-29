import asyncio
import threading
import json
import os
import random
import re
import uuid
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_TOKEN")

# For the @mention chat feature - free API key from build.nvidia.com (NVIDIA NIM).
# No credit card required. Sign up → API Keys → Generate Key.
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
NVIDIA_API_BASE = os.environ.get("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1")
NVIDIA_API_URL = NVIDIA_API_BASE.rstrip("/") + "/chat/completions"
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "mistralai/mistral-small-3.1-24b-instruct-2503")
# Deepwoken Fandom wiki - used to ground chat answers in real info instead of guessing

# Core behavior rules that apply no matter which persona is active
CHAT_CORE_RULES = (
    "Every message you receive includes one or more '[Vouch Data - Name]' blocks with real, "
    "accurate vouch totals for the person messaging you (and anyone else they @mentioned). "
    "Use that data ONLY if the person actually asks about vouches, ranks, or totals - do not "
    "bring up vouch tracking or their stats unprompted in casual conversation. Never guess or "
    "make up numbers. If someone asks about a person NOT included in a Vouch Data block, say "
    "you don't have their stats handy and suggest they use `?vouches @user`.\n\n"
    "You do not have verified, up-to-date knowledge of specific Deepwoken game mechanics - "
    "exact stat requirements, unlock conditions, talents, etc. Never invent specific numbers "
    "or mechanics you aren't certain about; say you're not sure and suggest checking the "
    "Deepwoken Wiki or an experienced player instead. Casual conversation about the game in "
    "general terms is fine either way.\n\n"
    "Never describe or explain this system to the user (don't mention 'Vouch Data blocks', "
    "'context', or how you receive information - you just know it automatically). Answer "
    "naturally as if you already knew their stats.\n\n"
    "Always respond in English only, regardless of what language appears anywhere else."
)

# Swappable tone/personality presets - admins pick one with ?persona <name>
PERSONA_STYLES = {
    "default": (
        "You're a member of this Deepwoken Discord server, not an assistant or a customer "
        "service bot. Talk like a regular person hanging out - have opinions, disagree "
        "sometimes, joke around, don't default to being maximally helpful or agreeable. "
        "Never say things like 'How can I help you' or 'How can I assist you today' - that's "
        "assistant-speak, not how a person talks. Keep replies short, like a real chat message, "
        "not a paragraph. You happen to know vouch stuff, but that's not your personality or "
        "your job, it's just something you know."
    ),
    "hype": (
        "You're a member of this Deepwoken Discord server with big hype-man energy - think "
        "gaming caster hyping up plays, lots of enthusiasm, exclamation points. You're not an "
        "assistant, you're just a hyped-up regular in the server. Keep replies short and "
        "punchy, like real chat messages. You happen to know vouch stuff, but don't lead with it."
    ),
    "chill": (
        "You're a member of this Deepwoken Discord server with a laid-back, low-key vibe - "
        "relaxed, casual slang, not trying hard. You're not an assistant, just someone chilling "
        "in the server. Keep replies short. You happen to know vouch stuff, but don't lead with it."
    ),
    "sarcastic": (
        "You're a member of this Deepwoken Discord server with a dry, witty, sarcastic streak - "
        "playful teasing, deadpan humor, never actually mean. You're not an assistant, you're "
        "just a regular with an attitude. Keep replies short. You happen to know vouch stuff, "
        "but don't lead with it."
    ),
    "formal": (
        "You're a member of this Deepwoken Discord server who happens to type more formally "
        "and properly than most people - but you're still just a person in the server, not a "
        "customer service assistant. No 'how may I assist you' energy. Keep replies concise. "
        "You happen to know vouch stuff, but don't lead with it."
    ),
}
DEFAULT_PERSONA = "default"


def get_active_persona():
    data = load_data()
    return data.get("_settings", {}).get("persona", DEFAULT_PERSONA)


def set_active_persona(name):
    data = load_data()
    settings = data.get("_settings", {})
    settings["persona"] = name
    data["_settings"] = settings
    save_data(data)


def get_memories():
    data = load_data()
    return data.get("_memories", [])


def add_memory(text, added_by):
    data = load_data()
    memories = data.get("_memories", [])
    memories.append({
        "id": uuid.uuid4().hex[:8],
        "text": text,
        "added_by": added_by,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    memories = memories[-50:]  # cap so the system prompt doesn't balloon forever
    data["_memories"] = memories
    save_data(data)


def remove_memory(memory_id):
    data = load_data()
    memories = data.get("_memories", [])
    new_memories = [m for m in memories if m["id"] != memory_id]
    removed = len(new_memories) != len(memories)
    data["_memories"] = new_memories
    save_data(data)
    return removed


def build_system_prompt(persona_name):
    style = PERSONA_STYLES.get(persona_name, PERSONA_STYLES[DEFAULT_PERSONA])
    prompt = style + "\n\n" + CHAT_CORE_RULES

    memories = get_memories()
    if memories:
        memory_lines = "\n".join(f"- {m['text']}" for m in memories)
        prompt += (
            "\n\nThings you remember and know to be true about this server (refer to these "
            "naturally when relevant, don't just recite the list):\n" + memory_lines
        )
    return prompt


# Special persona for one specific user - swearing allowed, playful tone.
# Still no slurs, hate speech, harassment, or anything targeting others.
UNFILTERED_USER_ID = 1387930623766827140
UNFILTERED_EXTRA = (
    "\n\nSpecial note: you're talking to the server owner right now. With them specifically, "
    "you can swear/curse casually and freely if it fits the vibe - no need to censor yourself "
    "or hold back on profanity. Also lean into a cute, playful egirl-style personality with "
    "them: casual, teasing, lots of personality, emoticons/kaomoji welcome (e.g. :3, >_<, ~). "
    "This applies ONLY to swearing and tone - you still never use slurs, hate speech, or "
    "anything targeting or harassing other people, and all your other rules still apply."
)

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

# ── Scheduled world-event pings ──
EVENT_PING_CHANNEL_ID = 1529142467658649640
EVENT_PING_TZ = ZoneInfo("Africa/Tripoli")  # Libya (Sabha) - UTC+2, no DST

# Times are HH:MM in Africa/Tripoli local time. Each event pings a role with
# the SAME NAME as the event (e.g. a role literally called "Carnival of Hearts").
EVENT_PING_SCHEDULE = {
    "Carnival of Hearts": [
        "07:00", "08:30", "10:00", "11:30", "13:00", "14:30", "16:00", "17:30",
        "19:00", "20:30", "22:00", "23:30", "01:00", "02:30", "04:00", "05:30",
    ],
    "Interluminary Parasol": [
        "07:30", "09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00",
        "19:30", "21:00", "22:30", "00:00", "01:30", "03:00", "04:30", "06:00",
    ],
    "Battle Royale": [
        "08:00", "09:30", "11:00", "12:30", "14:00", "15:30", "17:00", "18:30",
        "20:00", "21:30", "23:00", "00:30", "02:00", "03:30", "05:00", "06:30",
    ],
    "Doom of Caeranthil": [
        "07:00", "09:00", "11:00", "13:00", "15:00", "17:00", "19:00", "21:00",
        "23:00", "01:00", "03:00", "05:00",
    ],
}

# Tracks the last minute each event was pinged, to avoid double-pinging
# if the check loop happens to tick more than once within the same minute
_event_last_ping_minute = {}

# Deepwoken Fandom wiki, used by the ?wiki command
WIKI_API_URL = os.environ.get("WIKI_API_URL", "https://deepwoken.fandom.com/api.php")
WIKI_BASE_URL = os.environ.get("WIKI_BASE_URL", "https://deepwoken.fandom.com/wiki/")

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
    "security": [
        (5, "Sergeant"),
        (15, "Veteran"),
        (30, "Vanguard"),
    ],
}

# What each category's role ladder is measured against - "points" for Host/Support,
# but Security's ranks are defined in raw vouch COUNT, not weighted points.
ROLE_THRESHOLD_METRIC = {
    "pve": "points",
    "support": "points",
    "security": "points",
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


# ─────────────────────────────────────────────────────────────
# ECONOMY
# The dashboard can override event points and rank ladders. Anything it has
# not overridden falls back to the constants above.
# ─────────────────────────────────────────────────────────────

def get_events(category, data=None):
    """{event name: {points, cooldown}} for a category, with dashboard overrides applied."""
    base = CATEGORY_EVENTS.get(category, {})
    data = load_data() if data is None else data
    override = (data.get("_economy", {}).get("events") or {}).get(category)
    if not override:
        return base
    merged = {}
    for name, points in override.items():
        cfg = dict(base.get(name) or {"cooldown": 0})
        cfg["points"] = points
        merged[name] = cfg
    return merged


def get_event_points(category, event, data=None):
    return (get_events(category, data).get(event) or {}).get("points", 0)


def get_thresholds(category, data=None):
    """The live rank ladder as a list of (threshold, role name)."""
    data = load_data() if data is None else data
    override = (data.get("_economy", {}).get("ranks") or {}).get(category)
    if override:
        return [(row[0], row[1]) for row in override]
    return ROLE_THRESHOLDS.get(category, [])


def get_all_role_names(category, data=None):
    """Every role this ladder has ever used, so renamed ranks still get cleaned up."""
    names = {name for _, name in ROLE_THRESHOLDS.get(category, [])}
    names.update(name for _, name in get_thresholds(category, data))
    return names


def backup_data(tag="backup"):
    """Copy the current data file aside before anything destructive. Returns the path."""
    if not os.path.exists(DATA_FILE):
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    folder = os.path.dirname(DATA_FILE) or "."
    path = os.path.join(folder, f"vouches-{tag}-{stamp}.json")
    try:
        with open(DATA_FILE, "r") as source, open(path, "w") as dest:
            dest.write(source.read())
    except OSError as e:
        print(f"[Backup] Failed: {e}")
        return None

    # keep the ten most recent, drop the rest
    try:
        backups = sorted(f for f in os.listdir(folder) if f.startswith("vouches-") and f.endswith(".json"))
        for old in backups[:-10]:
            os.remove(os.path.join(folder, old))
    except OSError:
        pass
    return path


def count_manual_entries(data):
    """Vouches added by hand rather than posted in a channel, which a rescan cannot recover."""
    total = 0
    for uid, rec in data.items():
        if not uid.isdigit():
            continue
        for cat in CATEGORY_EVENTS:
            for entry in (rec.get(cat) or {}).get("log", []):
                if entry.get("backfilled"):
                    total += 1
    return total


def get_user_record(data, user_id, category):
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    if category not in data[uid]:
        data[uid][category] = {
            "total_points": 0,
            "total_vouches": 0,
            "events": {e: 0 for e in get_events(category, data)},
            "cooldowns": {},
            "log": [],
        }
    for e in get_events(category, data):
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

def record_vouch(data, target_ids, author_id, category, event_name, when=None, author_name=None):
    """
    Returns (recorded_target_ids, cooldown_target_ids, self_dropped_count).
    """
    when = when or datetime.now(timezone.utc)
    cfg = get_events(category).get(event_name) or {"points": 0, "cooldown": 0}
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
            "id": uuid.uuid4().hex[:8],
            "by": str(author_id),
            "by_name": author_name or "",
            "event": event_name,
            "points": points,
            "count": 1,
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
        lines.append(f"**{i}.** <@{uid}> - {pts} pts ({cnt} vouches)")
    return lines


_leaderboard_refresh_lock = asyncio.Lock()


async def refresh_live_leaderboards():
    async with _leaderboard_refresh_lock:
        await _refresh_live_leaderboards_inner()


async def _refresh_live_leaderboards_inner():
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
            # Whatever happened (deleted, edit failed, etc.) - clean up any old message
            # before posting a new one, so we never end up with duplicates in the channel.
            if msg_id:
                try:
                    old_msg = await channel.fetch_message(msg_id)
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
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

async def send_rank_up_dm(member, old_rank, new_rank):
    """DMs a member when they climb to a new rank role."""
    if old_rank:
        text = f"Congrats {member.mention} you've gone from **{old_rank}** to **{new_rank}**!"
    else:
        text = f"Congrats {member.mention} you've reached **{new_rank}**!"
    try:
        await member.send(text)
        return True
    except discord.Forbidden:
        return False  # DMs closed, nothing we can do
    except discord.HTTPException as e:
        print(f"[RankUp] Could not DM {member.id}: {e}")
        return False


async def update_role_for_user(guild, user_id, category, notify=True):
    """Assigns the correct rank role for a user in a category with a role ladder.

    notify=False skips the rank up DM, used for bulk resyncs so nobody gets spammed.
    """
    if guild is None or category not in ROLE_THRESHOLDS:
        return

    data = load_data()
    record = data.get(str(user_id), {}).get(category)
    metric = ROLE_THRESHOLD_METRIC.get(category, "points")
    if metric == "vouches":
        value = record["total_vouches"] if record else 0
    else:
        value = record["total_points"] if record else 0

    thresholds = get_thresholds(category, data)
    achieved_role_name = None
    for threshold, role_name in thresholds:
        if value >= threshold:
            achieved_role_name = role_name

    if achieved_role_name is None:
        # Hasn't reached the lowest rank yet - nothing to assign or remove
        return

    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return
        except discord.HTTPException:
            return

    category_role_names = get_all_role_names(category, data)
    roles_to_remove = [r for r in member.roles if r.name in category_role_names and r.name != achieved_role_name]
    role_to_add = discord.utils.get(guild.roles, name=achieved_role_name)

    # Where they stood before this update, so we only celebrate a real promotion
    ladder_order = [name for _, name in thresholds]
    held = [r.name for r in member.roles if r.name in category_role_names]
    old_rank = None
    old_index = -1
    for name in held:
        if name in ladder_order and ladder_order.index(name) > old_index:
            old_index = ladder_order.index(name)
            old_rank = name
    new_index = ladder_order.index(achieved_role_name) if achieved_role_name in ladder_order else -1
    promoted = achieved_role_name not in held and new_index > old_index

    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Vouch rank update")
        if role_to_add and role_to_add not in member.roles:
            await member.add_roles(role_to_add, reason="Vouch rank update")
            if notify and promoted:
                sent = await send_rank_up_dm(member, old_rank, achieved_role_name)
                if not sent:
                    await log_audit(
                        f"📬 {member.mention} reached **{achieved_role_name}** but has DMs closed."
                    )
    except discord.Forbidden:
        await log_audit(
            f"⚠️ Couldn't update rank role for <@{user_id}> - check the bot's role is above "
            f"the `{achieved_role_name}` role and has Manage Roles permission."
        )
    except discord.HTTPException:
        pass


async def resync_all_roles():
    """Recheck every stored member and hand out the correct rank role."""
    data = load_data()
    checked = 0
    updated = 0
    for guild in bot.guilds:
        for uid, rec in user_records(data):
            member = guild.get_member(int(uid))
            if member is None:
                continue
            checked += 1
            before = {r.name for r in member.roles}
            for category in ROLE_THRESHOLDS:
                if rec.get(category):
                    await update_role_for_user(guild, int(uid), category, notify=False)
            refreshed = guild.get_member(int(uid))
            if refreshed and {r.name for r in refreshed.roles} != before:
                updated += 1
            await asyncio.sleep(0.35)  # stay well clear of the rate limit
    await log_audit(f"🔄 Role resync from the dashboard - {updated} member(s) updated of {checked} checked.")
    return {"checked": checked, "updated": updated}


# ─────────────────────────────────────────────────────────────
# STREAK WARNINGS
# Runs once a day and DMs anyone whose daily streak is about to lapse.
# ─────────────────────────────────────────────────────────────

STREAK_WARNING_HOUR = int(os.environ.get("STREAK_WARNING_HOUR", "20"))  # UTC


@tasks.loop(time=dtime(hour=STREAK_WARNING_HOUR, minute=0, tzinfo=timezone.utc))
async def warn_expiring_streaks():
    """DM members who had a vouch yesterday but none today."""
    try:
        import dashboard
    except ImportError:
        return

    data = load_data()
    today = datetime.now(timezone.utc).date().isoformat()
    sent_log = data.setdefault("_streak_dm", {})
    warned = 0
    changed = False

    for uid, record in list(data.items()):
        if not uid.isdigit():
            continue
        if sent_log.get(uid) == today:
            continue  # already warned them today

        try:
            streak = dashboard.streak_stats(record)
        except Exception as e:
            print(f"[Streak] Could not read streak for {uid}: {e}")
            continue

        if not streak["at_risk"] or streak["current"] < 1:
            continue

        user = bot.get_user(int(uid))
        if user is None:
            try:
                user = await bot.fetch_user(int(uid))
            except (discord.NotFound, discord.HTTPException):
                continue

        hours = max(1, streak["hours_left"])
        try:
            await user.send(
                f"Your **{streak['current']} day** streak is about to break. "
                f"Get a vouch in the next {hours} hour{'s' if hours != 1 else ''} to keep it alive."
            )
            warned += 1
        except discord.Forbidden:
            pass  # DMs closed, skip quietly
        except discord.HTTPException as e:
            print(f"[Streak] DM to {uid} failed: {e}")
            continue

        sent_log[uid] = today
        changed = True
        await asyncio.sleep(1.2)  # stay polite with the DM rate limit

    # forget warnings older than a week so the log does not grow forever
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
    stale = [u for u, day in sent_log.items() if day < cutoff]
    for u in stale:
        del sent_log[u]
        changed = True

    if changed:
        fresh = load_data()
        fresh["_streak_dm"] = sent_log
        save_data(fresh)
    if warned:
        print(f"[Streak] Warned {warned} member(s)")


@warn_expiring_streaks.before_loop
async def before_streak_warnings():
    await bot.wait_until_ready()


# ─────────────────────────────────────────────────────────────
# CUSTOM ?COMMANDS (created from the dashboard)
# ─────────────────────────────────────────────────────────────

def get_custom_commands():
    return load_data().get("_commands", [])


def _bump_command_uses(name):
    data = load_data()
    for c in data.get("_commands", []):
        if c["name"] == name:
            c["uses"] = c.get("uses", 0) + 1
            save_data(data)
            return


def _fill_placeholders(text, message):
    return (text
            .replace("{user}", message.author.mention)
            .replace("{name}", message.author.display_name)
            .replace("{server}", message.guild.name if message.guild else "this server"))


async def try_custom_command(message):
    """Runs a dashboard-made ?command. Returns True if one matched."""
    content = message.content.strip()
    if not content.startswith("?") or len(content) < 2:
        return False
    name = content[1:].split()[0].lower()
    if not name or bot.get_command(name):
        return False  # never shadow a built-in

    for c in get_custom_commands():
        if c.get("name") != name or not c.get("enabled", True):
            continue
        text = _fill_placeholders(c.get("response", ""), message)
        try:
            if c.get("embed"):
                try:
                    color = discord.Color(int(str(c.get("color", "#2f9bf5")).lstrip("#"), 16))
                except ValueError:
                    color = discord.Color.blue()
                embed = discord.Embed(description=text, color=color)
                if c.get("title"):
                    embed.title = c["title"]
                await message.channel.send(embed=embed)
            else:
                await message.channel.send(text)
            _bump_command_uses(name)
        except discord.HTTPException as e:
            print(f"[CustomCommand] Failed to send ?{name}: {e}")
        return True
    return False


async def process_message_commands(message):
    """Custom ?commands get first refusal, then the built-in command handler."""
    if await try_custom_command(message):
        return
    await bot.process_commands(message)


# ─────────────────────────────────────────────────────────────
# @MENTION CHAT (calls the Claude API directly)
# ─────────────────────────────────────────────────────────────

# In-memory only - resets on restart, scoped per channel, capped length
CHAT_HISTORY = {}
CHAT_HISTORY_MAX_MESSAGES = 20  # ~10 back-and-forth turns


async def call_llm(history, system_prompt=None):
    if not NVIDIA_API_KEY:
        return "⚠️ Chat isn't set up yet - an admin needs to add an `NVIDIA_API_KEY` variable."

    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = [{"role": "system", "content": system_prompt or build_system_prompt(DEFAULT_PERSONA)}] + history
    payload = {
        "model": NVIDIA_MODEL,
        "messages": messages,
        "max_tokens": 400,
        "temperature": 0.7,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(NVIDIA_API_URL, json=payload, headers=headers, timeout=30) as resp:
                status = resp.status
                text = await resp.text()
                if status != 200:
                    print(f"[NVIDIA API] HTTP {status}: {text[:500]}")
                    if status == 404:
                        return ("⚠️ The AI provider rejected the request (HTTP 404). This usually means "
                                "the account is missing API access rather than anything being wrong here. "
                                "An admin can run `/aitest` for the details.")
                    if status in (401, 403):
                        return "⚠️ The AI provider rejected the API key (HTTP {}). Check `NVIDIA_API_KEY`.".format(status)
                    if status == 429:
                        return "⚠️ Rate limited by the AI provider. Try again in a minute."
                    return f"⚠️ Chat API returned an error (HTTP {status}). Check Railway logs for details."
                data = json.loads(text)
    except Exception as e:
        print(f"[NVIDIA API] Exception: {type(e).__name__}: {e}")
        return "⚠️ Couldn't reach the chat API right now. Try again in a bit."

    try:
        return data["choices"][0]["message"]["content"].strip() or "…"
    except (KeyError, IndexError, TypeError):
        err = data.get("error", {}).get("message", "unknown error") if isinstance(data, dict) else "unknown error"
        return f"⚠️ Chat error: {err}"


_WIKI_STOPWORDS = re.compile(
    r"\b(what are|what is|what's|how do i|how to|can i|do you know|"
    r"requirements for|requirements|unlock|get|for|the|a|an)\b",
    re.IGNORECASE,
)


def clean_wiki_query(text):
    """Strip filler words/punctuation so the wiki search has a cleaner term to match on."""
    cleaned = _WIKI_STOPWORDS.sub(" ", text.lower())
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text


# Fandom sits behind Cloudflare and rejects requests with a default python
# user agent, so identify ourselves properly.
WIKI_HEADERS = {
    "User-Agent": os.environ.get(
        "WIKI_USER_AGENT",
        "MatzysOverseer/1.0 (Discord bot; +https://github.com/) aiohttp",
    ),
    "Accept": "application/json",
}

# Set when a lookup fails for a reason other than "no results", so callers can
# tell a broken search apart from a genuine miss.
WIKI_LAST_ERROR = None


async def _wiki_get(session, params, timeout=10):
    """One call to the wiki API. Returns parsed JSON or None, and records why it failed."""
    global WIKI_LAST_ERROR
    try:
        async with session.get(WIKI_API_URL, params=params, timeout=timeout) as resp:
            body = await resp.text()
            if resp.status != 200:
                WIKI_LAST_ERROR = f"HTTP {resp.status}"
                print(f"[Wiki] HTTP {resp.status} from {WIKI_API_URL} :: {body[:300]}")
                return None
            try:
                return json.loads(body)
            except ValueError:
                WIKI_LAST_ERROR = "not JSON"
                print(f"[Wiki] Non-JSON response :: {body[:300]}")
                return None
    except asyncio.TimeoutError:
        WIKI_LAST_ERROR = "timed out"
        print("[Wiki] Request timed out")
    except Exception as e:
        WIKI_LAST_ERROR = f"{type(e).__name__}"
        print(f"[Wiki] Request failed: {type(e).__name__}: {e}")
    return None


def _squash(text):
    """Lowercase with everything but letters and digits removed."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


async def _wiki_search_titles(session, cleaned, raw_query):
    """Full text search, falling back to opensearch which is more forgiving."""
    data = await _wiki_get(session, {
        "action": "query", "list": "search", "srsearch": cleaned,
        "format": "json", "srlimit": 5, "srnamespace": 0,
    }, timeout=10)
    titles = [r["title"] for r in (data or {}).get("query", {}).get("search", [])]
    if titles:
        return titles

    # opensearch handles partial and misspelled names better than full text search
    data = await _wiki_get(session, {
        "action": "opensearch", "search": cleaned or raw_query,
        "limit": 5, "namespace": 0, "format": "json",
    }, timeout=10)
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        return data[1]
    return []


async def fetch_wiki_context(query, max_chars=900, max_sources=3):
    """
    Search the wiki, then scan the full text of the top candidates for the
    actual term, since many things (talents especially) live as a section
    inside a bigger page rather than their own article.
    Returns a list of {title, snippet, url}, best match first.
    """
    global WIKI_LAST_ERROR
    WIKI_LAST_ERROR = None

    cleaned = clean_wiki_query(query)
    search_terms = [w for w in re.findall(r"[a-zA-Z0-9]+", query.lower()) if len(w) > 2]
    if not search_terms:
        return []

    results = []
    async with aiohttp.ClientSession(headers=WIKI_HEADERS) as session:
        candidates = await _wiki_search_titles(session, cleaned, query)
        if not candidates:
            return []

        for title in candidates:
            if len(results) >= max_sources:
                break
            data = await _wiki_get(session, {
                "action": "query", "prop": "extracts", "explaintext": 1,
                "titles": title, "format": "json", "redirects": 1,
            }, timeout=14)
            if not data:
                continue

            pages = data.get("query", {}).get("pages", {})
            page = next(iter(pages.values()), {})
            full_text = page.get("extract") or ""
            if not full_text:
                continue

            url = WIKI_BASE_URL + title.replace(" ", "_")
            lower_text = full_text.lower()

            # "brickwall" should still match a page called "Brick Wall", so compare
            # with spaces and punctuation stripped out on both sides
            squashed_title = _squash(title)
            squashed_query = _squash(query)
            title_is_match = (
                squashed_query and squashed_title
                and (squashed_query in squashed_title or squashed_title in squashed_query)
            ) or any(_squash(t) and _squash(t) in squashed_title
                     for t in search_terms if len(t) > 3)

            match_pos = -1
            for term in sorted(search_terms, key=len, reverse=True):
                pos = lower_text.find(term)
                if pos != -1:
                    match_pos = pos
                    break
            if match_pos == -1:
                # try the squashed form against squashed text, for run-together names
                squashed_text = _squash(full_text)
                for term in sorted(search_terms, key=len, reverse=True):
                    st = _squash(term)
                    if st and st in squashed_text:
                        match_pos = 0
                        break

            if title_is_match and match_pos < 0:
                match_pos = 0
            if match_pos == -1:
                continue

            half = max_chars // 2
            start = max(0, match_pos - half)
            end = min(len(full_text), match_pos + half)
            snippet = full_text[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(full_text):
                snippet = snippet + "..."

            results.append({"title": title, "snippet": snippet, "url": url})

        # search found pages but none contained the term verbatim; the top hit is
        # still the best guess, so return its intro rather than nothing
        if not results and candidates:
            data = await _wiki_get(session, {
                "action": "query", "prop": "extracts", "explaintext": 1,
                "titles": candidates[0], "format": "json", "redirects": 1,
            }, timeout=14)
            pages = (data or {}).get("query", {}).get("pages", {})
            page = next(iter(pages.values()), {})
            intro = (page.get("extract") or "").strip()
            if intro:
                results.append({
                    "title": candidates[0],
                    "snippet": intro[:max_chars] + ("..." if len(intro) > max_chars else ""),
                    "url": WIKI_BASE_URL + candidates[0].replace(" ", "_"),
                })

    return results


WIKI_GROUNDING_RULES = (
    "\n\nWIKI RULES (follow these exactly):\n"
    "- The wiki context below is the ONLY source you may use for game facts: talents, mantras, "
    "weapons, bosses, stats, requirements, locations, drops.\n"
    "- If the context does not answer the question, say you could not find it on the wiki and "
    "point them at the page. Never guess or fill in numbers from memory.\n"
    "- Never invent talent requirements, stat thresholds or item stats. Quote what the context says.\n"
    "- Finish your answer with the source link on its own line.\n"
    "- If the question is about vouches, points or ranks, ignore the wiki context entirely and "
    "use the vouch data instead."
)


def format_wiki_context(sources):
    """Turn wiki hits into a block the model can quote from."""
    if not sources:
        return ""
    blocks = []
    for s in sources:
        blocks.append(f"[Wiki: {s['title']}]\n{s['snippet']}\nSource: {s['url']}")
    return "WIKI CONTEXT\n\n" + "\n\n".join(blocks)


_WIKI_SKIP = re.compile(
    r"\b(vouch|vouches|points?|rank|ranks|leaderboard|streak|profile|hosted?|hosting)\b",
    re.IGNORECASE,
)


def looks_like_wiki_question(text):
    """Cheap filter so casual chatter does not trigger a wiki round trip."""
    stripped = text.strip()
    if len(stripped) < 6:
        return False
    if _WIKI_SKIP.search(stripped) and "?" not in stripped:
        return False
    words = re.findall(r"[a-zA-Z0-9']+", stripped)
    if len(words) < 2:
        return False
    return True


def is_chat_enabled():
    data = load_data()
    return data.get("_settings", {}).get("chat_enabled", True)


def set_chat_enabled(enabled):
    data = load_data()
    settings = data.get("_settings", {})
    settings["chat_enabled"] = enabled
    data["_settings"] = settings
    save_data(data)


def get_vouch_summary_text(user_id, display_name):
    data = load_data()
    user_data = data.get(str(user_id), {})
    total = combined_total(user_data)

    if total == 0:
        return f"[Vouch Data - {display_name}]\nNo vouches recorded yet."

    lines = [f"[Vouch Data - {display_name}]", f"Total: {total} pts"]
    for cat in CATEGORY_EVENTS:
        record = user_data.get(cat)
        if record and record["total_vouches"]:
            lines.append(f"{CATEGORY_NAMES[cat]}: {record['total_points']} pts ({record['total_vouches']} vouches)")
    return "\n".join(lines)


async def handle_chat_mention(message):
    content = re.sub(rf"<@!?{bot.user.id}>", "", message.content).strip()
    if not content:
        content = "Hey!"

    # Direct leaderboard request - skip the LLM and post the real embed straight away
    lower = content.lower()
    if "leaderboard" in lower:
        if "security" in lower:
            category = "security"
        elif "support" in lower:
            category = "support"
        else:
            category = "pve"

        data = load_data()
        lines = build_leaderboard_lines(data, category, 10)
        embed = discord.Embed(
            title=f"🏆 {CATEGORY_NAMES[category]} Leaderboard",
            description="\n".join(lines) if lines else "No vouches yet.",
            color=discord.Color.blurple(),
        )
        await message.reply(embed=embed, mention_author=False)
        return

    channel_id = message.channel.id
    history = CHAT_HISTORY.setdefault(channel_id, [])
    history.append({"role": "user", "content": content})
    history[:] = history[-CHAT_HISTORY_MAX_MESSAGES:]

    # Give the model real vouch data: the asker's own stats, plus anyone else they @mentioned
    target_users = [(message.author.id, message.author.display_name)]
    for m in message.mentions:
        if m.id != bot.user.id and m.id != message.author.id:
            target_users.append((m.id, m.display_name))

    vouch_blocks = "\n\n".join(get_vouch_summary_text(uid, name) for uid, name in target_users)

    async with message.channel.typing():
        wiki_sources = []
        if looks_like_wiki_question(content):
            try:
                wiki_sources = await fetch_wiki_context(content)
            except Exception as e:
                print(f"[Wiki] Lookup error: {type(e).__name__}: {e}")

        wiki_block = format_wiki_context(wiki_sources)
        api_messages = history.copy()
        api_messages[-1] = {
            "role": "user",
            "content": "\n\n".join(part for part in [content, vouch_blocks, wiki_block] if part),
        }

        base_prompt = build_system_prompt(get_active_persona())
        active_prompt = base_prompt + UNFILTERED_EXTRA if message.author.id == UNFILTERED_USER_ID else base_prompt
        if wiki_sources:
            active_prompt += WIKI_GROUNDING_RULES
        reply_text = await call_llm(api_messages, system_prompt=active_prompt)

    history.append({"role": "assistant", "content": reply_text})
    history[:] = history[-CHAT_HISTORY_MAX_MESSAGES:]

    await message.reply(reply_text[:1900], mention_author=False)


# ─────────────────────────────────────────────────────────────
# BOT
# ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="?", intents=intents, help_command=None)


@tasks.loop(seconds=30)
async def event_ping_loop():
    channel = bot.get_channel(EVENT_PING_CHANNEL_ID)
    if channel is None:
        return

    now = datetime.now(EVENT_PING_TZ)
    current_hm = now.strftime("%H:%M")

    for event_name, times in EVENT_PING_SCHEDULE.items():
        if current_hm not in times:
            continue
        if _event_last_ping_minute.get(event_name) == current_hm:
            continue  # already pinged this exact minute
        _event_last_ping_minute[event_name] = current_hm

        role = discord.utils.get(channel.guild.roles, name=event_name) if channel.guild else None
        mention = role.mention if role else f"**{event_name}**"
        try:
            await channel.send(f"⏰ {mention} **{event_name}** is starting now!")
        except discord.HTTPException as e:
            print(f"[EventPing] Failed to send ping for {event_name}: {e}")
        if role is None:
            print(f"[EventPing] No role named '{event_name}' found in the server - pinged with plain text instead.")


@event_ping_loop.before_loop
async def before_event_ping_loop():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    # Start the web dashboard in a background thread
    try:
        import dashboard
        dashboard.set_bot(
            bot,
            loop=asyncio.get_running_loop(),
            thresholds=ROLE_THRESHOLDS,
            metric=ROLE_THRESHOLD_METRIC,
            resync=resync_all_roles,
            events=CATEGORY_EVENTS,
        )
        t = threading.Thread(target=dashboard.run_dashboard, daemon=True)
        t.start()
        print("[Dashboard] Started")
    except Exception as e:
        print(f"[Dashboard] Failed to start: {e}")

    if not warn_expiring_streaks.is_running():
        warn_expiring_streaks.start()
        print(f"[Streak] Daily warnings scheduled for {STREAK_WARNING_HOUR:02d}:00 UTC")

    try:
        synced = await bot.tree.sync()
        print(f"[Slash] Synced {len(synced)} command(s)")
    except discord.HTTPException as e:
        print(f"[Slash] Sync failed: {e}")
    await refresh_live_leaderboards()
    if not event_ping_loop.is_running():
        event_ping_loop.start()


# ── Passive "hanging out" chime-ins in one general channel ──
CHIME_IN_CHANNEL_ID = 1478405937080307806
_chime_in_counter = 0
_chime_in_threshold = random.randint(10, 15)


def _reset_chime_threshold():
    global _chime_in_threshold
    _chime_in_threshold = random.randint(10, 15)


async def maybe_chime_in(message):
    global _chime_in_counter

    if message.channel.id != CHIME_IN_CHANNEL_ID:
        return
    if not is_chat_enabled():
        return
    if message.content.startswith(bot.command_prefix):
        return  # don't count or trigger on bot commands

    _chime_in_counter += 1
    if _chime_in_counter < _chime_in_threshold:
        return

    _chime_in_counter = 0
    _reset_chime_threshold()

    recent_lines = []
    try:
        async for msg in message.channel.history(limit=6):
            if msg.author.bot:
                continue
            recent_lines.append(f"{msg.author.display_name}: {msg.content}")
    except discord.HTTPException:
        pass
    recent_lines.reverse()
    context_text = "\n".join(recent_lines) if recent_lines else "(no recent messages)"

    prompt_messages = [{
        "role": "user",
        "content": (
            f"Recent chat in this channel:\n{context_text}\n\n"
            "Jump into this conversation naturally with a short, casual message - like a "
            "regular server member randomly deciding to say something. Don't summarize the "
            "conversation and don't address it like an assistant would. Just react or "
            "contribute like a person casually chiming in. One or two sentences max."
        ),
    }]

    try:
        reply_text = await call_llm(prompt_messages, system_prompt=build_system_prompt(get_active_persona()))
    except Exception as e:
        print(f"[ChimeIn] Failed: {type(e).__name__}: {e}")
        return

    if reply_text and not reply_text.startswith("⚠️"):
        try:
            await message.channel.send(reply_text[:1900])
        except discord.HTTPException:
            pass


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user.mentioned_in(message) and not message.mention_everyone:
        if not is_chat_enabled():
            return
        await handle_chat_mention(message)
        return

    await maybe_chime_in(message)

    category = CHANNEL_CATEGORY.get(message.channel.id)
    if category is None:
        await process_message_commands(message)
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
                data, target_ids, message.author.id, "pve", event_name,
                author_name=message.author.display_name
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
                data, target_ids, message.author.id, category, event_name,
                author_name=message.author.display_name
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
            points = get_event_points(category, event_name, data)
            targets_str = " ".join(f"<@{t}>" for t in recorded_ids)
            await log_audit(
                f"✅ **{CATEGORY_NAMES[category]} - {event_name}** (+{points} pts each)\n"
                f"By: <@{message.author.id}> → {targets_str}"
            )
            await refresh_live_leaderboards()
            for target_id in recorded_ids:
                await update_role_for_user(message.guild, target_id, category)
        return

    await process_message_commands(message)


@bot.event
async def on_message_edit(before, after):
    """If someone edits a message in a vouch channel into a valid vouch format, count it."""
    if after.author.bot:
        return

    category = CHANNEL_CATEGORY.get(after.channel.id)
    if category is None:
        return

    if before.content == after.content:
        return

    data = load_data()
    recorded_ids, cooldown_ids, self_dropped = [], [], 0
    event_name = None
    handled = False

    if category == "pve":
        match = PVE_VOUCH_PATTERN.match(after.content)
        if match:
            handled = True
            target_ids = [int(uid) for uid in MENTION_PATTERN.findall(match.group(1))]
            event_name = parse_pve_event(match.group(2))
            if event_name is None:
                await after.add_reaction("❌")
                return
            recorded_ids, cooldown_ids, self_dropped = record_vouch(
                data, target_ids, after.author.id, "pve", event_name,
                author_name=after.author.display_name
            )
    else:
        match = PHRASE_VOUCH_PATTERN.match(after.content)
        if match:
            handled = True
            phrase = normalize(match.group(1))
            category, event_name = PHRASE_ALIASES[phrase]
            target_ids = [int(uid) for uid in MENTION_PATTERN.findall(match.group(2))]
            recorded_ids, cooldown_ids, self_dropped = record_vouch(
                data, target_ids, after.author.id, category, event_name,
                author_name=after.author.display_name
            )

    if not handled:
        return

    save_data(data)

    if self_dropped and not recorded_ids and not cooldown_ids:
        await after.add_reaction("🚫")
        return
    if self_dropped:
        await after.add_reaction("🚫")
    if cooldown_ids:
        await after.add_reaction("⏳")
    if recorded_ids:
        await after.add_reaction("✅")
        points = get_event_points(category, event_name, data)
        targets_str = " ".join(f"<@{t}>" for t in recorded_ids)
        await log_audit(
            f"✏️ **Edit vouch - {CATEGORY_NAMES[category]} - {event_name}** (+{points} pts each)\n"
            f"By: <@{after.author.id}> → {targets_str}"
        )
        await refresh_live_leaderboards()
        for target_id in recorded_ids:
            await update_role_for_user(after.guild, target_id, category)


# ─────────────────────────────────────────────────────────────
# RANK PROGRESS HELPERS
# ─────────────────────────────────────────────────────────────

def get_rank_progress(points, thresholds):
    """Returns (current_role, current_threshold, next_role, next_threshold). current_role is None if below the lowest threshold."""
    if points < thresholds[0][0]:
        return None, None, None, None

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
    lines = build_leaderboard_lines(data, category, top_n)

    embed = discord.Embed(
        title=f"🏆 {CATEGORY_NAMES[category]} Leaderboard",
        description="\n".join(lines) if lines else "No vouches yet.",
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed)


@bot.command(name="shutdown", aliases=["sleep"])
@commands.has_permissions(manage_guild=True)
async def shutdown_cmd(ctx):
    """Turns off the @mention chat feature. Vouch tracking keeps working normally."""
    set_chat_enabled(False)
    await ctx.send("💤 Chat is now off. @mentioning me won't get a reply until `?awake` is run. Vouch tracking still works as normal.")


@shutdown_cmd.error
async def shutdown_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to do that.")


@bot.command(name="awake", aliases=["wakeup"])
@commands.has_permissions(manage_guild=True)
async def awake_cmd(ctx):
    """Turns the @mention chat feature back on."""
    set_chat_enabled(True)
    await ctx.send("✅ Chat is back on.")


@awake_cmd.error
async def awake_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to do that.")


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
            thresholds = get_thresholds(cat)
            metric = ROLE_THRESHOLD_METRIC.get(cat, "points")
            metric_value = cnt if metric == "vouches" else pts
            unit = "vouches" if metric == "vouches" else "pts"

            current_role, current_threshold, next_role, next_threshold = get_rank_progress(metric_value, thresholds)
            if current_role is None:
                # Hasn't reached the lowest rank yet
                first_threshold, first_role = thresholds[0]
                remaining = first_threshold - metric_value
                value = f"**Points:** {pts} ({cnt} vouches)\n{remaining} {unit} to **{first_role}**"
            else:
                bar = progress_bar(metric_value, current_threshold, next_threshold)
                if next_role:
                    remaining = next_threshold - metric_value
                    progress_line = f"{bar}\n{metric_value}/{next_threshold} {unit} - {remaining} to **{next_role}**"
                else:
                    progress_line = f"{bar}\nMax rank reached! 🎉"
                value = f"**Rank:** {current_role}\n**Points:** {pts} ({cnt} vouches)\n{progress_line}"
        else:
            value = f"**Points:** {pts} ({cnt} vouches)"

        embed.add_field(name=CATEGORY_NAMES[cat], value=value, inline=False)

    await ctx.send(embed=embed)


@bot.command(name="cleanleaderboards")
@commands.has_permissions(manage_guild=True)
async def cleanleaderboards(ctx):
    """
    Deletes ALL existing leaderboard embed messages from the bot in the live
    leaderboard channel (cleans up any duplicates), then posts one fresh
    copy of each. Requires Manage Server permission.
    """
    channel = bot.get_channel(LIVE_LEADERBOARD_CHANNEL_ID)
    if channel is None:
        await ctx.send("⚠️ Couldn't find the live leaderboard channel.")
        return

    status = await ctx.send("🧹 Cleaning up duplicate leaderboard messages...")

    deleted = 0
    async for msg in channel.history(limit=200):
        if msg.author.id == bot.user.id and msg.embeds:
            title = msg.embeds[0].title or ""
            if "Leaderboard" in title:
                try:
                    await msg.delete()
                    deleted += 1
                except discord.HTTPException:
                    pass

    data = load_data()
    data["_live_messages"] = {}
    save_data(data)

    await refresh_live_leaderboards()
    await status.edit(content=f"✅ Removed {deleted} old leaderboard message(s) and posted fresh copies.")


@cleanleaderboards.error
async def cleanleaderboards_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to do that.")


@bot.command(name="testeventping")
@commands.has_permissions(manage_guild=True)
async def testeventping(ctx, *, event_name: str = None):
    """Manually fires an event ping right now, to test role/channel setup. Usage: ?testeventping <event name>"""
    if not event_name or event_name not in EVENT_PING_SCHEDULE:
        valid = ", ".join(EVENT_PING_SCHEDULE.keys())
        await ctx.send(f"⚠️ Usage: `?testeventping <event name>`. Valid: {valid}")
        return

    channel = bot.get_channel(EVENT_PING_CHANNEL_ID)
    if channel is None:
        await ctx.send("⚠️ Couldn't find the event ping channel.")
        return

    role = discord.utils.get(ctx.guild.roles, name=event_name) if ctx.guild else None
    mention = role.mention if role else f"**{event_name}** (⚠️ no matching role found!)"
    await channel.send(f"⏰ {mention} **{event_name}** is starting now! (test ping)")
    await ctx.send(f"✅ Test ping sent to <#{EVENT_PING_CHANNEL_ID}>.")


@testeventping.error
async def testeventping_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to do that.")


@bot.command(name="postleaderboards", aliases=["refreshleaderboards"])
@commands.has_permissions(manage_guild=True)
async def postleaderboards(ctx):
    """Force-posts/refreshes the 3 live leaderboard embeds immediately. Requires Manage Server permission."""
    await refresh_live_leaderboards()
    await ctx.send("✅ Live leaderboards posted/refreshed.")


@postleaderboards.error
async def postleaderboards_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to do that.")


@bot.command(name="addmemory", aliases=["remember"])
@commands.has_permissions(manage_guild=True)
async def addmemory(ctx, *, text: str = None):
    """Teaches the bot a permanent fact it'll remember even after restarts. Usage: ?addmemory <text>"""
    if not text:
        await ctx.send("⚠️ Usage: `?addmemory <text>` - e.g. `?addmemory Our server was founded in 2024`")
        return
    add_memory(text, ctx.author.id)
    await ctx.send(f"🧠 Got it, I'll remember: \"{text}\"")


@addmemory.error
async def addmemory_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to add memories.")


@bot.command(name="memories")
@commands.has_permissions(manage_guild=True)
async def memories_cmd(ctx):
    """Lists everything the bot currently remembers. Requires Manage Server permission."""
    memories = get_memories()
    if not memories:
        await ctx.send("I don't have any saved memories yet.")
        return
    lines = [f"`{m['id']}` - {m['text']}" for m in memories]
    text = "\n".join(lines)
    if len(text) > 1900:
        text = text[:1900] + "\n…(truncated)"
    await ctx.send(f"**🧠 Things I remember:**\n{text}")


@memories_cmd.error
async def memories_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to view memories.")


@bot.command(name="removememory", aliases=["forget"])
@commands.has_permissions(manage_guild=True)
async def removememory(ctx, memory_id: str = None):
    """Removes a saved memory by ID. Usage: ?removememory <id> - get IDs from ?memories"""
    if not memory_id:
        await ctx.send("⚠️ Usage: `?removememory <id>` - get IDs from `?memories`")
        return
    if remove_memory(memory_id):
        await ctx.send(f"🗑️ Forgot memory `{memory_id}`.")
    else:
        await ctx.send(f"⚠️ Couldn't find a memory with id `{memory_id}`.")


@removememory.error
async def removememory_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to remove memories.")


@bot.command(name="persona")
@commands.has_permissions(manage_guild=True)
async def persona_cmd(ctx, name: str = None):
    """Switch the bot's chat personality. Usage: ?persona <name>. See ?personas for options."""
    if name is None or name.lower() not in PERSONA_STYLES:
        available = ", ".join(PERSONA_STYLES.keys())
        await ctx.send(f"⚠️ Usage: `?persona <name>`. Available: {available}")
        return
    set_active_persona(name.lower())
    await ctx.send(f"✅ Personality switched to **{name.lower()}**.")


@persona_cmd.error
async def persona_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to do that.")


@bot.command(name="personas")
async def personas_cmd(ctx):
    """Lists available chat personalities and shows which one is active."""
    active = get_active_persona()
    lines = [f"**{name}**{' (active)' if name == active else ''}" for name in PERSONA_STYLES]
    await ctx.send("**Available personas:**\n" + "\n".join(lines))


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
            f"  {e}: {c} × {get_event_points(category, e)} = {c * get_event_points(category, e)} pts"
            for e, c in record["events"].items() if c
        ]
        await ctx.send(
            f"**{member.display_name}** - {CATEGORY_NAMES[category]}\n"
            f"Total: {record['total_points']} pts across {record['total_vouches']} vouches\n"
            + "\n".join(lines)
        )
        return

    total = combined_total(user_data)
    if total == 0:
        await ctx.send(f"{member.display_name} has no vouches yet.")
        return

    lines = [f"**{member.display_name}** - {total} pts total\n"]
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
        for canonical in get_events(category):
            if normalize(canonical) == match_name:
                event_name = canonical
                break

    if event_name is None:
        valid_list = ", ".join(get_events(category).keys())
        await ctx.send(f"⚠️ Couldn't recognize event `{event_text}`. Valid: {valid_list}")
        return

    if count < 1:
        await ctx.send("⚠️ Count must be at least 1.")
        return

    points = get_event_points(category, event_name, data)
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
        f"🛠️ **Backfill** - {count}x {event_name} ({CATEGORY_NAMES[category]}) for <@{member.id}> "
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
        lines.append(f"`{ref}` - {e.get('count', 1)}x {e['event']} (+{e['points']} pts) by <@{e['by']}> · {ts}")

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
            await ctx.send("⚠️ That entry wasn't a backfill - only backfilled entries can be reverted with this command.")
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
        f"↩️ **Reverted backfill** - {count}x {event_name} ({CATEGORY_NAMES[category]}) for <@{member.id}> "
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

    old_data = load_data()
    manual_before = count_manual_entries(old_data)
    backup_path = backup_data("presync")

    status = await ctx.send(
        "🔄 Scanning all vouch channels for history... this may take a bit.\n"
        + (f"Backed up the current data to `{os.path.basename(backup_path)}` first."
           if backup_path else "⚠️ Could not write a backup first.")
    )

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
                recorded_ids, _, _ = record_vouch(new_data, target_ids, msg.author.id, "pve", event_name, when,
                                                  author_name=msg.author.display_name)
                recorded_total += len(recorded_ids)
            else:
                match = PHRASE_VOUCH_PATTERN.match(msg.content)
                if not match:
                    continue
                phrase = normalize(match.group(1))
                evt_category, event_name = PHRASE_ALIASES[phrase]
                target_ids = [int(uid) for uid in MENTION_PATTERN.findall(match.group(2))]
                recorded_ids, _, _ = record_vouch(new_data, target_ids, msg.author.id, evt_category, event_name, when,
                                                  author_name=msg.author.display_name)
                recorded_total += len(recorded_ids)

    # Carry over everything that is not vouch data: settings, channel config,
    # custom commands, edited points and ranks, memories, analytics.
    for key, value in old_data.items():
        if not key.isdigit():
            new_data[key] = value

    save_data(new_data)
    await refresh_live_leaderboards()

    for uid, rec in new_data.items():
        if not uid.isdigit():
            continue
        for cat in ROLE_THRESHOLDS:
            if cat in rec:
                await update_role_for_user(ctx.guild, int(uid), cat, notify=False)

    await log_audit(
        f"🔄 **Sync** - scanned {scanned} messages, recorded {recorded_total} vouches "
        f"across {len(new_data)} users, run by <@{ctx.author.id}>"
    )

    vouchers = set()
    for key, rec in new_data.items():
        if not key.isdigit():
            continue
        for cat in CATEGORY_EVENTS:
            for entry in (rec.get(cat) or {}).get("log", []):
                if entry.get("by"):
                    vouchers.add(str(entry["by"]))

    summary = (f"✅ Sync complete. Scanned {scanned} messages, recorded {recorded_total} vouches "
               f"across {sum(1 for k in new_data if k.isdigit())} users, "
               f"given by {len(vouchers)} voucher(s).")
    if manual_before:
        summary += (f"\n⚠️ {manual_before} manually added vouch(es) were not in channel history and "
                    f"are gone. Restore from `{os.path.basename(backup_path)}` if you need them."
                    if backup_path else
                    f"\n⚠️ {manual_before} manually added vouch(es) could not be recovered by a rescan.")
    summary += "\nSettings, custom commands and rank config were kept."
    await status.edit(content=summary)


@syncvouches.error
async def syncvouches_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to sync vouch history.")
    else:
        await ctx.send(f"⚠️ Sync failed: {error}")



# ─────────────────────────────────────────────────────────────
# SLASH COMMANDS
# ─────────────────────────────────────────────────────────────

CATEGORY_CHOICES = [
    app_commands.Choice(name="Host", value="pve"),
    app_commands.Choice(name="Security", value="security"),
    app_commands.Choice(name="Support", value="support"),
]


async def event_autocomplete(interaction: discord.Interaction, current: str):
    category = getattr(interaction.namespace, "category", None) or "pve"
    events = get_events(category)
    matches = [e for e in events if current.lower() in e.lower()][:25]
    return [app_commands.Choice(name=f"{e} ({events[e]['points']} pts)", value=e) for e in matches]


@bot.tree.command(name="leaderboard", description="Show the top members for a category")
@app_commands.describe(category="Which leaderboard to show", top="How many places to list (1-25)")
@app_commands.choices(category=CATEGORY_CHOICES)
async def slash_leaderboard(interaction: discord.Interaction,
                            category: app_commands.Choice[str] = None,
                            top: int = 10):
    cat = category.value if category else "pve"
    top = max(1, min(25, top))
    data = load_data()
    lines = build_leaderboard_lines(data, cat, top)
    embed = discord.Embed(
        title=f"{CATEGORY_NAMES[cat]} Leaderboard",
        description="\n".join(lines) if lines else "No vouches recorded yet.",
        color=discord.Color.blue(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="vouches", description="Look up someone's vouch totals")
@app_commands.describe(member="Whose vouches to show (defaults to you)")
async def slash_vouches(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    summary = get_vouch_summary_text(member.id, member.display_name)
    embed = discord.Embed(
        title=f"{member.display_name}'s vouches",
        description=summary,
        color=discord.Color.blue(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rank", description="Show your rank role and progress to the next one")
@app_commands.describe(member="Whose rank to show (defaults to you)")
async def slash_rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    data = load_data()
    record = data.get(str(member.id), {})
    lines = []
    for category in ROLE_THRESHOLDS:
        ladder = get_thresholds(category, data)
        cat_rec = record.get(category)
        if not cat_rec or not ladder:
            continue
        metric = ROLE_THRESHOLD_METRIC.get(category, "points")
        value = cat_rec["total_vouches"] if metric == "vouches" else cat_rec["total_points"]
        current_role, current_at, next_role, next_at = get_rank_progress(value, ladder)
        bar = progress_bar(value, current_at, next_at)
        target = f"{round(max(0, next_at - value), 1)} to {next_role}" if next_at else "max rank"
        lines.append(f"**{CATEGORY_NAMES[category]}** - {current_role or 'Unranked'}\n{bar} {target}")
    embed = discord.Embed(
        title=f"{member.display_name}'s ranks",
        description="\n\n".join(lines) if lines else "No vouches recorded yet.",
        color=discord.Color.blue(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ask", description="Ask anything about the game, answered from the wiki")
@app_commands.describe(question="What do you want to know?")
async def slash_ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    try:
        sources = await fetch_wiki_context(question)
    except Exception as e:
        print(f"[Wiki] /ask lookup error: {type(e).__name__}: {e}")
        sources = []

    if not sources:
        if WIKI_LAST_ERROR:
            await interaction.followup.send(
                f"The wiki search is not responding right now ({WIKI_LAST_ERROR}). "
                "An admin can check the Railway logs for lines starting with [Wiki]."
            )
        else:
            await interaction.followup.send(
                f"I could not find anything on the wiki for **{question[:100]}**. "
                "Try naming the talent, mantra or boss directly."
            )
        return

    prompt = f"{question}\n\n{format_wiki_context(sources)}"
    answer = await call_llm(
        [{"role": "user", "content": prompt}],
        system_prompt=build_system_prompt(get_active_persona()) + WIKI_GROUNDING_RULES,
    )

    embed = discord.Embed(
        title=question[:250],
        description=answer[:3800],
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Sources",
        value="\n".join(f"[{s['title']}]({s['url']})" for s in sources)[:1000],
        inline=False,
    )
    embed.set_footer(text="Answered from the wiki. Check the source if it matters.")
    await interaction.followup.send(embed=embed)


# Model families that serve chat completions, and the ones that never do.
_CHAT_HINTS = ("instruct", "chat", "nemotron", "-it")
_NOT_CHAT = ("bge", "embed", "rerank", "retriever", "starcoder", "codegen", "fuyu",
             "clip", "vila", "stable-diffusion", "sdxl", "riva", "parakeet", "whisper",
             "molmo", "esm", "diffdock", "protein", "genmol", "ocr", "paddle", "nvclip")


def pick_chat_models(ids, limit=12):
    """Best guess at which catalogue entries are usable for chat, best first."""
    usable = []
    for mid in ids:
        low = mid.lower()
        if any(bad in low for bad in _NOT_CHAT):
            continue
        if any(hint in low for hint in _CHAT_HINTS):
            usable.append(mid)

    def score(mid):
        low = mid.lower()
        rank = 5
        for i, fam in enumerate(("nvidia/", "meta/", "mistralai/", "qwen/", "google/", "microsoft/")):
            if low.startswith(fam):
                rank = i
                break
        return (rank, len(mid))

    usable.sort(key=score)
    return usable[:limit]


async def fetch_model_ids():
    """Every model id the account can see, or None if the call failed."""
    if not NVIDIA_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}"}
    url = NVIDIA_API_BASE.rstrip("/") + "/models"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=20) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(await resp.text())
                return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception as e:
        print(f"[AI] Model list failed: {type(e).__name__}: {e}")
        return None


@bot.tree.command(name="aimodels", description="List AI models this account can use (admin only)")
@app_commands.describe(search="Optional filter, for example llama or mistral")
@app_commands.checks.has_permissions(administrator=True)
async def slash_aimodels(interaction: discord.Interaction, search: str = ""):
    await interaction.response.defer(ephemeral=True)
    ids = await fetch_model_ids()
    if ids is None:
        await interaction.followup.send(
            "Could not list models. Run `/aitest` to see why.", ephemeral=True)
        return

    if search:
        matches = [m for m in ids if search.lower() in m.lower()]
        title = f"{len(matches)} model(s) matching `{search}`"
        shown = matches[:25]
    else:
        shown = pick_chat_models(ids, limit=15)
        title = f"{len(ids)} models available. Best guesses for chat:"

    if not shown:
        await interaction.followup.send(
            f"Nothing matched `{search}`. Try a shorter word, or run `/aimodels` with no filter.",
            ephemeral=True)
        return

    body = "\n".join(f"`{m}`" for m in shown)
    footer = ("\n\nSet one of these as `NVIDIA_MODEL` in Railway, then redeploy."
              if not search else "")
    await interaction.followup.send(f"**{title}**\n{body}{footer}"[:1900], ephemeral=True)


@bot.tree.command(name="aitest", description="Diagnose the AI chat connection (admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_aitest(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not NVIDIA_API_KEY:
        await interaction.followup.send(
            "No `NVIDIA_API_KEY` is set in Railway. That is the whole problem.", ephemeral=True)
        return

    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
    lines = [f"Endpoint: `{NVIDIA_API_BASE}`", f"Model: `{NVIDIA_MODEL}`"]
    models_ok = False
    model_listed = False

    # step 1: can we list models? this proves the key and network are fine
    try:
        async with aiohttp.ClientSession() as session:
            url = NVIDIA_API_BASE.rstrip("/") + "/models"
            async with session.get(url, headers=headers, timeout=20) as resp:
                body = await resp.text()
                if resp.status == 200:
                    models_ok = True
                    try:
                        ids = [m.get("id", "") for m in json.loads(body).get("data", [])]
                    except ValueError:
                        ids = []
                    model_listed = NVIDIA_MODEL in ids
                    lines.append(f"GET /models: **OK** ({len(ids)} models available)")
                    lines.append(f"Your model is listed: **{'yes' if model_listed else 'no'}**")
                    if not model_listed and ids:
                        suggestions = pick_chat_models(ids, limit=5)
                        if suggestions:
                            lines.append("Chat models you could use instead:")
                            lines.extend(f"- `{s}`" for s in suggestions)
                            lines.append("Run `/aimodels` for the full list.")
                else:
                    lines.append(f"GET /models: **HTTP {resp.status}** :: {body[:150]}")
    except Exception as e:
        lines.append(f"GET /models: **failed** ({type(e).__name__})")

    # step 2: an actual tiny completion, which is what really matters
    chat_status = None
    try:
        payload = {"model": NVIDIA_MODEL,
                   "messages": [{"role": "user", "content": "ping"}],
                   "max_tokens": 5, "temperature": 0}
        async with aiohttp.ClientSession() as session:
            async with session.post(NVIDIA_API_URL, json=payload, headers=headers, timeout=30) as resp:
                chat_status = resp.status
                body = await resp.text()
                if resp.status == 200:
                    lines.append("POST /chat/completions: **OK** - chat is working")
                else:
                    lines.append(f"POST /chat/completions: **HTTP {resp.status}**")
                    lines.append(f"```{body[:300]}```")
    except Exception as e:
        lines.append(f"POST /chat/completions: **failed** ({type(e).__name__})")

    # the verdict
    if chat_status == 200:
        verdict = "Everything works."
    elif models_ok and chat_status == 404 and model_listed:
        verdict = ("Your key works and the model exists, but completions 404. This is an account "
                   "permission problem: the org is missing **Public API Endpoints** access. "
                   "Ask for it on the NVIDIA developer forums, or point `NVIDIA_API_BASE` at another "
                   "OpenAI compatible provider.")
    elif models_ok and not model_listed:
        verdict = ("`" + NVIDIA_MODEL + "` is not in the catalogue any more, which is why every "
                   "request 404s. Set `NVIDIA_MODEL` in Railway to one of the ids above and redeploy. "
                   "Use `/aimodels` to browse or search the rest.")
    elif not models_ok:
        verdict = "Even listing models failed, so the key or the endpoint is wrong."
    else:
        verdict = "Chat failed for a reason not covered above. The raw response is printed above."

    await interaction.followup.send("\n".join(lines) + f"\n\n**Verdict:** {verdict}", ephemeral=True)


@bot.tree.command(name="wikitest", description="Check the wiki connection (admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_wikitest(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    sources = await fetch_wiki_context("Talents")
    if sources:
        lines = "\n".join(f"- {s['title']} ({len(s['snippet'])} chars)" for s in sources)
        await interaction.followup.send(
            f"Wiki is reachable. Searching for 'Talents' returned:\n{lines}", ephemeral=True)
    else:
        await interaction.followup.send(
            f"Wiki lookup failed. Reason: `{WIKI_LAST_ERROR or 'no results'}`\n"
            f"API URL: `{WIKI_API_URL}`", ephemeral=True)


@bot.tree.command(name="commands", description="List the server's custom ?commands")
async def slash_commands(interaction: discord.Interaction):
    entries = [c for c in get_custom_commands() if c.get("enabled", True)]
    if not entries:
        await interaction.response.send_message(
            "No custom commands yet - an admin can create them on the dashboard.", ephemeral=True)
        return
    listing = "\n".join(f"`?{c['name']}`" + (f" - {c['title']}" if c.get("title") else "") for c in entries)
    embed = discord.Embed(title="Custom commands", description=listing, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="addvouch", description="Manually add a vouch (admin only)")
@app_commands.describe(category="Which category", member="Who gets the vouch",
                       event="Which event", count="How many times (default 1)")
@app_commands.choices(category=CATEGORY_CHOICES)
@app_commands.autocomplete(event=event_autocomplete)
@app_commands.checks.has_permissions(administrator=True)
async def slash_addvouch(interaction: discord.Interaction,
                         category: app_commands.Choice[str],
                         member: discord.Member,
                         event: str,
                         count: int = 1):
    cat = category.value
    if event not in get_events(cat):
        await interaction.response.send_message(f"`{event}` isn't a {CATEGORY_NAMES[cat]} event.", ephemeral=True)
        return
    count = max(1, min(50, count))
    await interaction.response.defer()

    data = load_data()
    record = get_user_record(data, member.id, cat)
    points = get_event_points(cat, event, data)
    record["total_points"] += points * count
    record["total_vouches"] += count
    record["events"][event] = record["events"].get(event, 0) + count
    record["log"].append({
        "id": uuid.uuid4().hex[:8],
        "by": interaction.user.id,
        "by_name": interaction.user.display_name,
        "event": event,
        "points": points * count,
        "count": count,
        "backfilled": True,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    save_data(data)

    await log_audit(
        f"✅ **{CATEGORY_NAMES[cat]} - {event}** (+{points * count} pts) added by "
        f"{interaction.user.mention} → {member.mention}"
    )
    await refresh_live_leaderboards()
    await update_role_for_user(interaction.guild, member.id, cat)
    await interaction.followup.send(
        f"Added **{event}** ×{count} to {member.mention} - now {round(record['total_points'], 1)} "
        f"{CATEGORY_NAMES[cat]} points."
    )


@bot.tree.command(name="resyncroles", description="Recheck everyone's rank roles (admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_resyncroles(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    result = await resync_all_roles()
    await interaction.followup.send(
        f"Resync done - {result['updated']} member(s) updated of {result['checked']} checked.", ephemeral=True)


@slash_aimodels.error
@slash_aitest.error
@slash_wikitest.error
@slash_addvouch.error
@slash_resyncroles.error
async def slash_admin_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need the Administrator permission to use that."
    else:
        msg = "Something went wrong running that command."
        print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)



if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("No token found. Set the DISCORD_TOKEN environment variable before running.")
    bot.run(TOKEN)
