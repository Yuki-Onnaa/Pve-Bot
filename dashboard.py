import csv
import io
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

import urllib.error
import urllib.request
from flask import Flask, Response, session, redirect, request, jsonify, render_template_string

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

DATA_FILE = os.environ.get("DATA_FILE", "/data/vouches.json")
_file_lock = threading.Lock()

# ── Discord OAuth2 ──
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
# e.g. https://dashboard.sapph.xyz/callback  - must match the Discord dev portal exactly
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "")
# Optional: restrict the dashboard to a single server. Empty = any server you admin.
REQUIRED_GUILD_ID = os.environ.get("GUILD_ID", "").strip()
# Optional: extra allowlist of Discord user IDs, comma separated. Empty = no extra filter.
ALLOWED_USER_IDS = {
    u.strip() for u in os.environ.get("ALLOWED_USER_IDS", "").split(",") if u.strip()
}

# Embedded dashboard logo (base64 so it needs no hosting).
LOGO_SRC = "data:image/jpeg;base64,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"

API_BASE = "https://discord.com/api/v10"
CDN_BASE = "https://cdn.discordapp.com"
PERM_ADMINISTRATOR = 0x8

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET", uuid.uuid4().hex)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
)

CATEGORY_NAMES = {"pve": "Host", "security": "Security", "support": "Support"}
ALL_CATEGORIES = list(CATEGORY_NAMES.keys())

FALLBACK_EVENT_POINTS = {
    "pve": {
        "Enmity": 1.5, "Elder": 2, "Titus": 3, "Hellmode": 15,
        "Deep Champion": 15, "Diluvian W (25)": 3, "Diluvian W (50)": 10,
        "Parasol": 5, "Layer 2 (1)": 3, "Layer 2 (2)": 7, "Other Bosses": 1,
    },
    "security": {
        "Security Vouch": 1, "Depths Vouch": 1.5,
        "Defense Vouch": 1, "Depths Defense Vouch": 1.5,
    },
    "support": {
        "Support Vouch": 1, "Backup Vouch": 2, "Depths Safe Vouch": 5,
    },
}

CATEGORY_EVENTS = FALLBACK_EVENT_POINTS  # kept for older references

PERSONAS = ["default", "hype", "chill", "sarcastic", "formal"]

# Built-in ?commands that custom commands may not shadow
RESERVED_COMMANDS = {
    "shutdown", "sleep", "awake", "wakeup", "profile", "cleanleaderboards",
    "testeventping", "postleaderboards", "refreshleaderboards", "addmemory",
    "remember", "memories", "removememory", "forget", "persona", "personas",
    "leaderboard", "sleaderboard", "suleaderboard", "vouches", "addvouch",
    "backfill", "backfillhistory", "revertbackfill", "undobackfill",
    "syncvouches", "scanhistory", "commands", "help",
}

DEFAULT_CONFIG = {
    "pve_channel_id": 1529113596657799178,
    "security_channel_id": 1527834552150659103,
    "support_channel_id": 1527834504658550924,
    "live_leaderboard_channel_id": 1530286316628217906,
    "audit_log_channel_id": 1530317395669815438,
    "event_ping_channel_id": 1529142467658649640,
    "chime_in_channel_id": 1478405937080307806,
}

DEFAULT_EVENT_SCHEDULE = {
    "Carnival of Hearts": ["07:00","08:30","10:00","11:30","13:00","14:30","16:00","17:30","19:00","20:30","22:00","23:30","01:00","02:30","04:00","05:30"],
    "Interluminary Parasol": ["07:30","09:00","10:30","12:00","13:30","15:00","16:30","18:00","19:30","21:00","22:30","00:00","01:30","03:00","04:30","06:00"],
    "Battle Royale": ["08:00","09:30","11:00","12:30","14:00","15:30","17:00","18:30","20:00","21:30","23:00","00:30","02:00","03:30","05:00","06:30"],
    "Doom of Caeranthil": ["07:00","09:00","11:00","13:00","15:00","17:00","19:00","21:00","23:00","01:00","03:00","05:00"],
}

# ─────────────────────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────────────────────

def load_data():
    with _file_lock:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        return {}

def save_data(data):
    with _file_lock:
        os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

def user_records(data):
    for uid, rec in data.items():
        if uid.isdigit():
            yield uid, rec

def combined_total(user_data):
    return sum(user_data.get(cat, {}).get("total_points", 0) for cat in ALL_CATEGORIES)

def ensure_user_cat(data, uid, category):
    uid = str(uid)
    data.setdefault(uid, {})
    if category not in data[uid]:
        data[uid][category] = {"total_points": 0, "total_vouches": 0, "events": {}, "cooldowns": {}, "log": []}
    for e in CATEGORY_EVENTS[category]:
        data[uid][category]["events"].setdefault(e, 0)
    return data[uid][category]

# ─────────────────────────────────────────────────────────────
# SITE ACTIVITY
# Page loads are counted in memory and flushed to disk periodically, so a busy
# day does not mean rewriting the whole JSON file on every request.
# ─────────────────────────────────────────────────────────────

ANALYTICS_RETENTION_DAYS = 120
_visit_buffer = {}
_visit_lock = threading.Lock()
_last_flush = [0.0]


def record_visit(uid, page):
    """Count one page view. Cheap: memory only, flushed on a timer."""
    day = datetime.now(timezone.utc).date().isoformat()
    with _visit_lock:
        bucket = _visit_buffer.setdefault(day, {})
        entry = bucket.setdefault(str(uid), {"views": 0, "pages": {}})
        entry["views"] += 1
        entry["pages"][page] = entry["pages"].get(page, 0) + 1
        due = (time.time() - _last_flush[0]) > 45 or sum(
            len(v) for v in _visit_buffer.values()
        ) > 40
    if due:
        flush_visits()


def flush_visits():
    """Fold the in-memory counts into the data file."""
    with _visit_lock:
        if not _visit_buffer:
            _last_flush[0] = time.time()
            return
        pending = {day: {u: dict(v) for u, v in users.items()} for day, users in _visit_buffer.items()}
        _visit_buffer.clear()
        _last_flush[0] = time.time()

    data = load_data()
    analytics = data.setdefault("_analytics", {})
    days = analytics.setdefault("days", {})
    last_seen = analytics.setdefault("last_seen", {})
    now_iso = datetime.now(timezone.utc).isoformat()

    for day, users in pending.items():
        stored_day = days.setdefault(day, {})
        for uid, entry in users.items():
            slot = stored_day.setdefault(uid, {"views": 0, "pages": {}})
            slot["views"] += entry["views"]
            for page, count in entry["pages"].items():
                slot["pages"][page] = slot["pages"].get(page, 0) + count
            last_seen[uid] = now_iso

    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=ANALYTICS_RETENTION_DAYS)).isoformat()
    for day in [d for d in days if d < cutoff]:
        del days[day]

    save_data(data)


# ─────────────────────────────────────────────────────────────
# BOT BRIDGE
# The dashboard runs in a thread inside the bot process, so it can borrow the
# bot's member cache and schedule coroutines on its event loop.
# ─────────────────────────────────────────────────────────────

_bridge = {
    "bot": None, "loop": None, "guild_id": None,
    "thresholds": {}, "metric": {}, "resync": None, "events": {},
}
_name_cache = {}

def set_bot(bot, loop=None, thresholds=None, metric=None, resync=None, guild_id=None, events=None):
    """Called once from the bot's on_ready so the dashboard can resolve names etc."""
    _bridge["bot"] = bot
    _bridge["loop"] = loop
    _bridge["thresholds"] = thresholds or {}
    _bridge["metric"] = metric or {}
    _bridge["resync"] = resync
    _bridge["guild_id"] = guild_id
    _bridge["events"] = events or {}
    _name_cache.clear()


# ─────────────────────────────────────────────────────────────
# ECONOMY (event points and rank ladders, editable from the dashboard)
# Stored overrides win; the bot's constants are the fallback.
# ─────────────────────────────────────────────────────────────

def default_event_points():
    """The bot's CATEGORY_EVENTS flattened to {category: {event: points}}."""
    if _bridge["events"]:
        return {
            cat: {name: cfg.get("points", 0) for name, cfg in events.items()}
            for cat, events in _bridge["events"].items()
        }
    return {cat: dict(events) for cat, events in FALLBACK_EVENT_POINTS.items()}


def default_ranks():
    return {cat: [list(row) for row in ladder] for cat, ladder in (_bridge["thresholds"] or {}).items()}


def get_economy(data=None):
    """Merged view of event points and rank ladders."""
    data = load_data() if data is None else data
    stored = data.get("_economy", {})
    events = default_event_points()
    events.update({c: dict(v) for c, v in (stored.get("events") or {}).items()})
    ranks = default_ranks()
    ranks.update({c: [list(r) for r in v] for c, v in (stored.get("ranks") or {}).items()})
    return {"events": events, "ranks": ranks}


def event_points(category, event, data=None):
    return get_economy(data)["events"].get(category, {}).get(event, 0)

def resolve_user(uid):
    """Discord display name + avatar for a user ID, falling back to the raw ID."""
    uid = str(uid)
    if uid in _name_cache:
        return _name_cache[uid]
    info = {"name": uid, "avatar": "", "resolved": False}
    bot = _bridge["bot"]
    if bot is not None:
        try:
            member = None
            for guild in getattr(bot, "guilds", []):
                member = guild.get_member(int(uid))
                if member:
                    break
            user = member or bot.get_user(int(uid))
            if user is not None:
                info = {
                    "name": getattr(user, "display_name", None) or user.name,
                    "avatar": str(user.display_avatar.url) if getattr(user, "display_avatar", None) else "",
                    "resolved": True,
                }
                _name_cache[uid] = info
        except (ValueError, AttributeError):
            pass
    return info

def rank_progress(category, points, vouches, data=None):
    """Current rank role, next rank and how far along the user is."""
    ladder = get_economy(data)["ranks"].get(category) or []
    if not ladder:
        return None
    value = vouches if _bridge["metric"].get(category) == "vouches" else points
    current = None
    current_at = 0
    nxt = None
    for threshold, name in ladder:
        if value >= threshold:
            current, current_at = name, threshold
        elif nxt is None:
            nxt = (threshold, name)
    if nxt is None:
        pct = 100
        remaining = 0
        next_name = None
        next_at = None
    else:
        next_at, next_name = nxt
        span = max(1, next_at - current_at)
        pct = max(0, min(100, round(((value - current_at) / span) * 100)))
        remaining = round(max(0, next_at - value), 1)
    return {
        "current": current, "next": next_name, "next_at": next_at,
        "pct": pct, "remaining": remaining, "value": round(value, 1),
    }

def run_on_bot(coro):
    """Schedule a coroutine on the bot's loop from this Flask thread."""
    loop = _bridge["loop"]
    if loop is None or coro is None:
        return None
    import asyncio
    return asyncio.run_coroutine_threadsafe(coro, loop)

# ─────────────────────────────────────────────────────────────
# DISCORD OAUTH2  (login with Discord, Administrator required)
# ─────────────────────────────────────────────────────────────

def oauth_configured():
    return bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI)

def avatar_url(user):
    if user.get("avatar"):
        ext = "gif" if str(user["avatar"]).startswith("a_") else "png"
        return f"{CDN_BASE}/avatars/{user['id']}/{user['avatar']}.{ext}?size=128"
    index = (int(user["id"]) >> 22) % 6
    return f"{CDN_BASE}/embed/avatars/{index}.png"

def guild_icon_url(guild):
    if guild.get("icon"):
        return f"{CDN_BASE}/icons/{guild['id']}/{guild['icon']}.png?size=128"
    return ""

def is_admin_guild(guild):
    """True if the logged-in user is the owner or holds Administrator in this guild."""
    if guild.get("owner"):
        return True
    try:
        return (int(guild.get("permissions", 0)) & PERM_ADMINISTRATOR) == PERM_ADMINISTRATOR
    except (ValueError, TypeError):
        return False

def discord_get(path, token):
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "MatzysOverseer (dashboard, 1.0)"},
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode())

def is_admin():
    return bool(session.get("user")) and session.get("role") == "admin" and bool(session.get("admin_guilds"))


def admin_required(f):
    """Blocks anything that isn't a Discord-authenticated server administrator."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def member_required(f):
    """Any signed-in member of the server. Admins pass this too."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

@app.route("/login")
def login():
    if session.get("user") and session.get("admin_guilds"):
        return redirect("/")
    return render_template_string(
        LOGIN_HTML,
        configured=oauth_configured(),
        error=request.args.get("error", ""),
    )

@app.route("/login/discord")
def login_discord():
    if not oauth_configured():
        return redirect("/login?error=" + urllib.parse.quote(
            "Discord login isn't set up yet. Add DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI."
        ))
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = urllib.parse.urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent",
    })
    return redirect(f"https://discord.com/oauth2/authorize?{params}")

