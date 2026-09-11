import asyncio
import threading
import json
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from data_store import DATA_FILE, load_data, save_data, data_txn

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_TOKEN")

# For the @mention chat feature - free API key from build.nvidia.com (NVIDIA NIM).
# No credit card required. Sign up → API Keys → Generate Key.
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
NVIDIA_API_BASE = os.environ.get("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1")
NVIDIA_API_URL = NVIDIA_API_BASE.rstrip("/") + "/chat/completions"
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5")
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
    with data_txn() as data:
        settings = data.get("_settings", {})
        settings["persona"] = name
        data["_settings"] = settings


def get_memories():
    data = load_data()
    return data.get("_memories", [])


def add_memory(text, added_by):
    with data_txn() as data:
        memories = data.get("_memories", [])
        memories.append({
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "added_by": added_by,
            "time": datetime.now(timezone.utc).isoformat(),
        })
        memories = memories[-50:]  # cap so the system prompt doesn't balloon forever
        data["_memories"] = memories


def remove_memory(memory_id):
    with data_txn() as data:
        memories = data.get("_memories", [])
        new_memories = [m for m in memories if m["id"] != memory_id]
        removed = len(new_memories) != len(memories)
        data["_memories"] = new_memories
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

# Each vouch category watches its own channel
PVE_CHANNEL_ID = 1529113596657799178
SECURITY_CHANNEL_ID = 1527834552150659103
SUPPORT_CHANNEL_ID = 1527834504658550924

# The main server. If set, slash commands sync here immediately on top of the
# normal global sync (which can take up to an hour to propagate on its own).
GUILD_ID = int(os.environ.get("GUILD_ID", "0"))

# Channel where the 3 live, auto-updating leaderboards get posted
LIVE_LEADERBOARD_CHANNEL_ID = 1530286316628217906

# Channel where every vouch / backfill / sync gets logged
AUDIT_LOG_CHANNEL_ID = 1530317395669815438

# These two channels always get mentioned at the start of a /host announcement's
# Notes line, so hosts don't have to type them by hand every time. Matched by
# channel name (not ID) so this keeps working if the channel is ever recreated.
HOST_NOTES_APPLY_CHANNEL_NAME = "apply-for-event"
HOST_NOTES_RULES_CHANNEL_NAME = "event-rules"

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

# Per-author, per-target cooldown for Host (PVE) vouches - applies no matter which
# event they're vouched for, on top of (not instead of) any per-event cooldown above.
# It's individual: one host vouching someone doesn't block a different host from
# vouching that same person - it only blocks that same author/target pair.
HOST_VOUCH_COOLDOWN_SECONDS = int(os.environ.get("HOST_VOUCH_COOLDOWN_SECONDS", str(5 * 60)))

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
    "Backup Vouch": {"points": 1, "cooldown": 0},
    "Depths Safe Vouch": {"points": 5, "cooldown": 0},
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
        (0, "Rookie"),
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
# ECONOMY
# The dashboard can override event points and rank ladders. Anything it has
# not overridden falls back to the constants above.
# ─────────────────────────────────────────────────────────────

def get_events(category, data=None):
    """{event name: {points, cooldown}} for a category, with dashboard overrides applied."""
    base = CATEGORY_EVENTS.get(category, {})
    data = load_data() if data is None else data
    econ = data.get("_economy", {})
    points_override = (econ.get("events") or {}).get(category)
    cooldown_override = (econ.get("cooldowns") or {}).get(category) or {}
    if not points_override:
        return base
    merged = {}
    for name, points in points_override.items():
        cfg = dict(base.get(name) or {"cooldown": 0})
        cfg["points"] = points
        if name in cooldown_override:
            cfg["cooldown"] = cooldown_override[name]
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

        # Host's per-event cooldown is deliberately global (blocks re-vouching the
        # same event too soon, regardless of who vouches) - it already has its own
        # separate per-voucher anti-farm check below. Security/Support cooldowns are
        # scoped per (voucher, target) instead, so two different hosts vouching the
        # same person for the same event within the window don't collide with each
        # other - only the same voucher repeating themselves does.
        cooldown_key = event_name if category == "pve" else f"{event_name}_{author_id}"

        if cooldown > 0:
            last = record["cooldowns"].get(cooldown_key)
            if last:
                last_dt = datetime.fromisoformat(last)
                if (when - last_dt).total_seconds() < cooldown:
                    cooldown_ids.append(target_id)
                    continue

        any_key = f"_any_{author_id}"
        if category == "pve" and HOST_VOUCH_COOLDOWN_SECONDS > 0:
            last_any = record["cooldowns"].get(any_key)
            if last_any:
                last_any_dt = datetime.fromisoformat(last_any)
                if (when - last_any_dt).total_seconds() < HOST_VOUCH_COOLDOWN_SECONDS:
                    cooldown_ids.append(target_id)
                    continue

        record["total_points"] += points
        record["total_vouches"] += 1
        record["events"][event_name] += 1
        record["cooldowns"][cooldown_key] = when.isoformat()
        if category == "pve":
            record["cooldowns"][any_key] = when.isoformat()
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


def already_credited_for_message(data, message_id):
    """Target ids that already got vouch credit for this exact message, so an edit
    can't re-earn points for someone it already covered (e.g. editing a vouch message
    hours later to add a second target would otherwise re-vouch the first one too,
    once their cooldown from the original vouch has expired)."""
    return set(data.get("_vouch_message_targets", {}).get(str(message_id), []))


