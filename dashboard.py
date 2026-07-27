import json
import os
import threading
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, session, redirect, request, jsonify, render_template_string

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

DATA_FILE = os.environ.get("DATA_FILE", "/data/vouches.json")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
_file_lock = threading.Lock()

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET", uuid.uuid4().hex)

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
# AUTH
# ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if not DASHBOARD_PASSWORD:
            error = "No password configured — add DASHBOARD_PASSWORD in Railway Variables."
        elif request.form.get("password") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        else:
            error = "Incorrect password."
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
@login_required
def index():
    return render_template_string(DASHBOARD_HTML)

# ── API: Status ──

@app.route("/api/status")
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
    record["log"].append({
        "id": uuid.uuid4().hex[:8],
        "by": "dashboard",
        "by_name": "Dashboard",
        "event": event_name,
        "points": points * count,
        "count": count,
        "backfilled": True,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    save_data(data)
    return jsonify({"ok": True, "new_total": record["total_points"]})

@app.route("/api/vouches/revert", methods=["POST"])
@login_required
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
@login_required
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
@login_required
def api_memories_get():
    data = load_data()
    return jsonify(data.get("_memories", []))

@app.route("/api/memories", methods=["POST"])
@login_required
def api_memories_add():
    body = request.json or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Text required"}), 400
    data = load_data()
    memories = data.get("_memories", [])
    memories.append({"id": uuid.uuid4().hex[:8], "text": text, "added_by": "dashboard", "time": datetime.now(timezone.utc).isoformat()})
    data["_memories"] = memories[-50:]
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/memories/<memory_id>", methods=["DELETE"])
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
def api_events_get():
    data = load_data()
    overrides = data.get("_event_schedule", {})
    schedule = {**DEFAULT_EVENT_SCHEDULE, **overrides}
    return jsonify(schedule)

@app.route("/api/events", methods=["POST"])
@login_required
def api_events_update():
    body = request.json or {}
    data = load_data()
    # Validate: each value should be a list of HH:MM strings
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
<title>Matzys Overseer — Login</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#080d17;color:#e1e7f0;font-family:'Inter',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;}
.login-card{background:#0f1520;border:1px solid #1e2d42;border-radius:12px;padding:48px;width:100%;max-width:400px;}
.logo{text-align:center;margin-bottom:32px;}
.logo-icon{width:56px;height:56px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);border-radius:14px;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;font-size:24px;}
.logo h1{font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:600;color:#e1e7f0;letter-spacing:0.5px;}
.logo p{color:#64748b;font-size:13px;margin-top:4px;}
label{display:block;font-size:13px;color:#94a3b8;margin-bottom:6px;font-weight:500;}
input[type=password]{width:100%;background:#141c2b;border:1px solid #1e2d42;border-radius:8px;padding:12px 14px;color:#e1e7f0;font-size:14px;font-family:'Inter',sans-serif;outline:none;transition:border-color 0.2s;}
input[type=password]:focus{border-color:#3b82f6;}
.btn{width:100%;background:#3b82f6;color:#fff;border:none;border-radius:8px;padding:13px;font-size:14px;font-weight:600;cursor:pointer;margin-top:20px;transition:background 0.2s;font-family:'Inter',sans-serif;}
.btn:hover{background:#2563eb;}
.error{background:#1f0d0d;border:1px solid #7f1d1d;color:#f87171;border-radius:8px;padding:12px 14px;font-size:13px;margin-bottom:20px;}
</style>
</head>
<body>
<div class="login-card">
  <div class="logo">
    <div class="logo-icon">◆</div>
    <h1>MATZYS OVERSEER</h1>
    <p>Admin Dashboard</p>
  </div>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST">
    <label>Password</label>
    <input type="password" name="password" autofocus placeholder="Enter admin password">
    <button class="btn" type="submit">Sign In</button>
  </form>
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
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#080d17;--sidebar:#0b1120;--card:#111827;--card2:#141e2d;
  --border:#1a2640;--border2:#243450;
  --blue:#3b82f6;--blue-dim:#1d4ed8;
  --purple:#8b5cf6;--green:#10b981;--red:#ef4444;--amber:#f59e0b;
  --text:#dde4ef;--muted:#4b5e7a;--subtle:#64748b;
  --mono:'JetBrains Mono',monospace;--sans:'Inter',sans-serif;
}
body{background:var(--bg);color:var(--text);font-family:var(--sans);display:flex;height:100vh;overflow:hidden;}
/* Sidebar */
.sidebar{width:220px;min-width:220px;background:var(--sidebar);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:20px 0;overflow-y:auto;transition:transform 0.25s ease,width 0.25s ease;z-index:100;}
.sidebar.collapsed{transform:translateX(-220px);width:0;min-width:0;padding:0;border:none;overflow:hidden;}
.hamburger{background:none;border:none;color:var(--text);font-size:18px;cursor:pointer;padding:4px 8px;border-radius:6px;line-height:1;}
.hamburger:hover{background:rgba(255,255,255,0.05);}
@media(max-width:700px){.sidebar{position:fixed;top:0;left:0;height:100vh;}.sidebar.collapsed{transform:translateX(-220px);}.overlay{display:block!important;}}
.sidebar-logo{padding:0 20px 24px;border-bottom:1px solid var(--border);}
.sidebar-logo .icon{width:36px;height:36px;background:linear-gradient(135deg,var(--blue),var(--purple));border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:10px;}
.sidebar-logo h2{font-family:var(--mono);font-size:13px;font-weight:600;color:var(--text);letter-spacing:0.5px;}
.sidebar-logo p{font-size:11px;color:var(--muted);margin-top:2px;}
.nav{padding:16px 0;flex:1;}
.nav-section{font-size:10px;font-weight:600;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;padding:0 20px 8px;}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 20px;cursor:pointer;color:var(--subtle);font-size:13px;font-weight:500;border-left:2px solid transparent;transition:all 0.15s;}
.nav-item:hover{color:var(--text);background:rgba(59,130,246,0.05);}
.nav-item.active{color:var(--blue);background:rgba(59,130,246,0.08);border-left-color:var(--blue);}
.nav-item .icon{font-size:15px;width:20px;text-align:center;}
.sidebar-footer{padding:16px 20px;border-top:1px solid var(--border);}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--green);display:inline-block;animation:pulse 2s infinite;margin-right:6px;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.status-label{font-size:12px;color:var(--subtle);}
.logout-btn{display:block;margin-top:10px;text-align:center;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.2);color:#f87171;border-radius:6px;padding:7px;font-size:12px;cursor:pointer;text-decoration:none;font-weight:500;transition:background 0.15s;}
.logout-btn:hover{background:rgba(239,68,68,0.2);}
/* Main */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;}
.topbar{height:52px;background:var(--sidebar);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 24px;gap:16px;flex-shrink:0;}
.topbar h1{font-size:15px;font-weight:600;color:var(--text);flex:1;}
.badge{background:rgba(59,130,246,0.15);color:var(--blue);border-radius:5px;padding:3px 8px;font-size:11px;font-weight:600;font-family:var(--mono);}
.badge.green{background:rgba(16,185,129,0.15);color:var(--green);}
.badge.red{background:rgba(239,68,68,0.15);color:var(--red);}
.badge.purple{background:rgba(139,92,246,0.15);color:var(--purple);}
.content{flex:1;overflow-y:auto;padding:24px;}
/* Section */
.section{display:none;}.section.active{display:block;}
/* Cards */
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px;}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px;margin-bottom:24px;}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;}
.stat-card .val{font-family:var(--mono);font-size:28px;font-weight:600;color:var(--text);}
.stat-card .lbl{font-size:12px;color:var(--muted);margin-top:4px;}
.stat-card .accent{width:3px;height:32px;border-radius:2px;float:right;margin-top:2px;}
.card-title{font-size:13px;font-weight:600;color:var(--text);margin-bottom:16px;display:flex;align-items:center;gap:8px;}
/* Tables */
table{width:100%;border-collapse:collapse;font-size:13px;}
th{text-align:left;padding:8px 12px;color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:0.8px;border-bottom:1px solid var(--border);}
td{padding:10px 12px;border-bottom:1px solid var(--border);color:var(--text);}
tr:last-child td{border-bottom:none;}
tr:hover td{background:rgba(255,255,255,0.02);}
.mono{font-family:var(--mono);font-size:12px;color:var(--muted);}
/* Tabs */
.tabs{display:flex;gap:2px;margin-bottom:20px;background:var(--card2);border-radius:8px;padding:3px;width:fit-content;}
.tab{padding:7px 16px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;color:var(--muted);transition:all 0.15s;}
.tab.active{background:var(--card);color:var(--text);}
/* Forms */
.form-group{margin-bottom:16px;}
.form-group label{display:block;font-size:12px;color:var(--subtle);margin-bottom:6px;font-weight:500;}
.form-group input,.form-group select{width:100%;background:var(--card2);border:1px solid var(--border);border-radius:7px;padding:9px 12px;color:var(--text);font-size:13px;font-family:var(--sans);outline:none;transition:border-color 0.15s;}
.form-group input:focus,.form-group select:focus{border-color:var(--blue);}
.form-group select option{background:var(--card2);}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
/* Buttons */
.btn{padding:8px 16px;border-radius:7px;border:none;cursor:pointer;font-size:13px;font-weight:500;font-family:var(--sans);transition:all 0.15s;}
.btn-primary{background:var(--blue);color:#fff;}.btn-primary:hover{background:var(--blue-dim);}
.btn-danger{background:rgba(239,68,68,0.15);color:var(--red);border:1px solid rgba(239,68,68,0.2);}.btn-danger:hover{background:rgba(239,68,68,0.25);}
.btn-ghost{background:rgba(255,255,255,0.05);color:var(--subtle);border:1px solid var(--border);}.btn-ghost:hover{color:var(--text);}
.btn-sm{padding:5px 10px;font-size:12px;}
/* Toggle */
.toggle-wrap{display:flex;align-items:center;gap:12px;}
.toggle{position:relative;width:44px;height:24px;cursor:pointer;}
.toggle input{opacity:0;width:0;height:0;position:absolute;}
.toggle-slider{position:absolute;inset:0;background:#1e2d42;border-radius:24px;transition:0.2s;}
.toggle input:checked + .toggle-slider{background:var(--green);}
.toggle-slider:before{content:'';position:absolute;width:18px;height:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:0.2s;}
.toggle input:checked + .toggle-slider:before{transform:translateX(20px);}
/* Memory item */
.memory-item{display:flex;align-items:center;gap:12px;padding:12px;background:var(--card2);border-radius:8px;margin-bottom:8px;}
.memory-item .text{flex:1;font-size:13px;}
.memory-item .id{font-family:var(--mono);font-size:10px;color:var(--muted);}
/* Audit item */
.audit-item{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);}
.audit-item:last-child{border-bottom:none;}
.audit-dot{width:8px;height:8px;border-radius:50%;margin-top:5px;flex-shrink:0;}
.audit-content{flex:1;}
.audit-content .main-text{font-size:13px;color:var(--text);}
.audit-content .meta{font-size:11px;color:var(--muted);margin-top:3px;font-family:var(--mono);}
/* User panel */
.user-detail{background:var(--card2);border-radius:10px;padding:20px;margin-top:20px;}
.cat-tabs{display:flex;gap:8px;margin-bottom:16px;}
.cat-tab{padding:5px 14px;border-radius:20px;font-size:12px;font-weight:500;cursor:pointer;border:1px solid var(--border);color:var(--muted);transition:all 0.15s;}
.cat-tab.active{border-color:var(--blue);color:var(--blue);background:rgba(59,130,246,0.1);}
/* Event times */
.times-grid{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;}
.time-chip{background:var(--card2);border:1px solid var(--border);border-radius:5px;padding:4px 9px;font-family:var(--mono);font-size:12px;color:var(--subtle);}
/* Misc */
.section-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;}
.section-header h2{font-size:18px;font-weight:600;}
.empty{text-align:center;padding:40px;color:var(--muted);font-size:13px;}
.alert{border-radius:8px;padding:12px 16px;font-size:13px;margin-bottom:16px;}
.alert-warn{background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.2);color:var(--amber);}
.alert-success{background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);color:var(--green);}
.alert-err{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.2);color:var(--red);}
.rank-bar{height:4px;background:var(--border);border-radius:2px;margin-top:4px;}
.rank-bar-fill{height:100%;border-radius:2px;background:var(--blue);}
</style>
</head>
<body>
<div id="overlay" onclick="toggleSidebar()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:99;"></div>

