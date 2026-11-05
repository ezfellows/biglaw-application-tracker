"""The applications ledger: one row per firm, its status, and the tick boxes.

applications.csv holds the programs you are applying to, one row per firm.
A firm's other track (a 1L program, a dual 1L/2L option) goes in that row's
`note`; a separate-application program (a fellowship with its own form) may
have its own row, added with `force`. cycle_others.csv holds programs you know
about but are not tracking yet; ticking one on the page (or `adopt`) moves it
in. Rows folded into their firm's row (`fold`) move to *_merged.csv with
`merged_into`, and anything that later names a folded id lands on the live row
without clearing or overwriting what that row already records.
"""

import datetime
import os
import re

from . import checklist, firms, store
from .checklist import CHECK_KEYS, checklist_done, checklist_str
from .config import settings

APP_COLS = ["id", "firm", "office", "program", "opens", "deadline", "letter_required",
            "letter", "applied", "channel", "referral", "screener", "callback",
            "offer", "offer_deadline", "update_sent", "outcome", "last_news",
            "recruiter", "recruiter_email", "note", "source", "updated",
            # track: 2L-<cycle> or 1L-<cycle-1>; open_status: open, upcoming, closed or
            # unknown when a page states the status but no date; checked: the day the
            # dates were last confirmed against a source
            "track", "open_status", "rolling", "materials", "apply_where", "checked",
            # confirmed: the day the firm's "we received your application" email came
            # (confirm_ref is that message's id); needs: the materials checklist when set
            # by hand, else read from `materials`; checklist: done items, item=date;...
            "confirmed", "confirm_ref", "needs", "checklist"]
OTHER_COLS = ["id", "firm", "office", "track", "program", "opens", "deadline", "open_status",
              "rolling", "letter_required", "materials", "apply_where", "note", "source", "checked"]
MERGED_COLS = ["merged_into", "merged_on"]
OUTCOMES = ("accepted", "declined", "rejected", "withdrawn")
LETTER_REQUIRED = ("y", "n", "optional", "?")

# timing rules, in days
APPLY_WINDOW = 21     # an opening inside three weeks needs its materials ready
APPLY_EARLY = 7       # rolling review: open a week and still unapplied is P1
DEADLINE_URGENT = 7   # a hard deadline inside a week is P1
CALLBACK_CHECKIN = 10 # no word ten days after a callback: check in with recruiting
OFFER_URGENT = 3      # offer deadline inside three days is P1
OFFER_SOON = 10
UNCONFIRMED_AFTER = 2 # applied two days ago and no receipt email: say so

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# fields that mean a row records something about an application
RECORDED = ("applied", "confirmed", "confirm_ref", "screener", "callback", "offer", "offer_deadline",
            "update_sent", "outcome", "last_news", "letter", "referral", "channel", "needs",
            "recruiter", "recruiter_email")
# ...and the ones that mean an application went in
SENT = ("applied", "confirmed", "screener", "callback", "offer", "outcome")


class TrackerError(ValueError):
    """A request the ledger refuses (the message says why and what to do)."""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:48]


def guess_track(program):
    """The 2L track unless the program name says it is a 1L program."""
    main, first = settings().tracks
    p = (program or "").lower()
    return first if re.search(r"\b1l\b", p) and str(settings().cycle) not in p else main


def track_of(r):
    return r.get("track") or guess_track(r.get("program"))


def merged_into(rid):
    """The id a folded row now lives in ('' if rid was never folded). Follows
    chains, so a row folded into a row that was itself folded lands on the live one."""
    s = settings()
    folded = {}
    for path in (s.apps_merged, s.others_merged):
        for r in store.read(path):
            if r.get("id") and r.get("merged_into"):
                folded.setdefault(r["id"], r["merged_into"])
    out, seen = "", set()
    while rid in folded and rid not in seen:
        seen.add(rid)
        out = rid = folded[rid]
    return out


# --- what a row needs next ------------------------------------------------------