def remember_message_vouch_targets(data, message_id, recorded_ids):
    if not recorded_ids:
        return
    store = data.setdefault("_vouch_message_targets", {})
    key = str(message_id)
    existing = set(store.get(key, []))
    existing.update(str(t) for t in recorded_ids)
    store[key] = list(existing)
    if len(store) > 2000:  # bound growth - drop the oldest tracked messages
        for old_key in list(store.keys())[:len(store) - 2000]:
            del store[old_key]


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
        # Re-read right before saving - `data` was captured before this loop's several
        # awaited Discord calls, so anything else (a vouch, a /host, etc.) could have
        # saved its own changes in the meantime. Saving the stale snapshot would
        # silently wipe that out; only _live_messages is ours to write here.
        data = load_data()
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
        embed = discord.Embed(description=text, color=discord.Color.dark_grey())
        embed.timestamp = datetime.now(timezone.utc)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
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

    # Some categories' ranks are gated behind a required role. Points still
    # accumulate either way, so the rank lands the moment someone is given
    # the gate role.
    is_gated = (category == HOSTER_GATE_CATEGORY and HOSTER_GATE_ROLE_ID) or category in CATEGORY_GATE_ROLE_NAMES
    if is_gated and not member_has_gate_role(member, category):
        stale = [r for r in member.roles if r.name in category_role_names]
        if stale:
            gate_label = (f"<@&{HOSTER_GATE_ROLE_ID}>" if category == HOSTER_GATE_CATEGORY
                          else CATEGORY_GATE_ROLE_NAMES.get(category, ""))
            try:
                await member.remove_roles(
                    *stale, reason=f"Missing the required role for {CATEGORY_NAMES.get(category, category)} ranks")
                await log_audit(
                    f"Removed {', '.join(r.name for r in stale)} from {member.mention} "
                    f"(missing {gate_label})"
                )
            except discord.Forbidden:
                print(f"[Roles] Missing permission to strip {category} ranks from {member.id}")
            except discord.HTTPException as e:
                print(f"[Roles] Could not strip {category} ranks from {member.id}: {e}")
        return

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
            if notify and promoted and not data.get(str(user_id), {}).get("rank_up_dm_opt_out"):
                sent = await send_rank_up_dm(member, old_rank, achieved_role_name)
                if not sent:
                    await log_audit(
                        f"{member.mention} reached **{achieved_role_name}** but has DMs closed."
                    )
    except discord.Forbidden:
        await log_audit(
            f"Couldn't update rank role for <@{user_id}> - check the bot's role is above "
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
    await log_audit(f"Role resync from the dashboard - {updated} member(s) updated of {checked} checked.")
    return {"checked": checked, "updated": updated}


# ─────────────────────────────────────────────────────────────
# TOP VOUCHER ROLE
# The people handing out the most Host vouches get a role, kept in sync
# automatically. Set TOP_VOUCHER_DAYS to 0 to rank on all time instead.
# ─────────────────────────────────────────────────────────────

# Host rank roles are only handed out to members holding this role.
# Set HOSTER_GATE_ROLE_ID to 0 to turn the gate off.
HOSTER_GATE_ROLE_ID = int(os.environ.get("HOSTER_GATE_ROLE_ID", "1528603062715813959"))
HOSTER_GATE_CATEGORY = "pve"

# Support/Security rank roles are likewise only handed out to members holding
# the matching gate role below, even if their points/vouches qualify.
# Set a value to "" to turn that category's gate off.
CATEGORY_GATE_ROLE_NAMES = {
    "support": os.environ.get("SUPPORT_GATE_ROLE_NAME", "ㅤㅤㅤㅤㅤㅤㅤSupportㅤㅤㅤㅤㅤㅤㅤㅤ"),
    "security": os.environ.get("SECURITY_GATE_ROLE_NAME", "ㅤㅤㅤㅤㅤㅤㅤSecurityㅤㅤㅤㅤㅤㅤㅤㅤ"),
}
CATEGORY_GATE_ROLE_NAMES = {k: v for k, v in CATEGORY_GATE_ROLE_NAMES.items() if v}


def member_has_gate_role(member, category):
    """Whether this member holds the role required for this category's ranks, if gated."""
    if category == HOSTER_GATE_CATEGORY and HOSTER_GATE_ROLE_ID:
        return any(r.id == HOSTER_GATE_ROLE_ID for r in member.roles)
    gate_name = CATEGORY_GATE_ROLE_NAMES.get(category)
    if gate_name:
        return any(r.name == gate_name for r in member.roles)
    return True  # not gated

TOP_VOUCHER_ROLE = os.environ.get("TOP_VOUCHER_ROLE", "Top Voucher")
TOP_VOUCHER_COUNT = int(os.environ.get("TOP_VOUCHER_COUNT", "2"))
TOP_VOUCHER_DAYS = int(os.environ.get("TOP_VOUCHER_DAYS", "30"))
TOP_VOUCHER_MAX = 5  # ceiling, so a big tie cannot hand the role to everyone


def compute_top_vouchers(limit=None, days=None, data=None):
    """User ids of whoever has given the most Host vouches. Ties at the cut are included."""
    limit = TOP_VOUCHER_COUNT if limit is None else limit
    days = TOP_VOUCHER_DAYS if days is None else days
    data = load_data() if data is None else data

    cutoff = ""
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    counts = {}
    for uid, rec in data.items():
        if not uid.isdigit():
            continue
        for entry in (rec.get("pve") or {}).get("log", []):
            when = entry.get("time", "")
            if cutoff and when < cutoff:
                continue
            by = (entry.get("by") or "").strip()
            if not by.isdigit() or by == uid:
                continue
            count_val = entry.get("count")
            count_val = int(count_val) if count_val not in (None, "") else 1
            counts[by] = counts.get(by, 0) + count_val

    if not counts:
        return [], {}

    # sort by count, then by id so the order never wobbles between runs
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    cut_value = ranked[min(limit, len(ranked)) - 1][1]
    winners = [uid for uid, n in ranked if n >= cut_value][:TOP_VOUCHER_MAX]
    return winners, counts


async def update_top_voucher_roles(announce=True):
    """Give the role to the current leaders and take it off everyone else."""
    winners, counts = compute_top_vouchers()
    if not winners:
        return {"added": 0, "removed": 0}

    added, removed = [], []
    for guild in bot.guilds:
        role = discord.utils.get(guild.roles, name=TOP_VOUCHER_ROLE)
        if role is None:
            continue
        if role >= guild.me.top_role:
            print(f"[TopVoucher] '{TOP_VOUCHER_ROLE}' sits above the bot's role in {guild.name}, cannot manage it")
            continue

        wanted = {int(uid) for uid in winners}
        try:
            for member in list(role.members):
                if member.id not in wanted:
                    await member.remove_roles(role, reason="No longer a top voucher")
                    removed.append(member)
                    await asyncio.sleep(0.4)

            for uid in wanted:
                member = guild.get_member(uid)
                if member is not None and role not in member.roles:
                    await member.add_roles(role, reason="Top voucher")
                    added.append(member)
                    await asyncio.sleep(0.4)
        except discord.Forbidden:
            print(f"[TopVoucher] Missing Manage Roles in {guild.name}")
            continue
        except discord.HTTPException as e:
            print(f"[TopVoucher] Role update failed in {guild.name}: {e}")
            continue

    if announce and (added or removed):
        window = "all time" if TOP_VOUCHER_DAYS <= 0 else f"last {TOP_VOUCHER_DAYS} days"
        parts = []
        if added:
            parts.append(", ".join(
                f"{m.mention} ({counts.get(str(m.id), 0)} Host vouches)" for m in added))
        line = f"**{TOP_VOUCHER_ROLE}** update ({window})"
        if parts:
            line += f"\nNow held by: {parts[0]}"
        if removed:
            line += f"\nRemoved from: " + ", ".join(m.mention for m in removed)
        await log_audit(line)

    return {"added": len(added), "removed": len(removed)}


@tasks.loop(minutes=60)
async def top_voucher_loop():
    try:
        await update_top_voucher_roles()
    except Exception as e:
        print(f"[TopVoucher] Loop error: {type(e).__name__}: {e}")


@top_voucher_loop.before_loop
async def before_top_voucher_loop():
    await bot.wait_until_ready()


# ─────────────────────────────────────────────────────────────
# STREAK WARNINGS
# Checks hourly and DMs anyone whose /host streak (rolling 24h since
# their last /host run) is about to lapse.
# ─────────────────────────────────────────────────────────────

@tasks.loop(hours=1)
async def warn_expiring_streaks():
    """DM members whose /host streak is within 4 hours of breaking."""
    try:
        import dashboard
    except ImportError:
        return

    data = load_data()
    sent_log = data.setdefault("_streak_dm", {})
    warned = 0
    changed = False

    for uid, record in list(data.items()):
        if not uid.isdigit():
            continue
        if record.get("streak_dm_opt_out"):
            continue  # opted out from the website

        try:
            streak = dashboard.host_streak_stats(record)
        except Exception as e:
            print(f"[Streak] Could not read host streak for {uid}: {e}")
            continue

        if not streak["at_risk"] or streak["current"] < 1 or not streak["last_at"]:
            continue
        if sent_log.get(uid) == streak["last_at"]:
            continue  # already warned for this run

        user = bot.get_user(int(uid))
        if user is None:
            try:
                user = await bot.fetch_user(int(uid))
            except (discord.NotFound, discord.HTTPException):
                continue

        hours = max(1, streak["hours_left"])
        try:
            await user.send(
                f"Your **{streak['current']} run** /host streak is about to break. "
                f"Run `/host` in the next {hours} hour{'s' if hours != 1 else ''} to keep it alive."
            )
            warned += 1
        except discord.Forbidden:
            pass  # DMs closed, skip quietly
        except discord.HTTPException as e:
            print(f"[Streak] DM to {uid} failed: {e}")
            continue

        sent_log[uid] = streak["last_at"]
        changed = True
        await asyncio.sleep(1.2)  # stay polite with the DM rate limit

    # forget warnings for runs more than 30 days old, so the log does not grow forever
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    stale = [u for u, last_at in sent_log.items() if last_at < cutoff]
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
    with data_txn() as data:
        for c in data.get("_commands", []):
            if c["name"] == name:
                c["uses"] = c.get("uses", 0) + 1
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


# Fandom removed the TextExtracts API (prop=extracts) from its wikis, so plain
# text has to be derived from the raw wikitext (prop=revisions) ourselves.
_WIKI_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_WIKI_REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
_WIKI_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_WIKI_GALLERY = re.compile(r"<gallery.*?</gallery>", re.IGNORECASE | re.DOTALL)
_WIKI_TAG = re.compile(r"<[^>]+>")
_WIKI_FILE_LINK = re.compile(r"\[\[(?:File|Image):[^\]]*\]\]", re.IGNORECASE)
_WIKI_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_WIKI_EXTLINK = re.compile(r"\[https?://\S+\s+([^\]]*)\]")
_WIKI_FILE_LINE = re.compile(r"^\s*\[*(File|Image):.*$", re.IGNORECASE | re.MULTILINE)


def wikitext_to_plaintext(text):
    """Strip MediaWiki markup down to readable prose the model can quote from."""
    text = _WIKI_COMMENT.sub("", text)
    text = _WIKI_GALLERY.sub("", text)
    text = _WIKI_REF.sub("", text)
    for _ in range(4):  # templates can nest a few levels (infoboxes, etc.)
        text, changed = _WIKI_TEMPLATE.subn("", text)
        if not changed:
            break
    text = _WIKI_FILE_LINK.sub("", text)
    text = _WIKI_EXTLINK.sub(r"\1", text)
    text = _WIKI_LINK.sub(r"\1", text)
    text = _WIKI_FILE_LINE.sub("", text)
    text = _WIKI_TAG.sub("", text)
    text = re.sub(r"'''''|'''|''", "", text)
    text = re.sub(r"^\s*={1,6}\s*|\s*={1,6}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


async def _wiki_page_text(session, title):
    """Raw wikitext for a title, cleaned to plain prose. Empty string on failure."""
    data = await _wiki_get(session, {
        "action": "query", "prop": "revisions", "rvprop": "content",
        "titles": title, "format": "json", "redirects": 1,
    }, timeout=14)
    if not data:
        return ""
    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    revisions = page.get("revisions") or []
    raw = revisions[0].get("*", "") if revisions else ""
    return wikitext_to_plaintext(raw) if raw else ""


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
            full_text = await _wiki_page_text(session, title)
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
            intro = await _wiki_page_text(session, candidates[0])
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
    with data_txn() as data:
        settings = data.get("_settings", {})
        settings["chat_enabled"] = enabled
        data["_settings"] = settings


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
# TICKETS
# Only the Host Request ticket type grants/revokes the Stage Perms role.
# Any other ticket type added later to the panel should NOT touch it.
# ─────────────────────────────────────────────────────────────

TICKET_CATEGORY_ID = int(os.environ.get("TICKET_CATEGORY_ID", "0"))
TICKET_CATEGORY_NAME = os.environ.get("TICKET_CATEGORY_NAME", "Host Requests")
STAGE_PERMS_ROLE_NAME = os.environ.get("STAGE_PERMS_ROLE_NAME", "Stage Perms")
HOST_REQUEST_TICKET_TYPE = "host_request"


def get_tickets(data=None):
    data = load_data() if data is None else data
    return data.get("_tickets", {})


def save_ticket(channel_id, user_id, ticket_type):
    with data_txn() as data:
        tickets = data.get("_tickets", {})
        tickets[str(channel_id)] = {
            "user_id": user_id,
            "type": ticket_type,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        data["_tickets"] = tickets


def pop_ticket(channel_id):
    with data_txn() as data:
        tickets = data.get("_tickets", {})
        ticket = tickets.pop(str(channel_id), None)
        data["_tickets"] = tickets
    return ticket


def find_open_ticket_channel(guild, user_id, ticket_type):
    for channel_id, info in get_tickets().items():
        if info.get("user_id") == user_id and info.get("type") == ticket_type:
            channel = guild.get_channel(int(channel_id))
            if channel is not None:
                return channel
    return None


def get_ticket_mod_role_names(data=None):
    """Role names granted ticket access from the dashboard, on top of Manage Server."""
    data = load_data() if data is None else data
    return [r.get("name") for r in data.get("_ticket_mod_roles", []) if r.get("name")]


def get_role_grant(member, data=None):
    """The single role name (if any) this member is allowed to grant/revoke via
    /giverole and /takerole, based on whether they hold one of the granter roles
    set from the dashboard's Role Grants tab. Each granter role is limited to
    handing out exactly one target role, independent of Discord's own role
    hierarchy - anyone with 'Senior Mod' whitelisted for 'Junior Mod' can't use
    these commands to hand out anything else, even a role that would normally
    sit below it."""
    data = load_data() if data is None else data
    member_role_names = {r.name for r in member.roles}
    for entry in data.get("_role_grants", []):
        if entry.get("granter_role_name") in member_role_names:
            return entry.get("role_name")
    return None


def staff_ticket_roles(guild):
    """Every role that can see/manage tickets - Manage Server holders plus configured ticket mods."""
    mod_names = set(get_ticket_mod_role_names())
    return [r for r in guild.roles if r.permissions.manage_guild or r.name in mod_names]


def is_ticket_staff(member):
    """Whether this member can manage tickets - Manage Server, or a configured ticket mod role."""
    if member.guild_permissions.manage_guild:
        return True
    mod_names = set(get_ticket_mod_role_names())
    return any(r.name in mod_names for r in member.roles)


async def create_ticket_channel(guild, opener, ticket_type, name_prefix):
    """Creates (or reuses) the ticket channel for this opener/type. Returns (channel, created)."""
    existing = find_open_ticket_channel(guild, opener.id, ticket_type)
    if existing is not None:
        return existing, False

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        opener: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    for role in staff_ticket_roles(guild):
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True)

    category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
    if not isinstance(category, discord.CategoryChannel):
        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)

    safe_name = re.sub(r"[^a-z0-9-]", "", opener.display_name.lower().replace(" ", "-"))
    safe_name = safe_name[:20] or str(opener.id)
    channel_name = f"{name_prefix}-{safe_name}"[:95]

    channel = await guild.create_text_channel(
        channel_name,
        category=category,
        overwrites=overwrites,
        reason=f"Ticket opened by {opener}",
    )
    save_ticket(channel.id, opener.id, ticket_type)
    return channel, True


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Host Request", style=discord.ButtonStyle.green,
                        custom_id="ticket_panel_host_request")
    async def open_host_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        if HOSTER_GATE_ROLE_ID and not any(r.id == HOSTER_GATE_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message(
                "You need the Host role to open a Host Request ticket.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        channel, created = await create_ticket_channel(
            guild, interaction.user, HOST_REQUEST_TICKET_TYPE, "host-request")

        if created:
            stage_role = discord.utils.get(guild.roles, name=STAGE_PERMS_ROLE_NAME)
            granted = False
            if stage_role is not None and stage_role < guild.me.top_role:
                try:
                    await interaction.user.add_roles(stage_role, reason="Opened a Host Request ticket")
                    granted = True
                except discord.Forbidden:
                    pass

            note = (f"You've been given **{STAGE_PERMS_ROLE_NAME}** for this session - it's removed "
                     f"once staff closes this ticket after you host.") if granted else (
                     f"⚠️ Couldn't grant **{STAGE_PERMS_ROLE_NAME}** - check the role exists and the "
                     f"bot's role sits above it.")
            embed = discord.Embed(
                title="Host Request",
                description=f"{interaction.user.mention} opened a Host Request ticket.\n{note}",
                color=discord.Color.green(),
            )
            mod_role_names = set(get_ticket_mod_role_names())
            mod_roles = [r for r in guild.roles if r.name in mod_role_names]
            ping = " ".join([interaction.user.mention] + [r.mention for r in mod_roles])
            await channel.send(
                content=ping, embed=embed, view=HostTicketCloseView(),
                allowed_mentions=discord.AllowedMentions(users=True, roles=True))
            await log_audit(
                f"{interaction.user.mention} opened a Host Request ticket ({channel.mention})"
                + (f" - granted **{STAGE_PERMS_ROLE_NAME}**." if granted else "."))

        await interaction.followup.send(f"Your ticket: {channel.mention}", ephemeral=True)


class HostTicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket (after host)", style=discord.ButtonStyle.red,
                        custom_id="ticket_close_host_request")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_peek = get_tickets().get(str(interaction.channel.id))
        is_opener = ticket_peek is not None and interaction.user.id == ticket_peek.get("user_id")
        if not is_opener and not is_ticket_staff(interaction.user):
            await interaction.response.send_message(
                "Only the ticket opener or ticket staff can close this ticket.", ephemeral=True)
            return

        await interaction.response.defer()
        guild = interaction.guild
        ticket = pop_ticket(interaction.channel.id)

        if ticket:
            stage_role = discord.utils.get(guild.roles, name=STAGE_PERMS_ROLE_NAME)
            member = guild.get_member(ticket["user_id"])
            removed = False
            if stage_role is not None and member is not None and stage_role in member.roles:
                try:
                    await member.remove_roles(stage_role, reason="Host Request ticket closed")
                    removed = True
                except discord.Forbidden:
                    pass
            await log_audit(
                f"Host Request ticket closed by {interaction.user.mention}"
                + (f" - removed **{STAGE_PERMS_ROLE_NAME}** from <@{ticket['user_id']}>."
                   if removed else f" for <@{ticket['user_id']}>."))

        await interaction.channel.send("Closing this ticket in 5 seconds...")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            pass


