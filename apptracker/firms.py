"""The firm list: keys, display names, aliases, and email domains.

firms.csv (its path is the `firms` setting) has one row per firm:

  key       short id used in the ledgers (latham, davis-polk, ...)
  name      display name
  aliases   other names it goes by, separated by ';' (matched in email text)
  target    y if it is on your list (the page's "My firms" view shows it)
  priority  1 (highest) and up; sorts the page
  offices   offices you care about, separated by ';'

Extra columns are ignored, so an existing roster with more columns works as is.
firm_domains.csv (the `domains` setting) maps sender domains to keys for the
optional receipt reader: `domain,firm`.
"""

import os
import re

from . import store
from .config import settings

FIRM_COLS = ["key", "name", "aliases", "target", "priority", "offices"]
_cache = {}


def forget():
    _cache.clear()


def _stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (path, st.st_mtime_ns, st.st_size)


def roster():
    """[{key, name, names, target, priority, offices}] from the firm list."""
    path = settings().firms
    stamp = _stamp(path)
    if stamp is None:
        return []
    if _cache.get("stamp") != stamp:
        out = []
        for r in store.read(path):
            if not (r.get("key") or "").strip():
                continue
            name = (r.get("name") or r["key"]).strip()
            names = [name] + [a.strip() for a in (r.get("aliases") or "").split(";") if a.strip()]
            out.append({"key": r["key"].strip(), "name": name, "names": names,
                        "target": (r.get("target") or "").strip().lower() in ("y", "yes", "true", "1"),
                        "priority": (r.get("priority") or "").strip(), "offices": r.get("offices") or ""})
        _cache.clear()
        _cache.update(stamp=stamp, rows=out, rx=None)
    return _cache["rows"]


def _patterns():
    roster()
    if _cache.get("rx") is None:
        pats = []
        for f in _cache.get("rows", []):
            for n in f["names"]:
                if len(n) < 3:
                    continue
                pats.append((len(n), re.compile(r"(?<![\w&])%s(?![\w&])" % re.escape(n), re.I), f["key"]))
        pats.sort(key=lambda t: -t[0])   # "Morrow Hale" before "Morrow"
        _cache["rx"] = pats
    return _cache["rx"]


def firm_in_text(text):
    """Key of the first firm named in text, longest name first ('' if none)."""
    for _, rx, key in _patterns():
        if rx.search(text or ""):
            return key
    return ""


def firm_name(key):
    for f in roster():
        if f["key"] == key:
            return f["name"]
    return key


def domain_map():
    return {r["domain"].strip().lower(): r["firm"].strip() for r in store.read(settings().domains)
            if (r.get("domain") or "").strip()}


def firm_of_email(email, domains=None):
    """Firm key for a sender address, by its domain or any parent domain."""
    domains = domains if domains is not None else domain_map()
    d = (email or "").lower().rpartition("@")[2]
    while d:
        if d in domains:
            return domains[d]
        d = d.partition(".")[2]
    return ""