<!-- SIDEBAR -->
<aside class="sidebar collapsed" id="sidebar">
  <div class="sidebar-logo">
    <div class="icon">◆</div>
    <h2>MATZYS OVERSEER</h2>
    <p>Admin Dashboard</p>
  </div>
  <nav class="nav">
    <div class="nav-section">Main</div>
    <div class="nav-item active" onclick="showSection('overview')"><span class="icon">⊡</span> Overview</div>
    <div class="nav-item" onclick="showSection('leaderboard')"><span class="icon">🏆</span> Leaderboards</div>
    <div class="nav-item" onclick="showSection('users')"><span class="icon">◉</span> Users</div>
    <div class="nav-section" style="margin-top:12px;">Bot</div>
    <div class="nav-item" onclick="showSection('audit')"><span class="icon">📋</span> Audit Log</div>
    <div class="nav-item" onclick="showSection('memories')"><span class="icon">🧠</span> Memories</div>
    <div class="nav-item" onclick="showSection('events')"><span class="icon">⏰</span> Event Schedule</div>
    <div class="nav-item" onclick="showSection('settings')"><span class="icon">⚙️</span> Settings</div>
  </nav>
  <div class="sidebar-footer">
    <div><span class="status-dot" id="bot-dot"></span><span class="status-label" id="bot-label">Loading...</span></div>
    <a class="logout-btn" href="/logout">Sign Out</a>
  </div>