# ─────────────────────────────────────────────────────────────
# ON-LEAVE
# One button toggles the on-leave role: taking it fills a short form,
# returning it just removes the role. Both channels (where the button
# lives, where leave/return logs post) are set from the dashboard's
# Settings page, not env vars, so staff can change them without a redeploy.
# ─────────────────────────────────────────────────────────────

ON_LEAVE_ROLE_NAME = os.environ.get("ON_LEAVE_ROLE_NAME", "on-leave")


def get_leave_config():
    data = load_data()
    cfg = data.get("_config", {})
    return cfg.get("on_leave_button_channel_id"), cfg.get("on_leave_log_channel_id")


def record_leave_log(entry):
    with data_txn() as data:
        logs = data.setdefault("_on_leave_logs", [])
        logs.append(entry)
        data["_on_leave_logs"] = logs[-1000:]


async def post_leave_log(guild, member, action, reason=None, duration=None, note=None):
    record_leave_log({
        "user_id": str(member.id),
        "username": str(member),
        "action": action,
        "reason": reason,
        "duration": duration,
        "note": note,
        "time": datetime.now(timezone.utc).isoformat(),
    })

    _, log_channel_id = get_leave_config()
    channel = bot.get_channel(int(log_channel_id)) if log_channel_id else None
    if channel is None:
        return
    if action == "start":
        embed = discord.Embed(title="On Leave", color=discord.Color.orange(),
                               description=f"{member.mention} is now on leave.")
        embed.add_field(name="Reason", value=reason or "-", inline=False)
        embed.add_field(name="Duration", value=duration or "-", inline=False)
        if note:
            embed.add_field(name="Note", value=note, inline=False)
    else:
        embed = discord.Embed(title="Back from Leave", color=discord.Color.green(),
                               description=f"{member.mention} is back from leave.")
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text=str(member.id))
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass


class OnLeaveModal(discord.ui.Modal, title="Going On Leave"):
    reason = discord.ui.TextInput(label="Reason", placeholder="Exams", max_length=200)
    duration = discord.ui.TextInput(label="Duration", placeholder="2-3 Weeks", max_length=100)
    note = discord.ui.TextInput(label="Note (optional)", required=False,
                                 style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, role):
        super().__init__()
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.user.add_roles(self.role, reason="Went on leave")
        except discord.Forbidden:
            await interaction.response.send_message(
                f"Couldn't give you **{ON_LEAVE_ROLE_NAME}** - the bot's role needs to sit above it.",
                ephemeral=True)
            return
        await post_leave_log(
            interaction.guild, interaction.user, "start",
            reason=str(self.reason), duration=str(self.duration),
            note=str(self.note) or None)
        await interaction.response.send_message(
            "You're marked as on leave. Click the button again when you're back.", ephemeral=True)


class OnLeaveButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="On Leave", style=discord.ButtonStyle.blurple,
                        custom_id="on_leave_toggle_button")
    async def toggle_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        role = discord.utils.get(guild.roles, name=ON_LEAVE_ROLE_NAME)
        if role is None:
            await interaction.response.send_message(
                f"No role named **{ON_LEAVE_ROLE_NAME}** exists - ask an admin to create it.", ephemeral=True)
            return

        if role in interaction.user.roles:
            try:
                await interaction.user.remove_roles(role, reason="Returned from leave")
            except discord.Forbidden:
                await interaction.response.send_message(
                    f"Couldn't remove **{ON_LEAVE_ROLE_NAME}** - the bot's role needs to sit above it.",
                    ephemeral=True)
                return
            await post_leave_log(guild, interaction.user, "end")
            await interaction.response.send_message("Welcome back! On-leave removed.", ephemeral=True)
            return

        await interaction.response.send_modal(OnLeaveModal(role))


async def ensure_leave_panel_posted():
    """Self-heals the panel message into the configured channel on startup."""
    button_channel_id, _ = get_leave_config()
    if not button_channel_id:
        return
    channel = bot.get_channel(int(button_channel_id))
    if channel is None:
        return

    data = load_data()
    existing_id = data.get("_on_leave_panel_message_id")
    if existing_id:
        try:
            await channel.fetch_message(int(existing_id))
            return
        except discord.NotFound:
            pass
        except discord.HTTPException:
            return

    embed = discord.Embed(
        title="On Leave",
        description="Click below to mark yourself on leave, or to remove it when you're back.",
        color=discord.Color.blurple(),
    )
    try:
        msg = await channel.send(embed=embed, view=OnLeaveButtonView())
    except discord.HTTPException:
        return
    with data_txn() as data:
        data["_on_leave_panel_message_id"] = str(msg.id)


# ─────────────────────────────────────────────────────────────
# HOST EVENT ANNOUNCEMENTS (/host)
# ─────────────────────────────────────────────────────────────

HOST_ANNOUNCE_CHANNEL_ID = int(os.environ.get("HOST_ANNOUNCE_CHANNEL_ID", "1527833921071616110"))
HOST_TEST_CHANNEL_ID = int(os.environ.get("HOST_TEST_CHANNEL_ID", "1478409787883524096"))
HOST_COOLDOWN_SECONDS = int(os.environ.get("HOST_COOLDOWN_SECONDS", str(30 * 60)))

# /host's region options - fixed dropdowns, not free text.
REGION_ROLE_NAME = {
    "EU": "SUPPORT (EU)",
    "NA": "SUPPORT (NA)",
    "Asia": "SUPPORT (ASIA)",
}
HOST_REGION_CHOICES = [app_commands.Choice(name=r, value=r) for r in REGION_ROLE_NAME]

SECURITY_REGION_ROLE_NAME = {
    "EU": "SECURITY (EU)",
    "NA": "SECURITY (NA)",
    "Asia": "SECURITY (ASIA)",
    "SA": "SECURITY (SA)",
    "OCE": "SECURITY (OCE)",
}
HOST_SECURITY_REGION_CHOICES = [app_commands.Choice(name=r, value=r) for r in SECURITY_REGION_ROLE_NAME]

# /host's event option - same list as the Host category on the website (Points & ranks).
HOST_EVENT_CHOICES = [app_commands.Choice(name=n, value=n) for n in CATEGORY_EVENTS["pve"]]

# Some event ping roles aren't named exactly like the event choice shown in /host.
EVENT_ROLE_NAME_OVERRIDES = {
    "Elder": "Elder Primadon",
    "Deep Champion": "Kyrsgarde Champion",
    "Parasol": "Interluminary Parasol",
    "Layer 2 (1)": "Layer 2",
    "Layer 2 (2)": "Layer 2",
    "Diluvian W (25)": "Other Bosses",
    "Diluvian W (50)": "Other Bosses",
}


def event_role_for(guild, event):
    """The role to ping for an event, using an override name where the role isn't
    named exactly like the event (e.g. "Elder" pings the "Elder Primadon" role)."""
    role_name = EVENT_ROLE_NAME_OVERRIDES.get(event, event)
    return discord.utils.get(guild.roles, name=role_name)


def build_stage_topic(event, region):
    """The live Stage's topic (what Discord shows as the stage's name/headline).
    Includes the region so people can tell at a glance which region a stage is
    for without opening the announcement."""
    return f"{event} ({region})" if region else event


def support_role_for_region(guild, region):
    """The single support role to ping for a chosen region, or None."""
    name = REGION_ROLE_NAME.get(region)
    return discord.utils.get(guild.roles, name=name) if name else None


def security_role_for_region(guild, region):
    """The single security role to ping for a chosen region, or None."""
    name = SECURITY_REGION_ROLE_NAME.get(region)
    return discord.utils.get(guild.roles, name=name) if name else None


def record_host_run(user_id, event, message_id=None, channel_id=None, co_host_ids=None, stage_channel_id=None,
                     region=None, stage_topic=None):
    """Logs a /host run for the host streak (rolling 24h window) and remembers the
    event hosted plus the posted message/stage, so /reping and /end know what to act on."""
    with data_txn() as data:
        record = data.setdefault(str(user_id), {})
        runs = record.get("host_runs", [])
        runs.append(datetime.now(timezone.utc).isoformat())
        record["host_runs"] = runs[-100:]
        record["host_runs_total"] = record.get("host_runs_total", 0) + 1
        record["last_host_event"] = event
        record["last_host"] = {
            "event": event,
            "region": region,
            "stage_topic": stage_topic,
            "message_id": str(message_id) if message_id else None,
            "channel_id": str(channel_id) if channel_id else None,
            "co_host_ids": [str(c) for c in co_host_ids] if co_host_ids else [],
            "stage_channel_id": str(stage_channel_id) if stage_channel_id else None,
        }


def no_active_event_message(last_host, action):
    """Explains why there's nothing to act on for /end, /reping, /cohost - distinguishing
    'never hosted', 'already ended', and 'someone took over' instead of lumping them all
    into a generic 'you haven't run /host yet', which is misleading after a takeover."""
    if last_host and last_host.get("ended") and last_host.get("taken_over_by"):
        return (f"<@{last_host['taken_over_by']}> took over hosting that event, "
                f"so there's nothing for you to {action}.")
    if last_host and last_host.get("ended"):
        return f"That event's already been marked as ended, so there's nothing for you to {action}."
    return f"You haven't run /host yet, so there's nothing to {action}."


def co_host_ids_from(last_host):
    """Reads the co-host id list from a last_host record, falling back to the old
    single co_host_id key for records saved before multiple co-hosts were supported."""
    ids = last_host.get("co_host_ids")
    if ids:
        return [str(i) for i in ids]
    legacy = last_host.get("co_host_id")
    return [str(legacy)] if legacy else []


async def grant_stage_perms(guild, member, reason):
    """Adds the Stage Perms role if it exists and the bot can manage it. Returns True if granted."""
    role = discord.utils.get(guild.roles, name=STAGE_PERMS_ROLE_NAME)
    if role is None or role >= guild.me.top_role:
        return False
    try:
        await member.add_roles(role, reason=reason)
        return True
    except discord.Forbidden:
        return False


async def revoke_stage_perms(guild, member, reason):
    """Removes the Stage Perms role if the member currently has it. Returns True if removed."""
    role = discord.utils.get(guild.roles, name=STAGE_PERMS_ROLE_NAME)
    if role is None or member is None or role not in member.roles:
        return False
    try:
        await member.remove_roles(role, reason=reason)
        return True
    except discord.Forbidden:
        return False


def find_host_for_stage(channel_id, topic):
    """Which user's last /host this live stage instance belongs to, by channel+topic match.
    Falls back to matching on the bare event name for records saved before stage
    topics started including the region."""
    data = load_data()
    for uid, record in data.items():
        if not uid.isdigit():
            continue
        last_host = record.get("last_host") or {}
        if str(last_host.get("stage_channel_id")) != str(channel_id):
            continue
        expected_topic = last_host.get("stage_topic") or last_host.get("event")
        if expected_topic == topic:
            return uid
    return None


