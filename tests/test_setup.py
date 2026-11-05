"""Settings, the firm list, `init`, the sample data, and what the repo may hold."""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from helpers import ROOT, TODAY, DataCase

from apptracker import applications as A
from apptracker import cli, config, firms, store, view


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="apptracker-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(config.use, None)

    def test_the_data_folder_defaults_next_to_the_code_and_can_move(self):
        old = os.environ.pop("APPTRACKER_DATA", None)
        try:
            self.assertEqual(config.Settings().data, os.path.join(ROOT, "data"))
            os.environ["APPTRACKER_DATA"] = self.tmp
            self.assertEqual(config.Settings().apps, os.path.join(self.tmp, "applications.csv"))
        finally:
            os.environ.pop("APPTRACKER_DATA", None)
            if old is not None:
                os.environ["APPTRACKER_DATA"] = old
        self.assertEqual(config.Settings(self.tmp).firms, os.path.join(self.tmp, "firms.csv"))

    def test_paths_in_config_are_read_from_the_data_folder(self):
        shared = os.path.join(self.tmp, "shared")
        os.makedirs(os.path.join(self.tmp, "data"))
        os.makedirs(shared)
        with open(os.path.join(shared, "roster.csv"), "w") as fh:
            fh.write("key,name,aliases,target,priority,offices,vault_rank\nhartwell,Hartwell & Pike LLP,Hartwell,y,1,DC,40\n")
        with open(os.path.join(self.tmp, "data", "config.json"), "w") as fh:
            json.dump({"firms": "../shared/roster.csv", "letters_dir": "~/no-such-letters-folder", "lock": "../.shared.lock"}, fh)
        s = config.use(os.path.join(self.tmp, "data"))
        self.assertEqual(s.firms, os.path.join(shared, "roster.csv"))
        self.assertEqual(s.letters_dir, os.path.expanduser("~/no-such-letters-folder"))
        self.assertEqual(s.lock, os.path.join(self.tmp, ".shared.lock"))
        self.assertEqual([f["key"] for f in firms.roster()], ["hartwell"])

    def test_no_letters_folder_means_no_letter_yet(self):
        config.use(self.tmp)
        self.assertEqual(A.letter_state("hartwell/dc"), "missing")
        self.assertEqual(A.letter_state("submitted"), "sent")
        self.assertEqual(A.letter_gap({"letter_required": "y"}), "no cover letter yet")

    def test_a_bad_config_is_refused(self):
        with open(os.path.join(self.tmp, "config.json"), "w") as fh:
            fh.write("[1, 2]")
        with self.assertRaises(ValueError):
            config.Settings(self.tmp)

    def test_today_follows_the_override(self):
        os.environ["APPTRACKER_TODAY"] = "2026-12-01"
        try:
            self.assertEqual(config.Settings(self.tmp).today().isoformat(), "2026-12-01")
        finally:
            del os.environ["APPTRACKER_TODAY"]


class FirmList(DataCase):
    def test_longest_name_first_and_ampersands(self):
        self.assertEqual(firms.firm_in_text("Morrow Hale Recruiting"), "morrow-hale")
        self.assertEqual(firms.firm_in_text("Morrow LLP Recruiting"), "morrow")
        self.assertEqual(firms.firm_in_text("from Hartwell & Pike"), "hartwell")
        self.assertEqual(firms.firm_in_text("Hartwellian"), "")
        self.assertEqual(firms.firm_name("quillon"), "Quillon Day LLP")
        self.assertEqual(firms.firm_name("unknown"), "unknown")

    def test_sender_domains_and_subdomains(self):
        self.assertEqual(firms.firm_of_email("careers@mail.hartwellpike.example"), "hartwell")
        self.assertEqual(firms.firm_of_email("someone@elsewhere.example"), "")

    def test_an_edited_list_is_read_again(self):
        self.assertEqual(firms.firm_in_text("Larkspur Ode"), "")
        with open(self.s.firms, "a") as fh:
            fh.write("larkspur,Larkspur Ode LLP,Larkspur Ode,y,3,NY,\n")
        self.assertEqual(firms.firm_in_text("Larkspur Ode"), "larkspur")
        self.assertTrue(next(f for f in firms.roster() if f["key"] == "larkspur")["target"])


