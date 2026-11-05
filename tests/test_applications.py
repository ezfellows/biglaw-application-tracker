"""The ledger: next steps, tick boxes, and one application per firm."""

import datetime
import io
import unittest
from contextlib import redirect_stdout

from helpers import TODAY, DataCase, app

from apptracker import applications as A
from apptracker import cli, phone, store, view
from apptracker.checklist import checklist_done


class NextStep(DataCase):
    def st(self, a, cfg=None):
        return A.app_state(a, TODAY, cfg or {})[:2]

    def test_opens_soon_without_a_letter_is_this_week(self):
        a = app(opens="2026-11-01", letter_required="y", letter="quillon/dc-lit")
        p, st, action = A.app_state(a, TODAY, {})
        self.assertEqual((p, st), (2, "prepare"))
        self.assertIn("letter draft", action)

    def test_opens_soon_with_final_letter_is_just_ready(self):
        self.assertEqual(self.st(app(opens="2026-11-01", letter_required="y", letter="hartwell/dc-lit")), (3, "ready"))

    def test_no_letter_needed_is_ready(self):
        self.assertEqual(self.st(app(opens="2026-11-01", letter_required="n")), (3, "ready"))

    def test_unknown_materials_count_as_a_gap(self):
        self.assertEqual(self.st(app(opens="2026-11-01")), (2, "prepare"))

    def test_rolling_open_a_week_unapplied_is_p1(self):
        self.assertEqual(self.st(app(opens="2026-10-01", letter_required="n")), (1, "open"))
        self.assertEqual(self.st(app(opens="2026-10-14", letter_required="n")), (2, "open"))

    def test_hard_deadline_inside_a_week_is_p1(self):
        self.assertEqual(self.st(app(opens="2026-12-01", deadline="2026-10-20")), (1, "deadline"))

    def test_passed_deadline_is_parked(self):
        self.assertEqual(self.st(app(deadline="2026-10-01")), (4, "missed"))

    def test_applied_and_quiet_is_parked(self):
        self.assertEqual(self.st(app(applied="2026-10-01")), (4, "applied"))

    def test_grades_out_means_send_an_update_once(self):
        cfg = {"grades_released": "2026-10-15"}
        self.assertEqual(self.st(app(applied="2026-10-01"), cfg), (2, "grades_update"))
        self.assertEqual(self.st(app(applied="2026-10-01", update_sent="2026-10-16"), cfg), (4, "applied"))

    def test_quiet_after_callback_means_check_in(self):
        self.assertEqual(self.st(app(applied="2026-09-01", callback="2026-10-01")), (2, "callback_quiet"))
        self.assertEqual(self.st(app(applied="2026-09-01", callback="2026-10-01", last_news="2026-10-12")),
                         (3, "after_callback"))

    def test_upcoming_callback_beats_everything_but_an_offer(self):
        self.assertEqual(self.st(app(applied="2026-09-01", callback="2026-10-20")), (3, "callback_set"))

    def test_offer_deadline_rules(self):
        self.assertEqual(self.st(app(applied="x", offer="2026-10-10", offer_deadline="2026-10-19")), (1, "offer_due"))
        self.assertEqual(self.st(app(applied="x", offer="2026-10-10", offer_deadline="2026-10-25")), (2, "offer"))
        self.assertEqual(self.st(app(applied="x", offer="2026-10-10")), (2, "offer"))

    def test_outcome_closes_it(self):
        self.assertEqual(self.st(app(applied="2026-10-01", outcome="rejected")), (4, "rejected"))

    def test_no_dates_means_check_the_careers_page(self):
        self.assertEqual(self.st(app()), (4, "no_dates"))

    def test_an_open_page_without_a_date_reads_as_open(self):
        self.assertEqual(A.app_state({"open_status": "open", "letter_required": "n"}, TODAY, {})[1], "open")
        self.assertEqual(A.app_state({"open_status": "closed"}, TODAY, {})[1], "closed")

    def test_grades_released_comes_from_the_config_when_not_given(self):
        self.s.save(grades_released="2026-10-15")
        self.assertEqual(A.app_state(app(applied="2026-10-01"), TODAY)[1], "grades_update")

    def test_status_follows_the_dates(self):
        st = lambda **kw: view.status(kw, datetime.date(2026, 11, 3))
        self.assertEqual(st(opens="2026-11-01"), "open")
        self.assertEqual(st(opens="2026-11-04"), "upcoming")
        self.assertEqual(st(opens="2026-10-01", deadline="2026-11-02"), "closed")
        self.assertEqual(st(open_status="open"), "open")
        self.assertEqual(st(), "tbd")
        self.assertEqual(st(opens="2026-11-01", applied="2026-11-02"), "applied")
        self.assertEqual(st(applied="2026-11-02", outcome="rejected"), "rejected")