def clear_stage_tracking(host_uid):
    """Unlinks a host's last_host from the stage it was on once that stage ends.
    Without this, a host's stale record keeps matching on (stage_channel_id, event)
    after they're done, so if anyone else later hosts the same event type on the
    same stage, find_host_for_stage / /host's ghost-check / /end's safety check can
    all misattribute that new, unrelated live stage to the old, finished host."""
    with data_txn() as data:
        record = data.get(str(host_uid))
        if record and record.get("last_host"):
            record["last_host"]["stage_channel_id"] = None
            record["last_host"]["ended"] = True


def reset_stale_live_tracking():
    """One-time cleanup for the new dashboard "Live now" page: clears every
    existing last_host's live-stage link so nothing carried over from before
    this feature existed shows up as live. Only /host sessions started after
    this runs will ever appear there. Runs once, gated by a flag in the data
    so it's a no-op on every restart after the first."""
    with data_txn() as data:
        if data.get("_live_tracking_reset"):
            return
        for uid, record in data.items():
            if not uid.isdigit():
                continue
            last_host = record.get("last_host")
            if last_host and last_host.get("stage_channel_id") and not last_host.get("ended"):
                last_host["stage_channel_id"] = None
                last_host["ended"] = True
        data["_live_tracking_reset"] = True


