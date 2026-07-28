import json
import os
import secrets
import threading
import urllib.parse
import uuid
from datetime import datetime, timezone
from functools import wraps

import urllib.error
import urllib.request
from flask import Flask, session, redirect, request, jsonify, render_template_string

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

DATA_FILE = os.environ.get("DATA_FILE", "/data/vouches.json")
_file_lock = threading.Lock()

# ── Discord OAuth2 ──
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
# e.g. https://dashboard.sapph.xyz/callback  — must match the Discord dev portal exactly
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "")
# Optional: restrict the dashboard to a single server. Empty = any server you admin.
REQUIRED_GUILD_ID = os.environ.get("GUILD_ID", "").strip()
# Optional: extra allowlist of Discord user IDs, comma separated. Empty = no extra filter.
ALLOWED_USER_IDS = {
    u.strip() for u in os.environ.get("ALLOWED_USER_IDS", "").split(",") if u.strip()
}

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

CATEGORY_EVENTS = {
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

PERSONAS = ["default", "hype", "chill", "sarcastic", "formal"]

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

def admin_required(f):
    """Blocks anything that isn't a Discord-authenticated server administrator."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user") or not session.get("admin_guilds"):
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

    if ALLOWED_USER_IDS and str(user["id"]) not in ALLOWED_USER_IDS:
        return fail("This Discord account isn't on the dashboard allowlist.")

    admin_guilds = [g for g in guilds if is_admin_guild(g)]
    if REQUIRED_GUILD_ID:
        admin_guilds = [g for g in admin_guilds if str(g["id"]) == REQUIRED_GUILD_ID]
        if not admin_guilds:
            return fail("You need the Administrator permission in the bot's server to open this dashboard.")
    if not admin_guilds:
        return fail("You need the Administrator permission in a server to open this dashboard.")

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
    session["guild_id"] = session["admin_guilds"][0]["id"]
    session.permanent = True
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
@admin_required
def index():
    return render_template_string(DASHBOARD_HTML)

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
            {"uid": uid, "points": rec[cat]["total_points"], "vouches": rec[cat]["total_vouches"]}
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
        if q and q not in uid:
            continue
        users.append({
            "uid": uid,
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
    result = {"uid": uid, "total": combined_total(rec), "categories": {}}
    for cat in ALL_CATEGORIES:
        cat_rec = rec.get(cat, {})
        log = cat_rec.get("log", [])
        result["categories"][cat] = {
            "total_points": cat_rec.get("total_points", 0),
            "total_vouches": cat_rec.get("total_vouches", 0),
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
    if category not in CATEGORY_EVENTS:
        return jsonify({"error": "Invalid category"}), 400
    if event_name not in CATEGORY_EVENTS[category]:
        return jsonify({"error": f"Invalid event for {category}"}), 400

    points = CATEGORY_EVENTS[category][event_name]
    data = load_data()
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

@app.route("/api/auditlog")
@admin_required
def api_auditlog():
    data = load_data()
    entries = []
    for uid, rec in user_records(data):
        for cat in ALL_CATEGORIES:
            for i, e in enumerate(rec.get(cat, {}).get("log", [])):
                entries.append({
                    "uid": uid, "category": cat,
                    "event": e.get("event"), "points": e.get("points"),
                    "by": e.get("by_name") or str(e.get("by", "")),
                    "time": e.get("time", ""), "backfilled": e.get("backfilled", False),
                    "id": e.get("id") or f"idx{i}",
                })
    entries.sort(key=lambda e: e.get("time") or "", reverse=True)
    return jsonify(entries[:300])

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
<title>Sign in — Matzys Overseer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#14171d;--panel:#1b2029;--panel-2:#222834;--border:#2b323f;
  --text:#f2f5f9;--muted:#9aa5b4;--blue:#2f9bf5;--red:#f0616d;
}
body{background:var(--bg);color:var(--text);font-family:'Poppins',system-ui,sans-serif;
  min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:24px;overflow-x:hidden}
.glow{position:fixed;top:-10%;right:-20%;width:70vw;height:70vw;border-radius:50%;
  background:radial-gradient(circle,rgba(47,155,245,0.35),transparent 62%);filter:blur(40px);pointer-events:none}
.card{position:relative;background:var(--panel);border:1px solid var(--border);border-radius:18px;
  padding:40px 32px;width:100%;max-width:420px;text-align:center}
.mark{width:56px;height:56px;margin:0 auto 20px;border-radius:16px;display:flex;align-items:center;
  justify-content:center;font-size:24px;background:linear-gradient(140deg,#2f9bf5,#1567c9);
  box-shadow:0 8px 30px rgba(47,155,245,0.35)}
h1{font-size:24px;font-weight:700;letter-spacing:-0.4px}
h1 span{color:var(--blue)}
p.sub{color:var(--muted);font-size:14px;margin-top:8px;line-height:1.5}
.discord-btn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;margin-top:28px;
  background:#5865f2;color:#fff;border:none;border-radius:12px;padding:14px;font-size:15px;font-weight:600;
  font-family:inherit;cursor:pointer;text-decoration:none;transition:transform .15s,background .15s}
.discord-btn:hover{background:#4752c4;transform:translateY(-1px)}
.discord-btn:disabled{background:var(--panel-2);color:var(--muted);cursor:not-allowed;transform:none}
.discord-btn svg{width:22px;height:22px;fill:currentColor}
.note{margin-top:18px;font-size:12px;color:var(--muted);line-height:1.6}
.note code{font-family:'JetBrains Mono',monospace;color:#c8d2e0;font-size:11px}
.error{background:rgba(240,97,109,0.1);border:1px solid rgba(240,97,109,0.3);color:var(--red);
  border-radius:12px;padding:12px 14px;font-size:13px;margin-top:22px;text-align:left;line-height:1.5}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
</style>
</head>
<body>
<div class="glow"></div>
<div class="card">
  <div class="mark">&#9670;</div>
  <h1>Matzys <span>Overseer</span></h1>
  <p class="sub">Sign in with Discord. You need the Administrator permission in the server to get in.</p>

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
</html>"""

# ─────────────────────────────────────────────────────────────
# DASHBOARD HTML
# ─────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Matzys Overseer — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#14171d;--header:#1a1e26;--card:#1e232c;--card-2:#252b36;
  --border:#2b323f;--border-2:#39414f;
  --blue:#2f9bf5;--blue-dark:#1a7fd4;--purple:#a78bfa;--green:#3ddc97;--red:#f0616d;--amber:#f5b942;
  --text:#f2f5f9;--muted:#9aa5b4;--dim:#6b7787;
  --mono:'JetBrains Mono',monospace;--sans:'Poppins',system-ui,sans-serif;
  --radius:16px;
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100dvh;
  display:flex;flex-direction:column;overflow-x:hidden}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px;border-radius:6px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}

