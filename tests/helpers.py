"""A throwaway data folder per test. Every firm, person and address here is invented."""

import csv
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apptracker import applications as A  # noqa: E402
from apptracker import config, store  # noqa: E402

TODAY = datetime.date(2026, 10, 17)

FIRMS = [
    # key, name, aliases, target, priority, offices
    ("hartwell", "Hartwell & Pike LLP", "Hartwell & Pike;Hartwell", "y", "2", "DC;NY"),
    ("brandt", "Brandt Mercer LLP", "Brandt Mercer", "y", "2", "NY"),
    ("quillon", "Quillon Day LLP", "Quillon Day;Quillon", "y", "1", "DC"),
    ("morrow", "Morrow LLP", "Morrow", "y", "1", "NY"),
    ("morrow-hale", "Morrow Hale LLP", "Morrow Hale", "y", "2", "NY"),
    ("vance", "Vance Okafor LLP", "Vance Okafor", "n", "", "DC"),
]
DOMAINS = [("hartwellpike.example", "hartwell"), ("brandtmercer.example", "brandt"),
           ("quillonday.example", "quillon"), ("vanceokafor.example", "vance")]


def make_data(path, cfg=None):
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "firms.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "name", "aliases", "target", "priority", "offices", "notes"])   # extra column: ignored
        for f in FIRMS:
            w.writerow(list(f) + [""])
    with open(os.path.join(path, "firm_domains.csv"), "w", newline="") as fh:
        fh.write("domain,firm\n" + "".join("%s,%s\n" % d for d in DOMAINS))
    for name, state in (("hartwell/dc-lit", "final"), ("quillon/dc-lit", "draft")):
        os.makedirs(os.path.join(path, "letters", name), exist_ok=True)
        with open(os.path.join(path, "letters", name, "letter.md"), "w") as fh:
            fh.write("---\nfirm: x\nstate: %s\n---\nDear Recruiting Committee,\n" % state)
    with open(os.path.join(path, "config.json"), "w") as fh:
        json.dump(dict({"letters_dir": "letters", "cycle": 2028}, **(cfg or {})), fh)


def msg(mid, frm, subject, body, date="2026-10-16T15:00:00Z", name="", **label):
    """A saved message; `kind` (and `program`) are what a reader adds after reading it."""
    return dict({"message_id": mid, "from": frm, "from_name": name, "subject": subject, "body": body, "date": date}, **label)


def app(**kw):
    row = {c: "" for c in A.APP_COLS}
    row.update({"id": "x", "firm": "hartwell"})
    row.update(kw)
    return row


class DataCase(unittest.TestCase):
    """Each test gets its own data folder with the invented firm list."""

    cfg = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="apptracker-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        make_data(self.tmp, self.cfg)
        self.s = config.use(self.tmp)

    def write_apps(self, rows):
        store.write(self.s.apps, A.APP_COLS, [dict({c: "" for c in A.APP_COLS}, **r) for r in rows])

    def write_others(self, rows):
        store.write(self.s.others, A.OTHER_COLS, rows)

    def apps(self):
        return {r["id"]: r for r in store.read(self.s.apps)}

    def archive(self, rid, into, path=None, **kw):
        """A row already folded into its firm's row (one application per firm)."""
        path = path or self.s.apps_merged
        rows = store.read(path) + [dict({"id": rid, "firm": rid.split("-")[0], "merged_into": into,
                                         "merged_on": "2026-11-04"}, **kw)]
        store.write(path, A.APP_COLS + A.MERGED_COLS, rows)