async def announce_event_ended(guild, host_uid, last_host):
    """Posts the 'event has ended' reply on a host's original /host announcement.
    Shared by /end and on_stage_instance_delete so the announcement gets the same
    reply whether a host runs /end or just ends the stage natively in Discord."""
    channel_id = last_host.get("channel_id")
    message_id = last_host.get("message_id")
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if channel is None or not message_id:
        return False
    try:
        original = await channel.fetch_message(int(message_id))
    except (discord.NotFound, discord.HTTPException, ValueError):
        return False

    member = guild.get_member(int(host_uid))
    host_mention = member.mention if member else f"<@{host_uid}>"
    users = [host_mention] + [f"<@{cid}>" for cid in co_host_ids_from(last_host)]
    try:
        await original.reply(
            f"{' '.join(users)} event has ended",
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    except discord.HTTPException:
        return False
    return True


def build_host_message(host, co_hosts, region, security_region, event, event_display, stage, notes,
                        guild=None, test=False):
    title = "TEST - Host Announcement" if test else "Host Announcement"
    co_hosts = co_hosts or []
    vouch_targets = " ".join([host.mention] + [c.mention for c in co_hosts])
    co_host_line = ", ".join(c.mention for c in co_hosts) if co_hosts else "-"

    notes_prefix = ""
    if guild is not None:
        apply_channel = discord.utils.get(guild.text_channels, name=HOST_NOTES_APPLY_CHANNEL_NAME)
        rules_channel = discord.utils.get(guild.text_channels, name=HOST_NOTES_RULES_CHANNEL_NAME)
        mentions = [c.mention for c in (apply_channel, rules_channel) if c]
        if mentions:
            notes_prefix = " ".join(mentions) + " "

    return (
        f"**{title}**\n"
        f"**Event Host:** {host.mention}\n"
        f"**Co Host:** {co_host_line}\n"
        f"**Region:** {region}\n"
        f"**Security Region:** {security_region}\n"
        f"**Event Type:** {event_display}\n"
        f"**Stage:** {stage}\n"
        f"**Notes:** {notes_prefix}{notes}\n"
        f"**vouches:** vouch {vouch_targets} {event.lower()}"
    )


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
async def on_member_update(before, after):
    """Grant or strip gated ranks the moment a required role changes hands."""
    if HOSTER_GATE_ROLE_ID:
        had = any(r.id == HOSTER_GATE_ROLE_ID for r in before.roles)
        has = any(r.id == HOSTER_GATE_ROLE_ID for r in after.roles)
        if had != has:
            try:
                await update_role_for_user(after.guild, after.id, HOSTER_GATE_CATEGORY, notify=has)
            except Exception as e:
                print(f"[Roles] Gate role update failed for {after.id} ({HOSTER_GATE_CATEGORY}): {e}")

    before_names = {r.name for r in before.roles}
    after_names = {r.name for r in after.roles}
    for category, gate_name in CATEGORY_GATE_ROLE_NAMES.items():
        had = gate_name in before_names
        has = gate_name in after_names
        if had != has:
            try:
                await update_role_for_user(after.guild, after.id, category, notify=has)
            except Exception as e:
                print(f"[Roles] Gate role update failed for {after.id} ({category}): {e}")


# ─────────────────────────────────────────────────────────────
# ANTI-NUKE / BACKUP & RESTORE
# Snapshots every channel's and role's settings (hourly, and on demand), and
# reacts to a burst of channel/role deletions by immediately stripping the
# actor's dangerous roles and recreating whatever they deleted from the last
# snapshot. Manual /restore, /backupnow and /antinuke are gated to the server
# owner or the Bot Manager role - NOT the bot's normal admin check, since the
# threat model here is specifically someone who already has that.
#
# Two things this can't do anything about, by Discord's own design: it can
# only strip roles positioned below the bot's own top role, and it can never
# act on the server owner. And a "restore" recreates channels/roles with the
# same name/settings - it can't resurrect the exact original IDs, so pinned
# messages, webhooks and old message history in a deleted channel are gone
# for good even after a restore.
# ─────────────────────────────────────────────────────────────

BOT_MANAGER_ROLE_NAME = os.environ.get("BOT_MANAGER_ROLE_NAME", "Bot Manager")
# Extra role IDs treated the same as the Bot Manager role above, comma separated,
# for roles you want trusted without renaming them to match BOT_MANAGER_ROLE_NAME.
BOT_MANAGER_ROLE_IDS = {
    int(r) for r in (os.environ.get("BOT_MANAGER_ROLE_IDS", "1481379874366292008").split(","))
    if r.strip()
}
ANTINUKE_WINDOW_SECONDS = int(os.environ.get("ANTINUKE_WINDOW_SECONDS", "12"))
ANTINUKE_THRESHOLD = int(os.environ.get("ANTINUKE_THRESHOLD", "3"))
ANTINUKE_DANGEROUS_PERMS = (
    "administrator", "manage_channels", "manage_roles", "manage_guild",
    "ban_members", "kick_members",
)

_destructive_action_log = {}  # user_id -> [datetime, ...], in-memory only


def is_owner_or_bot_manager(member, guild):
    if member.id == guild.owner_id:
        return True
    return any(r.name == BOT_MANAGER_ROLE_NAME or r.id in BOT_MANAGER_ROLE_IDS for r in member.roles)


def antinuke_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.guild is not None and is_owner_or_bot_manager(interaction.user, interaction.guild)
    return app_commands.check(predicate)


def is_antinuke_enabled():
    return load_data().get("_settings", {}).get("antinuke_enabled", True)


def set_antinuke_enabled(enabled):
    with data_txn() as data:
        settings = data.get("_settings", {})
        settings["antinuke_enabled"] = enabled
        data["_settings"] = settings


def snapshot_channel(ch):
    """A single channel's snapshot dict, or None if it's a kind this backup doesn't cover."""
    if isinstance(ch, discord.CategoryChannel):
        kind = "category"
    elif isinstance(ch, discord.TextChannel):
        kind = "text"
    elif isinstance(ch, discord.VoiceChannel):
        kind = "voice"
    elif isinstance(ch, discord.StageChannel):
        kind = "stage"
    else:
        return None  # forums/threads/etc. aren't covered by this backup

    overwrites = []
    for target, ow in ch.overwrites.items():
        allow, deny = ow.pair()
        overwrites.append({
            "target_id": str(target.id),
            "target_type": "role" if isinstance(target, discord.Role) else "member",
            "allow": allow.value, "deny": deny.value,
        })
    return {
        "id": str(ch.id), "kind": kind, "name": ch.name,
        "category_id": str(ch.category_id) if ch.category_id else None,
        "position": ch.position,
        "topic": getattr(ch, "topic", None),
        "nsfw": getattr(ch, "nsfw", False),
        "slowmode_delay": getattr(ch, "slowmode_delay", 0),
        "bitrate": getattr(ch, "bitrate", None),
        "user_limit": getattr(ch, "user_limit", None),
        "overwrites": overwrites,
    }


def snapshot_role(role):
    """A single role's snapshot dict, or None for the @everyone role."""
    if role.is_default():
        return None
    return {
        "id": str(role.id), "name": role.name, "color": role.color.value,
        "permissions": role.permissions.value, "position": role.position,
        "hoist": role.hoist, "mentionable": role.mentionable,
    }


def snapshot_guild(guild):
    channels = [c for c in (snapshot_channel(ch) for ch in guild.channels) if c is not None]

    roles = []
    role_members = {}
    for role in guild.roles:
        r = snapshot_role(role)
        if r is None:
            continue
        roles.append(r)
        role_members[str(role.id)] = [str(m.id) for m in role.members]

    return {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "guild_id": str(guild.id),
        "channels": channels,
        "roles": roles,
        "role_members": role_members,
    }


async def take_backup_snapshot(guild):
    snap = snapshot_guild(guild)
    with data_txn() as data:
        data["_backup_snapshot"] = snap
    return snap


def build_overwrites(guild, snap_overwrites, role_id_map):
    result = {}
    for ow in snap_overwrites:
        if ow["target_type"] == "role":
            target = role_id_map.get(ow["target_id"]) or guild.get_role(int(ow["target_id"]))
        else:
            target = guild.get_member(int(ow["target_id"]))
        if target is None:
            continue
        allow = discord.Permissions(ow["allow"])
        deny = discord.Permissions(ow["deny"])
        result[target] = discord.PermissionOverwrite.from_pair(allow, deny)
    return result


async def restore_missing(guild, snapshot):
    """Recreates any role or channel from the snapshot that no longer exists
    (matched by name), leaving anything still present untouched. Also hands
    a recreated role back to everyone who had it in the snapshot. Returns
    (channels_created, roles_created, members_restored)."""
    role_id_map = {}
    created_roles = 0
    restored_members = 0
    snap_role_members = snapshot.get("role_members", {})
    for r in sorted(snapshot["roles"], key=lambda r: r["position"]):
        live = discord.utils.get(guild.roles, name=r["name"])
        if live:
            role_id_map[r["id"]] = live
            continue
        try:
            new_role = await guild.create_role(
                name=r["name"], colour=discord.Colour(r["color"]),
                permissions=discord.Permissions(r["permissions"]),
                hoist=r["hoist"], mentionable=r["mentionable"],
                reason="Anti-nuke restore - recreated a missing role",
            )
            role_id_map[r["id"]] = new_role
            created_roles += 1
        except discord.HTTPException:
            continue

        for member_id in snap_role_members.get(r["id"], []):
            member = guild.get_member(int(member_id))
            if member is None:
                continue
            try:
                await member.add_roles(new_role, reason="Anti-nuke restore - had this role before it was deleted")
                restored_members += 1
            except discord.HTTPException:
                pass

    created_channels = 0
    snap_channels = snapshot["channels"]

    category_id_map = {}
    for c in [c for c in snap_channels if c["kind"] == "category"]:
        live = discord.utils.get(guild.categories, name=c["name"])
        if live:
            category_id_map[c["id"]] = live
            continue
        try:
            overwrites = build_overwrites(guild, c["overwrites"], role_id_map)
            new_cat = await guild.create_category(c["name"], overwrites=overwrites, reason="Anti-nuke restore")
            category_id_map[c["id"]] = new_cat
            created_channels += 1
        except discord.HTTPException:
            pass

    for c in [c for c in snap_channels if c["kind"] != "category"]:
        if c["kind"] == "text" and discord.utils.get(guild.text_channels, name=c["name"]):
            continue
        if c["kind"] == "voice" and discord.utils.get(guild.voice_channels, name=c["name"]):
            continue
        if c["kind"] == "stage" and discord.utils.get(guild.stage_channels, name=c["name"]):
            continue

        parent = category_id_map.get(c["category_id"]) if c["category_id"] else None
        overwrites = build_overwrites(guild, c["overwrites"], role_id_map)
        try:
            if c["kind"] == "text":
                await guild.create_text_channel(
                    c["name"], category=parent, overwrites=overwrites,
                    topic=c.get("topic"), nsfw=c.get("nsfw", False),
                    slowmode_delay=c.get("slowmode_delay", 0),
                    reason="Anti-nuke restore - recreated a missing channel",
                )
            elif c["kind"] == "voice":
                await guild.create_voice_channel(
                    c["name"], category=parent, overwrites=overwrites,
                    bitrate=c.get("bitrate") or 64000, user_limit=c.get("user_limit") or 0,
                    reason="Anti-nuke restore - recreated a missing channel",
                )
            elif c["kind"] == "stage":
                await guild.create_stage_channel(
                    c["name"], category=parent, overwrites=overwrites,
                    reason="Anti-nuke restore - recreated a missing channel",
                )
            created_channels += 1
        except discord.HTTPException:
            pass

    return created_channels, created_roles, restored_members


async def find_audit_actor(guild, action, target_id, within_seconds=5):
    """Who performed a just-happened destructive action, by cross-referencing
    the audit log (delete events don't carry the actor directly)."""
    try:
        async for entry in guild.audit_logs(action=action, limit=5):
            age = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
            if age > within_seconds:
                break
            if entry.target is not None and getattr(entry.target, "id", None) == target_id:
                return entry.user
    except discord.Forbidden:
        print("[AntiNuke] Missing View Audit Log permission - can't attribute deletions.")
    return None


async def handle_suspected_nuke(guild, user):
    member = guild.get_member(user.id)
    stripped = []
    if member is not None and guild.me is not None:
        dangerous = [
            r for r in member.roles
            if not r.is_default() and any(getattr(r.permissions, p) for p in ANTINUKE_DANGEROUS_PERMS)
        ]
        removable = [r for r in dangerous if r < guild.me.top_role]
        if removable:
            try:
                await member.remove_roles(*removable, reason="Anti-nuke: mass deletion pattern detected")
                stripped = [r.name for r in removable]
            except discord.HTTPException:
                pass

    snapshot = load_data().get("_backup_snapshot")
    restored_channels = restored_roles = restored_members = 0
    if snapshot:
        restored_channels, restored_roles, restored_members = await restore_missing(guild, snapshot)

    warning = (
        f"🚨 **Anti-nuke triggered** for {user.mention} (`{user.id}`)\n"
        f"{ANTINUKE_THRESHOLD}+ channel/role deletions within {ANTINUKE_WINDOW_SECONDS}s.\n"
        + (f"Stripped: {', '.join(stripped)}\n" if stripped else "Couldn't strip any roles (none removable, or they left).\n")
        + f"Auto-restored {restored_channels} channel(s) and {restored_roles} role(s) from the last backup"
        + (f", and gave {restored_members} member(s) their role(s) back." if restored_members else ".")
    )
    await log_audit(warning)

    notified = set()
    if guild.owner:
        notified.add(guild.owner.id)
        try:
            await guild.owner.send(warning)
        except discord.HTTPException:
            pass
    for m in guild.members:
        if m.id in notified or m.bot:
            continue
        if any(r.name == BOT_MANAGER_ROLE_NAME or r.id in BOT_MANAGER_ROLE_IDS for r in m.roles):
            notified.add(m.id)
            try:
                await m.send(warning)
            except discord.HTTPException:
                pass


def get_antinuke_whitelist_ids(data=None):
    data = load_data() if data is None else data
    return {str(e.get("id")) for e in data.get("_antinuke_whitelist", []) if e.get("id")}


async def record_destructive_action(guild, user):
    if user is None or user.bot:
        return
    if str(user.id) in get_antinuke_whitelist_ids():
        return
    now = datetime.now(timezone.utc)
    history = _destructive_action_log.setdefault(user.id, [])
    history.append(now)
    cutoff = now - timedelta(seconds=ANTINUKE_WINDOW_SECONDS)
    history[:] = [t for t in history if t > cutoff]
    if len(history) >= ANTINUKE_THRESHOLD:
        history.clear()  # avoid re-triggering on every action in the same burst
        await handle_suspected_nuke(guild, user)


@bot.event
async def on_guild_channel_create(channel):
    """Keeps the stored snapshot current the moment a channel appears, so a channel
    created and deleted between hourly snapshots is still recoverable via /restore."""
    ch = snapshot_channel(channel)
    if ch is None:
        return
    with data_txn() as data:
        snap = data.get("_backup_snapshot")
        if not snap:
            return
        channels = [c for c in snap.get("channels", []) if c["id"] != ch["id"]]
        channels.append(ch)
        snap["channels"] = channels
        data["_backup_snapshot"] = snap


@bot.event
async def on_guild_role_create(role):
    """Same idea as on_guild_channel_create, for roles."""
    r = snapshot_role(role)
    if r is None:
        return
    with data_txn() as data:
        snap = data.get("_backup_snapshot")
        if not snap:
            return
        roles = [x for x in snap.get("roles", []) if x["id"] != r["id"]]
        roles.append(r)
        snap["roles"] = roles
        role_members = snap.get("role_members", {})
        role_members[r["id"]] = [str(m.id) for m in role.members]
        snap["role_members"] = role_members
        data["_backup_snapshot"] = snap


@bot.event
async def on_guild_channel_delete(channel):
    if not is_antinuke_enabled():
        return
    guild = channel.guild
    actor = await find_audit_actor(guild, discord.AuditLogAction.channel_delete, channel.id)
    if actor:
        await record_destructive_action(guild, actor)


@bot.event
async def on_guild_role_delete(role):
    if not is_antinuke_enabled():
        return
    guild = role.guild
    actor = await find_audit_actor(guild, discord.AuditLogAction.role_delete, role.id)
    if actor:
        await record_destructive_action(guild, actor)


@tasks.loop(hours=1)
async def backup_snapshot_loop():
    for guild in bot.guilds:
        try:
            await take_backup_snapshot(guild)
        except discord.HTTPException as e:
            print(f"[Backup] Snapshot failed for {guild.id}: {e}")


@backup_snapshot_loop.before_loop
async def before_backup_snapshot_loop():
    await bot.wait_until_ready()


@bot.tree.command(name="restore", description="Recreate any channels/roles missing since the last backup (owner / Bot Manager only)")
@antinuke_check()
async def slash_restore(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    snapshot = load_data().get("_backup_snapshot")
    if not snapshot:
        await interaction.followup.send(
            "No backup exists yet - one is taken automatically every hour, or run /backupnow first.", ephemeral=True)
        return
    channels, roles, members = await restore_missing(interaction.guild, snapshot)
    if channels == 0 and roles == 0:
        msg = (
            f"Nothing to restore - everything in the backup taken {snapshot['taken_at']} already exists. "
            f"If what you deleted was created *after* that backup, it was never captured - run /backupnow "
            f"regularly, or note that channels/roles are now also saved the moment they're created."
        )
    else:
        msg = (
            f"Restored {channels} channel(s) and {roles} role(s) from the backup taken {snapshot['taken_at']}"
            + (f", and gave {members} member(s) their role(s) back." if members else ".")
        )
    await interaction.followup.send(msg, ephemeral=True)
    await log_audit(
        f"{interaction.user.mention} ran /restore - recreated {channels} channel(s), {roles} role(s), "
        f"restored {members} member role assignment(s).")


@bot.tree.command(name="backupnow", description="Take an immediate snapshot of channels and roles (owner / Bot Manager only)")
@antinuke_check()
async def slash_backupnow(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    snap = await take_backup_snapshot(interaction.guild)
    await interaction.followup.send(
        f"Backup taken: {len(snap['channels'])} channel(s), {len(snap['roles'])} role(s).", ephemeral=True)


@bot.tree.command(name="antinuke", description="Check or toggle anti-nuke auto-response (owner / Bot Manager only)")
@app_commands.describe(enabled="Turn auto-response on or off (omit to just check status)")
@antinuke_check()
async def slash_antinuke(interaction: discord.Interaction, enabled: bool = None):
    await interaction.response.defer(ephemeral=True)
    if enabled is None:
        snap = load_data().get("_backup_snapshot")
        status = "enabled" if is_antinuke_enabled() else "disabled"
        last = snap["taken_at"] if snap else "never"
        await interaction.followup.send(f"Anti-nuke is **{status}**. Last backup: {last}.", ephemeral=True)
        return
    set_antinuke_enabled(enabled)
    await interaction.followup.send(
        f"Anti-nuke auto-response is now **{'enabled' if enabled else 'disabled'}**.", ephemeral=True)
    await log_audit(f"{interaction.user.mention} {'enabled' if enabled else 'disabled'} anti-nuke auto-response.")


@slash_restore.error
@slash_backupnow.error
@slash_antinuke.error
async def slash_antinuke_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        msg = f"Only the server owner or someone with the **{BOT_MANAGER_ROLE_NAME}** role (or another trusted role) can use this."
    else:
        msg = "Something went wrong running that command."
        print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.event
async def on_stage_instance_delete(stage_instance):
    """Logs every stage that ends, not just ones ended through /end - Discord's native
    Stage UI lets a stage moderator end it directly, bypassing the bot entirely. Also
    posts the same 'event has ended' reply /end would post, and strips Stage Perms from
    whoever hosted it, so ending the stage itself is enough - no need to also run /end."""
    channel = stage_instance.channel
    where = channel.mention if channel else f"channel `{stage_instance.channel_id}`"
    await log_audit(f"Stage ended in {where} (topic: **{stage_instance.topic}**)")

    guild = getattr(channel, "guild", None)
    if guild is None:
        return
    host_uid = find_host_for_stage(stage_instance.channel_id, stage_instance.topic)
    if host_uid is None:
        return

    last_host = load_data().get(host_uid, {}).get("last_host") or {}
    clear_stage_tracking(host_uid)
    await announce_event_ended(guild, host_uid, last_host)

    member = guild.get_member(int(host_uid))
    if member is None:
        return
    removed = await revoke_stage_perms(guild, member, reason="Their stage ended")
    if removed:
        await log_audit(f"{member.mention}'s **{STAGE_PERMS_ROLE_NAME}** removed - their stage ended.")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    reset_stale_live_tracking()
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

    if not top_voucher_loop.is_running():
        top_voucher_loop.start()
        window = "all time" if TOP_VOUCHER_DAYS <= 0 else f"last {TOP_VOUCHER_DAYS} days"
        print(f"[TopVoucher] Tracking top {TOP_VOUCHER_COUNT} Host vouchers ({window})")

    if not warn_expiring_streaks.is_running():
        warn_expiring_streaks.start()
        print("[Streak] Host streak warnings checking hourly")

    if not backup_snapshot_loop.is_running():
        backup_snapshot_loop.start()
        print("[Backup] Channel/role snapshots running hourly")

    bot.add_view(TicketPanelView())
    bot.add_view(HostTicketCloseView())
    bot.add_view(OnLeaveButtonView())
    await ensure_leave_panel_posted()

    # Guild-scoped commands sync instantly; global commands can take up to an hour
    # and would show up as duplicates alongside a guild-scoped copy of the same
    # commands, so when a main guild is configured, register there ONLY and clear
    # any previously-registered global commands to remove the duplicates.
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            guild_synced = await bot.tree.sync(guild=guild_obj)
            print(f"[Slash] Synced {len(guild_synced)} command(s) instantly to guild {GUILD_ID}")

            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            print("[Slash] Cleared global command registrations (guild-scoped copies are now the only ones)")
        else:
            synced = await bot.tree.sync()
            print(f"[Slash] Synced {len(synced)} command(s) globally (can take up to an hour to show up)")
    except discord.HTTPException as e:
        print(f"[Slash] Sync failed: {e}")
    await refresh_live_leaderboards()
    if not event_ping_loop.is_running():
        event_ping_loop.start()


@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel == after.channel:
        return

    if after.channel is not None:
        data = load_data()
        user_data = data.get(str(member.id), {})
        for cat in CATEGORY_EVENTS:
            if user_data.get(cat, {}).get("total_vouches", 0) > 0:
                activity = discord.Activity(
                    type=discord.ActivityType.playing,
                    name="Hosting In Matzys"
                )
                try:
                    await bot.change_presence(activity=activity)
                except Exception as e:
                    print(f"[Activity] Failed to update: {e}")
                return


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

    recorded_ids, cooldown_ids, self_dropped = [], [], 0
    handled = False
    event_name = None
    target_ids = []

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
    else:
        match = PHRASE_VOUCH_PATTERN.match(message.content)
        if match:
            handled = True
            phrase = normalize(match.group(1))
            mentions_block = match.group(2)
            category, event_name = PHRASE_ALIASES[phrase]
            target_ids = [int(uid) for uid in MENTION_PATTERN.findall(mentions_block)]

    if handled:
        # Parsing/validation above is pure (no awaits), so it's fine outside the
        # lock. The actual record+save has to happen atomically together though.
        with data_txn() as data:
            recorded_ids, cooldown_ids, self_dropped = record_vouch(
                data, target_ids, message.author.id, category, event_name,
                author_name=message.author.display_name
            )
            remember_message_vouch_targets(data, message.id, recorded_ids)

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
                f"**{CATEGORY_NAMES[category]} - {event_name}** (+{points} pts each)\n"
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

    already_credited = already_credited_for_message(load_data(), after.id)
    recorded_ids, cooldown_ids, self_dropped = [], [], 0
    event_name = None
    handled = False
    target_ids = []

    if category == "pve":
        match = PVE_VOUCH_PATTERN.match(after.content)
        if match:
            handled = True
            target_ids = [int(uid) for uid in MENTION_PATTERN.findall(match.group(1))
                          if uid not in already_credited]
            event_name = parse_pve_event(match.group(2))
            if event_name is None:
                await after.add_reaction("❌")
                return
    else:
        match = PHRASE_VOUCH_PATTERN.match(after.content)
        if match:
            handled = True
            phrase = normalize(match.group(1))
            category, event_name = PHRASE_ALIASES[phrase]
            target_ids = [int(uid) for uid in MENTION_PATTERN.findall(match.group(2))
                          if uid not in already_credited]

    if not handled:
        return

    with data_txn() as data:
        recorded_ids, cooldown_ids, self_dropped = record_vouch(
            data, target_ids, after.author.id, category, event_name,
            author_name=after.author.display_name
        )
        remember_message_vouch_targets(data, after.id, recorded_ids)

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
            f"**Edit vouch - {CATEGORY_NAMES[category]} - {event_name}** (+{points} pts each)\n"
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


@bot.tree.command(name="ban", description="Ban a user by IP")
@app_commands.describe(member="The user to ban")
@app_commands.checks.has_permissions(manage_guild=True)
async def ban_user(interaction: discord.Interaction, member: discord.User):
    """Ban a user by IP."""
    from data_store import ban_ip, get_ips_for_user

    ips = get_ips_for_user(member.id)
    if not ips:
        await interaction.response.send_message(f"⚠️ No IP logs found for {member.display_name}. They may not have accessed the dashboard yet.")
        return

    for ip in ips:
        ban_ip(ip, member.id)

    await interaction.response.send_message(f"🚫 Banned {member.display_name} across {len(ips)} IP(s)")


@bot.tree.command(name="unban", description="Unban an IP")
@app_commands.describe(ip="The IP address to unban")
@app_commands.checks.has_permissions(manage_guild=True)
async def unban_user(interaction: discord.Interaction, ip: str):
    """Unban an IP."""
    from data_store import unban_ip, get_users_for_ip

    users = get_users_for_ip(ip)
    unban_ip(ip)
    await interaction.response.send_message(f"✅ Unbanned IP {ip} (was linked to {len(users)} user(s))")


@bot.tree.command(name="verify", description="Verify your access to server events")
async def verify_access(interaction: discord.Interaction):
    """Verify your access to server events."""
    dashboard_url = os.environ.get("DASHBOARD_URL", "https://mattzys.up.railway.app")
    verify_link = f"{dashboard_url}/dashboard/verify"

    embed = discord.Embed(
        title="🔐 Verify Access",
        description="Click the button below to verify your access to server events.",
        color=discord.Color.green()
    )

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link,
        label="Verify Access",
        url=verify_link,
        emoji="✅"
    ))

    await interaction.response.send_message(embed=embed, view=view)


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


@bot.command(name="info", aliases=["about"])
async def info_cmd(ctx):
    """Show bot info and legal documents."""
    dashboard_url = os.environ.get("DASHBOARD_URL", "https://matzys.up.railway.app")
    embed = discord.Embed(
        title="Pve-Bot",
        description="Community threat scoring and vouch tracking bot",
        color=0x7fc2b8
    )
    embed.add_field(
        name="Legal",
        value=f"[Terms of Service]({dashboard_url}/terms)\n[Privacy Policy]({dashboard_url}/privacy)",
        inline=False
    )
    embed.add_field(
        name="Repository",
        value="[Pve-Bot on GitHub](https://github.com/Yuki-Onnaa/Pve-Bot)",
        inline=False
    )
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

    with data_txn() as data:
        points = get_event_points(category, event_name, data)
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
    await refresh_live_leaderboards()
    await update_role_for_user(ctx.guild, member.id, category)

    await log_audit(
        f"**Backfill** - {count}x {event_name} ({CATEGORY_NAMES[category]}) for <@{member.id}> "
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
        f"**Reverted backfill** - {count}x {event_name} ({CATEGORY_NAMES[category]}) for <@{member.id}> "
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
    # custom commands, edited points and ranks, memories, analytics. Re-read
    # fresh rather than using the pre-scan snapshot - the channel scan above can
    # take a while, and anything saved elsewhere in the meantime (a settings
    # change, a memory add) would otherwise be silently lost when this saves.
    fresh_data = load_data()
    for key, value in fresh_data.items():
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
        f"**Sync** - scanned {scanned} messages, recorded {recorded_total} vouches "
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

    await update_top_voucher_roles(announce=False)

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


@bot.command(name="ticketpanel")
@commands.has_permissions(manage_guild=True)
async def ticketpanel_cmd(ctx):
    """Posts the ticket panel in this channel."""
    embed = discord.Embed(title="Host Request", color=discord.Color.blurple())
    await ctx.send(embed=embed, view=TicketPanelView())


@ticketpanel_cmd.error
async def ticketpanel_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You need Manage Server permission to post the ticket panel.")
    else:
        await ctx.send(f"⚠️ Couldn't post the ticket panel: {error}")


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
             "molmo", "esm", "diffdock", "protein", "genmol", "ocr", "paddle", "nvclip",
             "reward", "parse", "-vl", "guard", "safety", "moderation", "judge",
             "reranking", "asr", "tts")


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


@bot.tree.command(name="topvouchers", description="Who is handing out the most Host vouches")
async def slash_topvouchers(interaction: discord.Interaction):
    winners, counts = compute_top_vouchers()
    if not counts:
        await interaction.response.send_message("No Host vouches recorded yet.")
        return

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    lines = []
    for i, (uid, n) in enumerate(ranked, start=1):
        crown = " 🏅" if uid in winners else ""
        lines.append(f"**{i}.** <@{uid}> - {n} Host vouch{'es' if n != 1 else ''}{crown}")

    window = "all time" if TOP_VOUCHER_DAYS <= 0 else f"last {TOP_VOUCHER_DAYS} days"
    embed = discord.Embed(
        title="Top vouchers",
        description="\n".join(lines),
        color=discord.Color.blue(),
    )
    embed.set_footer(text=f"{window} - top {TOP_VOUCHER_COUNT} hold the {TOP_VOUCHER_ROLE} role")
    await interaction.response.send_message(embed=embed)


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

    with data_txn() as data:
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

    await log_audit(
        f"**{CATEGORY_NAMES[cat]} - {event}** (+{points * count} pts) added by "
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


@bot.tree.command(name="backfillhostbadges",
                   description="Seed host badge progress from existing /host history (admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_backfillhostbadges(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    updated = 0
    with data_txn() as data:
        for uid, record in user_records(data):
            historical = len(record.get("host_runs", []))
            if historical > record.get("host_runs_total", 0):
                record["host_runs_total"] = historical
                updated += 1
    await interaction.followup.send(
        f"Backfilled host badge progress for {updated} member(s) from their existing /host history. "
        f"Note: this only counts each person's last 100 /host runs (the same cap the streak tracker uses), "
        f"so anyone who's hosted more than that will show a lower count than reality.",
        ephemeral=True)


@bot.tree.command(name="giverole", description="Give someone the one role you're whitelisted to grant")
@app_commands.describe(member="Who to give the role to")
async def slash_giverole(interaction: discord.Interaction, member: discord.Member):
    role_name = get_role_grant(interaction.user)
    if not role_name:
        await interaction.response.send_message(
            "You aren't whitelisted to grant any role - ask an admin to add you in the dashboard's "
            "Role Grants tab.", ephemeral=True)
        return

    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if role is None:
        await interaction.response.send_message(
            f"No role named **{role_name}** exists anymore - ask an admin to check the Role Grants tab.",
            ephemeral=True)
        return
    if role in member.roles:
        await interaction.response.send_message(
            f"{member.mention} already has **{role_name}**.", ephemeral=True)
        return
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            f"Can't grant **{role_name}** - it sits above my own top role.", ephemeral=True)
        return

    try:
        await member.add_roles(role, reason=f"/giverole by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(f"Couldn't grant **{role_name}** - missing permissions.",
                                                  ephemeral=True)
        return
    await interaction.response.send_message(f"Gave {member.mention} **{role_name}**.", ephemeral=True)
    await log_audit(f"{interaction.user.mention} gave **{role_name}** to {member.mention} (/giverole)")


@bot.tree.command(name="takerole", description="Remove the one role you're whitelisted to grant")
@app_commands.describe(member="Who to remove the role from")
async def slash_takerole(interaction: discord.Interaction, member: discord.Member):
    role_name = get_role_grant(interaction.user)
    if not role_name:
        await interaction.response.send_message(
            "You aren't whitelisted to grant any role - ask an admin to add you in the dashboard's "
            "Role Grants tab.", ephemeral=True)
        return

    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if role is None or role not in member.roles:
        await interaction.response.send_message(f"{member.mention} doesn't have **{role_name}**.", ephemeral=True)
        return

    try:
        await member.remove_roles(role, reason=f"/takerole by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(f"Couldn't remove **{role_name}** - missing permissions.",
                                                  ephemeral=True)
        return
    await interaction.response.send_message(f"Removed **{role_name}** from {member.mention}.", ephemeral=True)
    await log_audit(f"{interaction.user.mention} removed **{role_name}** from {member.mention} (/takerole)")


@slash_aimodels.error
@slash_aitest.error
@slash_wikitest.error
@slash_addvouch.error
@slash_resyncroles.error
@slash_backfillhostbadges.error
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


@bot.tree.command(name="ticketpanel", description="Post the ticket panel in this channel (Manage Server only)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_ticketpanel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title="Host Request", color=discord.Color.blurple())
    await interaction.channel.send(embed=embed, view=TicketPanelView())
    await interaction.followup.send("Panel posted.", ephemeral=True)


@slash_ticketpanel.error
async def slash_ticketpanel_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need the Manage Server permission to use that."
    else:
        msg = "Something went wrong running that command."
        print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="leavepanel", description="Post the on-leave button in this channel (Manage Server only)")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_leavepanel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="On Leave",
        description="Click below to mark yourself on leave, or to remove it when you're back.",
        color=discord.Color.blurple(),
    )
    msg = await interaction.channel.send(embed=embed, view=OnLeaveButtonView())
    with data_txn() as data:
        data["_on_leave_panel_message_id"] = str(msg.id)
    await interaction.followup.send("Panel posted.", ephemeral=True)


@slash_leavepanel.error
async def slash_leavepanel_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need the Manage Server permission to use that."
    else:
        msg = "Something went wrong running that command."
        print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="host", description="Announce a hosted event - pings the right support/security roles")
