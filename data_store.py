"""Shared JSON data store for vouch_bot.py and dashboard.py.

Both processes/threads touch the exact same file - vouch_bot.py's asyncio
event loop and dashboard.py's Flask app run in the same OS process but on
different threads (dashboard runs in a background thread started by
vouch_bot.py). A lock defined separately in each file protects nothing
against the other file's reads/writes, which is how a dashboard admin edit
and a live /host command could silently clobber each other. Both files now
import load_data/save_data/data_txn from here so there is exactly one lock
guarding the file.
"""
import json
import os
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


def load_data():
    with _lock:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        return {}


def save_data(data):
    with _lock:
        os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)


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


def log_ip(user_id, ip):
    with data_txn() as data:
        if "_ip_logs" not in data:
            data["_ip_logs"] = {}
        if ip not in data["_ip_logs"]:
            data["_ip_logs"][ip] = {}
        data["_ip_logs"][ip][str(user_id)] = datetime.now().isoformat()


def get_ips_for_user(user_id):
    data = load_data()
    ip_logs = data.get("_ip_logs", {})
    return [ip for ip, users in ip_logs.items() if str(user_id) in users]


def get_users_for_ip(ip):
    data = load_data()
    ip_logs = data.get("_ip_logs", {})
    return list(ip_logs.get(ip, {}).keys())


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


def log_fingerprint(user_id, fingerprint_json):
    with data_txn() as data:
        if "_fingerprint_logs" not in data:
            data["_fingerprint_logs"] = {}
        if fingerprint_json not in data["_fingerprint_logs"]:
            data["_fingerprint_logs"][fingerprint_json] = {}
        data["_fingerprint_logs"][fingerprint_json][str(user_id)] = datetime.now().isoformat()


def get_fingerprints_for_user(user_id):
    data = load_data()
    fingerprint_logs = data.get("_fingerprint_logs", {})
    return [fp for fp, users in fingerprint_logs.items() if str(user_id) in users]


def get_users_for_fingerprint(fingerprint):
    data = load_data()
    fingerprint_logs = data.get("_fingerprint_logs", {})
    return list(fingerprint_logs.get(fingerprint, {}).keys())


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


def log_hwid(user_id, hwid):
    with data_txn() as data:
        if "_hwid_logs" not in data:
            data["_hwid_logs"] = {}
        if hwid not in data["_hwid_logs"]:
            data["_hwid_logs"][hwid] = {}
        data["_hwid_logs"][hwid][str(user_id)] = datetime.now().isoformat()


def get_hwids_for_user(user_id):
    data = load_data()
    hwid_logs = data.get("_hwid_logs", {})
    return [hwid for hwid, users in hwid_logs.items() if str(user_id) in users]


def get_users_for_hwid(hwid):
    data = load_data()
    hwid_logs = data.get("_hwid_logs", {})
    return list(hwid_logs.get(hwid, {}).keys())
