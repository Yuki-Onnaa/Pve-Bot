"""Shared data store for vouch_bot.py and dashboard.py.

Both run in the same OS process on different threads (the dashboard runs in a
background thread started by vouch_bot.py), so everything here is guarded by a
single lock - a dashboard admin edit and a live /host command can't clobber
each other.

Storage is SQLite. load_data()/save_data()/data_txn() still hand out the whole
top-level dict so callers didn't have to change, but each top-level key is its
own row and save_data() only rewrites the rows that actually changed. The
device logs (IPs, fingerprints, HWIDs), which grow without bound, live in their
own indexed table and are never part of that dict.

On first start, an existing JSON data file is imported automatically and
renamed to <name>.json.migrated.
"""
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime

DATA_FILE = os.environ.get("DATA_FILE", "/data/vouches.json")

# Reentrant so a thread already holding it (e.g. inside a data_txn) can safely
# call load_data()/save_data() again without deadlocking itself.
_lock = threading.RLock()

# Ban check cache (TTL: 60 seconds) to avoid repeated lookups for same identifiers
_ban_cache = {}
_ban_cache_ttl = 60

# Top-level keys the old JSON format kept device logs under -> device_logs.kind
LOG_SECTIONS = {"_ip_logs": "ip", "_fingerprint_logs": "fingerprint", "_hwid_logs": "hwid"}

_conn = None
_conn_path = None


def db_path():
    return os.environ.get("DB_FILE") or os.path.splitext(DATA_FILE)[0] + ".db"


def _db():
    """The shared connection, (re)opened if the configured path changed. Callers hold _lock."""
    global _conn, _conn_path
    path = db_path()
    if _conn is not None and _conn_path == path:
        return _conn
    if _conn is not None:
        _conn.close()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS device_logs ("
        " kind TEXT NOT NULL, value TEXT NOT NULL, user_id TEXT NOT NULL, seen_at TEXT NOT NULL,"
        " PRIMARY KEY (kind, value, user_id))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS device_logs_by_user ON device_logs (kind, user_id)")
    try:
        _migrate_json_file(conn)
    except BaseException:
        conn.close()
        raise
    _conn, _conn_path = conn, path
    return conn


def _migrate_json_file(conn):
    if not os.path.exists(DATA_FILE):
        return
    if conn.execute("SELECT 1 FROM kv LIMIT 1").fetchone():
        return
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
    _replace_all(conn, data)
    os.replace(DATA_FILE, DATA_FILE + ".migrated")
    print(f"[DataStore] Migrated {DATA_FILE} into {db_path()} ({len(data)} top-level keys)")


@contextmanager
def _write(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _insert_logs(conn, kind, section):
    conn.executemany(
        "INSERT INTO device_logs (kind, value, user_id, seen_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (kind, value, user_id) DO UPDATE SET seen_at = excluded.seen_at",
        [(kind, value, str(uid), seen) for value, users in (section or {}).items() for uid, seen in users.items()],
    )


def _replace_all(conn, data):
    with _write(conn):
        conn.execute("DELETE FROM kv")
        conn.execute("DELETE FROM device_logs")
        for key, value in data.items():
            if key in LOG_SECTIONS:
                _insert_logs(conn, LOG_SECTIONS[key], value)
            else:
                conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (key, _dumps(value)))


def _dumps(value):
    return json.dumps(value, separators=(",", ":"))


def load_data():
    with _lock:
        rows = _db().execute("SELECT key, value FROM kv").fetchall()
        return {key: json.loads(value) for key, value in rows}


def save_data(data):
    """Persists the top-level dict, writing only rows that changed and deleting
    keys that were removed. Device-log sections (only present when restoring an
    old JSON backup) are merged into the device log table."""
    with _lock:
        conn = _db()
        existing = dict(conn.execute("SELECT key, value FROM kv").fetchall())
        with _write(conn):
            for key, value in data.items():
                if key in LOG_SECTIONS:
                    _insert_logs(conn, LOG_SECTIONS[key], value)
                    continue
                encoded = _dumps(value)
                if existing.get(key) != encoded:
                    conn.execute(
                        "INSERT INTO kv (key, value) VALUES (?, ?)"
                        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                        (key, encoded),
                    )
            removed = [(key,) for key in existing if key not in data]
            if removed:
                conn.executemany("DELETE FROM kv WHERE key = ?", removed)