@app_commands.describe(
    event="Event type",
    region="Support region this is for",
    security_region="Security region this is for",
    co_host="Who's co-hosting with you",
    co_host2="Another co-host (optional)",
    co_host3="Another co-host (optional)",
    stage="Which stage channel this event is in - starts it and grants you Stage Perms",
    notes="Anything hosts should know (apply-for-event and event-rules are added automatically)",
)
@app_commands.choices(event=HOST_EVENT_CHOICES, region=HOST_REGION_CHOICES,
                       security_region=HOST_SECURITY_REGION_CHOICES)
async def slash_host(interaction: discord.Interaction, event: str, region: str, security_region: str,
                      stage: discord.StageChannel, notes: str, co_host: discord.Member = None,
                      co_host2: discord.Member = None, co_host3: discord.Member = None):
    co_hosts = []
    for c in (co_host, co_host2, co_host3):
        if c and c.id != interaction.user.id and c.id not in {h.id for h in co_hosts}:
            co_hosts.append(c)
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This only works inside the server.", ephemeral=True)
        return

    if HOSTER_GATE_ROLE_ID and not any(r.id == HOSTER_GATE_ROLE_ID for r in interaction.user.roles):
        await interaction.followup.send(
            "You need the Host role to use this.", ephemeral=True)
        return

    last_host = load_data().get(str(interaction.user.id), {}).get("last_host")
    if last_host and last_host.get("stage_channel_id"):
        prev_stage = guild.get_channel(int(last_host["stage_channel_id"]))
        expected_topic = last_host.get("stage_topic") or last_host.get("event")
        if (isinstance(prev_stage, discord.StageChannel) and prev_stage.instance
                and prev_stage.instance.topic == expected_topic):
            await interaction.followup.send(
                f"You still have an active hosted event (**{last_host.get('event')}**) on "
                f"{prev_stage.mention}. Run /end to close it first, or /takeover if someone "
                f"else is picking it up.",
                ephemeral=True)
            return

    if stage.instance:
        other_host_id = find_host_for_stage(stage.id, stage.instance.topic)
        if other_host_id and str(other_host_id) != str(interaction.user.id):
            other_member = guild.get_member(int(other_host_id))
            mention = other_member.mention if other_member else f"<@{other_host_id}>"
            await interaction.followup.send(
                f"{stage.mention} is already live with **{stage.instance.topic}**, hosted by {mention}. "
                f"Use /takeover if you're picking it up, or choose a different stage.",
                ephemeral=True)
            return
        else:
            await interaction.followup.send(
                f"{stage.mention} already has a live stage instance (**{stage.instance.topic}**). "
                f"End it first or choose a different stage.",
                ephemeral=True)
            return

    host_runs = load_data().get(str(interaction.user.id), {}).get("host_runs", [])
    if host_runs:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(host_runs[-1])).total_seconds()
        if elapsed < HOST_COOLDOWN_SECONDS:
            remaining = int((HOST_COOLDOWN_SECONDS - elapsed) // 60) + 1
            await interaction.followup.send(
                f"You can run /host again in about {remaining} minute{'s' if remaining != 1 else ''}.",
                ephemeral=True)
            return

    channel = bot.get_channel(HOST_ANNOUNCE_CHANNEL_ID)
    if channel is None:
        await interaction.followup.send("Couldn't find the events channel.", ephemeral=True)
        return

    event_role = event_role_for(guild, event)
    event_display = event_role.mention if event_role else f"**{event}**"

    support_role = support_role_for_region(guild, region)
    security_role = security_role_for_region(guild, security_region)
    ping_parts = [interaction.user.mention] + [c.mention for c in co_hosts]
    if support_role:
        ping_parts.append(support_role.mention)
    if security_role:
        ping_parts.append(security_role.mention)
    if event_role:
        ping_parts.append(event_role.mention)

    message = build_host_message(
        interaction.user, co_hosts, region, security_region, event, event_display, stage.mention, notes,
        guild=guild)
    sent_message = await channel.send(
        content=f"{' '.join(ping_parts)}\n{message}\n-----",
        allowed_mentions=discord.AllowedMentions(users=True, roles=True),
    )
    stage_topic = build_stage_topic(event, region)
    record_host_run(
        interaction.user.id, event,
        message_id=sent_message.id, channel_id=channel.id,
        co_host_ids=[c.id for c in co_hosts],
        stage_channel_id=stage.id,
        region=region, stage_topic=stage_topic,
    )

    granted = await grant_stage_perms(guild, interaction.user, reason=f"Hosting {event} via /host")
    stage_started = False
    try:
        await stage.create_instance(topic=stage_topic, reason=f"Hosted by {interaction.user}")
        stage_started = True
    except discord.HTTPException:
        pass

    notice = f"Posted in {channel.mention}."
    if not stage_started:
        notice += " Couldn't start the stage (it may already be live, or I'm missing permission)."
    if not granted:
        notice += f" Couldn't grant **{STAGE_PERMS_ROLE_NAME}** - check the role exists and my role sits above it."
    await interaction.followup.send(notice, ephemeral=True)

    co_host_note = f", co-hosts {', '.join(c.mention for c in co_hosts)}" if co_hosts else ""
    await log_audit(
        f"{interaction.user.mention} hosted **{event}** in {stage.mention} "
        f"(region: {region}, security region: {security_region}{co_host_note})")


@slash_host.error
async def slash_host_error(interaction: discord.Interaction, error):
    msg = "Something went wrong running that command."
    print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="reping", description="Reply to your last /host announcement to bump it - pings nobody")
