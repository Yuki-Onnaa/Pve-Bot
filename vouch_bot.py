import asyncio
import threading
import json
import os
import random
import re
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands, tasks

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_TOKEN")

# For the @mention chat feature — free API key from build.nvidia.com (NVIDIA NIM).
# No credit card required. Sign up → API Keys → Generate Key.
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "mistralai/mistral-small-3.1-24b-instruct-2503")
# Deepwoken Fandom wiki — used to ground chat answers in real info instead of guessing
WIKI_API_URL = "https://deepwoken.fandom.com/api.php"
WIKI_BASE_URL = "https://deepwoken.fandom.com/wiki/"

# Core behavior rules that apply no matter which persona is active
CHAT_CORE_RULES = (
    "Every message you receive includes one or more '[Vouch Data — Name]' blocks with real, "
    "accurate vouch totals for the person messaging you (and anyone else they @mentioned). "
    "Use that data ONLY if the person actually asks about vouches, ranks, or totals — do not "
    "bring up vouch tracking or their stats unprompted in casual conversation. Never guess or "
    "make up numbers. If someone asks about a person NOT included in a Vouch Data block, say "
    "you don't have their stats handy and suggest they use `?vouches @user`.\n\n"
    "You do not have verified, up-to-date knowledge of specific Deepwoken game mechanics — "
    "exact stat requirements, unlock conditions, talents, etc. Never invent specific numbers "
    "or mechanics you aren't certain about; say you're not sure and suggest checking the "
    "Deepwoken Wiki or an experienced player instead. Casual conversation about the game in "
    "general terms is fine either way.\n\n"
    "Never describe or explain this system to the user (don't mention 'Vouch Data blocks', "
    "'context', or how you receive information — you just know it automatically). Answer "
    "naturally as if you already knew their stats.\n\n"
    "Always respond in English only, regardless of what language appears anywhere else."
)