@contextmanager
def data_txn():
    """Hold the shared lock across an entire load -> mutate -> save sequence, so
    a concurrent writer (another bot command/loop, or a dashboard request) can't
    interleave and silently lose an update.

    Only wrap plain, synchronous dict mutations in this. Never `await` (or make
    a blocking Discord API round-trip) while inside this block - that would hold
    the lock for the duration of a network call and stall every other writer,
    bot and dashboard side alike, until it returns. Code that has to touch
    Discord in the middle of a read-modify-write should instead re-load right
    before its final save, to keep the race window small without blocking
    anything else.
    """
    with _lock:
        data = load_data()
        yield data
        save_data(data)


def export_all():
    """Everything, device logs included, in the original single-JSON format."""
    with _lock:
        data = load_data()
        for section, kind in LOG_SECTIONS.items():
            data[section] = get_log_section(kind)
        return data


def import_all(data):
    """Replaces the entire store (device logs included) with an export_all()-style dict."""
    with _lock:
        _replace_all(_db(), data)
        _ban_cache.clear()


def _cache_get(key):
    if key in _ban_cache:
        cached_time, cached_result = _ban_cache[key]
        if time.time() - cached_time < _ban_cache_ttl:
            return cached_result
        else:
            del _ban_cache[key]
    return None


def _cache_set(key, result):
    _ban_cache[key] = (time.time(), result)


def _cache_clear_key(key):
    if key in _ban_cache:
        del _ban_cache[key]


# ── Device logs ──

def _log(kind, user_id, value):
    with _lock:
        conn = _db()
        with _write(conn):
            _insert_logs(conn, kind, {value: {str(user_id): datetime.now().isoformat()}})


def log_device(user_id, ip=None, fingerprint=None, hwid=None):
    """Logs IP, fingerprint and HWID in a single transaction."""
    now = datetime.now().isoformat()
    with _lock:
        conn = _db()
        with _write(conn):
            for kind, value in (("ip", ip), ("fingerprint", fingerprint), ("hwid", hwid)):
                if value:
                    _insert_logs(conn, kind, {value: {str(user_id): now}})


def get_log_section(kind):
    """{value: {user_id: last_seen}} for one kind - the shape the old JSON sections had."""
    with _lock:
        rows = _db().execute(
            "SELECT value, user_id, seen_at FROM device_logs WHERE kind = ?", (kind,)
        ).fetchall()
    section = {}
    for value, uid, seen in rows:
        section.setdefault(value, {})[uid] = seen
    return section


def get_user_logs(kind, user_id):
    """{value: last_seen} for everything of one kind logged against a user."""
    with _lock:
        rows = _db().execute(
            "SELECT value, seen_at FROM device_logs WHERE kind = ? AND user_id = ?", (kind, str(user_id))
        ).fetchall()
    return dict(rows)


def _values_for_user(kind, user_id):
    return list(get_user_logs(kind, user_id))


def _users_for_value(kind, value):
    with _lock:
        rows = _db().execute(
            "SELECT user_id FROM device_logs WHERE kind = ? AND value = ?", (kind, value)
        ).fetchall()
    return [uid for (uid,) in rows]


def log_ip(user_id, ip):
    _log("ip", user_id, ip)


def log_fingerprint(user_id, fingerprint_json):
    _log("fingerprint", user_id, fingerprint_json)


def log_hwid(user_id, hwid):
    _log("hwid", user_id, hwid)


def get_ips_for_user(user_id):
    return _values_for_user("ip", user_id)


def get_users_for_ip(ip):
    return _users_for_value("ip", ip)


def get_fingerprints_for_user(user_id):
    return _values_for_user("fingerprint", user_id)


def get_users_for_fingerprint(fingerprint):
    return _users_for_value("fingerprint", fingerprint)


def get_hwids_for_user(user_id):
    return _values_for_user("hwid", user_id)


def get_users_for_hwid(hwid):
    return _users_for_value("hwid", hwid)


# ── Bans ──

def is_ip_banned(ip):
    cached = _cache_get(f"ip:{ip}")
    if cached is not None:
        return cached

    data = load_data()
    banned_ips = data.get("_ip_bans", {})
    if ip not in banned_ips:
        _cache_set(f"ip:{ip}", False)
        return False
    ban_record = banned_ips[ip]
    if "expires_at" in ban_record:
        expiry = datetime.fromisoformat(ban_record["expires_at"])
        if datetime.now() > expiry:
            unban_ip(ip)
            _cache_set(f"ip:{ip}", False)
            return False
    _cache_set(f"ip:{ip}", True)
    return True


def ban_ip(ip, user_id, expires_at=None):
    with data_txn() as data:
        if "_ip_bans" not in data:
            data["_ip_bans"] = {}
        ban_record = {"user_id": str(user_id), "banned_at": datetime.now().isoformat()}
        if expires_at:
            ban_record["expires_at"] = expires_at
        data["_ip_bans"][ip] = ban_record
    _cache_clear_key(f"ip:{ip}")