class Ticks(DataCase):
    """The page's tick box is the only way it writes the ledger."""

    def setUp(self):
        super().setUp()
        self.write_apps([dict(id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L Summer Associate",
                              opens="2026-11-01", deadline="2027-01-29", letter_required="y")])
        self.write_others([{"id": "quillon-dc-1l", "firm": "quillon", "office": "DC", "track": "1L-2027",
                            "program": "1L Summer Associate", "opens": "2026-11-01", "source": "https://quillonday.example/join"}])

    def test_ticking_and_unticking_writes_applied(self):
        later = TODAY + datetime.timedelta(days=16)
        self.assertEqual(A.set_applied("hartwell-dc-ny", "2026-11-02", later), "applied 2026-11-02")
        self.assertEqual(self.apps()["hartwell-dc-ny"]["applied"], "2026-11-02")
        self.assertEqual(A.set_applied("hartwell-dc-ny", "2026-11-02", later), "unchanged")
        self.assertEqual(A.set_applied("hartwell-dc-ny", "", later), "cleared")
        self.assertEqual(self.apps()["hartwell-dc-ny"]["applied"], "")

    def test_ticking_another_program_adds_it_to_the_ledger(self):
        A.set_applied("quillon-dc-1l", "2026-10-17", TODAY)
        row = self.apps()["quillon-dc-1l"]
        self.assertEqual((row["applied"], row["track"], row["source"]), ("2026-10-17", "1L-2027", "https://quillonday.example/join"))
        mine = [r for r in view.rows(TODAY) if r["id"] == "quillon-dc-1l"]
        self.assertEqual([r["mine"] for r in mine], [True])   # listed once, as yours

    def test_bad_input_is_refused(self):
        with self.assertRaises(ValueError):
            A.set_applied("hartwell-dc-ny", "2026-13-01", TODAY)
        with self.assertRaises(ValueError):
            A.set_applied("hartwell-dc-ny", "2026-12-25", TODAY)   # in the future
        with self.assertRaises(KeyError):
            A.set_applied("no-such-firm", "2026-10-17", TODAY)
        self.assertEqual(A.set_applied("quillon-dc-1l", "", TODAY), "unchanged")   # unticking a non-application adds nothing
        self.assertEqual(list(self.apps()), ["hartwell-dc-ny"])

    def test_unticking_an_adopted_program_drops_it_again(self):
        A.set_applied("quillon-dc-1l", "2026-10-16", TODAY)
        A.set_applied("quillon-dc-1l", "", TODAY)
        self.assertNotIn("quillon-dc-1l", self.apps())

    def test_a_row_you_added_yourself_is_never_dropped(self):
        apps = list(self.apps().values())
        apps.append(dict({c: "" for c in A.APP_COLS}, id="quillon-dc-1l", firm="quillon", program="1L Summer Associate, DC office"))
        self.write_apps(apps)
        A.set_applied("quillon-dc-1l", "2026-10-16", TODAY)
        A.set_applied("quillon-dc-1l", "", TODAY)
        self.assertIn("quillon-dc-1l", self.apps())

    def test_an_untick_returns_side_ticks_to_the_side_file(self):
        A.set_check("quillon-dc-1l", "resume", "2026-10-15", TODAY)
        A.set_applied("quillon-dc-1l", "2026-10-16", TODAY)
        self.assertEqual(self.apps()["quillon-dc-1l"]["checklist"], "resume=2026-10-15")
        A.set_applied("quillon-dc-1l", "", TODAY)
        self.assertNotIn("quillon-dc-1l", self.apps())
        self.assertEqual(A.other_checks(), {"quillon-dc-1l": "resume=2026-10-15"})


