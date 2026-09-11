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
from contextlib import contextmanager

DATA_FILE = os.environ.get("DATA_FILE", "/data/vouches.json")

# Reentrant so a thread already holding it (e.g. inside a data_txn) can safely
# call load_data()/save_data() again without deadlocking itself.
_lock = threading.RLock()


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
    data = load_data()
    banned_ips = data.get("_ip_bans", {})
    return ip in banned_ips


def ban_ip(ip, user_id):
    with data_txn() as data:
        if "_ip_bans" not in data:
            data["_ip_bans"] = {}
        data["_ip_bans"][ip] = {"user_id": str(user_id), "banned_at": datetime.now().isoformat()}


def unban_ip(ip):
    with data_txn() as data:
        if "_ip_bans" in data and ip in data["_ip_bans"]:
            del data["_ip_bans"][ip]


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
    data = load_data()
    banned_fingerprints = data.get("_fingerprint_bans", {})
    return fingerprint in banned_fingerprints


def ban_fingerprint(fingerprint, user_id):
    with data_txn() as data:
        if "_fingerprint_bans" not in data:
            data["_fingerprint_bans"] = {}
        data["_fingerprint_bans"][fingerprint] = {"user_id": str(user_id), "banned_at": datetime.now().isoformat()}


def unban_fingerprint(fingerprint):
    with data_txn() as data:
        if "_fingerprint_bans" in data and fingerprint in data["_fingerprint_bans"]:
            del data["_fingerprint_bans"][fingerprint]


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


from datetime import datetime