def letter_state(path):
    """'draft', 'final', 'sent', or 'missing' for the `letter` column: a folder
    under letters_dir holding letter.md (or a file there) whose front matter
    has a `state:` line. 'submitted' means a letter went in that never lived
    in that folder."""
    if not path:
        return "missing"
    if path == "submitted":
        return "sent"
    base = settings().letters_dir
    if not base:
        return "missing"
    f = os.path.join(base, path)
    if os.path.isdir(f):
        f = os.path.join(f, "letter.md")
    if not os.path.isfile(f):
        return "missing"
    with open(f, encoding="utf-8") as fh:
        head = fh.read(600)
    m = re.search(r"^state:\s*(\w+)", head, re.M)
    return m.group(1) if m else "draft"


def letter_gap(a):
    """What is missing before this application can go in, or ''."""
    need = (a.get("letter_required") or "?").lower()
    if need in ("n", "no"):
        return ""
    st = letter_state(a.get("letter"))
    if st in ("final", "sent"):
        return ""
    have = "no cover letter yet" if st == "missing" else "letter %s" % st
    if need == "optional":
        return "letter optional (%s)" % have
    if need in ("y", "yes"):
        return have
    return "materials unconfirmed; %s" % have


def app_state(a, today, cfg=None):
    """(priority, state, action) for one application. First rule wins."""
    cfg = cfg if cfg is not None else settings().raw
    when = lambda s: store.when_words(s, today)
    outcome = (a.get("outcome") or "").lower()
    if outcome in OUTCOMES:
        return (4, outcome, outcome)
    d = store.parse_date
    opens, deadline, applied = d(a.get("opens")), d(a.get("deadline")), d(a.get("applied"))

    offer = d(a.get("offer"))
    if offer:
        od = d(a.get("offer_deadline"))
        if od is None:
            return (2, "offer", "offer %s - confirm the decision deadline with recruiting" % when(a["offer"]))
        left = (od - today).days
        if left <= OFFER_URGENT:
            return (1, "offer_due", "offer decision due %s" % when(a["offer_deadline"]))
        return (2 if left <= OFFER_SOON else 3, "offer", "offer held; decide by %s" % when(a["offer_deadline"]))

    if applied:
        cb, sc, news = d(a.get("callback")), d(a.get("screener")), d(a.get("last_news"))
        if cb and cb > today:
            return (3, "callback_set", "callback %s - prepare" % when(a["callback"]))
        if sc and sc > today:
            return (3, "screener_set", "screener %s - prepare" % when(a["screener"]))
        grades = d(cfg.get("grades_released"))
        if grades and grades <= today and not a.get("update_sent"):
            return (2, "grades_update", "send your fall grades to recruiting")
        if cb:
            quiet = (today - max(cb, news or cb)).days
            if quiet >= CALLBACK_CHECKIN:
                return (2, "callback_quiet", "callback %d days ago, no word - check in with recruiting" % quiet)
            return (3, "after_callback", "callback %s - waiting" % when(a["callback"]))
        if sc:
            return (3, "after_screener", "screener %s - waiting" % when(a["screener"]))
        if a.get("confirmed"):
            heard = "; firm confirmed receipt %s" % when(a["confirmed"])
        elif (today - applied).days >= UNCONFIRMED_AFTER:
            heard = "; no confirmation email yet - check the portal shows it submitted"
        else:
            heard = ""
        return (4, "applied", "applied %s%s%s" % (when(a["applied"]), heard, " - " + a["note"] if a.get("note") else ""))

    gap = letter_gap(a)
    if deadline and deadline < today:
        return (4, "missed", "deadline passed %s" % when(a["deadline"]))
    if deadline and (deadline - today).days <= DEADLINE_URGENT:
        return (1, "deadline", "apply by %s%s" % (when(a["deadline"]), "; " + gap if gap else ""))
    if opens and opens <= today:
        prio = 1 if (today - opens).days >= APPLY_EARLY else 2
        return (prio, "open", "open since %s, rolling - apply%s" % (when(a["opens"]), "; " + gap if gap else ""))
    if opens:
        ahead = (opens - today).days
        if ahead <= APPLY_WINDOW:
            if gap:
                return (2, "prepare", "opens %s; %s" % (when(a["opens"]), gap))
            return (3, "ready", "opens %s; materials ready" % when(a["opens"]))
        return (3 if ahead <= 30 else 4, "upcoming", "opens %s%s" % (when(a["opens"]), "; " + gap if gap else ""))
    status = (a.get("open_status") or "").lower()
    if status == "open":   # the firm's page says it is open but gives no opening date
        return (2, "open", "open now - apply%s" % ("; " + gap if gap else ""))
    if status == "closed":
        return (4, "closed", "closed for this cycle")
    return (4, "no_dates", "dates unknown - check the careers page")