class ChecklistTicks(DataCase):
    def setUp(self):
        super().setUp()
        self.write_apps([dict(id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L", letter_required="y",
                              materials="Cover letter, resume and law school transcript. Suited assessment.")])
        self.write_others([{"id": "quillon-dc-1l", "firm": "quillon", "materials": "Resume."}])

    def test_ticking_and_unticking_an_item(self):
        self.assertEqual(A.set_check("hartwell-dc-ny", "suited", "2026-10-17", TODAY), "suited 2026-10-17")
        self.assertEqual(A.set_check("hartwell-dc-ny", "resume", "2026-10-16", TODAY), "resume 2026-10-16")
        self.assertEqual(self.apps()["hartwell-dc-ny"]["checklist"], "resume=2026-10-16;suited=2026-10-17")
        self.assertEqual(A.set_check("hartwell-dc-ny", "suited", "", TODAY), "suited cleared")
        self.assertEqual(A.set_check("quillon-dc-1l", "resume", "", TODAY), "unchanged")   # nothing to adopt
        with self.assertRaises(ValueError):
            A.set_check("hartwell-dc-ny", "bogus", "2026-10-17", TODAY)
        with self.assertRaises(ValueError):
            A.set_check("hartwell-dc-ny", "resume", "2026-12-25", TODAY)

    def test_rows_carry_the_checklist_and_phone_ticks_fold_in(self):
        row = [r for r in view.rows(TODAY) if r["id"] == "hartwell-dc-ny"][0]
        self.assertEqual(row["needs"], "resume;cover_letter;law_transcript:later;suited")
        ticks = [{"id": "hartwell-dc-ny__suited", "item": "suited", "done": "2026-10-17", "at": "2026-10-17T14:00:00Z"},
                 {"id": "quillon-dc-1l", "item": "resume", "done": "2026-10-17", "at": "2026-10-17T15:00:00Z"}]
        res = dict(phone.import_checks(ticks, TODAY))
        self.assertEqual(res, {"hartwell-dc-ny/suited": "suited 2026-10-17", "quillon-dc-1l/resume": "resume 2026-10-17"})
        self.assertEqual({r["id"]: r["checklist"] for r in self.apps().values()}, {"hartwell-dc-ny": "suited=2026-10-17"})
        other = [r for r in view.rows(TODAY) if r["id"] == "quillon-dc-1l"][0]
        self.assertEqual((other["mine"], other["checklist"]), (False, "resume=2026-10-17"))   # not adopted
        self.assertEqual(phone.import_checks(ticks, TODAY, since="2026-10-17T16:00:00Z"), [])


