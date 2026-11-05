"""BigLaw summer associate application tracker.

  python3 tracker.py init [--sample]       make the data folder (--sample: invented example data)
  python3 tracker.py serve [--port 8765]   then open http://localhost:8765
  python3 tracker.py app list [--due]      every application and what it needs next
  python3 tracker.py app add FIRM [...]    a new application row (one per firm)
  python3 tracker.py app adopt ID          bring a cycle_others.csv program in as an application
  python3 tracker.py app set ID k=v ...    change fields on one row
  python3 tracker.py app fold ID --into ID fold a firm's second row into its first
  python3 tracker.py export [--as-of T]    rows for the phone copy, as JSON
  python3 tracker.py import-checks FILE    fold ticks made on the phone into the ledger
  python3 tracker.py confirm query|new|ingest|list|resolve   application receipts from email

Every command takes --data DIR (default: data/ next to tracker.py, or
$APPTRACKER_DATA). Stdlib only.
"""

import argparse
import datetime
import json
import os
import shutil
import sys

from . import applications as A
from . import phone, receipts, server, store
from .config import SAMPLE, settings, use

EMPTY = {"applications.csv": A.APP_COLS, "cycle_others.csv": A.OTHER_COLS,
         "firms.csv": ["key", "name", "aliases", "target", "priority", "offices"],
         "firm_domains.csv": ["domain", "firm"]}


def cmd_init(a):
    s = settings()
    made = []
    if a.sample:
        if os.path.exists(s.apps):
            sys.exit("%s already holds applications.csv; pick an empty folder for the sample (--data DIR)" % s.data)
        for root, _, names in os.walk(SAMPLE):
            for n in names:
                src = os.path.join(root, n)
                dst = os.path.join(s.data, os.path.relpath(src, SAMPLE))
                if not os.path.exists(dst):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copyfile(src, dst)
                    made.append(os.path.relpath(dst, s.data))
    else:
        for name, cols in EMPTY.items():
            path = os.path.join(s.data, name)
            if not os.path.exists(path):
                store.write(path, cols, [])
                made.append(name)
        if not os.path.exists(os.path.join(s.data, "config.json")):
            s.save(cycle=s.cycle, timezone=s.get("timezone"))
            made.append("config.json")
    print("%s: %s" % (s.data, ", ".join(sorted(made)) if made else "nothing to add (all files exist)"))


def cmd_app(a):
    today = settings().today()
    if a.sub == "list":
        cfg = settings().raw
        items = sorted(((A.app_state(r, today, cfg), r) for r in A.read_apps()),
                       key=lambda t: (t[0][0], t[1].get("opens") or "9999"))
        for (p, st, act), r in items:
            if a.due and p > 2:
                continue
            print("P%d %-15s %-24s %s" % (p, st, r["id"][:24], act))
        if not items:
            print("no applications yet (app add FIRM, or tick one on the page)")
    elif a.sub == "add":
        print("added %s" % A.add(a.firm, a.office or "", a.program or "", a.id or "", a.letter_required or "?",
                                 a.source or "", a.track or "", a.force, today))
    elif a.sub == "adopt":
        print("adopted %s from cycle_others.csv" % A.adopt(a.id, today))
    elif a.sub == "set":
        r = A.set_fields(a.query, a.pairs, today)
        print("%s: %s" % (r["id"], ", ".join("%s=%s" % (k, r.get(k)) for k in A.APP_COLS[1:] if r.get(k))))
    elif a.sub == "fold":
        print(A.fold(a.id, a.into, today))


def cmd_export(a):
    if a.as_of and phone.ts(a.as_of) is None:
        sys.exit("--as-of must be an ISO time such as 2026-11-03T12:30:00Z")
    json.dump(phone.export(as_of=a.as_of), sys.stdout, indent=1)
    print()


def cmd_import(a):
    for flag, v in (("--since", a.since), ("--until", a.until)):
        if v and phone.ts(v) is None:
            sys.exit("%s must be an ISO time such as 2026-11-03T12:30:00.000Z, not %r" % (flag, v))
    res = phone.import_checks(phone.load_checks(a.file), since=a.since, until=a.until)
    for rid, r in res:
        print("%s: %s" % (rid, r))
    print("%d phone tick(s) newer than %s" % (len(res), a.since or "the start"))


def _load_messages(path):
    with open(path, encoding="utf-8") as fh:
        items = json.load(fh)
    if isinstance(items, dict):
        items = items.get("messages") or items.get("items") or []
    return items


