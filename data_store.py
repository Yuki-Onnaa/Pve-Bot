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
