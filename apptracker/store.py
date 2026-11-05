"""CSV files, the write lock, and dates.

Every ledger is a plain CSV with a header row. Writes go to a temp file that
replaces the original, so a crash never leaves half a file, and anything that
writes takes the lock first so the page, the CLI and a scheduled job take turns.
"""

import csv
import datetime
import os
import sys
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

from .config import settings


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    os.replace(tmp, path)


def ledger_lock(wait=60):
    """Hold the ledger lock until the returned file is closed (use it in a
    `with`) or the process ends."""
    path = settings().lock
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = open(path, "w")
    if fcntl is None:
        return lock
    waited = 0
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock
        except OSError:
            if waited >= wait:
                lock.close()
                sys.exit("another command has held the ledger lock for %ds; try again" % wait)
            time.sleep(1)
            waited += 1


def parse_date(s):
    """A date from 'YYYY-MM-DD...' or None."""
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def local_dt(s):
    """Naive local datetime (in the configured timezone) from an ISO stamp."""
    if not s:
        return None
    t = str(s).strip().replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(t)
    except ValueError:
        try:
            d = datetime.datetime.fromisoformat(t[:19])
        except ValueError:
            return None
    tz = settings().tz
    if d.tzinfo is not None and tz is not None:
        d = d.astimezone(tz)
    return d.replace(tzinfo=None)


def when_words(s, today):
    """'today', 'tomorrow', 'yesterday' or 'Mon 02 Nov', plus HH:MM if s has a time."""
    d = parse_date(s)
    if d is None:
        return "?"
    word = {0: "today", 1: "tomorrow", -1: "yesterday"}.get((d - today).days) or d.strftime("%a %d %b")
    s = str(s)
    hhmm = s[11:16] if len(s) >= 16 and s[10] == "T" else ""
    return "%s %s" % (word, hhmm) if hhmm else word