# --- the files ------------------------------------------------------------------

def read_apps():
    return store.read(settings().apps)


def read_others():
    return store.read(settings().others)


def save(apps):
    store.write(settings().apps, APP_COLS, sorted(apps, key=lambda r: r["id"]))


def other_checks():
    return {r["id"]: r["checklist"] for r in store.read(settings().other_checks) if r.get("checklist")}


def save_other_checks(side):
    store.write(settings().other_checks, ["id", "checklist"],
                [{"id": k, "checklist": v} for k, v in sorted(side.items()) if v])


def folded_to(apps, rid):
    """The live id rid was folded into, or '' when rid is itself live (or unknown)."""
    if any(r["id"] == rid for r in apps) or any(r["id"] == rid for r in read_others()):
        return ""
    return merged_into(rid)


def find_or_adopt(apps, rid, adopt):
    """The applications.csv row for rid. A cycle_others row becomes one when
    `adopt` (an application was recorded for it); otherwise None for those.
    Checklist ticks made on it before then come along."""
    hit = next((r for r in apps if r["id"] == rid), None)
    if hit is not None:
        return hit
    other = next((r for r in read_others() if r["id"] == rid), None)
    if other is None:
        live = merged_into(rid)   # folded into its firm's row (one application per firm)
        if live and live != rid:
            return find_or_adopt(apps, live, adopt)
        raise KeyError(rid)
    if not adopt:
        return None
    hit = {c: "" for c in APP_COLS}
    hit.update({k: v for k, v in other.items() if k in APP_COLS})
    side = other_checks()
    if side.get(rid):
        hit["checklist"] = side.pop(rid)
        save_other_checks(side)
    apps.append(hit)
    return hit


def drop_if_empty(apps, hit):
    """An adopted cycle_others row that no longer records anything goes back
    to being just another program (an untick, or a receipt undone), and its
    checklist ticks go back to the side file. A row you added or edited
    yourself (`app add`, a changed program or note) is never dropped."""
    if any((hit.get(c) or "").strip() and not (c == "confirm_ref" and hit[c].startswith("~")) for c in RECORDED):
        return False
    other = next((r for r in read_others() if r["id"] == hit["id"]), None)
    if other is None:
        return False
    if any((hit.get(k) or "") != (other.get(k) or "") for k in other if k in APP_COLS and k != "checklist"):
        return False
    if hit.get("checklist"):
        side = other_checks()
        side[hit["id"]] = hit["checklist"]
        save_other_checks(side)
    apps.remove(hit)
    return True


# --- tick boxes -------------------------------------------------------------------

def check_date(date, today, what):
    date = (date or "").strip()
    if date and (not DATE.match(date) or store.parse_date(date) is None):
        raise ValueError("%s must be YYYY-MM-DD or empty, not %r" % (what, date))
    if date and store.parse_date(date) > today + datetime.timedelta(days=1):
        raise ValueError("%s date %s is in the future" % (what, date))
    return date


def set_applied(rid, date, today=None):
    """Tick (date) or untick ('') one row. A cycle_others row becomes an
    application the first time it is ticked, and stops being one if it is
    unticked with nothing else recorded. Unticking also sets aside the receipt
    matched to it: that receipt was for something else."""
    today = today or settings().today()
    date = check_date(date, today, "applied")
    with store.ledger_lock():
        apps = read_apps()
        live = folded_to(apps, rid)
        if live:
            # a tick on a row since folded into its firm's row (a stale phone or page):
            # never clear or overwrite what the live row already records
            if not date:
                return "skipped: %s was folded into %s; untick on that row" % (rid, live)
            row = next((r for r in apps if r["id"] == live), None)
            if row is not None and row.get("applied"):
                return "unchanged (%s already applied %s)" % (live, row["applied"])
        hit = find_or_adopt(apps, rid, bool(date))
        if hit is None or hit.get("applied", "") == date:
            return "unchanged"
        hit["applied"] = date
        stash = hit.get("confirm_ref") or ""
        if not date:
            # set the receipt aside: an Undo the same day puts it back; a later
            # re-tick is a new application and waits for its own receipt
            hit["confirm_ref"] = "~%s@%s|%s" % (stash, today.isoformat(), hit.get("confirmed") or "") \
                if hit.get("confirmed") and not stash.startswith("~") else ""
            hit["confirmed"] = ""
        elif stash.startswith("~"):
            ref, _, rest = stash[1:].partition("@")
            day, _, conf = rest.partition("|")
            hit["confirm_ref"], hit["confirmed"] = (ref, conf) if day == today.isoformat() else ("", "")
        hit["updated"] = today.isoformat()
        if not date:
            drop_if_empty(apps, hit)
        save(apps)
    return "applied %s" % date if date else "cleared"