class OnePerFirm(DataCase):
    """One application per firm: a second row is refused, folded ids land on the live row."""

    def setUp(self):
        super().setUp()
        self.write_apps([dict(id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L Summer Associate",
                              opens="2026-11-01", deadline="2027-01-29", letter_required="y")])
        self.write_others([{"id": "quillon-dc-1l", "firm": "quillon", "office": "DC", "track": "1L-2027",
                            "program": "1L Summer Associate", "opens": "2026-11-01", "source": "https://quillonday.example/join"}])

    def run_cli(self, *argv):
        with self.assertRaises(SystemExit) as cm:
            cli.main(list(argv))
        return str(cm.exception)

    def quiet_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out:
            cli.main(list(argv))
        return out.getvalue()

    def test_a_tick_on_a_folded_row_lands_on_the_firms_row(self):
        self.archive("hartwell-1l", "hartwell-dc-ny")
        res = dict(phone.import_checks([{"id": "hartwell-1l", "applied": "2026-11-02", "at": "2026-11-02T14:00:00Z"},
                                        {"id": "hartwell-1l__resume", "item": "resume", "done": "2026-11-02",
                                         "at": "2026-11-02T14:01:00Z"}], TODAY + datetime.timedelta(days=16)))
        self.assertEqual(res, {"hartwell-1l -> hartwell-dc-ny": "applied 2026-11-02",
                               "hartwell-1l/resume -> hartwell-dc-ny": "resume 2026-11-02"})
        row = self.apps()["hartwell-dc-ny"]
        self.assertEqual((row["applied"], checklist_done(row).get("resume")), ("2026-11-02", "2026-11-02"))
        self.assertEqual(list(self.apps()), ["hartwell-dc-ny"])   # no row came back

    def test_a_folded_sweep_row_redirects_to_a_sweep_primary(self):
        self.archive("quillon-1l-old", "quillon-dc-1l", self.s.others_merged)
        A.set_check("quillon-1l-old", "resume", "2026-11-02", TODAY + datetime.timedelta(days=16))
        self.assertEqual(A.other_checks(), {"quillon-dc-1l": "resume=2026-11-02"})
        self.assertEqual(list(self.apps()), ["hartwell-dc-ny"])   # a checklist tick adopts nothing

    def test_a_stale_tick_on_a_folded_row_never_clears_or_overwrites_the_live_row(self):
        later = TODAY + datetime.timedelta(days=20)
        A.set_applied("hartwell-dc-ny", "2026-11-02", later)
        A.set_check("hartwell-dc-ny", "resume", "2026-11-01", later)
        self.archive("hartwell-1l", "hartwell-dc-ny")
        self.assertTrue(A.set_applied("hartwell-1l", "", later).startswith("skipped"))
        self.assertTrue(A.set_applied("hartwell-1l", "2026-11-05", later).startswith("unchanged"))
        self.assertTrue(A.set_check("hartwell-1l", "resume", "", later).startswith("skipped"))
        self.assertTrue(A.set_check("hartwell-1l", "resume", "2026-11-05", later).startswith("unchanged"))
        row = self.apps()["hartwell-dc-ny"]
        self.assertEqual((row["applied"], checklist_done(row)), ("2026-11-02", {"resume": "2026-11-01"}))

    def test_folded_chains_end_on_the_live_row(self):
        self.archive("hartwell-a", "hartwell-b")
        self.archive("hartwell-b", "hartwell-dc-ny")
        self.assertEqual(A.merged_into("hartwell-a"), "hartwell-dc-ny")
        self.assertEqual(A.merged_into("hartwell-dc-ny"), "")

    def test_app_add_refuses_a_folded_row_and_a_second_row_for_a_firm(self):
        self.archive("hartwell-1l", "hartwell-dc-ny")
        self.assertIn("was folded into hartwell-dc-ny", self.run_cli("app", "add", "hartwell", "--id", "hartwell-1l", "--force"))
        self.assertIn("hartwell already has a row: hartwell-dc-ny", self.run_cli("app", "add", "Hartwell & Pike", "--office", "LA"))
        self.assertIn("was folded into hartwell-dc-ny", self.run_cli("app", "set", "hartwell-1l", "note=x"))
        self.archive("hartwell", "hartwell-dc-ny")   # a folded id that is also a prefix of a live row
        self.assertIn("was folded into hartwell-dc-ny", self.run_cli("app", "set", "hartwell", "note=x"))
        self.assertEqual(self.apps()["hartwell-dc-ny"]["note"], "")   # nothing written through a prefix
        self.assertEqual(self.quiet_cli("app", "add", "hartwell", "--office", "LA", "--force"), "added hartwell-la\n")
        self.assertEqual(sorted(self.apps()), ["hartwell-dc-ny", "hartwell-la"])

    def test_app_add_at_a_tracked_program_points_to_adopt(self):
        said = self.run_cli("app", "add", "quillon", "--office", "NY")
        self.assertIn("app adopt", said)
        self.assertIn("quillon-dc-1l", said)
        self.assertIn("adopted quillon-dc-1l", self.quiet_cli("app", "adopt", "quillon-dc-1l"))
        row = self.apps()["quillon-dc-1l"]
        self.assertEqual((row["firm"], row["opens"], row["source"]), ("quillon", "2026-11-01", "https://quillonday.example/join"))

    def test_app_add_reads_firm_names_and_guesses_the_track(self):
        self.assertEqual(A.add("Brandt Mercer", office="NY", program="1L Summer Program", today=TODAY), "brandt-ny")
        self.assertEqual(self.apps()["brandt-ny"]["track"], "1L-2027")
        self.assertEqual(A.add("Unlisted Firm LLP", today=TODAY), "unlisted-firm-llp")   # not in firms.csv: a slug
        with self.assertRaises(A.TrackerError):
            A.add("brandt", office="DC", track="3L-2029", force=True, today=TODAY)

    def test_app_set_changes_fields_and_refuses_unknown_ones(self):
        r = A.set_fields("hartwell-dc", ["note=office of interest: DC", "screener=today"], TODAY)   # a unique prefix
        self.assertEqual((r["note"], r["screener"]), ("office of interest: DC", TODAY.isoformat()))
        with self.assertRaises(A.TrackerError):
            A.set_fields("hartwell-dc-ny", ["colour=blue"], TODAY)
        with self.assertRaises(A.TrackerError):
            A.set_fields("nobody", ["note=x"], TODAY)