def unban_ip(ip):
    with data_txn() as data:
        if "_ip_bans" in data and ip in data["_ip_bans"]:
            del data["_ip_bans"][ip]
    _cache_clear_key(f"ip:{ip}")


def is_fingerprint_banned(fingerprint):
    cached = _cache_get(f"fp:{fingerprint}")
    if cached is not None:
        return cached

    data = load_data()
    banned_fingerprints = data.get("_fingerprint_bans", {})
    if fingerprint not in banned_fingerprints:
        _cache_set(f"fp:{fingerprint}", False)
        return False
    ban_record = banned_fingerprints[fingerprint]
    if "expires_at" in ban_record:
        expiry = datetime.fromisoformat(ban_record["expires_at"])
        if datetime.now() > expiry:
            unban_fingerprint(fingerprint)
            _cache_set(f"fp:{fingerprint}", False)
            return False
    _cache_set(f"fp:{fingerprint}", True)
    return True


def ban_fingerprint(fingerprint, user_id, expires_at=None):
    with data_txn() as data:
        if "_fingerprint_bans" not in data:
            data["_fingerprint_bans"] = {}
        ban_record = {"user_id": str(user_id), "banned_at": datetime.now().isoformat()}
        if expires_at:
            ban_record["expires_at"] = expires_at
        data["_fingerprint_bans"][fingerprint] = ban_record
    _cache_clear_key(f"fp:{fingerprint}")


def unban_fingerprint(fingerprint):
    with data_txn() as data:
        if "_fingerprint_bans" in data and fingerprint in data["_fingerprint_bans"]:
            del data["_fingerprint_bans"][fingerprint]
    _cache_clear_key(f"fp:{fingerprint}")


def is_hwid_banned(hwid):
    cached = _cache_get(f"hwid:{hwid}")
    if cached is not None:
        return cached

    data = load_data()
    banned_hwids = data.get("_hwid_bans", {})
    if hwid not in banned_hwids:
        _cache_set(f"hwid:{hwid}", False)
        return False
    ban_record = banned_hwids[hwid]
    if "expires_at" in ban_record:
        expiry = datetime.fromisoformat(ban_record["expires_at"])
        if datetime.now() > expiry:
            unban_hwid(hwid)
            _cache_set(f"hwid:{hwid}", False)
            return False
    _cache_set(f"hwid:{hwid}", True)
    return True


def ban_hwid(hwid, user_id, expires_at=None):
    with data_txn() as data:
        if "_hwid_bans" not in data:
            data["_hwid_bans"] = {}
        ban_record = {"user_id": str(user_id), "banned_at": datetime.now().isoformat()}
        if expires_at:
            ban_record["expires_at"] = expires_at
        data["_hwid_bans"][hwid] = ban_record
    _cache_clear_key(f"hwid:{hwid}")


def unban_hwid(hwid):
    with data_txn() as data:
        if "_hwid_bans" in data and hwid in data["_hwid_bans"]:
            del data["_hwid_bans"][hwid]
    _cache_clear_key(f"hwid:{hwid}")


def is_device_banned(ip=None, fingerprint=None, hwid=None):
    """Checks all three ban lists with at most one read of the store."""
    checks = [(f"ip:{ip}", "_ip_bans", ip, unban_ip),
              (f"fp:{fingerprint}", "_fingerprint_bans", fingerprint, unban_fingerprint),
              (f"hwid:{hwid}", "_hwid_bans", hwid, unban_hwid)]
    checks = [c for c in checks if c[2]]
    pending = []
    for check in checks:
        cached = _cache_get(check[0])
        if cached:
            return True
        if cached is None:
            pending.append(check)
    if not pending:
        return False
    data = load_data()
    banned = False
    for cache_key, section, key, unban in pending:
        record = data.get(section, {}).get(key)
        hit = record is not None
        if hit and "expires_at" in record and datetime.now() > datetime.fromisoformat(record["expires_at"]):
            unban(key)
            hit = False
        _cache_set(cache_key, hit)
        banned = banned or hit
    return banned


if __name__ == "__main__":
    # python3 data_store.py export <file.json>  |  python3 data_store.py import <file.json>
    if len(sys.argv) != 3 or sys.argv[1] not in ("export", "import"):
        raise SystemExit("usage: data_store.py export|import <file.json>")
    command, path = sys.argv[1], sys.argv[2]
    if command == "export":
        with open(path, "w") as f:
            json.dump(export_all(), f, indent=2)
    else:
        with open(path) as f:
            import_all(json.load(f))
    print(f"{command}ed {path} ({db_path()})")