/* ── Header ── */
.header{position:sticky;top:0;z-index:60;background:var(--header);border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:12px;padding:10px 16px;flex-shrink:0}
.icon-btn{background:none;border:none;color:var(--text);cursor:pointer;padding:8px;border-radius:10px;
  display:flex;align-items:center;justify-content:center;line-height:0;transition:background .15s}
.icon-btn:hover{background:rgba(255,255,255,.06)}
.icon-btn svg{width:22px;height:22px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round}
.brand{width:34px;height:34px;border-radius:11px;display:flex;align-items:center;justify-content:center;
  font-size:16px;background:linear-gradient(140deg,#2f9bf5,#1567c9);box-shadow:0 6px 18px rgba(47,155,245,.3);flex-shrink:0}
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
.nav-item.active{color:var(--blue);background:rgba(47,155,245,.12)}
.nav-item .ic{font-size:15px;width:20px;text-align:center}
.drawer-foot{padding:14px 18px 0;border-top:1px solid var(--border);font-size:12px;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);display:inline-block;margin-right:7px;
  animation:pulse 2.4s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* ── Layout ── */
.content{flex:1;padding:28px 20px 40px;max-width:1180px;width:100%;margin:0 auto;position:relative}
.section{display:none}
.section.active{display:block;animation:fade .25s ease}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* ── Hero ── */
.hero{position:relative;padding:26px 0 34px}
.hero::before{content:'';position:absolute;top:-90px;right:-14%;width:min(78vw,560px);height:min(78vw,560px);
  border-radius:50%;background:radial-gradient(circle,rgba(47,155,245,.55),rgba(47,155,245,.06) 58%,transparent 70%);
  filter:blur(26px);pointer-events:none;z-index:-1}
.hero h1{font-size:clamp(34px,8vw,52px);font-weight:700;letter-spacing:-1.4px;line-height:1.08}
.hero h1 span{color:var(--blue)}
.hero p{margin-top:14px;font-size:clamp(18px,4.4vw,26px);color:#cdd5e0;font-weight:400;line-height:1.34;max-width:620px}

/* ── Feature cards ── */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.feature{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:24px;
  display:flex;flex-direction:column;transition:border-color .18s,transform .18s}
.feature:hover{border-color:var(--border-2);transform:translateY(-2px)}
.feature .ic{font-size:22px;margin-bottom:18px}
.feature h3{font-size:20px;font-weight:600;margin-bottom:10px}
.feature p{color:var(--muted);font-size:15px;line-height:1.5;flex:1}
.feature .btn{margin-top:20px;align-self:flex-start}

/* ── Buttons ── */
.btn{padding:11px 20px;border-radius:11px;border:none;cursor:pointer;font-size:14px;font-weight:500;
  font-family:var(--sans);transition:all .15s}
.btn-soft{background:var(--card-2);color:var(--text)}
.btn-soft:hover{background:#2e3542}
.btn-primary{background:var(--blue);color:#fff}
.btn-primary:hover{background:var(--blue-dark)}
.btn-danger{background:rgba(240,97,109,.14);color:var(--red);border:1px solid rgba(240,97,109,.24)}
.btn-danger:hover{background:rgba(240,97,109,.24)}
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
.badge{background:rgba(47,155,245,.15);color:var(--blue);border-radius:7px;padding:4px 10px;font-size:11.5px;
  font-weight:600;font-family:var(--mono)}
.badge.green{background:rgba(61,220,151,.14);color:var(--green)}
.badge.red{background:rgba(240,97,109,.14);color:var(--red)}
.tabs{display:flex;gap:3px;margin-bottom:18px;background:var(--card);border:1px solid var(--border);
  border-radius:12px;padding:4px;width:fit-content;max-width:100%;overflow-x:auto}
.tab{padding:8px 18px;border-radius:9px;cursor:pointer;font-size:13.5px;font-weight:500;color:var(--muted);
  white-space:nowrap;transition:all .15s}
.tab.active{background:var(--card-2);color:var(--text)}
.cat-tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.cat-tab{padding:6px 15px;border-radius:999px;font-size:12.5px;font-weight:500;cursor:pointer;
  border:1px solid var(--border);color:var(--muted);transition:all .15s}
.cat-tab.active{border-color:var(--blue);color:var(--blue);background:rgba(47,155,245,.1)}
.form-group{margin-bottom:16px}
.form-group label{display:block;font-size:12.5px;color:var(--muted);margin-bottom:7px;font-weight:500}
.form-group input,.form-group select,textarea{width:100%;background:var(--card-2);border:1px solid var(--border);
  border-radius:11px;padding:11px 13px;color:var(--text);font-size:14px;font-family:var(--sans);outline:none;
  transition:border-color .15s}
.form-group input:focus,.form-group select:focus,textarea:focus{border-color:var(--blue)}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.toggle-wrap{display:flex;align-items:center;gap:12px}
.toggle{position:relative;width:46px;height:26px;cursor:pointer;flex-shrink:0}
.toggle input{opacity:0;width:0;height:0;position:absolute}
.toggle-slider{position:absolute;inset:0;background:#333c4a;border-radius:26px;transition:.2s}
.toggle input:checked + .toggle-slider{background:var(--green)}
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
.alert{border-radius:12px;padding:13px 16px;font-size:13.5px;line-height:1.5}
.alert-warn{background:rgba(245,185,66,.1);border:1px solid rgba(245,185,66,.24);color:var(--amber)}
.alert-success{background:rgba(61,220,151,.1);border:1px solid rgba(61,220,151,.24);color:var(--green)}
.alert-err{background:rgba(240,97,109,.1);border:1px solid rgba(240,97,109,.24);color:var(--red)}
.user-detail{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:22px;margin-top:20px}

/* ── Footer ── */
.footer{border-top:1px solid var(--border);padding:22px 20px 30px;text-align:center;color:var(--dim);font-size:13px}
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

<div class="overlay" id="overlay" onclick="closeDrawer()"></div>

<!-- DRAWER -->
<aside class="drawer" id="drawer">
  <div class="drawer-head">
    <div class="brand">&#9670;</div>
    <div><h2>Matzys Overseer</h2><p>Admin dashboard</p></div>
  </div>
  <nav class="nav">
    <div class="nav-label">Main</div>
    <div class="nav-item active" data-sec="home" onclick="showSection('home',this)"><span class="ic">&#8962;</span> Home</div>
    <div class="nav-item" data-sec="overview" onclick="showSection('overview',this)"><span class="ic">&#9707;</span> Overview</div>
    <div class="nav-item" data-sec="leaderboard" onclick="showSection('leaderboard',this)"><span class="ic">&#127942;</span> Leaderboards</div>
    <div class="nav-item" data-sec="users" onclick="showSection('users',this)"><span class="ic">&#9673;</span> Members</div>
    <div class="nav-label">Bot</div>
    <div class="nav-item" data-sec="audit" onclick="showSection('audit',this)"><span class="ic">&#128203;</span> Audit log</div>
    <div class="nav-item" data-sec="memories" onclick="showSection('memories',this)"><span class="ic">&#129504;</span> Memories</div>
    <div class="nav-item" data-sec="events" onclick="showSection('events',this)"><span class="ic">&#9200;</span> Event schedule</div>
    <div class="nav-item" data-sec="settings" onclick="showSection('settings',this)"><span class="ic">&#9881;</span> Settings</div>
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
  <div class="brand">&#9670;</div>
  <div class="spacer"></div>
  <div class="picker">
    <button class="pill" id="guild-pill" onclick="toggleMenu('guild-menu')">
      <span class="fallback" id="guild-icon">&#9670;</span>
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
      <div class="menu-item" onclick="showSection('settings')"><span>&#9881;</span> Settings</div>
      <div class="menu-sep"></div>
      <a class="menu-item danger" href="/logout"><span>&#8617;</span> Sign out</a>
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
        <div class="ic">&#127942;</div>
        <h3>Leaderboards</h3>
        <p>See who is on top for hosting, security and support, ranked by the points your bot has handed out.</p>
        <button class="btn btn-soft" onclick="showSection('leaderboard')">Open leaderboards</button>
      </article>
      <article class="feature">
        <div class="ic">&#9673;</div>
        <h3>Members</h3>
        <p>Look up any member, add a vouch by hand, or revert one that shouldn't have counted.</p>
        <button class="btn btn-soft" onclick="showSection('users')">Manage members</button>
      </article>
      <article class="feature">
        <div class="ic">&#128203;</div>
        <h3>Audit log</h3>
        <p>Every vouch, who gave it and when. Backfilled entries are marked so you can spot them fast.</p>
        <button class="btn btn-soft" onclick="showSection('audit')">View audit log</button>
      </article>
      <article class="feature">
        <div class="ic">&#129504;</div>
        <h3>Memories</h3>
        <p>Teach the bot facts it should keep in mind during chats, and drop the ones it no longer needs.</p>
        <button class="btn btn-soft" onclick="showSection('memories')">Edit memories</button>
      </article>
      <article class="feature">
        <div class="ic">&#9200;</div>
        <h3>Event schedule</h3>
        <p>Check the ping times for every recurring event so nobody misses a run.</p>
        <button class="btn btn-soft" onclick="showSection('events')">View schedule</button>
      </article>
      <article class="feature">
        <div class="ic">&#9881;</div>
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
      <div class="stat"><div class="accent" style="background:var(--blue)"></div><div class="val" id="stat-users">—</div><div class="lbl">Total members</div></div>
      <div class="stat"><div class="accent" style="background:var(--green)"></div><div class="val" id="stat-vouches">—</div><div class="lbl">Total vouches</div></div>
      <div class="stat"><div class="accent" style="background:var(--purple)"></div><div class="val" id="stat-memories">—</div><div class="lbl">Memories saved</div></div>
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
      <input id="user-search" placeholder="Search by user ID" oninput="searchUsers()"
        style="background:var(--card-2);border:1px solid var(--border);border-radius:11px;padding:10px 14px;
        color:var(--text);font-family:var(--mono);font-size:13px;outline:none;min-width:220px">
    </div>
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr><th>User ID</th><th>Host</th><th>Security</th><th>Support</th><th>Total</th><th></th></tr></thead>
          <tbody id="users-table"><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <div class="user-detail" id="user-detail-panel" style="display:none">
      <div class="section-head" style="margin-bottom:14px">
        <h2 style="font-size:18px">Member <span class="mono" id="detail-uid" style="font-size:14px"></span></h2>
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
    <div class="section-head"><h2>Audit log</h2></div>
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

const CATEGORY_EVENTS = {
  pve: {"Enmity":1.5,"Elder":2,"Titus":3,"Hellmode":15,"Deep Champion":15,"Diluvian W (25)":3,"Diluvian W (50)":10,"Parasol":5,"Layer 2 (1)":3,"Layer 2 (2)":7,"Other Bosses":1},
  security: {"Security Vouch":1,"Depths Vouch":1.5,"Defense Vouch":1,"Depths Defense Vouch":1.5},
  support: {"Support Vouch":1,"Backup Vouch":2,"Depths Safe Vouch":5}
};
const CAT_NAMES = {pve:'Host',security:'Security',support:'Support'};
const CAT_COLORS = {pve:'var(--blue)',security:'var(--purple)',support:'var(--green)'};

// ── Helpers ──
async function api(path, opts={}) {
  const r = await fetch(path, {headers:{'Content-Type':'application/json'},...opts});
  if(r.status === 401){ window.location.href = '/login'; return {}; }
  return r.json();
}
function fmt(n){return typeof n==='number'?n.toLocaleString('en-US',{maximumFractionDigits:1}):n;}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
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
  if(name==='overview') loadStatus();
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
        '<span style="color:var(--muted)">#'+(i+1)+' <span class="mono">'+u.uid+'</span></span>'+
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
  wrap.innerHTML = '<table><thead><tr><th>#</th><th>User ID</th><th>Points</th><th>Vouches</th></tr></thead><tbody>' +
    rows.map((r,i)=>'<tr><td style="color:var(--dim)">'+(i+1)+'</td><td class="mono">'+r.uid+'</td>'+
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
    '<td class="mono">'+u.uid+'</td>'+
    '<td class="mono">'+fmt(u.pve)+'</td>'+
    '<td class="mono">'+fmt(u.security)+'</td>'+
    '<td class="mono">'+fmt(u.support)+'</td>'+
    '<td class="mono" style="color:var(--text);font-weight:600">'+fmt(u.total)+'</td>'+
    '<td><button class="btn btn-ghost btn-sm" onclick="viewUser(\\''+u.uid+'\\')">View</button></td></tr>').join('');
}
function searchUsers(){
  const q = document.getElementById('user-search').value.toLowerCase().trim();
  renderUsers(q ? usersData.filter(u=>u.uid.includes(q)) : usersData);
}
async function viewUser(uid){
  currentDetailUid = uid;
  document.getElementById('user-detail-panel').style.display='block';
  document.getElementById('detail-uid').textContent = uid;
  currentDetailData = await api('/api/users/'+uid);
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
  document.getElementById('detail-cat-content').innerHTML =
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
async function loadAudit(){
  const data = await api('/api/auditlog');
  const el = document.getElementById('audit-list');
  if(!data.length){el.innerHTML='<div class="empty">No audit entries yet.</div>';return;}
  el.innerHTML = data.map(e=>'<div class="audit-item">'+
    '<div class="audit-dot" style="background:'+(CAT_COLORS[e.category]||'var(--dim)')+'"></div>'+
    '<div class="audit-content"><div class="main-text"><span style="color:'+CAT_COLORS[e.category]+'">'+
    (CAT_NAMES[e.category]||e.category)+'</span> — '+esc(e.event)+' <span class="mono">('+fmt(e.points)+' pts)</span>'+
    (e.backfilled?' <span style="font-size:10px;color:var(--amber)">[backfill]</span>':'')+'</div>'+
    '<div class="meta">to '+e.uid+' · by '+esc(e.by||'?')+' · '+(e.time||'').substring(0,16).replace('T',' ')+'</div>'+
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
setInterval(loadStatus, 30000);
</script>
</body>
</html>"""

# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

def run_dashboard():
    port = int(os.environ.get("PORT", 8080))
    print(f"[Dashboard] Starting on http://0.0.0.0:{port}")
    if not oauth_configured():
        print("[Dashboard] Discord login is NOT configured — set DISCORD_CLIENT_ID, "
              "DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI.")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_dashboard()