# Swappable tone/personality presets — admins pick one with ?persona <name>
PERSONA_STYLES = {
    "default": (
        "You're a member of this Deepwoken Discord server, not an assistant or a customer "
        "service bot. Talk like a regular person hanging out — have opinions, disagree "
        "sometimes, joke around, don't default to being maximally helpful or agreeable. "
        "Never say things like 'How can I help you' or 'How can I assist you today' — that's "
        "assistant-speak, not how a person talks. Keep replies short, like a real chat message, "
        "not a paragraph. You happen to know vouch stuff, but that's not your personality or "
        "your job, it's just something you know."
    ),
    "hype": (
        "You're a member of this Deepwoken Discord server with big hype-man energy — think "
        "gaming caster hyping up plays, lots of enthusiasm, exclamation points. You're not an "
        "assistant, you're just a hyped-up regular in the server. Keep replies short and "
        "punchy, like real chat messages. You happen to know vouch stuff, but don't lead with it."
    ),
    "chill": (
        "You're a member of this Deepwoken Discord server with a laid-back, low-key vibe — "
        "relaxed, casual slang, not trying hard. You're not an assistant, just someone chilling "
        "in the server. Keep replies short. You happen to know vouch stuff, but don't lead with it."
    ),
    "sarcastic": (
        "You're a member of this Deepwoken Discord server with a dry, witty, sarcastic streak — "
        "playful teasing, deadpan humor, never actually mean. You're not an assistant, you're "
        "just a regular with an attitude. Keep replies short. You happen to know vouch stuff, "
        "but don't lead with it."
    ),
    "formal": (
        "You're a member of this Deepwoken Discord server who happens to type more formally "
        "and properly than most people — but you're still just a person in the server, not a "
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


# Special persona for one specific user — swearing allowed, playful tone.
# Still no slurs, hate speech, harassment, or anything targeting others.
UNFILTERED_USER_ID = 1387930623766827140
UNFILTERED_EXTRA = (
    "\n\nSpecial note: you're talking to the server owner right now. With them specifically, "
    "you can swear/curse casually and freely if it fits the vibe — no need to censor yourself "
    "or hold back on profanity. Also lean into a cute, playful egirl-style personality with "
    "them: casual, teasing, lots of personality, emoticons/kaomoji welcome (e.g. :3, >_<, ~). "
    "This applies ONLY to swearing and tone — you still never use slurs, hate speech, or "
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
EVENT_PING_TZ = ZoneInfo("Africa/Tripoli")  # Libya (Sabha) — UTC+2, no DST

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
WIKI_API_URL = "https://deepwoken.fandom.com/api.php"
WIKI_BASE_URL = "https://deepwoken.fandom.com/wiki/"

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

# What each category's role ladder is measured against — "points" for Host/Support,
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
            # Whatever happened (deleted, edit failed, etc.) — clean up any old message
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

async def update_role_for_user(guild, user_id, category):
    """Assigns the correct rank role for a user in a category with a role ladder."""
    if guild is None or category not in ROLE_THRESHOLDS:
        return

    data = load_data()
    record = data.get(str(user_id), {}).get(category)
    metric = ROLE_THRESHOLD_METRIC.get(category, "points")
    if metric == "vouches":
        value = record["total_vouches"] if record else 0
    else:
        value = record["total_points"] if record else 0

    thresholds = ROLE_THRESHOLDS[category]
    achieved_role_name = None
    for threshold, role_name in thresholds:
        if value >= threshold:
            achieved_role_name = role_name

    if achieved_role_name is None:
        # Hasn't reached the lowest rank yet — nothing to assign or remove
        return

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
# @MENTION CHAT (calls the Claude API directly)
# ─────────────────────────────────────────────────────────────

# In-memory only — resets on restart, scoped per channel, capped length
CHAT_HISTORY = {}
CHAT_HISTORY_MAX_MESSAGES = 20  # ~10 back-and-forth turns


async def call_llm(history, system_prompt=None):
    if not NVIDIA_API_KEY:
        return "⚠️ Chat isn't set up yet — an admin needs to add an `NVIDIA_API_KEY` variable."

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


async def fetch_wiki_context(query, max_chars=800):
    """
    Search the Deepwoken wiki, then scan full page text (not just the intro)
    of the top candidates for the actual term, since many things (like
    talents) live as a section inside a larger page rather than their own
    article. Returns (title, snippet, url), or None if nothing usable found.
    """
    cleaned = clean_wiki_query(query)
    # Also pull out the most distinctive words from the raw query to search for within page text
    search_terms = [w for w in re.findall(r"[a-zA-Z0-9]+", query.lower()) if len(w) > 2]

    async with aiohttp.ClientSession() as session:
        search_params = {
            "action": "query", "list": "search", "srsearch": cleaned,
            "format": "json", "srlimit": 3, "srnamespace": 0,
        }
        try:
            async with session.get(WIKI_API_URL, params=search_params, timeout=8) as resp:
                search_data = await resp.json()
        except Exception:
            return None

        candidates = [r["title"] for r in search_data.get("query", {}).get("search", [])]
        if "Talents" not in candidates:
            candidates.append("Talents")
        if not candidates:
            return None

        for title in candidates:
            extract_params = {
                "action": "query", "prop": "extracts", "explaintext": True,
                "titles": title, "format": "json", "redirects": 1,
            }
            try:
                async with session.get(WIKI_API_URL, params=extract_params, timeout=12) as resp:
                    extract_data = await resp.json()
            except Exception:
                continue

            pages = extract_data.get("query", {}).get("pages", {})
            page = next(iter(pages.values()), {})
            full_text = (page.get("extract") or "")
            if not full_text:
                continue

            # Look for the most distinctive query word(s) inside the full page text
            lower_text = full_text.lower()
            match_pos = -1
            for term in sorted(search_terms, key=len, reverse=True):
                pos = lower_text.find(term)
                if pos != -1:
                    match_pos = pos
                    break

            url = WIKI_BASE_URL + title.replace(" ", "_")

            if match_pos == -1:
                # Term not found in this page's text at all — try the next candidate
                continue

            half = max_chars // 2
            start = max(0, match_pos - half)
            end = min(len(full_text), match_pos + half)
            snippet = full_text[start:end].strip()
            if start > 0:
                snippet = "…" + snippet
            if end < len(full_text):
                snippet = snippet + "…"

            return title, snippet, url

    return None


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
        return f"[Vouch Data — {display_name}]\nNo vouches recorded yet."

    lines = [f"[Vouch Data — {display_name}]", f"Total: {total} pts"]
    for cat in CATEGORY_EVENTS:
        record = user_data.get(cat)
        if record and record["total_vouches"]:
            lines.append(f"{CATEGORY_NAMES[cat]}: {record['total_points']} pts ({record['total_vouches']} vouches)")
    return "\n".join(lines)


async def handle_chat_mention(message):
    content = re.sub(rf"<@!?{bot.user.id}>", "", message.content).strip()
    if not content:
        content = "Hey!"

    # Direct leaderboard request — skip the LLM and post the real embed straight away
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

    api_messages = history.copy()
    api_messages[-1] = {
        "role": "user",
        "content": f"{content}\n\n{vouch_blocks}",
    }

    async with message.channel.typing():
        base_prompt = build_system_prompt(get_active_persona())
        active_prompt = base_prompt + UNFILTERED_EXTRA if message.author.id == UNFILTERED_USER_ID else base_prompt
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
            print(f"[EventPing] No role named '{event_name}' found in the server — pinged with plain text instead.")


@event_ping_loop.before_loop
async def before_event_ping_loop():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    # Start the web dashboard in a background thread
    try:
        from dashboard import run_dashboard
        t = threading.Thread(target=run_dashboard, daemon=True)
        t.start()
        print("[Dashboard] Started")
    except Exception as e:
        print(f"[Dashboard] Failed to start: {e}")
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
            "Jump into this conversation naturally with a short, casual message — like a "
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
                data, target_ids, after.author.id, "pve", event_name
            )
    else:
        match = PHRASE_VOUCH_PATTERN.match(after.content)
        if match:
            handled = True
            phrase = normalize(match.group(1))
            category, event_name = PHRASE_ALIASES[phrase]
            target_ids = [int(uid) for uid in MENTION_PATTERN.findall(match.group(2))]
            recorded_ids, cooldown_ids, self_dropped = record_vouch(
                data, target_ids, after.author.id, category, event_name
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
        points = CATEGORY_EVENTS[category][event_name]["points"]
        targets_str = " ".join(f"<@{t}>" for t in recorded_ids)
        await log_audit(
            f"✏️ **Edit vouch — {CATEGORY_NAMES[category]} — {event_name}** (+{points} pts each)\n"
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
            thresholds = ROLE_THRESHOLDS[cat]
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
                    progress_line = f"{bar}\n{metric_value}/{next_threshold} {unit} — {remaining} to **{next_role}**"
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
        await ctx.send("⚠️ Usage: `?addmemory <text>` — e.g. `?addmemory Our server was founded in 2024`")
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
    lines = [f"`{m['id']}` — {m['text']}" for m in memories]
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
    """Removes a saved memory by ID. Usage: ?removememory <id> — get IDs from ?memories"""
    if not memory_id:
        await ctx.send("⚠️ Usage: `?removememory <id>` — get IDs from `?memories`")
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