class Init(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="apptracker-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(config.use, None)

    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(list(argv))
        return buf.getvalue()

    def test_init_makes_empty_files_and_never_overwrites(self):
        d = os.path.join(self.tmp, "mine")
        self.run_cli("--data", d, "init")
        for name in ("applications.csv", "cycle_others.csv", "firms.csv", "firm_domains.csv", "config.json"):
            self.assertTrue(os.path.exists(os.path.join(d, name)), name)
        with open(os.path.join(d, "applications.csv")) as fh:
            self.assertEqual(fh.read().strip(), ",".join(A.APP_COLS))
        with open(os.path.join(d, "config.json")) as fh:
            self.assertEqual(json.load(fh)["cycle"], 2028)
        self.run_cli("--data", d, "app", "add", "Hartwell & Pike", "--office", "DC")
        self.assertIn("nothing to add", self.run_cli("--data", d, "init"))
        self.assertEqual([r["id"] for r in store.read(os.path.join(d, "applications.csv"))], ["hartwell-pike-dc"])
        with self.assertRaises(SystemExit):
            self.run_cli("--data", d, "init", "--sample")      # the sample never lands on real data

    def test_the_sample_loads_and_follows_the_rules(self):
        d = os.path.join(self.tmp, "demo")
        self.run_cli("--data", d, "init", "--sample")
        rows = view.rows(TODAY)
        mine = [r for r in rows if r["mine"]]
        self.assertGreaterEqual(len(mine), 5)
        self.assertTrue(all(r["firm_name"].endswith("LLP") for r in rows))      # every row names a firm on the list
        seen = {}
        for r in store.read(config.settings().apps):                          # one row per firm, unless its note says why
            seen.setdefault(r["firm"], []).append(r)
        for firm, rs in seen.items():
            self.assertTrue(len(rs) == 1 or all("separate" in r["note"] for r in rs[1:]), firm)
        folded = {r["id"] for r in store.read(config.settings().apps_merged) + store.read(config.settings().others_merged)}
        self.assertFalse(folded & {r["id"] for r in rows})
        self.assertIn("P1", self.run_cli("--data", d, "app", "list"))
        self.assertEqual(A.letter_state("hartwell/dc"), "final")


TEXT = (".py", ".html", ".md", ".csv", ".json", ".txt", ".cfg", ".toml", "")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")


class Hygiene(unittest.TestCase):
    """What the repository may hold: invented people and reserved example domains only."""

    def files(self):
        try:
            out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            out = [os.path.relpath(os.path.join(r, n), ROOT) for r, ds, ns in os.walk(ROOT)
                   for n in ns if ".git" not in r.split(os.sep) and "__pycache__" not in r and "data" != os.path.relpath(r, ROOT).split(os.sep)[0]]
        return [f for f in out if os.path.splitext(f)[1] in TEXT and os.path.isfile(os.path.join(ROOT, f))]

    def test_addresses_are_on_example_domains(self):
        for f in self.files():
            with open(os.path.join(ROOT, f), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for m in EMAIL.finditer(text):
                dom = m.group(1).lower()
                self.assertTrue(dom == "example" or dom.endswith(".example") or dom in ("example.com", "example.org"),
                                "%s: %s" % (f, m.group(0)))

    def test_no_home_paths_or_private_links(self):
        rx = re.compile(r"/(?:Users|home)/\w|claude\.ai/(?:artifact|public)/\w|\(\d{3}\)\s*\d{3}-\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b")
        for f in self.files():
            with open(os.path.join(ROOT, f), encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    self.assertIsNone(rx.search(line), "%s:%d" % (f, n))

    def test_data_folder_is_ignored(self):
        with open(os.path.join(ROOT, ".gitignore")) as fh:
            self.assertIn("/data/", fh.read().split())


if __name__ == "__main__":
    unittest.main()