async def slash_reping(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This only works inside the server.", ephemeral=True)
        return

    if HOSTER_GATE_ROLE_ID and not any(r.id == HOSTER_GATE_ROLE_ID for r in interaction.user.roles):
        await interaction.followup.send(
            "You need the Host role to use this.", ephemeral=True)
        return

    last_host = load_data().get(str(interaction.user.id), {}).get("last_host")
    if not last_host or not last_host.get("message_id") or last_host.get("ended"):
        await interaction.followup.send(no_active_event_message(last_host, "re-ping"), ephemeral=True)
        return

    channel_id = last_host.get("channel_id")
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if channel is None:
        await interaction.followup.send("Couldn't find the events channel.", ephemeral=True)
        return

    try:
        original = await channel.fetch_message(int(last_host["message_id"]))
    except (discord.NotFound, discord.HTTPException, ValueError):
        await interaction.followup.send(
            "Couldn't find your last /host message - it may have been deleted.", ephemeral=True)
        return

    event = last_host.get("event", "")
    event_role = event_role_for(guild, event) if event else None
    content = event_role.mention if event_role else f"**{event}**"

    await original.reply(
        content,
        allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=True, replied_user=False),
    )
    await interaction.followup.send(f"Re-pinged in {channel.mention}.", ephemeral=True)
    await log_audit(f"{interaction.user.mention} re-pinged their hosted event")


@slash_reping.error
async def slash_reping_error(interaction: discord.Interaction, error):
    msg = "Something went wrong running that command."
    print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="end", description="Reply to your last /host announcement saying the event has ended")
async def slash_end(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This only works inside the server.", ephemeral=True)
        return

    if HOSTER_GATE_ROLE_ID and not any(r.id == HOSTER_GATE_ROLE_ID for r in interaction.user.roles):
        await interaction.followup.send(
            "You need the Host role to use this.", ephemeral=True)
        return

    last_host = load_data().get(str(interaction.user.id), {}).get("last_host")
    if not last_host or not last_host.get("message_id") or last_host.get("ended"):
        await interaction.followup.send(no_active_event_message(last_host, "end"), ephemeral=True)
        return

    channel_id = last_host.get("channel_id")
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if channel is None:
        await interaction.followup.send("Couldn't find the events channel.", ephemeral=True)
        return

    try:
        await channel.fetch_message(int(last_host["message_id"]))
    except (discord.NotFound, discord.HTTPException, ValueError):
        await interaction.followup.send(
            "Couldn't find your last /host message - it may have been deleted.", ephemeral=True)
        return

    stage_ended = False
    stage_skipped = False
    stage_delete_failed = False
    stage_channel_id = last_host.get("stage_channel_id")
    if stage_channel_id:
        stage_channel = guild.get_channel(int(stage_channel_id))
        if isinstance(stage_channel, discord.StageChannel) and stage_channel.instance:
            # Someone else may have started a new event on the same stage channel
            # since this host's last /host - only end it if it's still theirs.
            expected_topic = last_host.get("stage_topic") or last_host.get("event")
            if stage_channel.instance.topic == expected_topic:
                try:
                    # Deleting it fires on_stage_instance_delete, which posts the
                    # "event has ended" reply and strips Stage Perms for us.
                    await stage_channel.instance.delete(reason=f"Ended by {interaction.user}")
                    stage_ended = True
                except discord.HTTPException:
                    stage_delete_failed = True
            else:
                stage_skipped = True

    revoked = False
    if not stage_ended:
        # No live stage of theirs to delete (already ended, taken by someone else's
        # event, delete failed, or never started) - on_stage_instance_delete won't
        # fire for us, so post the notice, strip perms, and unlink tracking ourselves.
        clear_stage_tracking(interaction.user.id)
        await announce_event_ended(guild, str(interaction.user.id), last_host)
        revoked = await revoke_stage_perms(guild, interaction.user, reason="Ended their event via /end")

    notice = "Marked your event as ended."
    if stage_ended:
        notice += " Stage ended."
    elif stage_delete_failed:
        notice += (" I couldn't actually end the Stage though - check my permissions there "
                   "and end it manually if it's still live.")
    elif stage_skipped:
        notice += " Didn't touch the stage - someone else has a different event live on it now."
    if revoked:
        notice += f" **{STAGE_PERMS_ROLE_NAME}** removed."
    await interaction.followup.send(notice, ephemeral=True)
    await log_audit(f"{interaction.user.mention} ended their hosted event"
                     + (" (couldn't end the Stage - check bot permissions)" if stage_delete_failed else ""))


@slash_end.error
async def slash_end_error(interaction: discord.Interaction, error):
    msg = "Something went wrong running that command."
    print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="cohost", description="Set (or clear) the co-hosts on your last /host announcement")
@app_commands.describe(
    co_host="Who's co-hosting with you - leave all three blank to remove all co-hosts",
    co_host2="Another co-host (optional)",
    co_host3="Another co-host (optional)",
)
async def slash_cohost(interaction: discord.Interaction, co_host: discord.Member = None,
                        co_host2: discord.Member = None, co_host3: discord.Member = None):
    co_hosts = []
    for c in (co_host, co_host2, co_host3):
        if c and c.id != interaction.user.id and c.id not in {h.id for h in co_hosts}:
            co_hosts.append(c)
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This only works inside the server.", ephemeral=True)
        return

    if HOSTER_GATE_ROLE_ID and not any(r.id == HOSTER_GATE_ROLE_ID for r in interaction.user.roles):
        await interaction.followup.send("You need the Host role to use this.", ephemeral=True)
        return

    last_host = load_data().get(str(interaction.user.id), {}).get("last_host")
    if not last_host or not last_host.get("message_id") or last_host.get("ended"):
        await interaction.followup.send(no_active_event_message(last_host, "update"), ephemeral=True)
        return

    channel_id = last_host.get("channel_id")
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if channel is None:
        await interaction.followup.send("Couldn't find the events channel.", ephemeral=True)
        return

    try:
        original = await channel.fetch_message(int(last_host["message_id"]))
    except (discord.NotFound, discord.HTTPException, ValueError):
        await interaction.followup.send(
            "Couldn't find your last /host message - it may have been deleted.", ephemeral=True)
        return

    event = last_host.get("event", "")
    co_host_line = ", ".join(c.mention for c in co_hosts) if co_hosts else "-"
    vouch_targets = " ".join([interaction.user.mention] + [c.mention for c in co_hosts])
    content = re.sub(r"\*\*Co Host:\*\*.*", f"**Co Host:** {co_host_line}", original.content)
    content = re.sub(
        r"\*\*vouches:\*\*.*",
        f"**vouches:** vouch {vouch_targets} {event.lower()}",
        content,
    )
    try:
        await original.edit(content=content)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Couldn't edit the message: {e}", ephemeral=True)
        return

    with data_txn() as data:
        record = data.setdefault(str(interaction.user.id), {})
        if record.get("last_host"):
            record["last_host"]["co_host_ids"] = [str(c.id) for c in co_hosts]
            record["last_host"].pop("co_host_id", None)

    if co_hosts:
        names = ", ".join(c.mention for c in co_hosts)
        await interaction.followup.send(f"Set {names} as co-host(s) on your announcement.", ephemeral=True)
        await log_audit(f"{interaction.user.mention} set {names} as co-host(s) on their hosted event")
    else:
        await interaction.followup.send("Removed all co-hosts from your announcement.", ephemeral=True)
        await log_audit(f"{interaction.user.mention} removed all co-hosts from their hosted event")