</aside>

<!-- MAIN -->
<main class="main">
  <div class="topbar">
    <button class="hamburger" onclick="toggleSidebar()">☰</button>
    <h1 id="page-title">Overview</h1>
    <span class="badge" id="persona-badge">default</span>
    <span class="badge green" id="chat-badge">Chat ON</span>
  </div>
  <div class="content">

    <!-- OVERVIEW -->
    <section id="sec-overview" class="section active">
      <div class="card-grid" id="stat-cards">
        <div class="stat-card"><div class="accent" style="background:var(--blue)"></div><div class="val" id="stat-users">—</div><div class="lbl">Total Members</div></div>
        <div class="stat-card"><div class="accent" style="background:var(--green)"></div><div class="val" id="stat-vouches">—</div><div class="lbl">Total Vouches</div></div>
        <div class="stat-card"><div class="accent" style="background:var(--purple)"></div><div class="val" id="stat-memories">—</div><div class="lbl">Memories Saved</div></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;">
        <div class="card" id="ov-host"></div>
        <div class="card" id="ov-security"></div>
        <div class="card" id="ov-support"></div>
      </div>
    </section>

    <!-- LEADERBOARD -->
    <section id="sec-leaderboard" class="section">
      <div class="section-header"><h2>Leaderboards</h2></div>
      <div class="tabs">
        <div class="tab active" onclick="switchLbTab('pve',this)">Host</div>
        <div class="tab" onclick="switchLbTab('security',this)">Security</div>
        <div class="tab" onclick="switchLbTab('support',this)">Support</div>
      </div>
      <div class="card"><div id="lb-table-wrap"><div class="empty">Loading...</div></div></div>
    </section>

    <!-- USERS -->
    <section id="sec-users" class="section">
      <div class="section-header"><h2>Users</h2></div>
      <div class="card" style="margin-bottom:16px;">
        <div style="display:flex;gap:10px;">
          <div class="form-group" style="flex:1;margin:0;"><input id="user-search" placeholder="Search by User ID…" oninput="searchUsers()"></div>
          <button class="btn btn-primary" onclick="searchUsers()">Search</button>
        </div>
      </div>
      <div class="card" id="users-list-card">
        <table><thead><tr><th>User ID</th><th>Host</th><th>Security</th><th>Support</th><th>Total</th><th></th></tr></thead>
        <tbody id="users-table"></tbody></table>
      </div>
      <div id="user-detail-panel" style="display:none;" class="user-detail">
        <div class="section-header">
          <h2 id="detail-uid" style="font-size:15px;font-family:var(--mono)"></h2>
          <button class="btn btn-ghost btn-sm" onclick="closeDetail()">✕ Close</button>
        </div>
        <div class="cat-tabs" id="detail-cat-tabs"></div>
        <div id="detail-cat-content"></div>
        <div style="margin-top:20px;padding-top:16px;border-top:1px solid var(--border);">
          <div class="card-title">Add Vouch</div>
          <div class="form-row">
            <div class="form-group"><label>Category</label><select id="add-cat" onchange="populateEvents()"><option value="pve">Host</option><option value="security">Security</option><option value="support">Support</option></select></div>
            <div class="form-group"><label>Event</label><select id="add-event"></select></div>
          </div>
          <div class="form-row">
            <div class="form-group"><label>Count</label><input type="number" id="add-count" value="1" min="1"></div>
            <div class="form-group" style="display:flex;align-items:flex-end;"><button class="btn btn-primary" onclick="submitAddVouch()">Add Vouch</button></div>
          </div>
          <div id="add-result"></div>
        </div>
      </div>
    </section>

    <!-- AUDIT LOG -->
    <section id="sec-audit" class="section">
      <div class="section-header"><h2>Audit Log</h2><button class="btn btn-ghost btn-sm" onclick="loadAudit()">↻ Refresh</button></div>
      <div class="card"><div id="audit-list"><div class="empty">Loading...</div></div></div>
    </section>

    <!-- MEMORIES -->
    <section id="sec-memories" class="section">
      <div class="section-header"><h2>Memories</h2></div>
      <div class="card" style="margin-bottom:16px;">
        <div class="card-title">Add Memory</div>
        <div style="display:flex;gap:10px;">
          <div class="form-group" style="flex:1;margin:0;"><input id="new-memory-text" placeholder="Something the bot should always remember…"></div>
          <button class="btn btn-primary" onclick="addMemory()">Save</button>
        </div>
        <div id="memory-result" style="margin-top:10px;"></div>
      </div>
      <div class="card"><div id="memories-list"><div class="empty">Loading...</div></div></div>
    </section>

    <!-- EVENT SCHEDULE -->
    <section id="sec-events" class="section">
      <div class="section-header"><h2>Event Schedule</h2><button class="btn btn-ghost btn-sm" onclick="loadEvents()">↻ Refresh</button></div>
      <div class="alert alert-warn">⚠️ Time changes are stored and take effect on the next bot restart.</div>
      <div id="events-content"><div class="empty">Loading...</div></div>
    </section>

    <!-- SETTINGS -->
    <section id="sec-settings" class="section">
      <div class="section-header"><h2>Settings</h2></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        <div class="card">
          <div class="card-title">Bot Chat</div>
          <div class="form-group">
            <label>Chat Enabled</label>
            <div class="toggle-wrap">
              <label class="toggle"><input type="checkbox" id="chat-toggle" onchange="toggleChat()"><span class="toggle-slider"></span></label>
              <span style="font-size:13px;color:var(--subtle)" id="chat-toggle-label">Loading...</span>
            </div>
          </div>
          <div class="form-group">
            <label>Persona</label>
            <select id="persona-select" onchange="savePersona()">
              <option value="default">Default</option>
              <option value="hype">Hype</option>
              <option value="chill">Chill</option>
              <option value="sarcastic">Sarcastic</option>
              <option value="formal">Formal</option>
            </select>
          </div>
        </div>
        <div class="card">
          <div class="card-title">Vouch Channels</div>
          <div class="form-group"><label>Host Channel ID</label><input id="cfg-pve" placeholder="Channel ID" class="mono"></div>
          <div class="form-group"><label>Security Channel ID</label><input id="cfg-security" placeholder="Channel ID" class="mono"></div>
          <div class="form-group"><label>Support Channel ID</label><input id="cfg-support" placeholder="Channel ID" class="mono"></div>
        </div>
        <div class="card">
          <div class="card-title">Output Channels</div>
          <div class="form-group"><label>Live Leaderboard Channel ID</label><input id="cfg-lb" placeholder="Channel ID" class="mono"></div>
          <div class="form-group"><label>Audit Log Channel ID</label><input id="cfg-audit" placeholder="Channel ID" class="mono"></div>
          <div class="form-group"><label>Event Ping Channel ID</label><input id="cfg-events" placeholder="Channel ID" class="mono"></div>
          <div class="form-group"><label>General Chat Channel ID (AI chime-ins)</label><input id="cfg-chime" placeholder="Channel ID" class="mono"></div>
        </div>
        <div class="card" style="display:flex;flex-direction:column;justify-content:space-between;">
          <div>
            <div class="card-title">Save Channel Config</div>
            <div class="alert alert-warn" style="margin-bottom:0">Channel ID changes take effect after a bot restart in Railway.</div>
          </div>
          <button class="btn btn-primary" style="margin-top:16px" onclick="saveSettings()">Save All Settings</button>
          <div id="settings-result" style="margin-top:10px;"></div>
        </div>
      </div>
    </section>

  </div>