def set_check(rid, item, date, today=None):
    """Tick (date) or untick ('') one checklist item on one row. Ticks on a
    program you aren't tracking (a cycle_others row) are kept in a side file,
    so gathering a resume for one doesn't make it an application."""
    today = today or settings().today()
    if item not in CHECK_KEYS:
        raise ValueError("unknown checklist item %r" % item)
    date = check_date(date, today, item)
    with store.ledger_lock():
        apps = read_apps()
        live = folded_to(apps, rid)
        if live:
            if not date:   # a stale untick must not clear the live row's tick
                return "skipped: %s was folded into %s; untick on that row" % (rid, live)
            rid = live
        hit = find_or_adopt(apps, rid, False)
        side = None
        if hit is None:
            side = other_checks()
            done = checklist_done({"checklist": side.get(rid, "")})
        else:
            done = checklist_done(hit)
        if live and done.get(item):
            return "unchanged (%s already has %s %s)" % (live, item, done[item])
        if done.get(item, "") == date:
            return "unchanged"
        if date:
            done[item] = date
        else:
            done.pop(item, None)
        if hit is None:
            side[rid] = checklist_str(done)
            save_other_checks(side)
        else:
            hit["checklist"] = checklist_str(done)
            hit["updated"] = today.isoformat()
            save(apps)
    return "%s %s" % (item, date) if date else "%s cleared" % item


# --- adding, adopting, folding ------------------------------------------------------

def find_app(q, rows):
    """The row whose id is q, else the one row whose id starts with q. A folded
    id is refused before prefixes, so it never lands on another row."""
    hits = [r for r in rows if r["id"] == q]
    if not hits and merged_into(q):
        raise TrackerError("%s was folded into %s (one application per firm); use: app set %s ..."
                           % (q, merged_into(q), merged_into(q)))
    hits = hits or [r for r in rows if r["id"].startswith(q)]
    if len(hits) != 1:
        raise TrackerError("%d applications match %r%s" % (len(hits), q, ": " + ", ".join(h["id"] for h in hits) if hits else ""))
    return hits[0]


def add(firm, office="", program="", rid="", letter_required="?", source="", track="", force=False, today=None):
    """Add an application row. One per firm: a second row for a firm that has
    one (or that is tracked in cycle_others) is refused unless `force`, for a
    program with its own application form. Returns the new id."""
    today = today or settings().today()
    if letter_required and letter_required not in LETTER_REQUIRED:
        raise TrackerError("letter_required must be one of %s" % ", ".join(LETTER_REQUIRED))
    if track and track not in settings().tracks:
        raise TrackerError("track must be one of %s" % ", ".join(settings().tracks))
    with store.ledger_lock():
        rows = read_apps()
        key = firms.firm_in_text(firm) or slug(firm)
        if not key:
            raise TrackerError("no firm named")
        rid = rid or "%s%s" % (key, "-" + slug(office) if office else "")
        if any(r["id"] == rid for r in rows):
            raise TrackerError("already logged: %s (use app set)" % rid)
        if merged_into(rid):
            raise TrackerError("%s was folded into %s (one application per firm); use: app set %s ..."
                               % (rid, merged_into(rid), merged_into(rid)))
        same = [r["id"] for r in rows if r["firm"] == key]
        if same and not force:
            raise TrackerError("%s already has a row: %s. One application per firm: put another program or "
                               "office in that row's note, or pass --force for a separate application "
                               "(a fellowship with its own form)" % (key, ", ".join(same)))
        swept = [r["id"] for r in read_others() if r.get("firm") == key]
        if swept and not force:
            raise TrackerError("%s is already tracked in cycle_others.csv: %s. Bring that row in with: app adopt <id> "
                               "(it keeps its dates and materials), or pass --force" % (key, ", ".join(swept)))
        row = {c: "" for c in APP_COLS}
        row.update({"id": rid, "firm": key, "office": office or "", "program": program or "",
                    "letter_required": letter_required or "?", "source": source or "",
                    "track": track or guess_track(program), "updated": today.isoformat()})
        rows.append(row)
        save(rows)
    return rid


