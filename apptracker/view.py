"""What the page shows: one entry per program, plus the settings it needs."""

import collections
import re

from . import applications as A
from . import checklist, firms, store
from .config import settings

FIELDS = ["id", "firm", "office", "program", "track", "opens", "deadline", "open_status", "rolling",
          "letter_required", "letter", "materials", "apply_where", "applied", "outcome", "screener",
          "callback", "offer", "note", "source", "checked", "confirmed", "checklist"]


def status(r, today):
    """applied, open, upcoming, tbd or closed (or the outcome). tracker.html
    applies the same rules on the phone, where the day moves on between syncs."""
    if (r.get("outcome") or "").lower() in A.OUTCOMES:
        return r["outcome"].lower()
    if r.get("applied"):
        return "applied"
    t = today.isoformat()
    if r.get("deadline") and r["deadline"] < t:
        return "closed"
    if r.get("opens"):
        return "open" if r["opens"] <= t else "upcoming"
    st = (r.get("open_status") or "").lower()
    return st if st in ("open", "closed") else "tbd"


def _row(r, mine, roster, today, cfg):
    f = roster.get(r.get("firm"), {})
    d = {k: r.get(k, "") or "" for k in FIELDS}
    d.update(mine=mine, firm_name=f.get("name") or r.get("firm", ""), priority=f.get("priority", ""),
             target=bool(f.get("target")), track=A.track_of(r), status=status(r, today),
             letter_state=A.letter_state(r.get("letter")) if mine and r.get("letter") else "",
             next=A.app_state(r, today, cfg)[2] if mine else "",
             needs=checklist.needs_str(r), unsure=checklist.materials_unsure(r))
    return d


def rows(today=None):
    """Every row the page shows: your applications, then the other programs."""
    s = settings()
    today = today or s.today()
    roster = {f["key"]: f for f in firms.roster()}
    mine = A.read_apps()
    have = {r["id"] for r in mine}
    out = [_row(r, True, roster, today, s.raw) for r in mine]
    side = A.other_checks()
    folded = {r["id"] for r in store.read(s.others_merged)}   # never shown again, even if re-added by hand
    out += [_row(dict(r, checklist=side.get(r["id"], "")), False, roster, today, s.raw)
            for r in A.read_others() if r["id"] not in have and r["id"] not in folded]
    return out


def page_info(shown=None):
    """The tracks, office filter, timezone and heading the page draws with."""
    s = settings()
    main, first = s.tracks
    offices = [o for o in s.get("offices") or [] if o]
    if not offices and shown is not None:
        count = collections.Counter(o for r in shown for o in re.split(r"[;,/ ]+", r.get("office") or "") if o)
        offices = [o for o, _ in sorted(count.items(), key=lambda t: (-t[1], t[0]))][:8]
    return {"tracks": [{"key": main, "label": "2L · %d" % s.cycle, "short": "2L"},
                       {"key": first, "label": "1L · %d" % (s.cycle - 1), "short": "1L"}],
            "offices": offices, "tz": s.get("timezone"),
            "eyebrow": "%d summer associate · 1L programs for summer %d" % (s.cycle, s.cycle - 1)}