</main>

<script>
// ── State ──
let lbData = {};
let usersData = [];
let currentDetailUid = null;
let currentDetailData = null;
let currentDetailCat = 'pve';
let currentLbCat = 'pve';

const CATEGORY_EVENTS = {
  pve: {"Enmity":1.5,"Elder":2,"Titus":3,"Hellmode":15,"Deep Champion":15,"Diluvian W (25)":3,"Diluvian W (50)":10,"Parasol":5,"Layer 2 (1)":3,"Layer 2 (2)":7,"Other Bosses":1},
  security: {"Security Vouch":1,"Depths Vouch":1.5,"Defense Vouch":1,"Depths Defense Vouch":1.5},
  support: {"Support Vouch":1,"Backup Vouch":2,"Depths Safe Vouch":5}
};
const CAT_NAMES = {pve:'Host',security:'Security',support:'Support'};
const CAT_COLORS = {pve:'var(--blue)',security:'var(--purple)',support:'var(--green)'};

// ── Helpers ──
function api(path, opts={}) {
  return fetch(path, {headers:{'Content-Type':'application/json'},...opts}).then(r=>r.json());
}
function fmt(n){return typeof n==='number'?n.toLocaleString('en-US',{maximumFractionDigits:1}):n;}
function showAlert(el, msg, type='success') {
  el.innerHTML = `<div class="alert alert-${type}" style="margin-top:10px">${msg}</div>`;
  setTimeout(()=>el.innerHTML='', 3000);
}