def adopt(rid, today=None):
    """Make a cycle_others row one of your applications: the same row, with its
    dates and materials (and any checklist ticks), as a tick on the page does."""
    today = today or settings().today()
    with store.ledger_lock():
        rows = read_apps()
        if any(r["id"] == rid for r in rows):
            raise TrackerError("already logged: %s (use app set)" % rid)
        if merged_into(rid):
            raise TrackerError("%s was folded into %s; adopt %s instead" % (rid, merged_into(rid), merged_into(rid)))
        try:
            hit = find_or_adopt(rows, rid, True)
        except KeyError:
            raise TrackerError("no cycle_others row %r" % rid)
        hit["updated"] = today.isoformat()
        save(rows)
    return rid


def set_fields(query, pairs, today=None):
    """Set key=value fields on one row ('today' means today's date). Returns the row."""
    today = today or settings().today()
    with store.ledger_lock():
        rows = read_apps()
        r = find_app(query, rows)
        for kv in pairs:
            k, eq, v = kv.partition("=")
            if not eq or k not in APP_COLS or k == "id":
                raise TrackerError("unknown field %r (fields: %s)" % (k, ", ".join(APP_COLS[1:])))
            if v in ("today", "now"):
                v = today.isoformat()
            r[k] = v
        r["updated"] = today.isoformat()
        save(rows)
    return r


def fold(rid, into, today=None):
    """Fold one row into its firm's live row: the folded row moves to the
    *_merged.csv file next to it with merged_into, the live row's note gains
    its track and program, and its checklist ticks fill gaps on the live row.
    A row that records a sent application is refused: that is its own
    application, so keep it or clear it first."""
    today = today or settings().today()
    s = settings()
    with store.ledger_lock():
        apps, others = read_apps(), read_others()
        live = next((r for r in apps if r["id"] == into), None)
        if live is None:
            raise TrackerError("no application %r to fold into (fold into a row in applications.csv)" % into)
        if rid == into:
            raise TrackerError("a row can't be folded into itself")
        row = next((r for r in apps if r["id"] == rid), None)
        src, cols, merged = (s.apps, APP_COLS, s.apps_merged) if row is not None else (s.others, OTHER_COLS, s.others_merged)
        row = row if row is not None else next((r for r in others if r["id"] == rid), None)
        if row is None:
            raise TrackerError("no row %r in applications.csv or cycle_others.csv" % rid)
        if row.get("firm") != live.get("firm"):
            raise TrackerError("%s is %s and %s is %s: fold only rows for the same firm"
                               % (rid, row.get("firm"), into, live.get("firm")))
        sent = [c for c in SENT if (row.get(c) or "").strip()]
        if sent:
            raise TrackerError("%s records an application (%s); keep it as its own row or clear those first"
                               % (rid, ", ".join(sent)))
        bits = [track_of(row)] + [x for x in (row.get("program"), row.get("office")) if x]
        also = "also %s (folded from %s)" % (" ".join(bits), rid)
        live["note"] = "; ".join(x for x in (live.get("note"), also) if x)
        ticks = checklist_done(row)
        side = other_checks()
        if src == s.others and side.get(rid):
            ticks.update({k: v for k, v in checklist_done({"checklist": side.pop(rid)}).items() if k not in ticks})
            save_other_checks(side)
        done = checklist_done(live)
        for k, v in ticks.items():
            done.setdefault(k, v)
        live["checklist"] = checklist_str(done)
        live["updated"] = today.isoformat()
        archive = store.read(merged)
        archive = [r for r in archive if r.get("id") != rid]
        archive.append(dict(row, merged_into=into, merged_on=today.isoformat()))
        store.write(merged, cols + MERGED_COLS, archive)
        if src == s.apps:
            apps = [r for r in apps if r["id"] != rid]
        else:
            store.write(s.others, OTHER_COLS, [r for r in others if r["id"] != rid])
        save(apps)
    return "%s folded into %s" % (rid, into)