def cmd_confirm(a):
    if a.sub == "query":
        since = datetime.date.fromisoformat(a.since) if a.since else receipts.confirm_since()
        print("# window starts %s" % since.isoformat())
        for line in receipts.confirm_queries(since):
            print(line)
    elif a.sub == "new":
        seen = {r["message_id"] for r in store.read(settings().confirms)}
        for mid in a.ids:
            if mid not in seen:
                print(mid)
    elif a.sub == "ingest":
        res = receipts.ingest(_load_messages(a.file))
        for mid, kind, result in res:
            print("%s  %-17s %s" % (mid, kind, result))
        print("%d new message(s) read" % len(res))
    elif a.sub == "list":
        rows = receipts.needs_eye() if a.review else store.read(settings().confirms)
        for r in rows:
            print("%s  %s  %-17s %-14s %s | %s" % (r["date"], r["message_id"], r["kind"], r["app_id"] or r["firm"] or "-",
                                                  r["result"], r["subject"][:60]))
        if a.review and not rows:
            print("nothing needs a look")
    else:
        try:
            print(receipts.resolve(a.message_id, a.target))
        except KeyError as e:
            sys.exit("no logged message %s (see confirm list)" % e)
        except ValueError as e:
            sys.exit("%s (use an id from applications.csv or cycle_others.csv, or 'ignore')" % e)


def parser():
    ap = argparse.ArgumentParser(prog="tracker.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="the data folder (default: data/ next to tracker.py, or $APPTRACKER_DATA)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="make the data folder")
    p.add_argument("--sample", action="store_true", help="copy the invented sample data in")
    p = sub.add_parser("serve", help="serve the page on localhost")
    p.add_argument("--port", type=int)
    p = sub.add_parser("app", help="applications: list, add, adopt, set, fold")
    asub = p.add_subparsers(dest="sub", required=True)
    q = asub.add_parser("list")
    q.add_argument("--due", action="store_true", help="only P1 and P2")
    q = asub.add_parser("add", help="app add FIRM: a firm key or a name from firms.csv")
    q.add_argument("firm")
    q.add_argument("--office")
    q.add_argument("--program")
    q.add_argument("--id")
    q.add_argument("--letter-required", dest="letter_required", choices=A.LETTER_REQUIRED)
    q.add_argument("--source")
    q.add_argument("--track")
    q.add_argument("--force", action="store_true", help="allow a second row for a firm (a separate application)")
    q = asub.add_parser("adopt", help="app adopt ID: make a cycle_others.csv program an application")
    q.add_argument("id")
    q = asub.add_parser("set", help="app set ID key=value ...")
    q.add_argument("query")
    q.add_argument("pairs", nargs="+")
    q = asub.add_parser("fold", help="app fold ID --into LIVE_ID: one application per firm")
    q.add_argument("id")
    q.add_argument("--into", required=True)
    p = sub.add_parser("export", help="the phone copy's meta/rows document")
    p.add_argument("--as-of", help="when the phone's checks were listed (ISO, UTC); becomes synced_at")
    p = sub.add_parser("import-checks", help="fold phone ticks into the ledger")
    p.add_argument("file", help="a JSON file, or the directory a store listing saved checks into")
    p.add_argument("--since", default="", help="synced_at of the last sync; older ticks are skipped")
    p.add_argument("--until", default="", help="when the checks were listed (the export's --as-of); later ticks wait")
    p = sub.add_parser("confirm", help="application receipts from email")
    csub = p.add_subparsers(dest="sub", required=True)
    q = csub.add_parser("query", help="print the Gmail searches")
    q.add_argument("--since", help="YYYY-MM-DD; default two days before the last ingest")
    q = csub.add_parser("new", help="print the ids not read yet")
    q.add_argument("ids", nargs="*")
    q = csub.add_parser("ingest", help="read saved messages: [{message_id, date, from, from_name, subject, body}]")
    q.add_argument("file")
    q = csub.add_parser("list", help="what came in; --review for what needs a look")
    q.add_argument("--review", action="store_true")
    q = csub.add_parser("resolve", help="resolve MESSAGE_ID APP_ID|ignore")
    q.add_argument("message_id")
    q.add_argument("target")
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    if a.data:
        use(a.data)
    try:
        if a.cmd == "init":
            cmd_init(a)
        elif a.cmd == "serve":
            server.serve(a.port)
        elif a.cmd == "app":
            cmd_app(a)
        elif a.cmd == "export":
            cmd_export(a)
        elif a.cmd == "import-checks":
            cmd_import(a)
        else:
            cmd_confirm(a)
    except A.TrackerError as e:
        sys.exit(str(e))