@app.route("/callback")
def oauth_callback():
    def fail(msg):
        return redirect("/login?error=" + urllib.parse.quote(msg))

    if request.args.get("error"):
        return fail("Discord login was cancelled.")

    state = request.args.get("state", "")
    if not state or state != session.pop("oauth_state", None):
        return fail("Login expired or was tampered with. Try again.")

    code = request.args.get("code", "")
    if not code:
        return fail("Discord didn't return a login code. Try again.")

    payload = urllib.parse.urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }).encode()
    token_req = urllib.request.Request(
        f"{API_BASE}/oauth2/token",
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "MatzysOverseer (dashboard, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(token_req, timeout=15) as res:
            access_token = json.loads(res.read().decode())["access_token"]
        user = discord_get("/users/@me", access_token)
        guilds = discord_get("/users/@me/guilds", access_token)
    except urllib.error.HTTPError as e:
        print(f"[Dashboard] Discord OAuth error {e.code}: {e.read()[:300]}")
        return fail("Discord rejected the login. Check your client ID, secret and redirect URI.")
    except (urllib.error.URLError, TimeoutError):
        return fail("Couldn't reach Discord. Try again in a moment.")
    except (KeyError, ValueError):
        return fail("Discord returned an unexpected response. Try again.")

    admin_guilds = [g for g in guilds if is_admin_guild(g)]
    if REQUIRED_GUILD_ID:
        admin_guilds = [g for g in admin_guilds if str(g["id"]) == REQUIRED_GUILD_ID]
    if ALLOWED_USER_IDS and str(user["id"]) not in ALLOWED_USER_IDS:
        admin_guilds = []  # allowlist gates admin access only, not member access

    # Members just need to share a server with the bot.
    bot_guild_ids = {str(g.id) for g in getattr(_bridge["bot"], "guilds", [])}
    if REQUIRED_GUILD_ID:
        in_server = any(str(g["id"]) == REQUIRED_GUILD_ID for g in guilds)
    elif bot_guild_ids:
        in_server = any(str(g["id"]) in bot_guild_ids for g in guilds)
    else:
        in_server = True  # bot not ready yet, do not lock people out

    if not admin_guilds and not in_server:
        return fail("You are not in the bot's server, so there is nothing here for you yet.")

    session["role"] = "admin" if admin_guilds else "member"
    session["user"] = {
        "id": str(user["id"]),
        "username": user.get("global_name") or user.get("username", "Admin"),
        "handle": user.get("username", ""),
        "avatar": avatar_url(user),
    }
    session["admin_guilds"] = [
        {"id": str(g["id"]), "name": g["name"], "icon": guild_icon_url(g)}
        for g in sorted(admin_guilds, key=lambda g: g["name"].lower())
    ]
    if session["admin_guilds"]:
        session["guild_id"] = session["admin_guilds"][0]["id"]
    session.permanent = True
    return redirect("/" if session["role"] == "admin" else "/profile")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
def index():
    if not session.get("user"):
        return redirect("/login")
    if not is_admin():
        return redirect("/profile")
    record_visit(session["user"]["id"], "dashboard")
    return render_template_string(DASHBOARD_HTML)


@app.route("/profile")
@member_required
def profile_page():
    record_visit(session["user"]["id"], "profile")
    return render_template_string(PROFILE_HTML, user=session["user"], is_admin=is_admin())


@app.route("/api/profile")
@member_required
def api_profile():
    uid = str(session["user"]["id"])
    data = load_data()
    record = data.get(uid, {})
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).isoformat()
    prev_start = (now - timedelta(days=14)).isoformat()

    categories = []
    recent = []
    this_week = 0.0
    last_week = 0.0

    economy = get_economy(data)
    days = 30
    today = now.date()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    day_index = {d: i for i, d in enumerate(labels)}
    series = {}

    for cat in ALL_CATEGORIES:
        cat_rec = record.get(cat) or {}
        points = cat_rec.get("total_points", 0)
        vouches = cat_rec.get("total_vouches", 0)
        metric = (_bridge["metric"] or {}).get(cat, "points")
        value = vouches if metric == "vouches" else points

        # leaderboard position and the people either side of you
        board = sorted(
            ((uid2, r.get(cat, {}).get("total_points", 0)) for uid2, r in user_records(data)),
            key=lambda kv: kv[1], reverse=True,
        )
        board = [row for row in board if row[1] > 0]
        ranked = [p for _, p in board]
        position = None
        rivals = {"above": None, "below": None}
        for i, (uid2, pts) in enumerate(board):
            if uid2 == uid:
                position = i + 1
                if i > 0:
                    who = resolve_user(board[i - 1][0])
                    rivals["above"] = {"name": who["name"], "gap": round(board[i - 1][1] - pts, 1)}
                if i + 1 < len(board):
                    who = resolve_user(board[i + 1][0])
                    rivals["below"] = {"name": who["name"], "gap": round(pts - board[i + 1][1], 1)}
                break

        # every rank still ahead of you, and what it would take
        ladder = economy["ranks"].get(cat) or []
        events = economy["events"].get(cat) or {}
        best = sorted(((p, n) for n, p in events.items() if p > 0), reverse=True)[:4]
        goals = []
        for at, role_name in ladder:
            if at <= value:
                continue
            short = round(at - value, 1)
            if metric == "vouches":
                routes = [{"event": "any vouch", "need": int(short) + (1 if short % 1 else 0)}]
            else:
                routes = [{"event": n, "need": int(-(-short // p))} for p, n in best]
            goals.append({"role": role_name, "at": at, "short": short, "routes": routes})

        # daily points for the chart
        daily = [0.0] * days
        for entry in cat_rec.get("log", []):
            day = str(entry.get("time", ""))[:10]
            if day in day_index:
                daily[day_index[day]] += float(entry.get("points", 0) or 0)
        series[cat] = [round(v, 1) for v in daily]

        for entry in cat_rec.get("log", []):
            when = entry.get("time", "")
            pts = float(entry.get("points", 0) or 0)
            if when >= week_start:
                this_week += pts
            elif when >= prev_start:
                last_week += pts
            recent.append({
                "category": cat, "category_name": CATEGORY_NAMES[cat],
                "event": entry.get("event", ""), "points": pts,
                "time": when, "by": entry.get("by_name") or "",
            })

        categories.append({
            "key": cat,
            "name": CATEGORY_NAMES[cat],
            "points": round(points, 1),
            "vouches": vouches,
            "metric": metric,
            "position": position,
            "of": len(ranked),
            "rivals": rivals,
            "goals": goals,
            "rank": rank_progress(cat, points, vouches, data),
            "events": {k: v for k, v in (cat_rec.get("events") or {}).items() if v > 0},
        })

    recent.sort(key=lambda e: e["time"], reverse=True)

    # personal bests, from the same log entries
    by_day = {}
    for e in recent:
        by_day[e["time"][:10]] = by_day.get(e["time"][:10], 0) + e["points"]
    best_day = max(by_day.items(), key=lambda kv: kv[1]) if by_day else None
    active_days = len(by_day)
    first_seen = min((e["time"] for e in recent), default="")

    return jsonify({
        "user": session["user"],
        "total": round(combined_total(record), 1),
        "categories": categories,
        "recent": recent[:20],
        "this_week": round(this_week, 1),
        "last_week": round(last_week, 1),
        "has_data": bool(record),
        "chart": {"labels": labels, "series": series},
        "bests": {
            "best_day": {"date": best_day[0], "points": round(best_day[1], 1)} if best_day else None,
            "active_days": active_days,
            "first_seen": first_seen[:10],
            "total_vouches": sum(c["vouches"] for c in categories),
        },
    })


def _own_history(uid, args):
    """Every vouch this member has received, newest first, with filters applied."""
    data = load_data()
    record = data.get(str(uid), {})
    category = args.get("category", "")
    q = args.get("q", "").lower().strip()
    try:
        days = int(args.get("days", 0))
    except (ValueError, TypeError):
        days = 0
    cutoff = ""
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = []
    for cat in ALL_CATEGORIES:
        if category and cat != category:
            continue
        for e in (record.get(cat) or {}).get("log", []):
            when = e.get("time", "")
            if cutoff and when < cutoff:
                continue
            event = str(e.get("event", ""))
            by = e.get("by_name") or ""
            if q and q not in event.lower() and q not in by.lower():
                continue
            rows.append({
                "category": cat, "category_name": CATEGORY_NAMES[cat], "event": event,
                "points": float(e.get("points", 0) or 0), "count": e.get("count", 1),
                "by": by, "time": when, "backfilled": e.get("backfilled", False),
            })
    rows.sort(key=lambda r: r["time"], reverse=True)
    return rows


@app.route("/api/profile/history")
@member_required
def api_profile_history():
    rows = _own_history(session["user"]["id"], request.args)
    return jsonify({"rows": rows[:500], "total": len(rows),
                    "points": round(sum(r["points"] for r in rows), 1)})


@app.route("/api/profile/history.csv")
@member_required
def api_profile_history_csv():
    rows = _own_history(session["user"]["id"], request.args)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "category", "event", "points", "count", "given_by", "backfilled"])
    for r in rows:
        writer.writerow([r["time"], r["category_name"], r["event"], r["points"],
                         r["count"], r["by"], "yes" if r["backfilled"] else "no"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=my-vouches-{stamp}.csv"})

# ── API: Session ──

@app.route("/api/me")
@admin_required
def api_me():
    guilds = session.get("admin_guilds", [])
    current = next((g for g in guilds if g["id"] == session.get("guild_id")), guilds[0])
    return jsonify({"user": session["user"], "guilds": guilds, "guild": current})

@app.route("/api/guild", methods=["POST"])
@admin_required
def api_select_guild():
    gid = str((request.json or {}).get("guild_id", ""))
    if not any(g["id"] == gid for g in session.get("admin_guilds", [])):
        return jsonify({"error": "You don't administrate that server"}), 403
    session["guild_id"] = gid
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

# ── API: Status ──

@app.route("/api/status")
@admin_required
def api_status():
    data = load_data()
    settings = data.get("_settings", {})
    config = {**DEFAULT_CONFIG, **data.get("_config", {})}
    total_users = sum(1 for uid in data if uid.isdigit())
    total_vouches = sum(
        rec.get(cat, {}).get("total_vouches", 0)
        for uid, rec in user_records(data)
        for cat in ALL_CATEGORIES
    )
    return jsonify({
        "chat_enabled": settings.get("chat_enabled", True),
        "persona": settings.get("persona", "default"),
        "memory_count": len(data.get("_memories", [])),
        "user_count": total_users,
        "total_vouches": total_vouches,
        "config": config,
    })

# ── API: Leaderboard ──

@app.route("/api/leaderboard")
@admin_required
def api_leaderboard():
    data = load_data()
    result = {}
    for cat in ALL_CATEGORIES:
        ranked = sorted(
            user_records(data),
            key=lambda kv: kv[1].get(cat, {}).get("total_points", 0),
            reverse=True,
        )
        ranked = [(uid, rec) for uid, rec in ranked if rec.get(cat, {}).get("total_points", 0) > 0][:25]
        result[cat] = [
            {"uid": uid, "points": rec[cat]["total_points"], "vouches": rec[cat]["total_vouches"],
             **resolve_user(uid)}
            for uid, rec in ranked
        ]
    return jsonify(result)

# ── API: Users ──

@app.route("/api/users")
@admin_required
def api_users():
    data = load_data()
    q = request.args.get("q", "").lower()
    users = []
    for uid, rec in user_records(data):
        if q and q not in uid and q not in resolve_user(uid)["name"].lower():
            continue
        users.append({
            "uid": uid,
            **resolve_user(uid),
            "total": combined_total(rec),
            "pve": rec.get("pve", {}).get("total_points", 0),
            "security": rec.get("security", {}).get("total_points", 0),
            "support": rec.get("support", {}).get("total_points", 0),
        })
    users.sort(key=lambda u: u["total"], reverse=True)
    return jsonify(users[:100])

@app.route("/api/users/<uid>")
@admin_required
def api_user_detail(uid):
    if not uid.isdigit():
        return jsonify({"error": "Invalid user ID"}), 400
    data = load_data()
    rec = data.get(uid, {})
    result = {"uid": uid, "total": combined_total(rec), "categories": {}, **resolve_user(uid)}
    for cat in ALL_CATEGORIES:
        cat_rec = rec.get(cat, {})
        log = cat_rec.get("log", [])
        result["categories"][cat] = {
            "total_points": cat_rec.get("total_points", 0),
            "total_vouches": cat_rec.get("total_vouches", 0),
            "rank": rank_progress(cat, cat_rec.get("total_points", 0), cat_rec.get("total_vouches", 0)),
            "events": cat_rec.get("events", {}),
            "log": [
                {**e, "idx_id": f"idx{i}" if not e.get("id") else e.get("id")}
                for i, e in enumerate(log[-20:])
            ],
        }
    return jsonify(result)

# ── API: Vouches ──

@app.route("/api/vouches/add", methods=["POST"])
@admin_required
def api_add_vouch():
    body = request.json or {}
    uid = str(body.get("uid", "")).strip()
    category = body.get("category", "")
    event_name = body.get("event_name", "")
    try:
        count = max(1, int(body.get("count", 1)))
    except (ValueError, TypeError):
        count = 1

    if not uid.isdigit():
        return jsonify({"error": "Invalid user ID"}), 400
    if category not in ALL_CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400

    data = load_data()
    economy = get_economy(data)
    if event_name not in economy["events"].get(category, {}):
        return jsonify({"error": f"Invalid event for {category}"}), 400

    points = economy["events"][category][event_name]
    record = ensure_user_cat(data, uid, category)
    record["total_points"] += points * count
    record["total_vouches"] += count
    record["events"][event_name] += count
    actor = session.get("user", {})
    record["log"].append({
        "id": uuid.uuid4().hex[:8],
        "by": actor.get("id", "dashboard"),
        "by_name": actor.get("username", "Dashboard"),
        "event": event_name,
        "points": points * count,
        "count": count,
        "backfilled": True,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    save_data(data)
    return jsonify({"ok": True, "new_total": record["total_points"]})

@app.route("/api/vouches/revert", methods=["POST"])
@admin_required
def api_revert_vouch():
    body = request.json or {}
    uid = str(body.get("uid", "")).strip()
    category = body.get("category", "")
    log_id = str(body.get("log_id", "")).strip()

    if not uid.isdigit() or category not in CATEGORY_EVENTS:
        return jsonify({"error": "Invalid uid or category"}), 400

    data = load_data()
    record = data.get(uid, {}).get(category)
    if not record:
        return jsonify({"error": "No record found for this user/category"}), 404

    entry = None
    entry_index = None
    for i, e in enumerate(record["log"]):
        ref = e.get("id") or f"idx{i}"
        if ref == log_id:
            entry = e
            entry_index = i
            break

    if entry is None:
        return jsonify({"error": "Log entry not found"}), 404

    points = entry.get("points", 0)
    count = entry.get("count", 1)
    event_name = entry.get("event", "")
    record["total_points"] = max(0, record["total_points"] - points)
    record["total_vouches"] = max(0, record["total_vouches"] - count)
    record["events"][event_name] = max(0, record["events"].get(event_name, 0) - count)
    del record["log"][entry_index]
    save_data(data)
    return jsonify({"ok": True, "new_total": record["total_points"]})

@app.route("/api/vouches/delete_user", methods=["POST"])
@admin_required
def api_delete_user():
    body = request.json or {}
    uid = str(body.get("uid", "")).strip()
    category = body.get("category", None)
    if not uid.isdigit():
        return jsonify({"error": "Invalid user ID"}), 400
    data = load_data()
    if uid not in data:
        return jsonify({"error": "User not found"}), 404
    if category:
        if category in data[uid]:
            del data[uid][category]
    else:
        del data[uid]
    save_data(data)
    return jsonify({"ok": True})

# ── API: Memories ──

@app.route("/api/memories", methods=["GET"])
@admin_required
def api_memories_get():
    data = load_data()
    return jsonify(data.get("_memories", []))

@app.route("/api/memories", methods=["POST"])
@admin_required
def api_memories_add():
    body = request.json or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Text required"}), 400
    data = load_data()
    memories = data.get("_memories", [])
    memories.append({
        "id": uuid.uuid4().hex[:8],
        "text": text,
        "added_by": session.get("user", {}).get("username", "dashboard"),
        "time": datetime.now(timezone.utc).isoformat(),
    })
    data["_memories"] = memories[-50:]
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/memories/<memory_id>", methods=["DELETE"])
@admin_required
def api_memories_delete(memory_id):
    data = load_data()
    memories = data.get("_memories", [])
    new_m = [m for m in memories if m["id"] != memory_id]
    if len(new_m) == len(memories):
        return jsonify({"error": "Not found"}), 404
    data["_memories"] = new_m
    save_data(data)
    return jsonify({"ok": True})

# ── API: Settings ──

@app.route("/api/settings", methods=["GET"])
@admin_required
def api_settings_get():
    data = load_data()
    config = {**DEFAULT_CONFIG, **data.get("_config", {})}
    return jsonify({
        "chat_enabled": data.get("_settings", {}).get("chat_enabled", True),
        "persona": data.get("_settings", {}).get("persona", "default"),
        "config": config,
        "personas": PERSONAS,
    })

@app.route("/api/settings", methods=["POST"])
@admin_required
def api_settings_update():
    body = request.json or {}
    data = load_data()
    settings = data.setdefault("_settings", {})
    cfg = data.setdefault("_config", {})

    if "chat_enabled" in body:
        settings["chat_enabled"] = bool(body["chat_enabled"])
    if "persona" in body and body["persona"] in PERSONAS:
        settings["persona"] = body["persona"]

    channel_keys = [
        "pve_channel_id", "security_channel_id", "support_channel_id",
        "live_leaderboard_channel_id", "audit_log_channel_id",
        "event_ping_channel_id", "chime_in_channel_id",
    ]
    for key in channel_keys:
        if key in body:
            try:
                cfg[key] = int(body[key])
            except (ValueError, TypeError):
                pass

    save_data(data)
    return jsonify({"ok": True})

# ── API: Audit Log ──

def _collect_audit(args):
    """Flatten every log entry, newest first, applying the given filters."""
    data = load_data()
    category = args.get("category", "")
    uid_filter = args.get("uid", "").strip()
    q = args.get("q", "").lower().strip()
    try:
        days = int(args.get("days", 0))
    except (ValueError, TypeError):
        days = 0
    cutoff = ""
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    entries = []
    for uid, rec in user_records(data):
        if uid_filter and uid_filter not in uid:
            continue
        for cat in ALL_CATEGORIES:
            if category and cat != category:
                continue
            for i, e in enumerate(rec.get(cat, {}).get("log", [])):
                when = e.get("time", "")
                if cutoff and when < cutoff:
                    continue
                who = resolve_user(uid)
                by_name = e.get("by_name") or str(e.get("by", ""))
                if q and q not in str(e.get("event", "")).lower() and q not in by_name.lower() \
                        and q not in who["name"].lower() and q not in uid:
                    continue
                entries.append({
                    "uid": uid, "name": who["name"], "avatar": who["avatar"],
                    "category": cat, "event": e.get("event"), "points": e.get("points"),
                    "by": by_name, "time": when, "backfilled": e.get("backfilled", False),
                    "id": e.get("id") or f"idx{i}",
                })
    entries.sort(key=lambda e: e.get("time") or "", reverse=True)
    return entries

@app.route("/api/auditlog")
@admin_required
def api_auditlog():
    return jsonify(_collect_audit(request.args)[:400])

@app.route("/api/auditlog.csv")
@admin_required
def api_auditlog_csv():
    entries = _collect_audit(request.args)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "category", "event", "points", "user_id", "user_name", "given_by", "backfilled"])
    for e in entries:
        writer.writerow([e["time"], CATEGORY_NAMES.get(e["category"], e["category"]), e["event"],
                         e["points"], e["uid"], e["name"], e["by"], "yes" if e["backfilled"] else "no"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit-log-{stamp}.csv"},
    )

# ── API: Points over time (chart) ──

@app.route("/api/points_over_time")
@admin_required
def api_points_over_time():
    try:
        days = max(7, min(180, int(request.args.get("days", 30))))
    except (ValueError, TypeError):
        days = 30
    data = load_data()
    today = datetime.now(timezone.utc).date()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    index = {d: i for i, d in enumerate(labels)}
    series = {cat: [0.0] * days for cat in ALL_CATEGORIES}

    for uid, rec in user_records(data):
        for cat in ALL_CATEGORIES:
            for e in rec.get(cat, {}).get("log", []):
                day = str(e.get("time", ""))[:10]
                if day in index:
                    series[cat][index[day]] += float(e.get("points", 0) or 0)

    return jsonify({
        "labels": labels,
        "series": {cat: [round(v, 1) for v in vals] for cat, vals in series.items()},
        "totals": {cat: round(sum(vals), 1) for cat, vals in series.items()},
    })

# ── API: Role resync ──

@app.route("/api/roles/resync", methods=["POST"])
@admin_required
def api_roles_resync():
    resync = _bridge.get("resync")
    if resync is None or _bridge.get("loop") is None:
        return jsonify({"error": "Bot isn't connected yet. Try again once it's online."}), 503
    try:
        future = run_on_bot(resync())
        result = future.result(timeout=120) if future else {}
    except Exception as exc:
        return jsonify({"error": f"Resync failed: {exc}"}), 500
    return jsonify({"ok": True, **(result or {})})

# ── API: Site activity (admins only) ──

@app.route("/api/analytics")
@admin_required
def api_analytics():
    flush_visits()
    try:
        days = max(7, min(ANALYTICS_RETENTION_DAYS, int(request.args.get("days", 30))))
    except (ValueError, TypeError):
        days = 30

    data = load_data()
    analytics = data.get("_analytics", {})
    stored = analytics.get("days", {})
    last_seen = analytics.get("last_seen", {})

    today = datetime.now(timezone.utc).date()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    views = []
    uniques = []
    per_user = {}
    page_totals = {}

    for day in labels:
        bucket = stored.get(day, {})
        views.append(sum(u.get("views", 0) for u in bucket.values()))
        uniques.append(len(bucket))
        for uid, entry in bucket.items():
            slot = per_user.setdefault(uid, {"views": 0, "days": 0})
            slot["views"] += entry.get("views", 0)
            slot["days"] += 1
            for page, count in (entry.get("pages") or {}).items():
                page_totals[page] = page_totals.get(page, 0) + count

    people = []
    for uid, slot in per_user.items():
        who = resolve_user(uid)
        people.append({
            "uid": uid, "name": who["name"], "avatar": who["avatar"], "resolved": who["resolved"],
            "views": slot["views"], "days": slot["days"],
            "last_seen": last_seen.get(uid, ""),
        })
    people.sort(key=lambda p: p["views"], reverse=True)

    # anyone who has signed in before but not in this window
    dormant = [uid for uid in last_seen if uid not in per_user]

    return jsonify({
        "labels": labels,
        "views": views,
        "uniques": uniques,
        "people": people[:100],
        "pages": page_totals,
        "totals": {
            "views": sum(views),
            "people": len(per_user),
            "dormant": len(dormant),
            "busiest": max(zip(views, labels))[1] if any(views) else None,
            "per_day": round(sum(views) / max(1, days), 1),
        },
    })


# ── API: Points and ranks ──

@app.route("/api/economy", methods=["GET"])
@admin_required
def api_economy_get():
    economy = get_economy()
    return jsonify({
        "events": economy["events"],
        "ranks": economy["ranks"],
        "metric": _bridge["metric"] or {},
        "category_names": CATEGORY_NAMES,
        "defaults": {"events": default_event_points(), "ranks": default_ranks()},
    })


@app.route("/api/economy", methods=["POST"])
@admin_required
def api_economy_save():
    body = request.json or {}
    section = body.get("section")
    category = body.get("category")
    if category not in ALL_CATEGORIES:
        return jsonify({"error": "Unknown category."}), 400

    data = load_data()
    economy = data.setdefault("_economy", {})

    if section == "events":
        rows = body.get("events") or []
        cleaned = {}
        for row in rows:
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            if len(name) > 60:
                return jsonify({"error": f"'{name[:20]}...' is too long (60 characters max)."}), 400
            if name in cleaned:
                return jsonify({"error": f"'{name}' is listed twice."}), 400
            try:
                points = round(float(row.get("points", 0)), 2)
            except (ValueError, TypeError):
                return jsonify({"error": f"'{name}' needs a number for points."}), 400
            if points < 0 or points > 1000:
                return jsonify({"error": f"'{name}' must be between 0 and 1000 points."}), 400
            cleaned[name] = int(points) if points == int(points) else points
        if not cleaned:
            return jsonify({"error": "Keep at least one event in this category."}), 400

        removed = [e for e in get_economy(data)["events"].get(category, {}) if e not in cleaned]
        economy.setdefault("events", {})[category] = cleaned
        save_data(data)
        return jsonify({"ok": True, "removed": removed, "count": len(cleaned)})

    if section == "ranks":
        rows = body.get("ranks") or []
        cleaned = []
        seen_names = set()
        for row in rows:
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            if len(name) > 90:
                return jsonify({"error": f"'{name[:20]}...' is too long for a role name."}), 400
            if name.lower() in seen_names:
                return jsonify({"error": f"'{name}' is listed twice."}), 400
            seen_names.add(name.lower())
            try:
                at = round(float(row.get("at", 0)), 2)
            except (ValueError, TypeError):
                return jsonify({"error": f"'{name}' needs a number to unlock at."}), 400
            if at < 0:
                return jsonify({"error": f"'{name}' cannot unlock below zero."}), 400
            cleaned.append([int(at) if at == int(at) else at, name])

        cleaned.sort(key=lambda r: r[0])
        for i in range(1, len(cleaned)):
            if cleaned[i][0] == cleaned[i - 1][0]:
                return jsonify({
                    "error": f"'{cleaned[i][1]}' and '{cleaned[i-1][1]}' both unlock at {cleaned[i][0]}."
                }), 400

        economy.setdefault("ranks", {})[category] = cleaned
        save_data(data)
        return jsonify({"ok": True, "count": len(cleaned), "ranks_changed": True})

    return jsonify({"error": "Nothing to save."}), 400


@app.route("/api/economy/reset", methods=["POST"])
@admin_required
def api_economy_reset():
    body = request.json or {}
    section = body.get("section")
    category = body.get("category")
    if category not in ALL_CATEGORIES or section not in ("events", "ranks"):
        return jsonify({"error": "Unknown category or section."}), 400
    data = load_data()
    economy = data.get("_economy", {})
    if category in economy.get(section, {}):
        del economy[section][category]
        save_data(data)
    return jsonify({"ok": True})


# ── API: Custom ? commands ──

def _valid_command_name(name):
    return bool(re.fullmatch(r"[a-z0-9_-]{1,24}", name))

@app.route("/api/commands", methods=["GET"])
@admin_required
def api_commands_get():
    data = load_data()
    return jsonify(data.get("_commands", []))

@app.route("/api/commands", methods=["POST"])
@admin_required
def api_commands_save():
    body = request.json or {}
    name = str(body.get("name", "")).strip().lower().lstrip("?")
    response_text = (body.get("response") or "").strip()

    if not _valid_command_name(name):
        return jsonify({"error": "Names may use letters, numbers, - and _ only (max 24 characters)."}), 400
    if name in RESERVED_COMMANDS:
        return jsonify({"error": f"?{name} is a built-in command. Pick another name."}), 400
    if not response_text:
        return jsonify({"error": "Give the command something to say."}), 400
    if len(response_text) > 1900:
        return jsonify({"error": "Response is too long (1900 characters max)."}), 400

    data = load_data()
    commands_list = data.get("_commands", [])
    entry = {
        "name": name,
        "response": response_text,
        "embed": bool(body.get("embed", False)),
        "title": (body.get("title") or "").strip()[:200],
        "color": (body.get("color") or "#c9d0da").strip()[:7],
        "enabled": bool(body.get("enabled", True)),
        "uses": 0,
        "created_by": session.get("user", {}).get("username", "dashboard"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    for i, c in enumerate(commands_list):
        if c["name"] == name:
            entry["uses"] = c.get("uses", 0)
            entry["created_at"] = c.get("created_at", entry["created_at"])
            commands_list[i] = entry
            break
    else:
        if len(commands_list) >= 100:
            return jsonify({"error": "You've hit the 100 custom command limit."}), 400
        commands_list.append(entry)

    data["_commands"] = sorted(commands_list, key=lambda c: c["name"])
    save_data(data)
    return jsonify({"ok": True, "command": entry})

@app.route("/api/commands/<name>", methods=["DELETE"])
@admin_required
def api_commands_delete(name):
    data = load_data()
    commands_list = data.get("_commands", [])
    remaining = [c for c in commands_list if c["name"] != name.lower()]
    if len(remaining) == len(commands_list):
        return jsonify({"error": "No command by that name."}), 404
    data["_commands"] = remaining
    save_data(data)
    return jsonify({"ok": True})

# ── API: Event Schedule ──

@app.route("/api/events", methods=["GET"])
@admin_required
def api_events_get():
    data = load_data()
    overrides = data.get("_event_schedule", {})
    schedule = {**DEFAULT_EVENT_SCHEDULE, **overrides}
    return jsonify(schedule)

@app.route("/api/events", methods=["POST"])
@admin_required
def api_events_update():
    body = request.json or {}
    data = load_data()
    validated = {}
    for event, times in body.items():
        if isinstance(times, list):
            validated[event] = [t for t in times if isinstance(t, str) and len(t) == 5]
    data["_event_schedule"] = validated
    save_data(data)
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
# LOGIN HTML
# ─────────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in - Matzys Overseer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0a0b0e;--panel:#15181d;--panel-2:#1c2027;--border:#242830;
  --text:#f4f6f9;--muted:#98a1ae;--moon:#e8edf4;--red:#d98891;
}
body{background:var(--bg);color:var(--text);font-family:'Poppins',system-ui,sans-serif;
  min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:24px;overflow-x:hidden}
.glow{position:fixed;top:-10%;right:-20%;width:70vw;height:70vw;border-radius:50%;
  background:radial-gradient(circle,rgba(226,233,243,0.22),transparent 62%);filter:blur(40px);pointer-events:none}
.card{position:relative;z-index:1;background:var(--panel);border:1px solid var(--border);border-radius:18px;
  padding:40px 32px;width:100%;max-width:420px;text-align:center}
.mark{width:72px;height:72px;margin:0 auto 22px;border-radius:20px;display:block;object-fit:cover;
  border:1px solid var(--border);box-shadow:0 10px 34px rgba(0,0,0,.5)}
h1{font-size:26px;font-weight:700;letter-spacing:-0.6px}
h1 span{color:var(--moon)}
p.sub{color:var(--muted);font-size:14px;margin-top:8px;line-height:1.5}
.discord-btn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;margin-top:30px;
  background:#5865f2;color:#fff;border:none;border-radius:12px;padding:14px;font-size:15px;font-weight:600;
  font-family:inherit;cursor:pointer;text-decoration:none;transition:transform .15s,background .15s}
.discord-btn:hover{background:#4752c4;transform:translateY(-1px)}
.discord-btn:disabled{background:var(--panel-2);color:var(--muted);cursor:not-allowed;transform:none}
.discord-btn svg{width:22px;height:22px;fill:currentColor}
.note{margin-top:18px;font-size:12px;color:var(--muted);line-height:1.6}
.note code{font-family:'JetBrains Mono',monospace;color:#c9d0da;font-size:11px}
.error{background:rgba(217,136,145,0.1);border:1px solid rgba(217,136,145,0.3);color:var(--red);
  border-radius:12px;padding:12px 14px;font-size:13px;margin-top:22px;text-align:left;line-height:1.5}
:focus-visible{outline:2px solid var(--moon);outline-offset:2px}
/* ── Drifting blossom, echoing the logo ── */
.petals{position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:0}
.petal{position:absolute;top:-12vh;width:var(--w);height:var(--h);
  background:linear-gradient(140deg,#ffffff,#c9d2e0);
  border-radius:100% 0 100% 0;opacity:0;
  animation:petal-fall var(--dur) linear var(--delay) infinite;will-change:transform,opacity}
@keyframes petal-fall{
  0%{transform:translate3d(0,-12vh,0) rotate(0deg) scale(.9);opacity:0}
  12%{opacity:var(--o)}
  88%{opacity:var(--o)}
  100%{transform:translate3d(var(--drift),112vh,0) rotate(var(--spin)) scale(1);opacity:0}
}
@media (prefers-reduced-motion:reduce){.petals{display:none}}

</style>
</head>
<body>
<div class="petals" aria-hidden="true">
  <i class="petal" style="left:93.7%;--w:7px;--h:6px;--o:0.11;--dur:31.0s;--delay:-2.8s;--drift:3.5vw;--spin:-300deg"></i>
  <i class="petal" style="left:1.8%;--w:6px;--h:5px;--o:0.11;--dur:18.5s;--delay:-12.7s;--drift:10.8vw;--spin:360deg"></i>
  <i class="petal" style="left:61.7%;--w:6px;--h:5px;--o:0.11;--dur:27.0s;--delay:-1.5s;--drift:-7.4vw;--spin:-300deg"></i>
  <i class="petal" style="left:11.5%;--w:13px;--h:11px;--o:0.21;--dur:26.7s;--delay:-16.8s;--drift:6.5vw;--spin:360deg"></i>
  <i class="petal" style="left:55.7%;--w:9px;--h:7px;--o:0.12;--dur:29.1s;--delay:-16.9s;--drift:4.6vw;--spin:720deg"></i>
  <i class="petal" style="left:51.7%;--w:11px;--h:10px;--o:0.19;--dur:32.7s;--delay:-10.8s;--drift:-6.5vw;--spin:540deg"></i>
  <i class="petal" style="left:76.8%;--w:11px;--h:8px;--o:0.16;--dur:25.4s;--delay:-10.3s;--drift:-0.5vw;--spin:-300deg"></i>
  <i class="petal" style="left:9.9%;--w:5px;--h:4px;--o:0.25;--dur:19.6s;--delay:-14.7s;--drift:-12.8vw;--spin:360deg"></i>
  <i class="petal" style="left:54.4%;--w:13px;--h:12px;--o:0.26;--dur:22.8s;--delay:-10.5s;--drift:0.9vw;--spin:720deg"></i>
  <i class="petal" style="left:82.8%;--w:5px;--h:5px;--o:0.19;--dur:28.3s;--delay:-1.8s;--drift:7.0vw;--spin:-300deg"></i>
  <i class="petal" style="left:81.0%;--w:11px;--h:9px;--o:0.18;--dur:28.4s;--delay:-0.7s;--drift:-0.1vw;--spin:540deg"></i>
  <i class="petal" style="left:9.8%;--w:9px;--h:7px;--o:0.25;--dur:19.2s;--delay:-7.4s;--drift:-2.3vw;--spin:720deg"></i>
  <i class="petal" style="left:14.8%;--w:5px;--h:4px;--o:0.16;--dur:19.3s;--delay:-12.9s;--drift:2.5vw;--spin:720deg"></i>
  <i class="petal" style="left:67.0%;--w:7px;--h:6px;--o:0.15;--dur:18.4s;--delay:-4.5s;--drift:5.8vw;--spin:360deg"></i>
  <i class="petal" style="left:81.9%;--w:8px;--h:6px;--o:0.16;--dur:19.5s;--delay:-16.0s;--drift:4.3vw;--spin:-420deg"></i>
  <i class="petal" style="left:67.7%;--w:6px;--h:5px;--o:0.22;--dur:28.5s;--delay:-1.6s;--drift:13.0vw;--spin:-300deg"></i>
</div>
<div class="glow"></div>
<div class="card">
  <img class="mark" src="__LOGO__" alt="">
  <h1>Matzys <span>Overseer</span></h1>

  {% if error %}<div class="error">{{ error }}</div>{% endif %}

  {% if configured %}
  <a class="discord-btn" href="/login/discord">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.3 4.4A19.8 19.8 0 0 0 15.4 3l-.24.5c1.6.38 2.9 1 4.1 1.9a13.9 13.9 0 0 0-4.9-1.5 17.4 17.4 0 0 0-4.7 0c-.5.06-1.2.2-2.1.4-.9.2-1.6.5-2.1.7 1.2-.9 2.5-1.5 4-1.9L9.2 3a19.8 19.8 0 0 0-4.9 1.4C2.7 6.9 1.8 9.8 1.6 13a15 15 0 0 0 4.5 2.3c.4-.5.7-1 1-1.6-.6-.2-1.1-.5-1.5-.8l.4-.3a11.9 11.9 0 0 0 10.2 0l.4.3c-.5.3-1 .6-1.6.8.3.6.6 1.1 1 1.6a15 15 0 0 0 4.5-2.3c-.2-3.6-1.3-6.5-3.2-8.6ZM8.6 12.7c-.9 0-1.6-.9-1.6-1.9s.7-1.9 1.6-1.9 1.7.8 1.6 1.9c0 1-.7 1.9-1.6 1.9Zm6 0c-.9 0-1.6-.9-1.6-1.9s.7-1.9 1.6-1.9 1.7.8 1.6 1.9c0 1-.7 1.9-1.6 1.9Z"/></svg>
    Continue with Discord
  </a>
  {% else %}
  <button class="discord-btn" disabled>Discord login not configured</button>
  <div class="note">Set <code>DISCORD_CLIENT_ID</code>, <code>DISCORD_CLIENT_SECRET</code> and
    <code>DISCORD_REDIRECT_URI</code> in your Railway variables, then reload this page.</div>
  {% endif %}
</div>
</body>
</html>""".replace("__LOGO__", LOGO_SRC)


# ─────────────────────────────────────────────────────────────
# PROFILE HTML (any signed-in member)
# ─────────────────────────────────────────────────────────────

PROFILE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>My profile - Matzys Overseer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0a0b0e;--header:#101216;--card:#15181d;--card-2:#1c2027;--border:#242830;--border-2:#343a45;
  --moon:#e8edf4;--steel:#9aa8c2;--sage:#93b3a1;--red:#d98891;--amber:#d8bb86;
  --text:#f4f6f9;--muted:#98a1ae;--dim:#646c79;
  --mono:'JetBrains Mono',monospace;--sans:'Poppins',system-ui,sans-serif;--radius:16px;
}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100dvh;
  display:flex;flex-direction:column;overflow-x:hidden}
:focus-visible{outline:2px solid var(--moon);outline-offset:2px;border-radius:6px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
/* ── Drifting blossom, echoing the logo ── */
.petals{position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:0}
.petal{position:absolute;top:-12vh;width:var(--w);height:var(--h);
  background:linear-gradient(140deg,#ffffff,#c9d2e0);
  border-radius:100% 0 100% 0;opacity:0;
  animation:petal-fall var(--dur) linear var(--delay) infinite;will-change:transform,opacity}
@keyframes petal-fall{
  0%{transform:translate3d(0,-12vh,0) rotate(0deg) scale(.9);opacity:0}
  12%{opacity:var(--o)}
  88%{opacity:var(--o)}
  100%{transform:translate3d(var(--drift),112vh,0) rotate(var(--spin)) scale(1);opacity:0}
}
@media (prefers-reduced-motion:reduce){.petals{display:none}}

.header{position:sticky;top:0;z-index:50;background:var(--header);border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:12px;padding:10px 16px}
.brand{width:34px;height:34px;border-radius:11px;display:block;object-fit:cover;flex-shrink:0;
  border:1px solid var(--border)}
.brand-name{font-size:14px;font-weight:600}
.spacer{flex:1}
.hlink{color:var(--muted);text-decoration:none;font-size:13.5px;padding:8px 12px;border-radius:10px}
.hlink:hover{color:var(--text);background:rgba(255,255,255,.05)}
.hlink.avatar img{width:34px;height:34px;border-radius:50%;display:block;border:1px solid var(--border)}
.hlink.avatar{padding:0}
.content{flex:1;padding:26px 20px 40px;max-width:900px;width:100%;margin:0 auto;position:relative;z-index:1}
.hero{position:relative;padding:18px 0 30px}
.hero::before{content:'';position:absolute;top:-90px;right:-16%;width:min(78vw,520px);height:min(78vw,520px);
  border-radius:50%;background:radial-gradient(circle,rgba(226,233,243,.28),rgba(226,233,243,.04) 55%,transparent 70%);
  filter:blur(26px);pointer-events:none;z-index:-1}
.hero h1{font-size:clamp(30px,7.5vw,46px);font-weight:700;letter-spacing:-1.2px;line-height:1.1}
.hero h1 span{color:var(--moon)}
.hero p{margin-top:12px;font-size:clamp(16px,4vw,21px);color:#c9d0da;line-height:1.35}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:22px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px}
.stat .val{font-family:var(--mono);font-size:26px;font-weight:600}
.stat .lbl{font-size:12.5px;color:var(--muted);margin-top:4px}
.stat .delta{font-size:12px;margin-top:6px;font-family:var(--mono)}
.up{color:var(--sage)}.down{color:var(--red)}.flat{color:var(--dim)}
h2.sec{font-size:19px;font-weight:600;letter-spacing:-.3px;margin:26px 0 14px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:22px;margin-bottom:14px}
.cat-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.cat-name{font-size:16px;font-weight:600}
.cat-pos{font-size:12px;color:var(--muted);font-family:var(--mono)}
.rank-top{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:9px;flex-wrap:wrap}
.rank-name{font-size:14px;font-weight:600}
.rank-next{font-size:11.5px;color:var(--muted);font-family:var(--mono)}
.rank-bar{height:8px;border-radius:5px;background:#242830;overflow:hidden}
.rank-fill{height:100%;border-radius:5px;transition:width .5s ease}
.cat-stats{display:flex;gap:22px;margin-top:16px;flex-wrap:wrap}
.cat-stats div{font-size:12.5px;color:var(--muted)}
.cat-stats b{display:block;font-family:var(--mono);font-size:19px;color:var(--text);font-weight:600;margin-bottom:2px}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}
.chip{background:var(--card-2);border:1px solid var(--border);border-radius:8px;padding:5px 11px;font-size:12px;color:var(--muted)}
.chip b{color:var(--text);font-family:var(--mono)}
.act{display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)}
.act:last-child{border-bottom:none}
.act .dot{width:8px;height:8px;border-radius:50%;margin-top:6px;flex-shrink:0}
.act .main{font-size:13.5px;line-height:1.45}
.act .meta{font-size:11.5px;color:var(--dim);margin-top:3px;font-family:var(--mono)}
.bests{display:flex;flex-wrap:wrap;gap:18px;padding:16px 18px;background:var(--card);
  border:1px solid var(--border);border-radius:var(--radius);margin-bottom:22px}
.bests div{font-size:12px;color:var(--muted)}
.bests b{display:block;font-family:var(--mono);font-size:16px;color:var(--text);font-weight:600;margin-bottom:2px}
.rivals{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.rival{background:var(--card-2);border:1px solid var(--border);border-radius:9px;padding:7px 11px;font-size:12px;color:var(--muted)}
.rival b{color:var(--text)}
.goals{margin-top:16px;border-top:1px solid var(--border);padding-top:14px}
.goal{margin-bottom:12px}
.goal:last-child{margin-bottom:0}
.goal .g-top{font-size:13px;margin-bottom:6px}
.goal .g-top b{font-weight:600}
.routes{display:flex;flex-wrap:wrap;gap:6px}
.route{background:var(--card-2);border:1px solid var(--border);border-radius:8px;padding:4px 9px;
  font-size:11.5px;color:var(--muted);font-family:var(--mono)}
.route b{color:var(--text)}
.chart-wrap{width:100%;overflow:hidden}
.chart-wrap svg{width:100%;height:auto;display:block}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;font-size:12px;color:var(--muted)}
.legend i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:6px}
.filters{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
.filters select,.filters input{background:var(--card-2);border:1px solid var(--border);border-radius:10px;
  padding:9px 12px;color:var(--text);font-size:13px;font-family:var(--sans);outline:none}
.filters input{min-width:150px}
.filters select:focus,.filters input:focus{border-color:var(--moon)}
.btn{padding:9px 16px;border-radius:10px;border:none;cursor:pointer;font-size:13px;font-weight:500;
  font-family:var(--sans);background:var(--card-2);color:var(--text);transition:background .15s}
.btn:hover{background:#262b33}
.hist-sum{font-size:12.5px;color:var(--muted);margin-bottom:12px;font-family:var(--mono)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 10px;color:var(--dim);font-weight:500;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.9px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:10px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
.table-wrap{overflow-x:auto}
.empty{text-align:center;padding:40px 20px;color:var(--dim);font-size:13.5px;line-height:1.6}
.footer{position:relative;z-index:1;border-top:1px solid var(--border);padding:22px 20px 30px;text-align:center;color:var(--dim);font-size:13px}
.footer a{color:var(--dim);text-decoration:none;margin:0 5px}
.footer a:hover{color:var(--muted)}
</style>
</head>
<body>
<div class="petals" aria-hidden="true">
  <i class="petal" style="left:93.7%;--w:7px;--h:6px;--o:0.11;--dur:31.0s;--delay:-2.8s;--drift:3.5vw;--spin:-300deg"></i>
  <i class="petal" style="left:1.8%;--w:6px;--h:5px;--o:0.11;--dur:18.5s;--delay:-12.7s;--drift:10.8vw;--spin:360deg"></i>
  <i class="petal" style="left:61.7%;--w:6px;--h:5px;--o:0.11;--dur:27.0s;--delay:-1.5s;--drift:-7.4vw;--spin:-300deg"></i>
  <i class="petal" style="left:11.5%;--w:13px;--h:11px;--o:0.21;--dur:26.7s;--delay:-16.8s;--drift:6.5vw;--spin:360deg"></i>
  <i class="petal" style="left:55.7%;--w:9px;--h:7px;--o:0.12;--dur:29.1s;--delay:-16.9s;--drift:4.6vw;--spin:720deg"></i>
  <i class="petal" style="left:51.7%;--w:11px;--h:10px;--o:0.19;--dur:32.7s;--delay:-10.8s;--drift:-6.5vw;--spin:540deg"></i>
  <i class="petal" style="left:76.8%;--w:11px;--h:8px;--o:0.16;--dur:25.4s;--delay:-10.3s;--drift:-0.5vw;--spin:-300deg"></i>
  <i class="petal" style="left:9.9%;--w:5px;--h:4px;--o:0.25;--dur:19.6s;--delay:-14.7s;--drift:-12.8vw;--spin:360deg"></i>
  <i class="petal" style="left:54.4%;--w:13px;--h:12px;--o:0.26;--dur:22.8s;--delay:-10.5s;--drift:0.9vw;--spin:720deg"></i>
  <i class="petal" style="left:82.8%;--w:5px;--h:5px;--o:0.19;--dur:28.3s;--delay:-1.8s;--drift:7.0vw;--spin:-300deg"></i>
  <i class="petal" style="left:81.0%;--w:11px;--h:9px;--o:0.18;--dur:28.4s;--delay:-0.7s;--drift:-0.1vw;--spin:540deg"></i>
  <i class="petal" style="left:9.8%;--w:9px;--h:7px;--o:0.25;--dur:19.2s;--delay:-7.4s;--drift:-2.3vw;--spin:720deg"></i>
  <i class="petal" style="left:14.8%;--w:5px;--h:4px;--o:0.16;--dur:19.3s;--delay:-12.9s;--drift:2.5vw;--spin:720deg"></i>
  <i class="petal" style="left:67.0%;--w:7px;--h:6px;--o:0.15;--dur:18.4s;--delay:-4.5s;--drift:5.8vw;--spin:360deg"></i>
  <i class="petal" style="left:81.9%;--w:8px;--h:6px;--o:0.16;--dur:19.5s;--delay:-16.0s;--drift:4.3vw;--spin:-420deg"></i>
  <i class="petal" style="left:67.7%;--w:6px;--h:5px;--o:0.22;--dur:28.5s;--delay:-1.6s;--drift:13.0vw;--spin:-300deg"></i>
</div>
<header class="header">
  <img class="brand" src="__LOGO__" alt="">
  <span class="brand-name">Matzys Overseer</span>
  <div class="spacer"></div>
  {% if is_admin %}<a class="hlink" href="/">Dashboard</a>{% endif %}
  <a class="hlink" href="/logout">Sign out</a>
  <span class="hlink avatar"><img src="{{ user.avatar }}" alt=""></span>
</header>

<main class="content">
  <div class="hero">
    <h1>Welcome back, <span>{{ user.username }}</span></h1>
    <p>Here is where you stand.</p>
  </div>

  <div class="stat-grid">
    <div class="stat"><div class="val" id="s-total">-</div><div class="lbl">Total points</div></div>
    <div class="stat"><div class="val" id="s-week">-</div><div class="lbl">Points this week</div>
      <div class="delta" id="s-delta"></div></div>
    <div class="stat"><div class="val" id="s-vouches">-</div><div class="lbl">Total vouches</div></div>
  </div>

  <div class="bests" id="bests"></div>

  <div id="cats"></div>

  <h2 class="sec">Your activity</h2>
  <div class="card">
    <div class="chart-wrap" id="chart"><div class="empty">Loading...</div></div>
    <div class="legend" id="chart-legend"></div>
  </div>

  <h2 class="sec">Your vouch history</h2>
  <div class="card">
    <div class="filters">
      <select id="f-cat">
        <option value="">All categories</option>
        <option value="pve">Host</option><option value="security">Security</option><option value="support">Support</option>
      </select>
      <select id="f-days">
        <option value="0">All time</option><option value="7">Last 7 days</option>
        <option value="30">Last 30 days</option><option value="90">Last 90 days</option>
      </select>
      <input id="f-q" placeholder="Search event or staff">
      <button class="btn" id="f-export">Export CSV</button>
    </div>
    <div class="hist-sum" id="hist-sum"></div>
    <div class="table-wrap" id="history"><div class="empty">Loading...</div></div>
  </div>
</main>

<footer class="footer">
  <span>&copy; 2026 Matzys Overseer</span>
  <a href="/logout">Sign out</a>
</footer>

<script>
const CAT_COLORS = {pve:'#f4f6f9', security:'#8d9bb5', support:'#9dbcaa'};
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function fmt(n){return typeof n==='number'?n.toLocaleString('en-US',{maximumFractionDigits:1}):n;}

function rivalsHTML(r){
  if(!r || (!r.above && !r.below)) return '';
  let out = '<div class="rivals">';
  if(r.above) out += '<span class="rival"><b>' + fmt(r.above.gap) + '</b> behind ' + esc(r.above.name) + '</span>';
  if(r.below) out += '<span class="rival"><b>' + fmt(r.below.gap) + '</b> ahead of ' + esc(r.below.name) + '</span>';
  return out + '</div>';
}
function goalsHTML(c){
  if(!c.goals || !c.goals.length) return '';
  const unit = c.metric === 'vouches' ? 'vouches' : 'points';
  const rows = c.goals.slice(0,3).map(function(g){
    const routes = (g.routes || []).filter(function(r){ return r.need > 0; })
      .map(function(r){ return '<span class="route"><b>' + r.need + '</b> ' + esc(r.event) + '</span>'; }).join('');
    return '<div class="goal"><div class="g-top"><b>' + esc(g.role) + '</b> needs ' +
      fmt(g.short) + ' more ' + unit + '</div><div class="routes">' + routes + '</div></div>';
  }).join('');
  return '<div class="goals">' + rows + '</div>';
}

async function load(){
  let d;
  try {
    const r = await fetch('/api/profile', {headers:{'Content-Type':'application/json'}});
    if(r.status === 401){window.location.href = '/login'; return;}
    d = await r.json();
  } catch (e) {
    document.getElementById('recent').innerHTML =
      '<div class="empty">Could not load your profile. Try refreshing.</div>';
    return;
  }

  document.getElementById('s-total').textContent = fmt(d.total);
  document.getElementById('s-week').textContent = fmt(d.this_week);
  document.getElementById('s-vouches').textContent =
    d.categories.reduce(function(a,c){return a + c.vouches;}, 0);

  const diff = d.this_week - d.last_week;
  const delta = document.getElementById('s-delta');
  if(d.last_week === 0 && d.this_week === 0){delta.textContent = 'no activity yet'; delta.className = 'delta flat';}
  else if(diff > 0){delta.textContent = '+' + fmt(diff) + ' vs last week'; delta.className = 'delta up';}
  else if(diff < 0){delta.textContent = fmt(diff) + ' vs last week'; delta.className = 'delta down';}
  else {delta.textContent = 'same as last week'; delta.className = 'delta flat';}

  document.getElementById('cats').innerHTML = d.categories.map(function(c){
    const color = CAT_COLORS[c.key] || '#e8edf4';
    const rk = c.rank;
    const bar = rk
      ? '<div class="rank-top"><span class="rank-name">' + esc(rk.current || 'No rank yet') + '</span>' +
        '<span class="rank-next">' + (rk.next ? fmt(rk.remaining) + ' to ' + esc(rk.next) : 'Top rank reached') +
        '</span></div><div class="rank-bar"><div class="rank-fill" style="width:' + rk.pct +
        '%;background:' + color + '"></div></div>'
      : '<div class="rank-next">No rank ladder set for this category.</div>';
    const pos = c.position
      ? '<span class="cat-pos">#' + c.position + ' of ' + c.of + '</span>'
      : '<span class="cat-pos">unranked</span>';
    const chips = Object.keys(c.events).map(function(e){
      return '<span class="chip">' + esc(e) + ' <b>' + c.events[e] + '</b></span>';
    }).join('');
    return '<div class="card">' +
      '<div class="cat-head"><span class="cat-name" style="color:' + color + '">' + esc(c.name) + '</span>' + pos + '</div>' +
      bar +
      '<div class="cat-stats"><div><b>' + fmt(c.points) + '</b>points</div>' +
      '<div><b>' + c.vouches + '</b>vouches</div></div>' +
      (chips ? '<div class="chips">' + chips + '</div>' : '') +
      rivalsHTML(c.rivals) + goalsHTML(c) +
      '</div>';
  }).join('');

  const b = d.bests || {};
  document.getElementById('bests').innerHTML =
    '<div><b>' + (b.best_day ? fmt(b.best_day.points) : '0') + '</b>best day' +
      (b.best_day ? ' (' + b.best_day.date + ')' : '') + '</div>' +
    '<div><b>' + (b.active_days || 0) + '</b>active days</div>' +
    '<div><b>' + (b.total_vouches || 0) + '</b>vouches</div>' +
    '<div><b>' + (b.first_seen || '-') + '</b>first vouch</div>';

  renderChart(d.chart);
  loadHistory();
}

function renderChart(c){
  const holder = document.getElementById('chart');
  if(!c || !c.labels){ holder.innerHTML = '<div class="empty">No activity yet.</div>'; return; }
  const cats = ['pve','security','support'];
  const all = cats.reduce(function(a,k){ return a.concat(c.series[k] || []); }, []);
  const max = Math.max(1, Math.max.apply(null, all));
  if(max <= 1 && all.every(function(v){ return v === 0; })){
    holder.innerHTML = '<div class="empty">No points in the last 30 days.</div>';
    document.getElementById('chart-legend').innerHTML = '';
    return;
  }
  const W = 760, H = 230, PL = 42, PR = 12, PT = 14, PB = 26;
  const n = c.labels.length;
  const x = function(i){ return PL + (i * (W - PL - PR)) / Math.max(1, n - 1); };
  const y = function(v){ return PT + (H - PT - PB) * (1 - v / max); };
  let g = '';
  for(let i = 0; i <= 4; i++){
    const v = max * i / 4, yy = y(v);
    g += '<line x1="' + PL + '" y1="' + yy + '" x2="' + (W - PR) + '" y2="' + yy +
         '" stroke="#242830" stroke-width="1"/>' +
         '<text x="' + (PL - 8) + '" y="' + (yy + 4) + '" fill="#646c79" font-size="11" text-anchor="end">' +
         fmt(Math.round(v)) + '</text>';
  }
  const step = Math.max(1, Math.floor(n / 5));
  for(let i = 0; i < n; i += step){
    g += '<text x="' + x(i) + '" y="' + (H - 7) + '" fill="#646c79" font-size="11" text-anchor="middle">' +
         c.labels[i].slice(5) + '</text>';
  }
  let lines = '';
  cats.forEach(function(k){
    const pts = (c.series[k] || []).map(function(v,i){ return x(i) + ',' + y(v); }).join(' ');
    lines += '<polyline points="' + pts + '" fill="none" stroke="' + CAT_COLORS[k] +
             '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
  });
  holder.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" role="img">' +
    g + lines + '</svg>';
  document.getElementById('chart-legend').innerHTML = cats.map(function(k){
    const tot = (c.series[k] || []).reduce(function(a,v){ return a + v; }, 0);
    return '<span><i style="background:' + CAT_COLORS[k] + '"></i>' + CAT_NAMES[k] + ' ' + fmt(Math.round(tot * 10) / 10) + '</span>';
  }).join('');
}

function histQuery(){
  const p = new URLSearchParams();
  const cat = document.getElementById('f-cat').value;
  const days = document.getElementById('f-days').value;
  const q = document.getElementById('f-q').value.trim();
  if(cat) p.set('category', cat);
  if(days && days !== '0') p.set('days', days);
  if(q) p.set('q', q);
  return p.toString();
}
async function loadHistory(){
  const holder = document.getElementById('history');
  let d;
  try { d = await (await fetch('/api/profile/history?' + histQuery())).json(); }
  catch(e){ holder.innerHTML = '<div class="empty">Could not load history.</div>'; return; }
  document.getElementById('hist-sum').textContent =
    d.total + ' vouches, ' + fmt(d.points) + ' points';
  if(!d.rows.length){
    holder.innerHTML = '<div class="empty">Nothing matches those filters.</div>';
    return;
  }
  holder.innerHTML = '<table><thead><tr><th>Date</th><th>Event</th><th>Category</th>' +
    '<th>Points</th><th>Given by</th></tr></thead><tbody>' +
    d.rows.map(function(r){
      return '<tr><td style="white-space:nowrap;color:var(--muted);font-size:12px">' +
        String(r.time || '').substring(0,10) + '</td>' +
        '<td>' + esc(r.event) + (r.backfilled ? ' <span style="font-size:10px;color:var(--amber)">[added]</span>' : '') + '</td>' +
        '<td style="color:' + (CAT_COLORS[r.category] || '#646c79') + '">' + esc(r.category_name) + '</td>' +
        '<td style="font-family:var(--mono)">+' + fmt(r.points) + '</td>' +
        '<td style="color:var(--muted);font-size:12px">' + esc(r.by || '-') + '</td></tr>';
    }).join('') + '</tbody></table>';
}

let histTimer = null;
document.addEventListener('DOMContentLoaded', function(){
  document.getElementById('f-cat').onchange = loadHistory;
  document.getElementById('f-days').onchange = loadHistory;
  document.getElementById('f-q').oninput = function(){
    clearTimeout(histTimer); histTimer = setTimeout(loadHistory, 300);
  };
  document.getElementById('f-export').onclick = function(){
    window.location.href = '/api/profile/history.csv?' + histQuery();
  };
});
load();
</script>
</body>
</html>""".replace("__LOGO__", LOGO_SRC)

# ─────────────────────────────────────────────────────────────
# DASHBOARD HTML
# ─────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Matzys Overseer - Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0a0b0e;--header:#101216;--card:#15181d;--card-2:#1c2027;
  --border:#242830;--border-2:#343a45;
  --moon:#e8edf4;--moon-dim:#cdd5e0;--steel:#9aa8c2;--sage:#93b3a1;--red:#d98891;--amber:#d8bb86;
  --text:#f4f6f9;--muted:#98a1ae;--dim:#646c79;
  --mono:'JetBrains Mono',monospace;--sans:'Poppins',system-ui,sans-serif;
  --radius:16px;
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100dvh;
  display:flex;flex-direction:column;overflow-x:hidden}
:focus-visible{outline:2px solid var(--moon);outline-offset:2px;border-radius:6px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
/* ── Drifting blossom, echoing the logo ── */
.petals{position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:0}
.petal{position:absolute;top:-12vh;width:var(--w);height:var(--h);
  background:linear-gradient(140deg,#ffffff,#c9d2e0);
  border-radius:100% 0 100% 0;opacity:0;
  animation:petal-fall var(--dur) linear var(--delay) infinite;will-change:transform,opacity}
@keyframes petal-fall{
  0%{transform:translate3d(0,-12vh,0) rotate(0deg) scale(.9);opacity:0}
  12%{opacity:var(--o)}
  88%{opacity:var(--o)}
  100%{transform:translate3d(var(--drift),112vh,0) rotate(var(--spin)) scale(1);opacity:0}
}
@media (prefers-reduced-motion:reduce){.petals{display:none}}


/* ── Header ── */
.header{position:sticky;top:0;z-index:60;background:var(--header);border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:12px;padding:10px 16px;flex-shrink:0}
.icon-btn{background:none;border:none;color:var(--text);cursor:pointer;padding:8px;border-radius:10px;
  display:flex;align-items:center;justify-content:center;line-height:0;transition:background .15s}
.icon-btn:hover{background:rgba(255,255,255,.06)}
.icon-btn svg{width:22px;height:22px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round}
.brand{width:34px;height:34px;border-radius:11px;display:block;object-fit:cover;flex-shrink:0;
  border:1px solid var(--border)}
.spacer{flex:1}

/* Guild picker pill */
.picker{position:relative}
.pill{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--border);
  border-radius:999px;padding:6px 14px 6px 6px;cursor:pointer;color:var(--text);font-family:inherit;
  font-size:14px;font-weight:500;max-width:min(52vw,320px);transition:border-color .15s}
.pill:hover{border-color:var(--border-2)}
.pill img,.pill .fallback{width:30px;height:30px;border-radius:50%;flex-shrink:0;object-fit:cover}
.pill .fallback{background:var(--card-2);display:flex;align-items:center;justify-content:center;
  font-size:12px;font-weight:600;color:var(--muted)}
.pill .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pill .chev{width:16px;height:16px;stroke:var(--muted);fill:none;stroke-width:2.4;flex-shrink:0}
.menu{position:absolute;top:calc(100% + 8px);background:var(--card);border:1px solid var(--border);
  border-radius:14px;padding:6px;min-width:240px;box-shadow:0 18px 40px rgba(0,0,0,.5);display:none;z-index:70}
.menu.open{display:block}
.picker .menu{left:50%;transform:translateX(-50%)}
.menu-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:10px;cursor:pointer;
  font-size:14px;color:var(--text);background:none;border:none;width:100%;text-align:left;font-family:inherit;
  text-decoration:none}
.menu-item:hover{background:var(--card-2)}
.menu-item img,.menu-item .fallback{width:26px;height:26px;border-radius:50%}
.menu-item.danger{color:var(--red)}
.menu-label{padding:8px 10px 4px;font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--dim)}
.menu-sep{height:1px;background:var(--border);margin:6px 4px}
.avatar-btn{padding:0;background:none;border:none;cursor:pointer;border-radius:50%;flex-shrink:0}
.avatar-btn img{width:38px;height:38px;border-radius:50%;display:block;border:1px solid var(--border)}
.user-menu-wrap{position:relative}
.user-menu-wrap .menu{right:0}

/* ── Drawer nav ── */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:80;opacity:0;pointer-events:none;transition:opacity .2s}
.overlay.show{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;left:0;height:100dvh;width:264px;background:var(--header);z-index:90;
  border-right:1px solid var(--border);transform:translateX(-100%);transition:transform .22s ease;
  display:flex;flex-direction:column;padding:18px 0}
.drawer.open{transform:none}
.drawer-head{display:flex;align-items:center;gap:10px;padding:0 18px 18px;border-bottom:1px solid var(--border)}
.drawer-head h2{font-size:14px;font-weight:600}
.drawer-head p{font-size:11px;color:var(--dim)}
.nav{padding:14px 10px;flex:1;overflow-y:auto}
.nav-label{font-size:10px;letter-spacing:1.4px;text-transform:uppercase;color:var(--dim);padding:10px 10px 6px}
.nav-item{display:flex;align-items:center;gap:11px;padding:11px 12px;border-radius:11px;cursor:pointer;
  color:var(--muted);font-size:14px;font-weight:500;transition:all .15s}
.nav-item:hover{color:var(--text);background:var(--card)}
.nav-item.active{color:var(--moon);background:rgba(232,237,244,.12)}
.nav-item .ic{width:19px;height:19px;flex-shrink:0}
.menu-item .mi{width:17px;height:17px;flex-shrink:0}
.drawer-foot{padding:14px 18px 0;border-top:1px solid var(--border);font-size:12px;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--sage);display:inline-block;margin-right:7px;
  animation:pulse 2.4s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* ── Layout ── */
.content{flex:1;padding:28px 20px 40px;max-width:1180px;width:100%;margin:0 auto;position:relative;z-index:1}
.section{display:none}
.section.active{display:block;animation:fade .25s ease}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* ── Hero ── */
.hero{position:relative;padding:26px 0 34px}
.hero::before{content:'';position:absolute;top:-90px;right:-14%;width:min(78vw,560px);height:min(78vw,560px);
  border-radius:50%;background:radial-gradient(circle,rgba(226,233,243,.30),rgba(226,233,243,.05) 55%,transparent 70%);
  filter:blur(26px);pointer-events:none;z-index:-1}
.hero h1{font-size:clamp(34px,8vw,52px);font-weight:700;letter-spacing:-1.4px;line-height:1.08}
.hero h1 span{color:var(--moon)}
.hero p{margin-top:14px;font-size:clamp(18px,4.4vw,26px);color:#c9d0da;font-weight:400;line-height:1.34;max-width:620px}

/* ── Feature cards ── */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.feature{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:24px;
  display:flex;flex-direction:column;transition:border-color .18s,transform .18s}
.feature:hover{border-color:var(--border-2);transform:translateY(-2px)}
.feature .ic{margin-bottom:18px;color:var(--moon);line-height:0}
.feature .ic svg{width:26px;height:26px}
.feature h3{font-size:20px;font-weight:600;margin-bottom:10px}
.feature p{color:var(--muted);font-size:15px;line-height:1.5;flex:1}
.feature .btn{margin-top:20px;align-self:flex-start}

/* ── Buttons ── */
.btn{padding:11px 20px;border-radius:11px;border:none;cursor:pointer;font-size:14px;font-weight:500;
  font-family:var(--sans);transition:all .15s}
.btn-soft{background:var(--card-2);color:var(--text)}
.btn-soft:hover{background:#262b33}
.btn-primary{background:var(--moon);color:#0a0b0e}
.btn-primary:hover{background:#ffffff}
.btn-danger{background:rgba(217,136,145,.14);color:var(--red);border:1px solid rgba(217,136,145,.24)}
.btn-danger:hover{background:rgba(217,136,145,.24)}
.btn-ghost{background:rgba(255,255,255,.05);color:var(--muted);border:1px solid var(--border)}
.btn-ghost:hover{color:var(--text)}
.btn-sm{padding:6px 12px;font-size:12.5px;border-radius:9px}

/* ── Generic surfaces ── */
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:22px}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.section-head h2{font-size:24px;font-weight:600;letter-spacing:-.5px}
.card-title{font-size:14px;font-weight:600;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;margin-bottom:22px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px}
.stat .val{font-family:var(--mono);font-size:28px;font-weight:600}
.stat .lbl{font-size:12.5px;color:var(--muted);margin-top:4px}
.stat .accent{width:3px;height:30px;border-radius:2px;float:right}
.grid-3{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;padding:9px 12px;color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase;
  letter-spacing:.9px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:11px 12px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}
.mono{font-family:var(--mono);font-size:12px;color:var(--muted)}
.badge{background:rgba(232,237,244,.15);color:var(--moon);border-radius:7px;padding:4px 10px;font-size:11.5px;
  font-weight:600;font-family:var(--mono)}
.badge.green{background:rgba(147,179,161,.14);color:var(--sage)}
.badge.red{background:rgba(217,136,145,.14);color:var(--red)}
.tabs{display:flex;gap:3px;margin-bottom:18px;background:var(--card);border:1px solid var(--border);
  border-radius:12px;padding:4px;width:fit-content;max-width:100%;overflow-x:auto}
.tab{padding:8px 18px;border-radius:9px;cursor:pointer;font-size:13.5px;font-weight:500;color:var(--muted);
  white-space:nowrap;transition:all .15s}
.tab.active{background:var(--card-2);color:var(--text)}
.cat-tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.cat-tab{padding:6px 15px;border-radius:999px;font-size:12.5px;font-weight:500;cursor:pointer;
  border:1px solid var(--border);color:var(--muted);transition:all .15s}
.cat-tab.active{border-color:var(--moon);color:var(--moon);background:rgba(232,237,244,.1)}
.form-group{margin-bottom:16px}
.form-group label{display:block;font-size:12.5px;color:var(--muted);margin-bottom:7px;font-weight:500}
.form-group input,.form-group select,textarea{width:100%;background:var(--card-2);border:1px solid var(--border);
  border-radius:11px;padding:11px 13px;color:var(--text);font-size:14px;font-family:var(--sans);outline:none;
  transition:border-color .15s}
.form-group input:focus,.form-group select:focus,textarea:focus{border-color:var(--moon)}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.toggle-wrap{display:flex;align-items:center;gap:12px}
.toggle{position:relative;width:46px;height:26px;cursor:pointer;flex-shrink:0}
.toggle input{opacity:0;width:0;height:0;position:absolute}
.toggle-slider{position:absolute;inset:0;background:#2b313a;border-radius:26px;transition:.2s}
.toggle input:checked + .toggle-slider{background:var(--sage)}
.toggle-slider:before{content:'';position:absolute;width:20px;height:20px;left:3px;bottom:3px;background:#fff;
  border-radius:50%;transition:.2s}
.toggle input:checked + .toggle-slider:before{transform:translateX(20px)}
.memory-item{display:flex;align-items:center;gap:12px;padding:14px;background:var(--card-2);border-radius:12px;margin-bottom:9px}
.memory-item .text{flex:1;font-size:13.5px;line-height:1.45}
.memory-item .id{font-family:var(--mono);font-size:10.5px;color:var(--dim);margin-top:4px}
.audit-item{display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)}
.audit-item:last-child{border-bottom:none}
.audit-dot{width:8px;height:8px;border-radius:50%;margin-top:6px;flex-shrink:0}
.audit-content .main-text{font-size:13.5px;line-height:1.45}
.audit-content .meta{font-size:11.5px;color:var(--dim);margin-top:3px;font-family:var(--mono)}
.times-grid{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.time-chip{background:var(--card-2);border:1px solid var(--border);border-radius:8px;padding:5px 10px;
  font-family:var(--mono);font-size:12px;color:var(--muted)}
.empty{text-align:center;padding:44px 20px;color:var(--dim);font-size:13.5px}
.member{display:flex;align-items:center;gap:10px;min-width:0}
.member img,.member .ph{width:30px;height:30px;border-radius:50%;flex-shrink:0;background:var(--card-2)}
.member .ph{display:flex;align-items:center;justify-content:center;font-size:12px;color:var(--muted);font-weight:600}
.member .who{min-width:0}
.member .nm{font-size:13.5px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.member .id{font-family:var(--mono);font-size:10.5px;color:var(--dim)}
.rank-row{background:var(--card-2);border-radius:12px;padding:14px;margin-bottom:12px}
.rank-top{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:9px;flex-wrap:wrap}
.rank-name{font-size:14px;font-weight:600}
.rank-next{font-size:11.5px;color:var(--muted);font-family:var(--mono)}
.rank-bar{height:7px;border-radius:4px;background:#242830;overflow:hidden}
.rank-fill{height:100%;border-radius:4px;background:linear-gradient(90deg,#8e97a6,#f4f6f9);transition:width .4s}
.filters{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:16px;align-items:center}
.filters select,.filters input{background:var(--card-2);border:1px solid var(--border);border-radius:10px;
  padding:9px 12px;color:var(--text);font-size:13px;font-family:var(--sans);outline:none}
.filters input{font-family:var(--mono);min-width:150px}
.filters select:focus,.filters input:focus{border-color:var(--moon)}
.chart-wrap{position:relative;width:100%;overflow:hidden}
.chart-wrap svg{width:100%;height:auto;display:block}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;font-size:12px;color:var(--muted)}
.legend i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:6px}
.cmd-item{display:flex;align-items:center;gap:12px;padding:14px;background:var(--card-2);border-radius:12px;margin-bottom:9px}
.cmd-item .body{flex:1;min-width:0}
.cmd-item .nm{font-family:var(--mono);font-size:13.5px;font-weight:600;color:var(--moon)}
.cmd-item .rp{font-size:12.5px;color:var(--muted);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmd-item .mt{font-size:10.5px;color:var(--dim);margin-top:4px;font-family:var(--mono)}
.off{opacity:.5}
.prefix-wrap{position:relative}
.prefix-wrap span{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--dim);
  font-family:var(--mono);font-size:14px;pointer-events:none}
.prefix-wrap input{padding-left:28px!important;font-family:var(--mono)}
.eco-row{display:flex;gap:9px;align-items:center;margin-bottom:9px}
.eco-row input{background:var(--card-2);border:1px solid var(--border);border-radius:10px;padding:10px 12px;
  color:var(--text);font-size:13.5px;font-family:var(--sans);outline:none;min-width:0}
.eco-row input:focus{border-color:var(--moon)}
.eco-row .nm{flex:1}
.eco-row .num{width:104px;font-family:var(--mono);text-align:right}
.eco-row .del{background:none;border:1px solid var(--border);color:var(--dim);border-radius:10px;
  width:38px;height:38px;flex-shrink:0;cursor:pointer;font-size:16px;line-height:1;transition:all .15s}
.eco-row .del:hover{color:var(--red);border-color:rgba(217,136,145,.4)}
.eco-head{display:flex;gap:9px;padding:0 4px 8px;font-size:11px;letter-spacing:.9px;
  text-transform:uppercase;color:var(--dim)}
.eco-head .nm{flex:1}
.eco-head .num{width:104px;text-align:right}
.eco-head .sp{width:38px;flex-shrink:0}
.eco-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:14px;align-items:center}
.eco-note{font-size:12.5px;color:var(--muted);line-height:1.5;margin-bottom:14px}
.alert{border-radius:12px;padding:13px 16px;font-size:13.5px;line-height:1.5}
.alert-warn{background:rgba(216,187,134,.1);border:1px solid rgba(216,187,134,.24);color:var(--amber)}
.alert-success{background:rgba(147,179,161,.1);border:1px solid rgba(147,179,161,.24);color:var(--sage)}
.alert-err{background:rgba(217,136,145,.1);border:1px solid rgba(217,136,145,.24);color:var(--red)}
.user-detail{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:22px;margin-top:20px}

/* ── Footer ── */
.footer{position:relative;z-index:1;border-top:1px solid var(--border);padding:22px 20px 30px;text-align:center;color:var(--dim);font-size:13px}
.footer a{color:var(--dim);text-decoration:none;margin:0 4px}
.footer a:hover{color:var(--muted)}
.footer .sep{opacity:.5;margin:0 4px}
@media(max-width:560px){
  .form-row{grid-template-columns:1fr}
  .content{padding:22px 16px 32px}
  .feature{padding:20px}
}
</style>
</head>
<body>
<div class="petals" aria-hidden="true">
  <i class="petal" style="left:93.7%;--w:7px;--h:6px;--o:0.11;--dur:31.0s;--delay:-2.8s;--drift:3.5vw;--spin:-300deg"></i>
  <i class="petal" style="left:1.8%;--w:6px;--h:5px;--o:0.11;--dur:18.5s;--delay:-12.7s;--drift:10.8vw;--spin:360deg"></i>
  <i class="petal" style="left:61.7%;--w:6px;--h:5px;--o:0.11;--dur:27.0s;--delay:-1.5s;--drift:-7.4vw;--spin:-300deg"></i>
  <i class="petal" style="left:11.5%;--w:13px;--h:11px;--o:0.21;--dur:26.7s;--delay:-16.8s;--drift:6.5vw;--spin:360deg"></i>
  <i class="petal" style="left:55.7%;--w:9px;--h:7px;--o:0.12;--dur:29.1s;--delay:-16.9s;--drift:4.6vw;--spin:720deg"></i>
  <i class="petal" style="left:51.7%;--w:11px;--h:10px;--o:0.19;--dur:32.7s;--delay:-10.8s;--drift:-6.5vw;--spin:540deg"></i>
  <i class="petal" style="left:76.8%;--w:11px;--h:8px;--o:0.16;--dur:25.4s;--delay:-10.3s;--drift:-0.5vw;--spin:-300deg"></i>
  <i class="petal" style="left:9.9%;--w:5px;--h:4px;--o:0.25;--dur:19.6s;--delay:-14.7s;--drift:-12.8vw;--spin:360deg"></i>
  <i class="petal" style="left:54.4%;--w:13px;--h:12px;--o:0.26;--dur:22.8s;--delay:-10.5s;--drift:0.9vw;--spin:720deg"></i>
  <i class="petal" style="left:82.8%;--w:5px;--h:5px;--o:0.19;--dur:28.3s;--delay:-1.8s;--drift:7.0vw;--spin:-300deg"></i>
  <i class="petal" style="left:81.0%;--w:11px;--h:9px;--o:0.18;--dur:28.4s;--delay:-0.7s;--drift:-0.1vw;--spin:540deg"></i>
  <i class="petal" style="left:9.8%;--w:9px;--h:7px;--o:0.25;--dur:19.2s;--delay:-7.4s;--drift:-2.3vw;--spin:720deg"></i>
  <i class="petal" style="left:14.8%;--w:5px;--h:4px;--o:0.16;--dur:19.3s;--delay:-12.9s;--drift:2.5vw;--spin:720deg"></i>
  <i class="petal" style="left:67.0%;--w:7px;--h:6px;--o:0.15;--dur:18.4s;--delay:-4.5s;--drift:5.8vw;--spin:360deg"></i>
  <i class="petal" style="left:81.9%;--w:8px;--h:6px;--o:0.16;--dur:19.5s;--delay:-16.0s;--drift:4.3vw;--spin:-420deg"></i>
  <i class="petal" style="left:67.7%;--w:6px;--h:5px;--o:0.22;--dur:28.5s;--delay:-1.6s;--drift:13.0vw;--spin:-300deg"></i>
</div>

<div class="overlay" id="overlay" onclick="closeDrawer()"></div>

<!-- DRAWER -->
<aside class="drawer" id="drawer">
  <div class="drawer-head">
    <img class="brand" src="__LOGO__" alt="">
    <div><h2>Matzys Overseer</h2><p>Admin dashboard</p></div>
  </div>
  <nav class="nav">
    <div class="nav-label">Main</div>
    <div class="nav-item active" data-sec="home" onclick="showSection('home',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg> Home</div>
    <div class="nav-item" data-sec="overview" onclick="showSection('overview',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/></svg> Overview</div>
    <div class="nav-item" data-sec="leaderboard" onclick="showSection('leaderboard',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 21V11M12 21V4M19 21v-6"/></svg> Leaderboards</div>
    <div class="nav-item" data-sec="users" onclick="showSection('users',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg> Members</div>
    <div class="nav-label">Bot</div>
    <div class="nav-item" data-sec="activity" onclick="showSection('activity',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg> Site activity</div>
    <div class="nav-item" data-sec="economy" onclick="showSection('economy',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M18 7h2M4 12h4M13 12h7M4 17h9M18 17h2M14 4.5v5M9 9.5v5M14 14.5v5"/></svg> Points &amp; ranks</div>
    <div class="nav-item" data-sec="commands" onclick="showSection('commands',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 9l3 3-3 3M13 15h4M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/></svg> Commands</div>
    <div class="nav-item" data-sec="audit" onclick="showSection('audit',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2M9 2h6v4H9zM8 12h8M8 16h5"/></svg> Audit log</div>
    <div class="nav-item" data-sec="memories" onclick="showSection('memories',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg> Memories</div>
    <div class="nav-item" data-sec="events" onclick="showSection('events',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5V12l3 2"/></svg> Event schedule</div>
    <div class="nav-item" data-sec="settings" onclick="showSection('settings',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3M13 4.5v5M7 9.5v5M13 14.5v5"/></svg> Settings</div>
  </nav>
  <div class="drawer-foot">
    <div><span class="dot"></span><span id="bot-label">Checking bot…</span></div>
  </div>
</aside>

<!-- HEADER -->
<header class="header">
  <button class="icon-btn" onclick="openDrawer()" aria-label="Open menu">
    <svg viewBox="0 0 24 24"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
  </button>
  <img class="brand" src="__LOGO__" alt="">
  <div class="spacer"></div>
  <div class="picker">
    <button class="pill" id="guild-pill" onclick="toggleMenu('guild-menu')">
      <span class="fallback" id="guild-icon">&nbsp;</span>
      <span class="name" id="guild-name">Loading…</span>
      <svg class="chev" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>
    </button>
    <div class="menu" id="guild-menu">
      <div class="menu-label">Your servers</div>
      <div id="guild-list"></div>
    </div>
  </div>
  <div class="spacer"></div>
  <div class="user-menu-wrap">
    <button class="avatar-btn" onclick="toggleMenu('user-menu')" aria-label="Account">
      <img id="user-avatar" alt="" src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==">
    </button>
    <div class="menu" id="user-menu">
      <div class="menu-label" id="user-handle">Signed in</div>
      <a class="menu-item" href="/profile"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8"/></svg> My profile</a>
      <div class="menu-item" onclick="showSection('settings')"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3M13 4.5v5M7 9.5v5M13 14.5v5"/></svg> Settings</div>
      <div class="menu-sep"></div>
      <a class="menu-item danger" href="/logout"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg> Sign out</a>
    </div>
  </div>
</header>

<main class="content">

  <!-- HOME -->
  <section id="sec-home" class="section active">
    <div class="hero">
      <h1>Welcome <span id="hero-name">there</span>,</h1>
      <p>find commonly used dashboard pages below.</p>
    </div>
    <div class="cards">
      <article class="feature">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg></div>
        <h3>Site activity</h3>
        <p>See how much the dashboard and profiles actually get used, and by whom.</p>
        <button class="btn btn-soft" onclick="showSection('activity')">View activity</button>
      </article>
      <article class="feature">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M18 7h2M4 12h4M13 12h7M4 17h9M18 17h2M14 4.5v5M9 9.5v5M14 14.5v5"/></svg></div>
        <h3>Points &amp; ranks</h3>
        <p>Change what each event is worth and where every rank role unlocks.</p>
        <button class="btn btn-soft" onclick="showSection('economy')">Points &amp; ranks</button>
      </article>
      <article class="feature">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 9l3 3-3 3M13 15h4M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/></svg></div>
        <h3>Custom commands</h3>
        <p>Build your own <code style="font-family:var(--mono);color:var(--moon)">?commands</code> - pick a name, write the reply, and the bot answers instantly.</p>
        <button class="btn btn-soft" onclick="showSection('commands')">Make a command</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 21V11M12 21V4M19 21v-6"/></svg></div>
        <h3>Leaderboards</h3>
        <p>See who is on top for hosting, security and support, ranked by the points your bot has handed out.</p>
        <button class="btn btn-soft" onclick="showSection('leaderboard')">Open leaderboards</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
        <h3>Members</h3>
        <p>Look up any member, add a vouch by hand, or revert one that shouldn't have counted.</p>
        <button class="btn btn-soft" onclick="showSection('users')">Manage members</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2M9 2h6v4H9zM8 12h8M8 16h5"/></svg></div>
        <h3>Audit log</h3>
        <p>Every vouch, who gave it and when. Backfilled entries are marked so you can spot them fast.</p>
        <button class="btn btn-soft" onclick="showSection('audit')">View audit log</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></div>
        <h3>Memories</h3>
        <p>Teach the bot facts it should keep in mind during chats, and drop the ones it no longer needs.</p>
        <button class="btn btn-soft" onclick="showSection('memories')">Edit memories</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5V12l3 2"/></svg></div>
        <h3>Event schedule</h3>
        <p>Check the ping times for every recurring event so nobody misses a run.</p>
        <button class="btn btn-soft" onclick="showSection('events')">View schedule</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3M13 4.5v5M7 9.5v5M13 14.5v5"/></svg></div>
        <h3>Settings</h3>
        <p>Point the bot at the right channels, pick its persona, and switch chat on or off.</p>
        <button class="btn btn-soft" onclick="showSection('settings')">Open settings</button>
      </article>
    </div>
  </section>

  <!-- OVERVIEW -->
  <section id="sec-overview" class="section">
    <div class="section-head">
      <h2>Overview</h2>
      <div><span class="badge" id="persona-badge">default</span> <span class="badge green" id="chat-badge">Chat on</span></div>
    </div>
    <div class="stat-grid">
      <div class="stat"><div class="accent" style="background:var(--moon)"></div><div class="val" id="stat-users">-</div><div class="lbl">Total members</div></div>
      <div class="stat"><div class="accent" style="background:var(--sage)"></div><div class="val" id="stat-vouches">-</div><div class="lbl">Total vouches</div></div>
      <div class="stat"><div class="accent" style="background:var(--steel)"></div><div class="val" id="stat-memories">-</div><div class="lbl">Memories saved</div></div>
    </div>
    <div class="card" style="margin-bottom:16px">
      <div class="section-head" style="margin-bottom:14px">
        <div class="card-title" style="margin:0">Points awarded over time</div>
        <select id="chart-days" onchange="loadChart()"
          style="background:var(--card-2);border:1px solid var(--border);border-radius:10px;padding:7px 11px;
          color:var(--text);font-size:12.5px;font-family:var(--sans);outline:none">
          <option value="14">Last 14 days</option>
          <option value="30" selected>Last 30 days</option>
          <option value="90">Last 90 days</option>
        </select>
      </div>
      <div class="chart-wrap" id="chart"><div class="empty">Loading…</div></div>
      <div class="legend" id="chart-legend"></div>
    </div>
    <div class="grid-3">
      <div class="card" id="ov-host"></div>
      <div class="card" id="ov-security"></div>
      <div class="card" id="ov-support"></div>
    </div>
  </section>

  <!-- LEADERBOARD -->
  <section id="sec-leaderboard" class="section">
    <div class="section-head"><h2>Leaderboards</h2></div>
    <div class="tabs">
      <div class="tab active" onclick="switchLbTab('pve',this)">Host</div>
      <div class="tab" onclick="switchLbTab('security',this)">Security</div>
      <div class="tab" onclick="switchLbTab('support',this)">Support</div>
    </div>
    <div class="card"><div class="table-wrap" id="lb-table-wrap"><div class="empty">Loading…</div></div></div>
  </section>

  <!-- USERS -->
  <section id="sec-users" class="section">
    <div class="section-head">
      <h2>Members</h2>
      <input id="user-search" placeholder="Search name or ID" oninput="searchUsers()"
        style="background:var(--card-2);border:1px solid var(--border);border-radius:11px;padding:10px 14px;
        color:var(--text);font-family:var(--mono);font-size:13px;outline:none;min-width:220px">
    </div>
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Member</th><th>Host</th><th>Security</th><th>Support</th><th>Total</th><th></th></tr></thead>
          <tbody id="users-table"><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <div class="user-detail" id="user-detail-panel" style="display:none">
      <div class="section-head" style="margin-bottom:14px">
        <h2 style="font-size:18px" id="detail-name">Member</h2>
        <button class="btn btn-ghost btn-sm" onclick="closeDetail()">Close</button>
      </div>
      <div class="cat-tabs" id="detail-cat-tabs"></div>
      <div id="detail-cat-content"></div>
      <div class="card" style="margin-top:20px;background:var(--card-2)">
        <div class="card-title">Add a vouch</div>
        <div class="form-row">
          <div class="form-group"><label>Category</label>
            <select id="add-cat" onchange="populateEvents()">
              <option value="pve">Host</option><option value="security">Security</option><option value="support">Support</option>
            </select>
          </div>
          <div class="form-group"><label>Event</label><select id="add-event"></select></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Count</label><input id="add-count" type="number" min="1" value="1"></div>
          <div class="form-group" style="display:flex;align-items:flex-end">
            <button class="btn btn-primary" style="width:100%" onclick="submitAddVouch()">Add vouch</button>
          </div>
        </div>
        <div id="add-result"></div>
      </div>
    </div>
  </section>

  <!-- AUDIT -->
  <section id="sec-audit" class="section">
    <div class="section-head">
      <h2>Audit log</h2>
      <button class="btn btn-ghost btn-sm" onclick="exportAudit()">Export CSV</button>
    </div>
    <div class="filters">
      <select id="f-cat" onchange="loadAudit()">
        <option value="">All categories</option>
        <option value="pve">Host</option><option value="security">Security</option><option value="support">Support</option>
      </select>
      <select id="f-days" onchange="loadAudit()">
        <option value="0">All time</option><option value="7">Last 7 days</option>
        <option value="30">Last 30 days</option><option value="90">Last 90 days</option>
      </select>
      <input id="f-q" placeholder="Search event, name or ID" oninput="debouncedAudit()">
      <button class="btn btn-ghost btn-sm" onclick="clearAuditFilters()">Clear</button>
    </div>
    <div class="card"><div id="audit-list"><div class="empty">Loading…</div></div></div>
  </section>

  <!-- MEMORIES -->
  <section id="sec-memories" class="section">
    <div class="section-head"><h2>Memories</h2></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Add a memory</div>
      <div class="form-group">
        <textarea id="new-memory-text" rows="3" placeholder="Something the bot should remember"></textarea>
      </div>
      <button class="btn btn-primary" onclick="addMemory()">Save memory</button>
      <div id="memory-result" style="margin-top:12px"></div>
    </div>
    <div class="card"><div id="memories-list"><div class="empty">Loading…</div></div></div>
  </section>

  <!-- EVENTS -->
  <section id="sec-events" class="section">
    <div class="section-head"><h2>Event schedule</h2></div>
    <div id="events-content"><div class="empty">Loading…</div></div>
  </section>

  <!-- SITE ACTIVITY -->
  <section id="sec-activity" class="section">
    <div class="section-head">
      <h2>Site activity</h2>
      <select id="act-days" onchange="loadActivity()"
        style="background:var(--card-2);border:1px solid var(--border);border-radius:10px;padding:8px 12px;
        color:var(--text);font-size:13px;font-family:var(--sans);outline:none">
        <option value="7">Last 7 days</option>
        <option value="30" selected>Last 30 days</option>
        <option value="90">Last 90 days</option>
      </select>
    </div>
    <div class="stat-grid" id="act-stats"></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Page views and visitors</div>
      <div class="chart-wrap" id="act-chart"><div class="empty">Loading...</div></div>
      <div class="legend" id="act-legend"></div>
    </div>
    <div class="card">
      <div class="card-title">Who is using it</div>
      <div class="table-wrap" id="act-people"><div class="empty">Loading...</div></div>
    </div>
  </section>

  <!-- ECONOMY -->
  <section id="sec-economy" class="section">
    <div class="section-head"><h2>Points &amp; ranks</h2></div>
    <div class="tabs" id="eco-tabs">
      <div class="tab active" data-eco="pve">Host</div>
      <div class="tab" data-eco="security">Security</div>
      <div class="tab" data-eco="support">Support</div>
    </div>

    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Event points</div>
      <div class="eco-note" id="ev-note">What each vouch is worth in this category.</div>
      <div class="eco-head"><span class="nm">Event</span><span class="num">Points</span><span class="sp"></span></div>
      <div id="ev-rows"></div>
      <div class="eco-actions">
        <button class="btn btn-ghost btn-sm" id="ev-add">Add event</button>
        <button class="btn btn-primary" id="ev-save">Save event points</button>
        <button class="btn btn-ghost btn-sm" id="ev-reset">Reset to defaults</button>
      </div>
      <div id="ev-result"></div>
    </div>

    <div class="card">
      <div class="card-title">Rank ladder</div>
      <div class="eco-note" id="rk-note">Role names must match your Discord roles exactly.</div>
      <div class="eco-head"><span class="nm">Role name</span><span class="num" id="rk-unit">Unlocks at</span><span class="sp"></span></div>
      <div id="rk-rows"></div>
      <div class="eco-actions">
        <button class="btn btn-ghost btn-sm" id="rk-add">Add rank</button>
        <button class="btn btn-primary" id="rk-save">Save rank ladder</button>
        <button class="btn btn-ghost btn-sm" id="rk-reset">Reset to defaults</button>
      </div>
      <div id="rk-result"></div>
    </div>
  </section>

  <!-- COMMANDS -->
  <section id="sec-commands" class="section">
    <div class="section-head"><h2>Custom commands</h2></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title" id="cmd-form-title">Create a command</div>
      <div class="form-row">
        <div class="form-group"><label>Command name</label>
          <div class="prefix-wrap"><span>?</span><input id="cmd-name" placeholder="rules" maxlength="24"></div>
        </div>
        <div class="form-group"><label>Embed title (optional)</label>
          <input id="cmd-title" placeholder="Server rules" maxlength="200">
        </div>
      </div>
      <div class="form-group"><label>Response</label>
        <textarea id="cmd-response" rows="4" maxlength="1900"
          placeholder="What the bot replies with. You can use {user} for the person who ran it."></textarea>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Send as embed</label>
          <div class="toggle-wrap"><label class="toggle"><input type="checkbox" id="cmd-embed">
            <span class="toggle-slider"></span></label>
            <span style="font-size:13px;color:var(--muted)">Nicer formatting, coloured bar</span></div>
        </div>
        <div class="form-group"><label>Embed colour</label>
          <input id="cmd-color" type="color" value="#c9d0da" style="height:44px;padding:4px">
        </div>
      </div>
      <button class="btn btn-primary" onclick="saveCommand()">Save command</button>
      <button class="btn btn-ghost" onclick="resetCommandForm()" style="margin-left:8px">Reset</button>
      <div id="cmd-result"></div>
    </div>
    <div class="card"><div id="cmd-list"><div class="empty">Loading…</div></div></div>
  </section>

  <!-- SETTINGS -->
  <section id="sec-settings" class="section">
    <div class="section-head"><h2>Settings</h2></div>
    <div class="grid-3" style="margin-bottom:16px">
      <div class="card">
        <div class="card-title">AI chat</div>
        <div class="toggle-wrap">
          <label class="toggle"><input type="checkbox" id="chat-toggle" onchange="toggleChat()"><span class="toggle-slider"></span></label>
          <span id="chat-toggle-label" style="font-size:13.5px;color:var(--muted)">Chat is on</span>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Rank roles</div>
        <p style="font-size:13px;color:var(--muted);line-height:1.5;margin-bottom:14px">
          Recheck every member's points and hand out the right rank role.</p>
        <button class="btn btn-soft" id="resync-btn" onclick="resyncRoles()">Resync all roles</button>
        <div id="resync-result"></div>
      </div>
      <div class="card">
        <div class="card-title">Persona</div>
        <div class="form-group" style="margin:0">
          <select id="persona-select" onchange="savePersona()">
            <option value="default">default</option><option value="hype">hype</option>
            <option value="chill">chill</option><option value="sarcastic">sarcastic</option>
            <option value="formal">formal</option>
          </select>
        </div>
      </div>
    </div>
    <div class="grid-3">
      <div class="card">
        <div class="card-title">Channels</div>
        <div class="form-group"><label>Host vouch channel ID</label><input id="cfg-pve" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Security vouch channel ID</label><input id="cfg-security" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Support vouch channel ID</label><input id="cfg-support" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Live leaderboard channel ID</label><input id="cfg-lb" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Audit log channel ID</label><input id="cfg-audit" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Event ping channel ID</label><input id="cfg-events" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>General chat channel ID</label><input id="cfg-chime" class="mono" placeholder="Channel ID"></div>
      </div>
      <div class="card" style="display:flex;flex-direction:column;justify-content:space-between">
        <div>
          <div class="card-title">Save channels</div>
          <div class="alert alert-warn">Channel changes apply after you restart the bot in Railway.</div>
        </div>
        <div>
          <button class="btn btn-primary" style="margin-top:16px" onclick="saveSettings()">Save all settings</button>
          <div id="settings-result" style="margin-top:12px"></div>
        </div>
      </div>
    </div>
  </section>

</main>

<footer class="footer">
  <span id="footer-copy">&copy; 2026 Matzys Overseer</span>
  <span class="sep">&middot;</span><a href="#" onclick="return false">Terms</a>
  <span class="sep">&middot;</span><a href="#" onclick="return false">Privacy</a>
  <span class="sep">&middot;</span><a href="/logout">Sign out</a>
</footer>

<script>
// ── State ──
let lbData = {};
let usersData = [];
let currentDetailUid = null;
let currentDetailData = null;
let currentDetailCat = 'pve';
let currentLbCat = 'pve';
let me = null;

let CATEGORY_EVENTS = {
  pve: {"Enmity":1.5,"Elder":2,"Titus":3,"Hellmode":15,"Deep Champion":15,"Diluvian W (25)":3,"Diluvian W (50)":10,"Parasol":5,"Layer 2 (1)":3,"Layer 2 (2)":7,"Other Bosses":1},
  security: {"Security Vouch":1,"Depths Vouch":1.5,"Defense Vouch":1,"Depths Defense Vouch":1.5},
  support: {"Support Vouch":1,"Backup Vouch":2,"Depths Safe Vouch":5}
};
const CAT_NAMES = {pve:'Host',security:'Security',support:'Support'};
const CAT_COLORS = {pve:'var(--moon)',security:'var(--steel)',support:'var(--sage)'};

// ── Helpers ──
async function api(path, opts={}) {
  const r = await fetch(path, {headers:{'Content-Type':'application/json'},...opts});
  if(r.status === 401){ window.location.href = '/login'; return {}; }
  return r.json();
}
function fmt(n){return typeof n==='number'?n.toLocaleString('en-US',{maximumFractionDigits:1}):n;}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function memberCell(u){
  const pic = u.avatar ? '<img alt="" src="'+u.avatar+'">'
                       : '<span class="ph">'+esc((u.name||'?').slice(0,1).toUpperCase())+'</span>';
  const nm = u.resolved ? esc(u.name) : 'Unknown member';
  return '<div class="member">'+pic+'<div class="who"><div class="nm">'+nm+
         '</div><div class="id">'+u.uid+'</div></div></div>';
}
function showAlert(el,msg,type='success'){
  el.innerHTML = '<div class="alert alert-'+type+'" style="margin-top:10px">'+msg+'</div>';
  setTimeout(()=>el.innerHTML='',3500);
}

// ── Drawer + menus ──
function openDrawer(){document.getElementById('drawer').classList.add('open');document.getElementById('overlay').classList.add('show');}
function closeDrawer(){document.getElementById('drawer').classList.remove('open');document.getElementById('overlay').classList.remove('show');}
function toggleMenu(id){
  document.querySelectorAll('.menu').forEach(m=>{ if(m.id!==id) m.classList.remove('open'); });
  document.getElementById(id).classList.toggle('open');
}
document.addEventListener('click',e=>{
  if(!e.target.closest('.menu') && !e.target.closest('.pill') && !e.target.closest('.avatar-btn'))
    document.querySelectorAll('.menu').forEach(m=>m.classList.remove('open'));
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){closeDrawer();document.querySelectorAll('.menu').forEach(m=>m.classList.remove('open'));}
});

// ── Session ──
async function loadMe(){
  me = await api('/api/me');
  if(!me.user) return;
  document.getElementById('hero-name').textContent = me.user.username;
  document.getElementById('user-avatar').src = me.user.avatar;
  document.getElementById('user-handle').textContent = me.user.handle ? '@'+me.user.handle : 'Signed in';
  renderGuild(me.guild);
  document.getElementById('guild-list').innerHTML = me.guilds.map(g=>
    '<button class="menu-item" onclick="selectGuild(\\''+g.id+'\\')">'+guildIcon(g)+'<span>'+esc(g.name)+'</span></button>'
  ).join('');
}
function guildIcon(g){
  return g.icon ? '<img alt="" src="'+g.icon+'">'
                : '<span class="fallback">'+esc((g.name||'?').slice(0,1).toUpperCase())+'</span>';
}
function renderGuild(g){
  if(!g) return;
  document.getElementById('guild-name').textContent = g.name;
  const holder = document.getElementById('guild-icon');
  if(g.icon){
    const img = new Image(); img.src = g.icon; img.alt = '';
    holder.replaceWith(img); img.id = 'guild-icon';
  } else { holder.textContent = (g.name||'?').slice(0,1).toUpperCase(); }
}
async function selectGuild(id){
  const r = await api('/api/guild',{method:'POST',body:JSON.stringify({guild_id:id})});
  if(r.ok) location.reload();
}

// ── Navigation ──
function showSection(name, el){
  closeDrawer();
  document.querySelectorAll('.menu').forEach(m=>m.classList.remove('open'));
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(i=>i.classList.remove('active'));
  document.getElementById('sec-'+name).classList.add('active');
  const nav = el && el.classList.contains('nav-item') ? el : document.querySelector('.nav-item[data-sec="'+name+'"]');
  if(nav) nav.classList.add('active');
  window.scrollTo({top:0,behavior:'smooth'});
  if(name==='leaderboard') loadLeaderboard();
  if(name==='audit') loadAudit();
  if(name==='memories') loadMemories();
  if(name==='events') loadEvents();
  if(name==='settings') loadSettings();
  if(name==='users') loadUsers();
  if(name==='overview'){loadStatus();loadChart();}
  if(name==='commands') loadCommands();
  if(name==='economy') loadEconomy();
  if(name==='activity') loadActivity();
}

// ── Status ──
async function loadStatus(){
  const d = await api('/api/status');
  if(!d || d.user_count===undefined) return;
  document.getElementById('bot-label').textContent = 'Bot online';
  document.getElementById('stat-users').textContent = d.user_count;
  document.getElementById('stat-vouches').textContent = d.total_vouches;
  document.getElementById('stat-memories').textContent = d.memory_count;
  document.getElementById('persona-badge').textContent = d.persona;
  const chatBadge = document.getElementById('chat-badge');
  chatBadge.textContent = d.chat_enabled ? 'Chat on' : 'Chat off';
  chatBadge.className = 'badge ' + (d.chat_enabled ? 'green' : 'red');
  loadOverview();
}

// ── Overview ──
async function loadOverview(){
  const d = await api('/api/leaderboard');
  lbData = d;
  ['pve','security','support'].forEach(cat=>{
    const catEl = document.getElementById('ov-' + (cat==='pve'?'host':cat));
    if(!catEl) return;
    const top3 = (d[cat]||[]).slice(0,3);
    catEl.innerHTML = '<div class="card-title" style="color:'+CAT_COLORS[cat]+'">'+CAT_NAMES[cat]+'</div>' +
      (top3.length ? top3.map((u,i)=>
        '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:13.5px">'+
        '<span style="color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">#'+(i+1)+' '+esc(u.resolved?u.name:u.uid)+'</span>'+
        '<span class="mono" style="color:var(--text)">'+fmt(u.points)+' pts</span></div>').join('')
        : '<div class="empty" style="padding:20px">Nothing here yet.</div>');
  });
}

// ── Leaderboard ──
async function loadLeaderboard(){
  if(!Object.keys(lbData).length) lbData = await api('/api/leaderboard');
  renderLbTable(currentLbCat);
}
function switchLbTab(cat, el){
  currentLbCat = cat;
  document.querySelectorAll('.tabs .tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  renderLbTable(cat);
}
function renderLbTable(cat){
  const rows = (lbData[cat]||[]);
  const wrap = document.getElementById('lb-table-wrap');
  if(!rows.length){wrap.innerHTML='<div class="empty">No vouches recorded yet.</div>';return;}
  wrap.innerHTML = '<table><thead><tr><th>#</th><th>Member</th><th>Points</th><th>Vouches</th></tr></thead><tbody>' +
    rows.map((r,i)=>'<tr><td style="color:var(--dim)">'+(i+1)+'</td><td>'+memberCell(r)+'</td>'+
      '<td class="mono" style="color:var(--text);font-weight:600">'+fmt(r.points)+'</td>'+
      '<td style="color:var(--muted)">'+r.vouches+'</td></tr>').join('') + '</tbody></table>';
}

// ── Users ──
async function loadUsers(){
  const d = await api('/api/users');
  usersData = d;
  renderUsers(d);
  populateEvents();
}
function renderUsers(list){
  const tb = document.getElementById('users-table');
  if(!list.length){tb.innerHTML='<tr><td colspan="6" class="empty">No members found.</td></tr>';return;}
  tb.innerHTML = list.map(u=>'<tr>'+
    '<td>'+memberCell(u)+'</td>'+
    '<td class="mono">'+fmt(u.pve)+'</td>'+
    '<td class="mono">'+fmt(u.security)+'</td>'+
    '<td class="mono">'+fmt(u.support)+'</td>'+
    '<td class="mono" style="color:var(--text);font-weight:600">'+fmt(u.total)+'</td>'+
    '<td><button class="btn btn-ghost btn-sm" onclick="viewUser(\\''+u.uid+'\\')">View</button></td></tr>').join('');
}
function searchUsers(){
  const q = document.getElementById('user-search').value.toLowerCase().trim();
  renderUsers(q ? usersData.filter(u=>u.uid.includes(q) || (u.name||'').toLowerCase().includes(q)) : usersData);
}
async function viewUser(uid){
  currentDetailUid = uid;
  document.getElementById('user-detail-panel').style.display='block';
  currentDetailData = await api('/api/users/'+uid);
  document.getElementById('detail-name').innerHTML =
    (currentDetailData.resolved ? esc(currentDetailData.name) : 'Member') +
    ' <span class="mono" style="font-size:13px;color:var(--dim)">'+uid+'</span>';
  renderDetailCatTabs();
  renderDetailCat(currentDetailCat);
  document.getElementById('user-detail-panel').scrollIntoView({behavior:'smooth'});
}
function closeDetail(){
  document.getElementById('user-detail-panel').style.display='none';
  currentDetailUid=null;currentDetailData=null;
}
function renderDetailCatTabs(){
  document.getElementById('detail-cat-tabs').innerHTML = Object.keys(CAT_NAMES).map(cat=>
    '<div class="cat-tab '+(cat===currentDetailCat?'active':'')+'" onclick="switchDetailCat(\\''+cat+'\\',this)">'+CAT_NAMES[cat]+'</div>'
  ).join('');
}
function switchDetailCat(cat, el){
  currentDetailCat=cat;
  document.querySelectorAll('.cat-tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  renderDetailCat(cat);
}
function renderDetailCat(cat){
  const rec = currentDetailData && currentDetailData.categories ? currentDetailData.categories[cat] : null;
  if(!rec){document.getElementById('detail-cat-content').innerHTML='<div class="empty">Nothing recorded here.</div>';return;}
  const evRows = Object.entries(rec.events||{}).filter(([,v])=>v>0)
    .map(([e,c])=>'<tr><td>'+esc(e)+'</td><td class="mono">'+c+'</td><td class="mono">'+fmt(c*(CATEGORY_EVENTS[cat][e]||0))+' pts</td></tr>').join('');
  const logRows = (rec.log||[]).slice().reverse().map(e=>'<tr>'+
    '<td class="mono" style="font-size:11px">'+(e.time||'').substring(0,16).replace('T',' ')+'</td>'+
    '<td>'+esc(e.event)+'</td><td class="mono">'+fmt(e.points)+'</td>'+
    '<td class="mono" style="font-size:11px">'+esc(e.by_name||e.by||'')+'</td>'+
    '<td><button class="btn btn-danger btn-sm" onclick="revertVouch(\\''+(e.idx_id||e.id)+'\\',\\''+cat+'\\')">Revert</button></td></tr>').join('');
  const rk = rec.rank;
  const rankBlock = rk ? '<div class="rank-row"><div class="rank-top">'+
      '<span class="rank-name">'+(rk.current?esc(rk.current):'No rank yet')+'</span>'+
      '<span class="rank-next">'+(rk.next?fmt(rk.remaining)+' to '+esc(rk.next):'Top rank reached')+'</span></div>'+
      '<div class="rank-bar"><div class="rank-fill" style="width:'+rk.pct+'%"></div></div></div>' : '';
  document.getElementById('detail-cat-content').innerHTML = rankBlock +
    '<div class="form-row" style="margin-bottom:16px">'+
      '<div class="stat"><div class="val" style="font-size:22px">'+fmt(rec.total_points)+'</div><div class="lbl">Points</div></div>'+
      '<div class="stat"><div class="val" style="font-size:22px">'+rec.total_vouches+'</div><div class="lbl">Vouches</div></div></div>'+
    (evRows?'<div class="table-wrap"><table style="margin-bottom:16px"><thead><tr><th>Event</th><th>Count</th><th>Points</th></tr></thead><tbody>'+evRows+'</tbody></table></div>':'')+
    (logRows?'<div class="card-title">Recent log</div><div class="table-wrap"><table><thead><tr><th>Time</th><th>Event</th><th>Pts</th><th>By</th><th></th></tr></thead><tbody>'+logRows+'</tbody></table></div>':'');
}
function populateEvents(){
  const cat = document.getElementById('add-cat').value;
  document.getElementById('add-event').innerHTML =
    Object.keys(CATEGORY_EVENTS[cat]).map(e=>'<option value="'+esc(e)+'">'+esc(e)+'</option>').join('');
}
async function submitAddVouch(){
  if(!currentDetailUid) return;
  const body = {uid:currentDetailUid,category:document.getElementById('add-cat').value,
    event_name:document.getElementById('add-event').value,count:parseInt(document.getElementById('add-count').value)||1};
  const r = await api('/api/vouches/add',{method:'POST',body:JSON.stringify(body)});
  const el = document.getElementById('add-result');
  if(r.ok){showAlert(el,'Added. New total: '+fmt(r.new_total)+' pts','success');viewUser(currentDetailUid);}
  else showAlert(el,r.error||'Could not add that vouch.','err');
}
async function revertVouch(logId,cat){
  if(!confirm('Revert this vouch?')) return;
  const r = await api('/api/vouches/revert',{method:'POST',body:JSON.stringify({uid:currentDetailUid,category:cat,log_id:logId})});
  if(r.ok) viewUser(currentDetailUid); else alert(r.error||'Could not revert that vouch.');
}

// ── Audit ──
function auditQuery(){
  const p = new URLSearchParams();
  const cat = document.getElementById('f-cat').value;
  const days = document.getElementById('f-days').value;
  const q = document.getElementById('f-q').value.trim();
  if(cat) p.set('category',cat);
  if(days && days!=='0') p.set('days',days);
  if(q) p.set('q',q);
  return p.toString();
}
let auditTimer = null;
function debouncedAudit(){clearTimeout(auditTimer);auditTimer=setTimeout(loadAudit,300);}
function clearAuditFilters(){
  document.getElementById('f-cat').value='';
  document.getElementById('f-days').value='0';
  document.getElementById('f-q').value='';
  loadAudit();
}
function exportAudit(){window.location.href='/api/auditlog.csv?'+auditQuery();}
async function loadAudit(){
  const data = await api('/api/auditlog?'+auditQuery());
  const el = document.getElementById('audit-list');
  if(!data.length){el.innerHTML='<div class="empty">Nothing matches those filters.</div>';return;}
  el.innerHTML = data.map(e=>'<div class="audit-item">'+
    '<div class="audit-dot" style="background:'+(CAT_COLORS[e.category]||'var(--dim)')+'"></div>'+
    '<div class="audit-content"><div class="main-text"><span style="color:'+CAT_COLORS[e.category]+'">'+
    (CAT_NAMES[e.category]||e.category)+'</span> - '+esc(e.event)+' <span class="mono">('+fmt(e.points)+' pts)</span>'+
    (e.backfilled?' <span style="font-size:10px;color:var(--amber)">[backfill]</span>':'')+'</div>'+
    '<div class="meta">to '+esc(e.name||e.uid)+' · by '+esc(e.by||'?')+' · '+(e.time||'').substring(0,16).replace('T',' ')+'</div>'+
    '</div></div>').join('');
}

// ── Memories ──
async function loadMemories(){
  const data = await api('/api/memories');
  const el = document.getElementById('memories-list');
  if(!data.length){el.innerHTML='<div class="empty">No memories saved yet.</div>';return;}
  el.innerHTML = data.map(m=>'<div class="memory-item"><div style="flex:1"><div class="text">'+esc(m.text)+
    '</div><div class="id">'+m.id+' · '+(m.time||'').substring(0,10)+'</div></div>'+
    '<button class="btn btn-danger btn-sm" onclick="deleteMemory(\\''+m.id+'\\')">Delete</button></div>').join('');
}
async function addMemory(){
  const text = document.getElementById('new-memory-text').value.trim();
  if(!text) return;
  const r = await api('/api/memories',{method:'POST',body:JSON.stringify({text})});
  showAlert(document.getElementById('memory-result'), r.ok?'Memory saved.':(r.error||'Could not save.'), r.ok?'success':'err');
  if(r.ok){document.getElementById('new-memory-text').value='';loadMemories();}
}
async function deleteMemory(id){
  if(!confirm('Delete this memory?')) return;
  await api('/api/memories/'+id,{method:'DELETE'});
  loadMemories();
}

// ── Events ──
async function loadEvents(){
  const data = await api('/api/events');
  document.getElementById('events-content').innerHTML = Object.entries(data).map(([event,times])=>
    '<div class="card" style="margin-bottom:14px"><div class="section-head" style="margin-bottom:10px">'+
    '<div class="card-title" style="margin:0">'+esc(event)+'</div>'+
    '<span class="mono">'+times.length+' times</span></div>'+
    '<div class="times-grid">'+times.map(t=>'<span class="time-chip">'+t+'</span>').join('')+'</div></div>').join('');
}

// ── Site activity ──
async function loadActivity(){
  const days = document.getElementById('act-days').value;
  const d = await api('/api/analytics?days=' + days);
  if(!d || !d.labels) return;

  const t = d.totals || {};
  document.getElementById('act-stats').innerHTML =
    '<div class="stat"><div class="val">' + fmt(t.views || 0) + '</div><div class="lbl">Page views</div></div>' +
    '<div class="stat"><div class="val">' + (t.people || 0) + '</div><div class="lbl">People who visited</div></div>' +
    '<div class="stat"><div class="val">' + fmt(t.per_day || 0) + '</div><div class="lbl">Views per day</div></div>' +
    '<div class="stat"><div class="val" style="font-size:18px">' + (t.busiest || '-') +
      '</div><div class="lbl">Busiest day</div></div>';

  drawActivityChart(d);

  const el = document.getElementById('act-people');
  if(!d.people.length){
    el.innerHTML = '<div class="empty">Nobody has opened the site in this window.</div>';
    return;
  }
  el.innerHTML = '<table><thead><tr><th>Member</th><th>Views</th><th>Days active</th><th>Last seen</th></tr></thead><tbody>' +
    d.people.map(function(p){
      return '<tr><td>' + memberCell(p) + '</td>' +
        '<td class="mono">' + p.views + '</td>' +
        '<td class="mono">' + p.days + '</td>' +
        '<td class="mono" style="font-size:11px;color:var(--muted)">' +
        String(p.last_seen || '').substring(0,16).replace('T',' ') + '</td></tr>';
    }).join('') + '</tbody></table>';
}

function drawActivityChart(d){
  const holder = document.getElementById('act-chart');
  const max = Math.max(1, Math.max.apply(null, d.views.concat(d.uniques)));
  if(!d.views.some(function(v){ return v > 0; })){
    holder.innerHTML = '<div class="empty">No visits recorded yet.</div>';
    document.getElementById('act-legend').innerHTML = '';
    return;
  }
  const W = 760, H = 240, PL = 44, PR = 12, PT = 14, PB = 28;
  const n = d.labels.length;
  const x = function(i){ return PL + (i * (W - PL - PR)) / Math.max(1, n - 1); };
  const y = function(v){ return PT + (H - PT - PB) * (1 - v / max); };
  let g = '';
  for(let i = 0; i <= 4; i++){
    const v = max * i / 4, yy = y(v);
    g += '<line x1="' + PL + '" y1="' + yy + '" x2="' + (W - PR) + '" y2="' + yy +
         '" stroke="#242830" stroke-width="1"/>' +
         '<text x="' + (PL - 8) + '" y="' + (yy + 4) + '" fill="#646c79" font-size="11" text-anchor="end">' +
         Math.round(v) + '</text>';
  }
  const step = Math.max(1, Math.floor(n / 5));
  for(let i = 0; i < n; i += step){
    g += '<text x="' + x(i) + '" y="' + (H - 8) + '" fill="#646c79" font-size="11" text-anchor="middle">' +
         d.labels[i].slice(5) + '</text>';
  }
  const line = function(vals, color, dash){
    return '<polyline points="' + vals.map(function(v,i){ return x(i) + ',' + y(v); }).join(' ') +
      '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"' +
      (dash ? ' stroke-dasharray="4 4"' : '') + '/>';
  };
  holder.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" role="img">' +
    g + line(d.views, '#f4f6f9', false) + line(d.uniques, '#8d9bb5', true) + '</svg>';
  const pages = d.pages || {};
  document.getElementById('act-legend').innerHTML =
    '<span><i style="background:#f4f6f9"></i>Page views</span>' +
    '<span><i style="background:#8d9bb5"></i>Unique visitors</span>' +
    '<span style="color:var(--dim)">dashboard ' + (pages.dashboard || 0) +
    ' / profile ' + (pages.profile || 0) + '</span>';
}

// ── Points and ranks ──
let ECONOMY = null;
let ecoCat = 'pve';

function ecoRow(name, value, numMin){
  const row = document.createElement('div');
  row.className = 'eco-row';
  const a = document.createElement('input');
  a.className = 'nm'; a.value = name == null ? '' : name; a.placeholder = 'Name';
  const b = document.createElement('input');
  b.className = 'num'; b.type = 'number'; b.step = '0.5'; b.min = String(numMin);
  b.value = value == null ? '' : value;
  const x = document.createElement('button');
  x.className = 'del'; x.type = 'button'; x.title = 'Remove'; x.textContent = '\u00d7';
  x.onclick = function(){ row.remove(); };
  row.appendChild(a); row.appendChild(b); row.appendChild(x);
  return row;
}
function readRows(id, valueKey){
  const out = [];
  document.getElementById(id).querySelectorAll('.eco-row').forEach(function(r){
    const name = r.querySelector('.nm').value.trim();
    const num = r.querySelector('.num').value;
    if(!name && num === '') return;
    const item = {name: name};
    item[valueKey] = num === '' ? 0 : Number(num);
    out.push(item);
  });
  return out;
}
async function loadEconomy(){
  ECONOMY = await api('/api/economy');
  if(!ECONOMY || !ECONOMY.events) return;
  CATEGORY_EVENTS = ECONOMY.events;
  renderEconomy();
}
function renderEconomy(){
  if(!ECONOMY) return;
  const events = ECONOMY.events[ecoCat] || {};
  const ranks = ECONOMY.ranks[ecoCat] || [];
  const metric = (ECONOMY.metric || {})[ecoCat] === 'vouches' ? 'vouches' : 'points';

  const ev = document.getElementById('ev-rows');
  ev.innerHTML = '';
  Object.keys(events).forEach(function(name){ ev.appendChild(ecoRow(name, events[name], 0)); });

  const rk = document.getElementById('rk-rows');
  rk.innerHTML = '';
  ranks.forEach(function(r){ rk.appendChild(ecoRow(r[1], r[0], 0)); });

  document.getElementById('rk-unit').textContent = 'Unlocks at (' + metric + ')';
  document.getElementById('rk-note').textContent =
    'Measured in ' + metric + '. Role names must match your Discord roles exactly.';
  if(!ranks.length) rk.innerHTML = '<div class="empty">No rank ladder for this category yet.</div>';
}
async function saveEconomy(section){
  const el = document.getElementById(section === 'events' ? 'ev-result' : 'rk-result');
  const body = {section: section, category: ecoCat};
  if(section === 'events') body.events = readRows('ev-rows', 'points');
  else body.ranks = readRows('rk-rows', 'at');
  const r = await api('/api/economy', {method:'POST', body: JSON.stringify(body)});
  if(!r.ok){ showAlert(el, r.error || 'Could not save.', 'err'); return; }
  if(section === 'events'){
    let msg = 'Saved ' + r.count + ' events. New vouches use these values right away.';
    if(r.removed && r.removed.length){
      msg += ' Removed: ' + r.removed.map(esc).join(', ') + '. Past vouches keep their original points.';
    }
    showAlert(el, msg, 'success');
  } else {
    showAlert(el, 'Saved ' + r.count + ' ranks. Run a resync in Settings to apply them to everyone now.', 'success');
  }
  await loadEconomy();
}
async function resetEconomy(section){
  if(!confirm('Reset this section back to the values in the bot code?')) return;
  await api('/api/economy/reset', {method:'POST', body: JSON.stringify({section: section, category: ecoCat})});
  await loadEconomy();
}
document.addEventListener('DOMContentLoaded', function(){
  document.getElementById('eco-tabs').addEventListener('click', function(e){
    const tab = e.target.closest('[data-eco]');
    if(!tab) return;
    ecoCat = tab.dataset.eco;
    document.querySelectorAll('#eco-tabs .tab').forEach(function(t){ t.classList.remove('active'); });
    tab.classList.add('active');
    renderEconomy();
  });
  document.getElementById('ev-add').onclick = function(){
    document.getElementById('ev-rows').appendChild(ecoRow('', '', 0));
  };
  document.getElementById('rk-add').onclick = function(){
    const rk = document.getElementById('rk-rows');
    if(rk.querySelector('.empty')) rk.innerHTML = '';
    rk.appendChild(ecoRow('', '', 0));
  };
  document.getElementById('ev-save').onclick = function(){ saveEconomy('events'); };
  document.getElementById('rk-save').onclick = function(){ saveEconomy('ranks'); };
  document.getElementById('ev-reset').onclick = function(){ resetEconomy('events'); };
  document.getElementById('rk-reset').onclick = function(){ resetEconomy('ranks'); };
});

// ── Chart ──
async function loadChart(){
  const days = document.getElementById('chart-days').value;
  const d = await api('/api/points_over_time?days='+days);
  if(!d || !d.labels) return;
  renderChart(d);
}
function renderChart(d){
  const W=760,H=240,PL=44,PR=12,PT=14,PB=28;
  const cats=['pve','security','support'];
  const colors={pve:'#f4f6f9',security:'#8d9bb5',support:'#9dbcaa'};
  const all=cats.flatMap(c=>d.series[c]||[]);
  const max=Math.max(1,...all);
  const n=d.labels.length;
  const x=i=>PL+(i*(W-PL-PR))/Math.max(1,n-1);
  const y=v=>PT+(H-PT-PB)*(1-v/max);
  let g='';
  for(let i=0;i<=4;i++){
    const v=max*i/4, yy=y(v);
    g+='<line x1="'+PL+'" y1="'+yy+'" x2="'+(W-PR)+'" y2="'+yy+'" stroke="#242830" stroke-width="1"/>'+
       '<text x="'+(PL-8)+'" y="'+(yy+4)+'" fill="#646c79" font-size="11" text-anchor="end">'+fmt(Math.round(v))+'</text>';
  }
  const step=Math.max(1,Math.floor(n/5));
  for(let i=0;i<n;i+=step){
    g+='<text x="'+x(i)+'" y="'+(H-8)+'" fill="#646c79" font-size="11" text-anchor="middle">'+d.labels[i].slice(5)+'</text>';
  }
  let lines='';
  cats.forEach(c=>{
    const pts=(d.series[c]||[]).map((v,i)=>x(i)+','+y(v)).join(' ');
    lines+='<polyline points="'+pts+'" fill="none" stroke="'+colors[c]+'" stroke-width="2" '+
           'stroke-linejoin="round" stroke-linecap="round"/>';
  });
  document.getElementById('chart').innerHTML =
    '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet" role="img">'+g+lines+'</svg>';
  document.getElementById('chart-legend').innerHTML = cats.map(c=>
    '<span><i style="background:'+colors[c]+'"></i>'+CAT_NAMES[c]+' - '+fmt(d.totals[c])+' pts</span>').join('');
}

// ── Role resync ──
async function resyncRoles(){
  const btn=document.getElementById('resync-btn'), el=document.getElementById('resync-result');
  btn.disabled=true; btn.textContent='Resyncing…';
  const r=await api('/api/roles/resync',{method:'POST'});
  btn.disabled=false; btn.textContent='Resync all roles';
  if(r.ok) showAlert(el,'Done - '+(r.updated||0)+' member(s) updated, '+(r.checked||0)+' checked.','success');
  else showAlert(el, r.error||'Resync failed.','err');
}

// ── Custom commands ──
let editingCommand = null;
let commandsCache = [];
async function loadCommands(){
  const list = await api('/api/commands');
  commandsCache = Array.isArray(list) ? list : [];
  const el = document.getElementById('cmd-list');
  if(!commandsCache.length){el.innerHTML='<div class="empty">No custom commands yet. Make your first one above.</div>';return;}
  el.innerHTML = commandsCache.map((c,i)=>'<div class="cmd-item '+(c.enabled?'':'off')+'">'+
    '<div class="body"><div class="nm">?'+esc(c.name)+'</div>'+
    '<div class="rp">'+esc(c.response)+'</div>'+
    '<div class="mt">'+(c.embed?'embed · ':'')+(c.uses||0)+' uses · by '+esc(c.created_by||'?')+'</div></div>'+
    '<button class="btn btn-ghost btn-sm" data-edit="'+i+'">Edit</button>'+
    '<button class="btn btn-danger btn-sm" data-del="'+i+'">Delete</button></div>').join('');
  el.querySelectorAll('[data-edit]').forEach(b=>{
    b.onclick=()=>editCommand(commandsCache[Number(b.dataset.edit)]);
  });
  el.querySelectorAll('[data-del]').forEach(b=>{
    b.onclick=()=>deleteCommand(commandsCache[Number(b.dataset.del)].name);
  });
}
function editCommand(c){
  if(!c) return;
  editingCommand = c.name;
  document.getElementById('cmd-form-title').textContent = 'Editing ?'+c.name;
  document.getElementById('cmd-name').value = c.name;
  document.getElementById('cmd-title').value = c.title||'';
  document.getElementById('cmd-response').value = c.response||'';
  document.getElementById('cmd-embed').checked = !!c.embed;
  document.getElementById('cmd-color').value = c.color||'#c9d0da';
  window.scrollTo({top:0,behavior:'smooth'});
}
function resetCommandForm(){
  editingCommand = null;
  document.getElementById('cmd-form-title').textContent = 'Create a command';
  ['cmd-name','cmd-title','cmd-response'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('cmd-embed').checked=false;
  document.getElementById('cmd-color').value='#e8edf4';
}
async function saveCommand(){
  const body={
    name:document.getElementById('cmd-name').value,
    title:document.getElementById('cmd-title').value,
    response:document.getElementById('cmd-response').value,
    embed:document.getElementById('cmd-embed').checked,
    color:document.getElementById('cmd-color').value,
    enabled:true,
  };
  const r=await api('/api/commands',{method:'POST',body:JSON.stringify(body)});
  const el=document.getElementById('cmd-result');
  if(r.ok){showAlert(el,'Saved. Members can use ?'+r.command.name+' right away.','success');resetCommandForm();loadCommands();}
  else showAlert(el, r.error||'Could not save that command.','err');
}
async function deleteCommand(name){
  if(!confirm('Delete ?'+name+'?')) return;
  await api('/api/commands/'+encodeURIComponent(name),{method:'DELETE'});
  loadCommands();
}

// ── Settings ──
async function loadSettings(){
  const d = await api('/api/settings');
  document.getElementById('chat-toggle').checked = d.chat_enabled;
  document.getElementById('chat-toggle-label').textContent = d.chat_enabled ? 'Chat is on' : 'Chat is off';
  document.getElementById('persona-select').value = d.persona;
  const c = d.config||{};
  document.getElementById('cfg-pve').value = c.pve_channel_id||'';
  document.getElementById('cfg-security').value = c.security_channel_id||'';
  document.getElementById('cfg-support').value = c.support_channel_id||'';
  document.getElementById('cfg-lb').value = c.live_leaderboard_channel_id||'';
  document.getElementById('cfg-audit').value = c.audit_log_channel_id||'';
  document.getElementById('cfg-events').value = c.event_ping_channel_id||'';
  document.getElementById('cfg-chime').value = c.chime_in_channel_id||'';
}
async function toggleChat(){
  const enabled = document.getElementById('chat-toggle').checked;
  await api('/api/settings',{method:'POST',body:JSON.stringify({chat_enabled:enabled})});
  document.getElementById('chat-toggle-label').textContent = enabled ? 'Chat is on' : 'Chat is off';
  const chatBadge = document.getElementById('chat-badge');
  chatBadge.textContent = enabled ? 'Chat on' : 'Chat off';
  chatBadge.className = 'badge ' + (enabled ? 'green' : 'red');
}
async function savePersona(){
  const p = document.getElementById('persona-select').value;
  await api('/api/settings',{method:'POST',body:JSON.stringify({persona:p})});
  document.getElementById('persona-badge').textContent = p;
}
async function saveSettings(){
  const body = {
    pve_channel_id: document.getElementById('cfg-pve').value,
    security_channel_id: document.getElementById('cfg-security').value,
    support_channel_id: document.getElementById('cfg-support').value,
    live_leaderboard_channel_id: document.getElementById('cfg-lb').value,
    audit_log_channel_id: document.getElementById('cfg-audit').value,
    event_ping_channel_id: document.getElementById('cfg-events').value,
    chime_in_channel_id: document.getElementById('cfg-chime').value,
    persona: document.getElementById('persona-select').value,
    chat_enabled: document.getElementById('chat-toggle').checked,
  };
  const r = await api('/api/settings',{method:'POST',body:JSON.stringify(body)});
  showAlert(document.getElementById('settings-result'),
    r.ok ? 'Settings saved. Restart the bot to apply channel changes.' : 'Could not save settings.',
    r.ok ? 'success' : 'err');
}

// ── Init ──
loadMe();
loadStatus();
loadEconomy();
setInterval(loadStatus, 30000);
</script>
</body>
</html>""".replace("__LOGO__", LOGO_SRC)

# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

def run_dashboard():
    port = int(os.environ.get("PORT", 8080))
    print(f"[Dashboard] Starting on http://0.0.0.0:{port}")
    if not oauth_configured():
        print("[Dashboard] Discord login is NOT configured - set DISCORD_CLIENT_ID, "
              "DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI.")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_dashboard()
