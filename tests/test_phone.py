"""The phone copy: export for the store, ticks back from it."""

import io
import json
import os
import unittest
from contextlib import redirect_stdout

from helpers import TODAY, DataCase

from apptracker import applications as A
from apptracker import cli, phone


class PhoneSync(DataCase):
    def setUp(self):
        super().setUp()
        self.write_apps([dict(id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L Summer Associate",
                              opens="2026-11-01", deadline="2027-01-29", letter_required="y")])
        self.write_others([{"id": "quillon-dc-1l", "firm": "quillon", "office": "DC", "track": "1L-2027",
                            "program": "1L Summer Associate", "opens": "2026-11-01"}])

    def test_phone_checks_fold_into_the_ledger(self):
        ticks = [{"id": "checks/hartwell-dc-ny", "data": {"id": "hartwell-dc-ny", "applied": "2026-10-16", "at": "2026-10-17T01:00:00Z"}},
                 {"id": "quillon-dc-1l", "applied": "2026-10-17", "at": "2026-10-17T14:00:00Z"},
                 {"id": "gone", "applied": "2026-10-17", "at": "2026-10-17T15:00:00Z"}]
        res = dict(phone.import_checks(ticks, TODAY))
        self.assertEqual((res["hartwell-dc-ny"], res["quillon-dc-1l"]), ("applied 2026-10-16", "applied 2026-10-17"))
        self.assertTrue(res["gone"].startswith("skipped"))
        self.assertEqual({k: r["applied"] for k, r in self.apps().items()},
                         {"hartwell-dc-ny": "2026-10-16", "quillon-dc-1l": "2026-10-17"})
        # unticked on the computer since; the next sync must not re-tick it from the old phone tick
        A.set_applied("hartwell-dc-ny", "", TODAY)
        self.assertEqual(phone.import_checks(ticks, TODAY, since="2026-10-17T12:00:00Z")[0][0], "quillon-dc-1l")
        self.assertEqual(self.apps()["hartwell-dc-ny"]["applied"], "")

    def test_checks_load_from_the_store_listing_directory(self):
        d = os.path.join(self.tmp, "listing", "checks")
        os.makedirs(d)
        with open(os.path.join(d, "hartwell-dc-ny.json"), "w") as fh:
            json.dump({"applied": "2026-10-16", "at": "2026-10-17T01:00:00Z"}, fh)
        self.assertEqual(phone.load_checks(os.path.dirname(d)),
                         [{"applied": "2026-10-16", "at": "2026-10-17T01:00:00Z", "id": "hartwell-dc-ny"}])
        with open(os.path.join(self.tmp, "listing.json"), "w") as fh:
            json.dump({"docs": [{"id": "hartwell-dc-ny", "applied": ""}]}, fh)
        self.assertEqual(phone.load_checks(os.path.join(self.tmp, "listing.json")), [{"id": "hartwell-dc-ny", "applied": ""}])

    def test_export_stays_small_and_carries_what_the_page_needs(self):
        out = phone.export(TODAY)
        self.assertTrue(out["synced_at"].endswith("Z"))
        self.assertNotIn("applied", out["rows"][0])   # empty fields are dropped
        self.assertLess(len(json.dumps(out)), 256 * 1024)
        self.assertEqual([t["key"] for t in out["tracks"]], ["2L-2028", "1L-2027"])
        self.assertEqual((out["offices"], out["tz"]), (["DC", "NY"], "America/New_York"))

    def test_phone_stamps_compare_as_times(self):
        tick = {"id": "hartwell-dc-ny__resume", "item": "resume", "done": "2026-10-17", "at": "2026-10-17T12:40:05.300Z"}
        self.assertEqual(len(phone.import_checks([tick], TODAY, since="2026-10-17T12:40:05Z")), 1)
        self.assertEqual(phone.export(TODAY, as_of="2026-10-17T12:00:00Z")["synced_at"], "2026-10-17T12:00:00.000Z")

    def test_phone_ticks_after_the_listing_wait_for_the_next_sync(self):
        tick = {"id": "hartwell-dc-ny", "applied": "2026-10-17", "at": "2026-10-17T12:40:05.600Z"}
        self.assertEqual(phone.import_checks([tick], TODAY, since="2026-10-17T12:00:00Z", until="2026-10-17T12:40:05.000Z"), [])
        self.assertEqual(len(phone.import_checks([tick], TODAY, since="2026-10-17T12:40:05.000Z")), 1)

    def test_the_cli_checks_its_stamps(self):
        for argv in (["export", "--as-of", "yesterday"], ["import-checks", "x.json", "--since", "noon"]):
            with self.assertRaises(SystemExit) as cm:
                cli.main(argv)
            self.assertIn("ISO time", str(cm.exception))
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["export", "--as-of", "2026-10-17T12:00:00Z"])
        self.assertEqual(json.loads(buf.getvalue())["synced_at"], "2026-10-17T12:00:00.000Z")


if __name__ == "__main__":
    unittest.main()
