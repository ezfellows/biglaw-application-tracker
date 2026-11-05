"""The phone copy: the same page published as a private claude.ai artifact.

The artifact's store holds one document, meta/rows (export's output), plus one
checks/<id> document per tick made on the phone (checks/<id>__<item> for a
checklist item). A sync, run on the computer that holds the ledger:

  1. list and save the checks documents, noting when they were listed (T);
  2. import-checks the saved checks with --since the last synced_at and
     --until T (older ticks were folded in already, or overruled since);
  3. export --as-of T and write the output over meta/rows.

The page applies only ticks newer than that sync. Nothing here talks to the
network; whatever runs the sync moves the JSON.
"""

import datetime
import json
import os
import re

from . import applications as A
from . import view
from .config import settings


def ts(s):
    """Aware UTC datetime from an ISO stamp ('...Z', with or without
    milliseconds), or None. Stamps are compared as times, not strings:
    '12:40:05.300Z' sorts before '12:40:05Z' as text."""
    if not s:
        return None
    t = str(s).strip().replace("Z", "+00:00")
    t = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], t, count=1)   # 3.9 wants 3 or 6 digits
    try:
        d = datetime.datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def export(today=None, as_of=None):
    """The meta/rows document. Empty fields are dropped to keep it well under
    the store's 256 KiB document limit. `synced_at` must be the moment the
    phone's checks were listed (as_of), not now: a tick made between the
    listing and this write would otherwise read as already synced."""
    today = today or settings().today()
    when = ts(as_of) or datetime.datetime.now(datetime.timezone.utc)
    shown = view.rows(today)
    slim = [{k: v for k, v in r.items() if v not in ("", None, False)} for r in shown]
    out = {"synced_at": when.astimezone(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
           "today": today.isoformat(), "rows": slim}
    out.update(view.page_info(shown))
    return out


def load_checks(path):
    """Phone ticks from a JSON file (a list, or the store's listing) or from a
    directory of per-document JSON files, as a store listing saves them."""
    if os.path.isdir(path):
        items = []
        for root, _, names in os.walk(path):
            for n in sorted(names):
                if n.endswith(".json"):
                    with open(os.path.join(root, n), encoding="utf-8") as fh:
                        body = json.load(fh)
                    body.setdefault("id", n[:-5])
                    items.append(body)
        return items
    with open(path, encoding="utf-8") as fh:
        items = json.load(fh)
    if isinstance(items, dict):
        items = items.get("docs") or items.get("documents") or items.get("items") or []
    return items


def import_checks(items, today=None, since="", until=""):
    """Apply phone ticks: {id, applied, at} for the applied box, {id, item,
    done, at} for a checklist item. Ticks at or before `since` (the last sync)
    are skipped. Ticks after `until` (the moment the checks were listed, which
    becomes the next synced_at) wait for the next sync. Returns [(id, result)],
    oldest first."""
    cut, stop = ts(since), ts(until)
    found = []
    for it in items:
        body = it.get("data") if isinstance(it.get("data"), dict) else it
        rid = (body.get("id") or it.get("id") or it.get("doc_id") or "").rsplit("/", 1)[-1]
        item = body.get("item") or ""
        if item and rid.endswith("__" + item):   # a document id, not the row id
            rid = rid[:-len(item) - 2]
        at = ts(body.get("at"))
        if rid and (cut is None or (at is not None and at > cut)) and (stop is None or (at is not None and at <= stop)):
            found.append((at or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), rid, item,
                          body.get("done" if item else "applied", "")))
    out = []
    for _, rid, item, date in sorted(found, key=lambda t: t[:3]):
        label = rid + ("/" + item if item else "")
        live = A.folded_to(A.read_apps(), rid)
        if live:
            label += " -> " + live   # ticked on a row since folded into its firm's row
        try:
            out.append((label, A.set_check(rid, item, date, today) if item else A.set_applied(rid, date, today)))
        except (KeyError, ValueError) as e:
            out.append((rid + ("/" + item if item else ""), "skipped: %s" % e))
    return out