@slash_cohost.error
async def slash_cohost_error(interaction: discord.Interaction, error):
    msg = "Something went wrong running that command."
    print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="changeevent", description="Change what event your currently hosted stage is focused on")
@app_commands.describe(event="New event type")
@app_commands.choices(event=HOST_EVENT_CHOICES)
async def slash_changeevent(interaction: discord.Interaction, event: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This only works inside the server.", ephemeral=True)
        return

    if HOSTER_GATE_ROLE_ID and not any(r.id == HOSTER_GATE_ROLE_ID for r in interaction.user.roles):
        await interaction.followup.send("You need the Host role to use this.", ephemeral=True)
        return

    new_event = event.value

    last_host = load_data().get(str(interaction.user.id), {}).get("last_host")
    if not last_host or not last_host.get("message_id") or last_host.get("ended"):
        await interaction.followup.send(no_active_event_message(last_host, "change the event for"), ephemeral=True)
        return

    old_event = last_host.get("event", "")
    if old_event == new_event:
        await interaction.followup.send(f"You're already hosting **{new_event}**.", ephemeral=True)
        return

    channel_id = last_host.get("channel_id")
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if channel is None:
        await interaction.followup.send("Couldn't find the events channel.", ephemeral=True)
        return

    try:
        original = await channel.fetch_message(int(last_host["message_id"]))
    except (discord.NotFound, discord.HTTPException, ValueError):
        await interaction.followup.send(
            "Couldn't find your last /host message - it may have been deleted.", ephemeral=True)
        return

    # Keep the live Stage's topic in sync with last_host["event"] - /end, /takeover,
    # and the natural-stage-end handler all match a live stage to its host by
    # (stage_channel_id, topic). If the topic doesn't move with the event, this
    # host's own /end would see a mismatch and think someone else's unrelated
    # event is live there instead of ending their own.
    region = last_host.get("region")
    old_topic = last_host.get("stage_topic") or old_event
    new_topic = build_stage_topic(new_event, region)
    stage_channel_id = last_host.get("stage_channel_id")
    stage_channel = guild.get_channel(int(stage_channel_id)) if stage_channel_id else None
    if not (isinstance(stage_channel, discord.StageChannel) and stage_channel.instance
            and stage_channel.instance.topic == old_topic):
        await interaction.followup.send(
            "Your event's Stage isn't live anymore, so there's nothing to change.", ephemeral=True)
        return

    try:
        await stage_channel.instance.edit(topic=new_topic)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Couldn't update the Stage topic: {e}", ephemeral=True)
        return

    event_role = event_role_for(guild, new_event)
    event_display = event_role.mention if event_role else f"**{new_event}**"
    co_host_ids = co_host_ids_from(last_host)
    vouch_targets = " ".join([interaction.user.mention] + [f"<@{cid}>" for cid in co_host_ids])
    content = re.sub(r"\*\*Event Type:\*\*.*", f"**Event Type:** {event_display}", original.content)
    content = re.sub(
        r"\*\*vouches:\*\*.*",
        f"**vouches:** vouch {vouch_targets} {new_event.lower()}",
        content,
    )
    try:
        await original.edit(content=content)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Couldn't edit the message: {e}", ephemeral=True)
        return

    with data_txn() as data:
        record = data.setdefault(str(interaction.user.id), {})
        if record.get("last_host"):
            record["last_host"]["event"] = new_event
            record["last_host"]["stage_topic"] = new_topic
        record["last_host_event"] = new_event

    try:
        await original.reply(
            f"Event changed to {event_display}",
            allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=True, replied_user=False),
        )
    except discord.HTTPException:
        pass

    await interaction.followup.send(f"Changed your event to **{new_event}**.", ephemeral=True)
    await log_audit(f"{interaction.user.mention} changed their hosted event from **{old_event}** to **{new_event}**")


@slash_changeevent.error
async def slash_changeevent_error(interaction: discord.Interaction, error):
    msg = "Something went wrong running that command."
    print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="takeover", description="Take over hosting from another host - no need to /end and re-/host")
@app_commands.describe(current_host="Who's currently hosting the event you're taking over")
async def slash_takeover(interaction: discord.Interaction, current_host: discord.Member):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This only works inside the server.", ephemeral=True)
        return

    if HOSTER_GATE_ROLE_ID and not any(r.id == HOSTER_GATE_ROLE_ID for r in interaction.user.roles):
        await interaction.followup.send("You need the Host role to use this.", ephemeral=True)
        return

    if current_host.id == interaction.user.id:
        await interaction.followup.send("You can't take over your own event.", ephemeral=True)
        return

    data = load_data()
    last_host = data.get(str(current_host.id), {}).get("last_host")
    if not last_host or not last_host.get("message_id"):
        await interaction.followup.send(f"{current_host.mention} hasn't run /host recently.", ephemeral=True)
        return

    stage_channel_id = last_host.get("stage_channel_id")
    stage_channel = guild.get_channel(int(stage_channel_id)) if stage_channel_id else None
    expected_topic = last_host.get("stage_topic") or last_host.get("event")
    stage_live = (
        isinstance(stage_channel, discord.StageChannel)
        and stage_channel.instance
        and stage_channel.instance.topic == expected_topic
    )
    if not stage_live:
        await interaction.followup.send(
            f"{current_host.mention}'s last hosted event isn't live anymore, so there's nothing to take over.",
            ephemeral=True,
        )
        return

    channel_id = last_host.get("channel_id")
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if channel is None:
        await interaction.followup.send("Couldn't find the events channel.", ephemeral=True)
        return

    try:
        original = await channel.fetch_message(int(last_host["message_id"]))
    except (discord.NotFound, discord.HTTPException, ValueError):
        await interaction.followup.send(
            "Couldn't find that host's /host message - it may have been deleted.", ephemeral=True)
        return

    event = last_host.get("event", "")
    co_host_ids = co_host_ids_from(last_host)
    vouch_targets = " ".join([interaction.user.mention] + [f"<@{cid}>" for cid in co_host_ids])
    content = re.sub(r"\*\*Event Host:\*\*.*", f"**Event Host:** {interaction.user.mention}", original.content)
    content = re.sub(
        r"\*\*vouches:\*\*.*",
        f"**vouches:** vouch {vouch_targets} {event.lower()}",
        content,
    )
    try:
        await original.edit(content=content)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Couldn't edit the message: {e}", ephemeral=True)
        return

    # Move the tracking from the outgoing host to the incoming one. Keep the outgoing
    # host's record (marked ended + who took over) instead of wiping it, so their
    # /end, /reping, /cohost give an accurate "X took over" message instead of the
    # misleading "you haven't run /host yet".
    with data_txn() as data:
        old_record = data.setdefault(str(current_host.id), {})
        if old_record.get("last_host"):
            old_record["last_host"]["ended"] = True
            old_record["last_host"]["stage_channel_id"] = None
            old_record["last_host"]["taken_over_by"] = str(interaction.user.id)
        new_record = data.setdefault(str(interaction.user.id), {})
        runs = new_record.get("host_runs", [])
        runs.append(datetime.now(timezone.utc).isoformat())
        new_record["host_runs"] = runs[-100:]
        new_record["host_runs_total"] = new_record.get("host_runs_total", 0) + 1
        new_record["last_host_event"] = event
        new_record["last_host"] = {
            "event": event,
            "region": last_host.get("region"),
            "stage_topic": last_host.get("stage_topic") or event,
            "message_id": last_host.get("message_id"),
            "channel_id": last_host.get("channel_id"),
            "co_host_ids": co_host_ids,
            "stage_channel_id": last_host.get("stage_channel_id"),
        }

    await revoke_stage_perms(guild, current_host, reason=f"Handed off hosting to {interaction.user}")
    granted = await grant_stage_perms(guild, interaction.user, reason=f"Took over hosting from {current_host}")

    speaker_note = ""
    stage_channel_id = last_host.get("stage_channel_id")
    if stage_channel_id:
        stage_channel = guild.get_channel(int(stage_channel_id))
        if isinstance(stage_channel, discord.StageChannel):
            try:
                if current_host.voice and current_host.voice.channel and current_host.voice.channel.id == stage_channel.id:
                    await current_host.edit(suppress=True)
            except discord.HTTPException:
                pass
            try:
                if interaction.user.voice and interaction.user.voice.channel and interaction.user.voice.channel.id == stage_channel.id:
                    await interaction.user.edit(suppress=False)
                elif interaction.user.voice:
                    await interaction.user.move_to(stage_channel)
                    await interaction.user.edit(suppress=False)
                else:
                    speaker_note = " Join the stage yourself to be promoted to speaker - I can't pull you in from outside voice."
            except discord.HTTPException:
                speaker_note = " Couldn't update your speaker status on the stage - do it manually if needed."

    notice = f"Took over hosting **{event}** from {current_host.mention}."
    if not granted:
        notice += f" Couldn't grant **{STAGE_PERMS_ROLE_NAME}**."
    notice += speaker_note
    await interaction.followup.send(notice, ephemeral=True)
    await log_audit(f"{interaction.user.mention} took over hosting **{event}** from {current_host.mention}")


@slash_takeover.error
async def slash_takeover_error(interaction: discord.Interaction, error):
    msg = "Something went wrong running that command."
    print(f"[Slash] Error: {error}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="hosttest", description="Send a test host announcement to check the channel/role setup (Manage Server only)")
@app_commands.describe(event="Event to test the role lookup with (optional)")
@app_commands.choices(event=HOST_EVENT_CHOICES)
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_hosttest(interaction: discord.Interaction, event: str = "Test Event"):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This only works inside the server.", ephemeral=True)
        return

    channel = bot.get_channel(HOST_TEST_CHANNEL_ID)
    if channel is None:
        await interaction.followup.send(
            f"Couldn't find the test channel (ID `{HOST_TEST_CHANNEL_ID}`).", ephemeral=True)
        return

    region = "EU/NA/Asia (test)"
    security_region = "EU/NA/Asia/SA/OCE (test)"
    event_role = event_role_for(guild, event)
    event_display = event_role.mention if event_role else f"**{event}** (no matching role found)"

    def check_roles(mapping):
        found, missing = [], []
        for region_name, role_name in mapping.items():
            role = discord.utils.get(guild.roles, name=role_name)
            (found if role else missing).append(region_name)
        return found, missing

    support_found, support_missing = check_roles(REGION_ROLE_NAME)
    security_found, security_missing = check_roles(SECURITY_REGION_ROLE_NAME)

    message = build_host_message(
        interaction.user, [interaction.user], region, security_region, event, event_display,
        "Test stage - ignore", "This is a test post from /hosttest. Ignore it.", guild=guild, test=True)
    await channel.send(content=message, allowed_mentions=discord.AllowedMentions.none())
    await interaction.followup.send(
        f"Test posted in {channel.mention} (nobody was pinged).\n"
        f"Support roles found: " + (", ".join(support_found) or "none")
        + (f". Missing: {', '.join(support_missing)}" if support_missing else "") + "\n"
        f"Security roles found: " + (", ".join(security_found) or "none")
        + (f". Missing: {', '.join(security_missing)}" if security_missing else "") + "\n"
        + (f"Event role: **{event_role.name}**" if event_role else f"No role found named '{event}'."),
        ephemeral=True,
    )


@slash_hosttest.error
async def slash_hosttest_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need the Manage Server permission to use that."
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