// ── Sidebar ──
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  const ov = document.getElementById('overlay');
  const collapsed = sb.classList.toggle('collapsed');
  ov.style.display = collapsed ? 'none' : 'block';
}
function closeSidebarOnMobile() {
  if(window.innerWidth <= 700) {
    document.getElementById('sidebar').classList.add('collapsed');
    document.getElementById('overlay').style.display = 'none';
  }
}

// ── Navigation ──
function showSection(name) {
  closeSidebarOnMobile();
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(i=>i.classList.remove('active'));
  document.getElementById('sec-'+name).classList.add('active');
  event.currentTarget.classList.add('active');
  const titles = {overview:'Overview',leaderboard:'Leaderboards',users:'Users',audit:'Audit Log',memories:'Memories',events:'Event Schedule',settings:'Settings'};
  document.getElementById('page-title').textContent = titles[name] || name;
  if(name==='leaderboard') loadLeaderboard();
  if(name==='audit') loadAudit();
  if(name==='memories') loadMemories();
  if(name==='events') loadEvents();
  if(name==='settings') loadSettings();
  if(name==='users') loadUsers();
}

// ── Status ──
async function loadStatus() {
  const d = await api('/api/status');
  document.getElementById('bot-dot').style.background = 'var(--green)';
  document.getElementById('bot-label').textContent = 'Bot Online';
  document.getElementById('stat-users').textContent = d.user_count;
  document.getElementById('stat-vouches').textContent = d.total_vouches;
  document.getElementById('stat-memories').textContent = d.memory_count;
  document.getElementById('persona-badge').textContent = d.persona;
  const chatBadge = document.getElementById('chat-badge');
  chatBadge.textContent = d.chat_enabled ? 'Chat ON' : 'Chat OFF';
  chatBadge.className = 'badge ' + (d.chat_enabled ? 'green' : 'red');
  loadOverview();
}

