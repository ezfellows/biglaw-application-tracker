"""Where the tracker keeps its files, and the few settings it reads.

Everything lives in one data directory: `data/` next to this package unless
`--data DIR` or the APPTRACKER_DATA environment variable says otherwise. An
optional `config.json` in that directory may set:

  firms            CSV of firm names: key,name,aliases,target,priority,offices
                   (default firms.csv)
  domains          CSV of email domains to firm keys, for receipts
                   (default firm_domains.csv)
  letters_dir      folder of cover letters; the `letter` column names a
                   subfolder holding letter.md with a `state:` line (optional)
  cycle            the summer the 2L programs hire for (default 2028); tracks
                   are then 2L-2028 and 1L-2027
  timezone         IANA zone that decides what "today" is (default America/New_York)
  offices          office codes for the page's filter (default: those in the data)
  grades_released  YYYY-MM-DD once first-semester grades are out
  receipts_since   YYYY-MM-DD where the first receipt search starts
  receipt_skip_senders  sender domains the receipt searches leave out
  lock             lock file shared by everything that writes these CSVs
                   (default .tracker.lock)
  port             port for `serve` (default 8765)

Relative paths are read from the data directory; `~` is expanded.
"""

import datetime
import json
import os

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8
    ZoneInfo = None

PACKAGE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(PACKAGE)
SAMPLE = os.path.join(ROOT, "sample")

FILES = {
    "apps": "applications.csv",              # one row per application (one per firm)
    "others": "cycle_others.csv",            # programs you know about but are not applying to yet
    "other_checks": "cycle_checks.csv",      # checklist ticks on those programs
    "confirms": "confirmations.csv",         # one row per receipt email read
    "apps_merged": "applications_merged.csv",  # rows folded into their firm's row
    "others_merged": "cycle_others_merged.csv",
    "config": "config.json",
}

DEFAULTS = {
    "firms": "firms.csv",
    "domains": "firm_domains.csv",
    "letters_dir": "",
    "cycle": 2028,
    "timezone": "America/New_York",
    "offices": [],
    "grades_released": "",
    "receipts_since": "",
    "receipt_skip_senders": [],
    "lock": ".tracker.lock",
    "port": 8765,
}


class Settings(object):
    def __init__(self, data=None):
        data = data or os.environ.get("APPTRACKER_DATA") or os.path.join(ROOT, "data")
        self.data = os.path.abspath(os.path.expanduser(data))
        self.raw = dict(DEFAULTS)
        cfg = os.path.join(self.data, FILES["config"])
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8") as fh:
                got = json.load(fh)
            if not isinstance(got, dict):
                raise ValueError("%s must hold a JSON object" % cfg)
            self.raw.update(got)
        for key, name in FILES.items():
            setattr(self, key, os.path.join(self.data, name))

    def get(self, key, default=None):
        v = self.raw.get(key)
        return DEFAULTS.get(key, default) if v is None else v

    def path(self, key):
        v = self.get(key)
        return os.path.abspath(os.path.join(self.data, os.path.expanduser(v))) if v else ""

    @property
    def firms(self):
        return self.path("firms")

    @property
    def domains(self):
        return self.path("domains")

    @property
    def letters_dir(self):
        return self.path("letters_dir")

    @property
    def lock(self):
        return self.path("lock")

    @property
    def cycle(self):
        return int(self.get("cycle"))

    @property
    def tracks(self):
        """(main, first_year): the 2L program for `cycle`, the 1L one the summer before."""
        return ("2L-%d" % self.cycle, "1L-%d" % (self.cycle - 1))

    @property
    def tz(self):
        if ZoneInfo is None:
            return None
        try:
            return ZoneInfo(self.get("timezone"))
        except Exception:
            return None

    def today(self):
        v = os.environ.get("APPTRACKER_TODAY")
        if v:
            return datetime.date.fromisoformat(v)
        tz = self.tz
        return datetime.datetime.now(tz).date() if tz else datetime.date.today()

    def save(self, **changes):
        """Write changed settings back to config.json (keeps keys it doesn't know)."""
        path = os.path.join(self.data, FILES["config"])
        cur = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                cur = json.load(fh)
        cur.update(changes)
        os.makedirs(self.data, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, indent=2)
            fh.write("\n")
        self.raw.update(changes)


_current = None


def settings():
    """The settings every module reads. Loaded on first use."""
    global _current
    if _current is None:
        _current = Settings()
    return _current


def use(data=None):
    """Point the tracker at a data directory (and re-read its config.json)."""
    global _current
    _current = Settings(data)
    from . import firms   # the firm list is cached per file; a new directory may name another
    firms.forget()
    return _current