class Fold(DataCase):
    def setUp(self):
        super().setUp()
        self.write_apps([
            dict(id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L Summer Associate", track="2L-2028",
                 checklist="resume=2026-10-01", note="DC first"),
            dict(id="hartwell-1l", firm="hartwell", office="DC", program="1L Summer Associate", track="1L-2027",
                 checklist="resume=2026-10-05;suited=2026-10-06"),
            dict(id="brandt-ny", firm="brandt", office="NY", program="2028 Summer Associate", applied="2026-10-10"),
            dict(id="brandt-1l", firm="brandt", office="NY", program="1L program", applied="2026-10-11"),
        ])
        self.write_others([{"id": "hartwell-ny-1l", "firm": "hartwell", "office": "NY", "track": "1L-2027", "program": "1L NY"}])

    def test_folding_moves_the_row_and_keeps_the_live_rows_ticks(self):
        self.assertEqual(A.fold("hartwell-1l", "hartwell-dc-ny", TODAY), "hartwell-1l folded into hartwell-dc-ny")
        live = self.apps()["hartwell-dc-ny"]
        self.assertNotIn("hartwell-1l", self.apps())
        self.assertEqual(checklist_done(live), {"resume": "2026-10-01", "suited": "2026-10-06"})   # gaps filled, nothing overwritten
        self.assertEqual(live["note"], "DC first; also 1L-2027 1L Summer Associate DC (folded from hartwell-1l)")
        archived = store.read(self.s.apps_merged)
        self.assertEqual([(r["id"], r["merged_into"], r["merged_on"]) for r in archived], [("hartwell-1l", "hartwell-dc-ny", TODAY.isoformat())])
        self.assertEqual(A.merged_into("hartwell-1l"), "hartwell-dc-ny")

    def test_folding_a_tracked_program_takes_its_side_ticks_and_hides_it(self):
        A.set_check("hartwell-ny-1l", "writing_sample", "2026-10-12", TODAY)
        A.fold("hartwell-ny-1l", "hartwell-dc-ny", TODAY)
        self.assertEqual(store.read(self.s.others), [])
        self.assertEqual([r["id"] for r in store.read(self.s.others_merged)], ["hartwell-ny-1l"])
        self.assertEqual(A.other_checks(), {})
        self.assertEqual(checklist_done(self.apps()["hartwell-dc-ny"]).get("writing_sample"), "2026-10-12")
        self.assertNotIn("hartwell-ny-1l", [r["id"] for r in view.rows(TODAY)])

    def test_folding_refuses_another_firm_a_sent_application_and_itself(self):
        for rid, into, says in (("brandt-1l", "brandt-ny", "records an application (applied)"),
                                ("hartwell-1l", "brandt-ny", "fold only rows for the same firm"),
                                ("hartwell-dc-ny", "hartwell-dc-ny", "itself"),
                                ("nobody", "hartwell-dc-ny", "no row"),
                                ("hartwell-1l", "hartwell-ny-1l", "no application")):
            with self.assertRaises(A.TrackerError) as cm:
                A.fold(rid, into, TODAY)
            self.assertIn(says, str(cm.exception))
        self.assertEqual(len(self.apps()), 4)


class TrackRules(DataCase):
    cfg = {"cycle": 2030}

    def test_tracks_follow_the_cycle(self):
        self.assertEqual(self.s.tracks, ("2L-2030", "1L-2029"))
        self.assertEqual(A.guess_track("1L Summer Associate"), "1L-2029")
        self.assertEqual(A.guess_track("2030 Summer Associate (1L and 2L)"), "2L-2030")
        self.assertEqual(A.guess_track("Summer Associate"), "2L-2030")
        info = view.page_info([])
        self.assertEqual([t["key"] for t in info["tracks"]], ["2L-2030", "1L-2029"])
        self.assertIn("2030 summer associate", info["eyebrow"])


if __name__ == "__main__":
    unittest.main()