// ── Overview ──
async function loadOverview() {
  const d = await api('/api/leaderboard');
  lbData = d;
  ['pve','security','support'].forEach(cat => {
    const el = document.getElementById('ov-'+cat.replace('pve','host').replace('pve','host'));
    const top3 = (d[cat]||[]).slice(0,3);
    const catEl = document.getElementById('ov-' + (cat==='pve'?'host':cat));
    catEl.innerHTML = `<div class="card-title" style="color:${CAT_COLORS[cat]}">${CAT_NAMES[cat]}</div>` +
      (top3.length ? top3.map((u,i)=>`<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:13px"><span style="color:var(--muted)">#${i+1} <span style="font-family:var(--mono);font-size:11px">${u.uid}</span></span><span style="font-family:var(--mono)">${fmt(u.points)}pts</span></div>`).join('') : '<div class="empty" style="padding:20px">No data</div>');
  });
}

// ── Leaderboard ──
async function loadLeaderboard() {
  if(!Object.keys(lbData).length) {
    const d = await api('/api/leaderboard');
    lbData = d;
  }
  renderLbTable(currentLbCat);
}
function switchLbTab(cat, el) {
  currentLbCat = cat;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  renderLbTable(cat);
}
function renderLbTable(cat) {
  const rows = (lbData[cat]||[]);
  const wrap = document.getElementById('lb-table-wrap');
  if(!rows.length){wrap.innerHTML='<div class="empty">No vouches recorded yet.</div>';return;}
  wrap.innerHTML = '<table><thead><tr><th>#</th><th>User ID</th><th>Points</th><th>Vouches</th></tr></thead><tbody>' +
    rows.map((r,i)=>`<tr><td style="color:var(--muted)">${i+1}</td><td class="mono">${r.uid}</td><td style="font-family:var(--mono)">${fmt(r.points)}</td><td style="color:var(--muted)">${r.vouches}</td></tr>`).join('') +
    '</tbody></table>';
}

// ── Users ──
async function loadUsers() {
  const d = await api('/api/users');
  usersData = d;
  renderUsers(d);
  populateEvents();
}
function renderUsers(list) {
  const tb = document.getElementById('users-table');
  if(!list.length){tb.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:20px">No users found.</td></tr>';return;}
  tb.innerHTML = list.map(u=>`<tr>
    <td class="mono">${u.uid}</td>
    <td style="font-family:var(--mono)">${fmt(u.pve)}</td>
    <td style="font-family:var(--mono)">${fmt(u.security)}</td>
    <td style="font-family:var(--mono)">${fmt(u.support)}</td>
    <td style="font-family:var(--mono);font-weight:600">${fmt(u.total)}</td>
    <td><button class="btn btn-ghost btn-sm" onclick="viewUser('${u.uid}')">View</button></td>
  </tr>`).join('');
}
function searchUsers() {
  const q = document.getElementById('user-search').value.toLowerCase().trim();
  renderUsers(q ? usersData.filter(u=>u.uid.includes(q)) : usersData);
}
async function viewUser(uid) {
  currentDetailUid = uid;
  document.getElementById('user-detail-panel').style.display='block';
  document.getElementById('detail-uid').textContent = uid;
  currentDetailData = await api('/api/users/'+uid);
  renderDetailCatTabs();
  renderDetailCat(currentDetailCat);
  document.getElementById('user-detail-panel').scrollIntoView({behavior:'smooth'});
}
function closeDetail() {
  document.getElementById('user-detail-panel').style.display='none';
  currentDetailUid=null;currentDetailData=null;
}
function renderDetailCatTabs() {
  document.getElementById('detail-cat-tabs').innerHTML = Object.keys(CAT_NAMES).map(cat=>
    `<div class="cat-tab ${cat===currentDetailCat?'active':''}" onclick="switchDetailCat('${cat}',this)">${CAT_NAMES[cat]}</div>`
  ).join('');
}
function switchDetailCat(cat,el) {
  currentDetailCat=cat;
  document.querySelectorAll('.cat-tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  renderDetailCat(cat);
}
function renderDetailCat(cat) {
  const rec = currentDetailData?.categories?.[cat];
  if(!rec){document.getElementById('detail-cat-content').innerHTML='<div class="empty">No data.</div>';return;}
  const evRows = Object.entries(rec.events||{}).filter(([,v])=>v>0)
    .map(([e,c])=>`<tr><td>${e}</td><td class="mono">${c}</td><td class="mono">${fmt(c*(CATEGORY_EVENTS[cat][e]||0))} pts</td></tr>`).join('');
  const logRows = (rec.log||[]).slice().reverse().map(e=>`<tr>
    <td class="mono" style="font-size:11px">${(e.time||'').substring(0,16).replace('T',' ')}</td>
    <td>${e.event}</td>
    <td class="mono">${fmt(e.points)}</td>
    <td class="mono" style="font-size:11px">${e.by||''}</td>
    <td><button class="btn btn-danger btn-sm" onclick="revertVouch('${e.idx_id||e.id}','${cat}')">Revert</button></td>
  </tr>`).join('');
  document.getElementById('detail-cat-content').innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
      <div class="stat-card" style="padding:14px"><div class="val" style="font-size:22px">${fmt(rec.total_points)}</div><div class="lbl">Points</div></div>
      <div class="stat-card" style="padding:14px"><div class="val" style="font-size:22px">${rec.total_vouches}</div><div class="lbl">Vouches</div></div>
    </div>
    ${evRows?`<table style="margin-bottom:16px"><thead><tr><th>Event</th><th>Count</th><th>Points</th></tr></thead><tbody>${evRows}</tbody></table>`:''}
    ${logRows?`<div class="card-title">Recent Log</div><table><thead><tr><th>Time</th><th>Event</th><th>Pts</th><th>By</th><th></th></tr></thead><tbody>${logRows}</tbody></table>`:''}
  `;
}
function populateEvents() {
  const cat = document.getElementById('add-cat').value;
  const sel = document.getElementById('add-event');
  sel.innerHTML = Object.keys(CATEGORY_EVENTS[cat]).map(e=>`<option value="${e}">${e}</option>`).join('');
}
async function submitAddVouch() {
  if(!currentDetailUid) return;
  const body = {uid:currentDetailUid,category:document.getElementById('add-cat').value,event_name:document.getElementById('add-event').value,count:parseInt(document.getElementById('add-count').value)||1};
  const r = await api('/api/vouches/add',{method:'POST',body:JSON.stringify(body)});
  const el = document.getElementById('add-result');
  if(r.ok){showAlert(el,`✅ Added! New total: ${fmt(r.new_total)} pts`,'success');viewUser(currentDetailUid);}
  else showAlert(el,'❌ '+r.error,'err');
}
async function revertVouch(logId,cat) {
  if(!confirm('Revert this vouch?')) return;
  const r = await api('/api/vouches/revert',{method:'POST',body:JSON.stringify({uid:currentDetailUid,category:cat,log_id:logId})});
  if(r.ok){viewUser(currentDetailUid);}
  else alert('Error: '+r.error);
}

// ── Audit ──
async function loadAudit() {
  const data = await api('/api/auditlog');
  const el = document.getElementById('audit-list');
  if(!data.length){el.innerHTML='<div class="empty">No audit entries yet.</div>';return;}
  el.innerHTML = data.map(e=>`<div class="audit-item">
    <div class="audit-dot" style="background:${CAT_COLORS[e.category]||'var(--muted)'}"></div>
    <div class="audit-content">
      <div class="main-text"><span style="color:${CAT_COLORS[e.category]}">${CAT_NAMES[e.category]||e.category}</span> — ${e.event} <span style="color:var(--muted);font-family:var(--mono)">(${fmt(e.points)} pts)</span>${e.backfilled?' <span style="font-size:10px;color:var(--amber)">[backfill]</span>':''}</div>
      <div class="meta">→ UID ${e.uid} · from ${e.by||'?'} · ${(e.time||'').substring(0,16).replace('T',' ')}</div>
    </div>
  </div>`).join('');
}

// ── Memories ──
async function loadMemories() {
  const data = await api('/api/memories');
  const el = document.getElementById('memories-list');
  if(!data.length){el.innerHTML='<div class="empty">No memories saved yet.</div>';return;}
  el.innerHTML = data.map(m=>`<div class="memory-item">
    <div style="flex:1"><div class="text">${m.text}</div><div class="id">${m.id} · ${(m.time||'').substring(0,10)}</div></div>
    <button class="btn btn-danger btn-sm" onclick="deleteMemory('${m.id}')">Delete</button>
  </div>`).join('');
}
async function addMemory() {
  const text = document.getElementById('new-memory-text').value.trim();
  if(!text) return;
  const r = await api('/api/memories',{method:'POST',body:JSON.stringify({text})});
  showAlert(document.getElementById('memory-result'),r.ok?'✅ Memory saved.':'❌ '+r.error,r.ok?'success':'err');
  if(r.ok){document.getElementById('new-memory-text').value='';loadMemories();}
}
async function deleteMemory(id) {
  if(!confirm('Delete this memory?')) return;
  await api('/api/memories/'+id,{method:'DELETE'});
  loadMemories();
}

// ── Events ──
async function loadEvents() {
  const data = await api('/api/events');
  const el = document.getElementById('events-content');
  el.innerHTML = Object.entries(data).map(([event,times])=>`
    <div class="card" style="margin-bottom:14px">
      <div class="section-header" style="margin-bottom:10px">
        <div class="card-title" style="margin:0">${event}</div>
        <span class="mono" style="font-size:11px">${times.length} times</span>
      </div>
      <div class="times-grid">${times.map(t=>`<span class="time-chip">${t}</span>`).join('')}</div>
    </div>
  `).join('');
}

// ── Settings ──
async function loadSettings() {
  const d = await api('/api/settings');
  document.getElementById('chat-toggle').checked = d.chat_enabled;
  document.getElementById('chat-toggle-label').textContent = d.chat_enabled ? 'Chat is ON' : 'Chat is OFF';
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
async function toggleChat() {
  const enabled = document.getElementById('chat-toggle').checked;
  await api('/api/settings',{method:'POST',body:JSON.stringify({chat_enabled:enabled})});
  document.getElementById('chat-toggle-label').textContent = enabled ? 'Chat is ON' : 'Chat is OFF';
  const chatBadge = document.getElementById('chat-badge');
  chatBadge.textContent = enabled ? 'Chat ON' : 'Chat OFF';
  chatBadge.className = 'badge ' + (enabled ? 'green' : 'red');
}
async function savePersona() {
  const p = document.getElementById('persona-select').value;
  await api('/api/settings',{method:'POST',body:JSON.stringify({persona:p})});
  document.getElementById('persona-badge').textContent = p;
}
async function saveSettings() {
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
  showAlert(document.getElementById('settings-result'),r.ok?'✅ Settings saved. Restart bot for channel changes to take effect.':'❌ Error saving.',r.ok?'success':'err');
}

// ── Init ──
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
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_dashboard()
