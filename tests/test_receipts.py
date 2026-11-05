"""Application receipts: classifying mail and matching it to rows."""

import datetime
import unittest

from helpers import TODAY, DataCase, msg

from apptracker import applications as A
from apptracker import receipts, store
from apptracker.checklist import checklist_done


class Confirmations(DataCase):
    """confirm: receipt emails mark applications confirmed."""

    def setUp(self):
        super().setUp()
        base = {c: "" for c in A.APP_COLS}
        self.write_apps([
            dict(base, id="brandt-ny", firm="brandt", office="NY", program="2028 Summer Associate",
                 track="2L-2028", applied="2026-10-01"),
            dict(base, id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L Summer Associate", track="2L-2028"),
            dict(base, id="hartwell-1l", firm="hartwell", office="DC", program="1L Summer Associate", track="1L-2027"),
        ])
        self.write_others([
            {"id": "quillon-dc-1l", "firm": "quillon", "office": "DC", "track": "1L-2027", "program": "1L Summer Associate"}])

    def test_receipts_are_told_apart_from_lookalikes(self):
        c = lambda *a: receipts.classify(msg("x", *a))[0]
        self.assertEqual(c("recruiting@vanceokafor.example", "Confirmation",
                           "<p>Dear JORDAN:<br>Your application has been received by Vance Okafor.</p>"), "application")
        self.assertEqual(c("mailer@ats.example", "Morrow Hale Confirmation",
                           "This email serves as confirmation that your application has been received."), "application")
        self.assertEqual(c("recruiting@vanceokafor.example", "Vance Okafor / Career Opportunities",
                           "Thank you for visiting our Careers page. To continue your application, please click here to Apply."), "started")
        self.assertEqual(c("recruiting@morrowhale.example", "Your Questions, Answered",
                           "Once we have received your application, our team reviews it on a rolling basis."), "other")
        self.assertEqual(c("recruiting@quillonday.example", "Applications Now Open!",
                           "Thank you for applying last year? Apply again now."), "other")
        self.assertEqual(c("noreply@suited.example", "Thank you for completing your Suited assessment", ""), "assessment")
        self.assertEqual(c("x@hartwellpike.example", "Next steps", "Dear Jordan, we would like to invite you to a screening interview."), "status")

    def test_a_receipt_confirms_the_ticked_application(self):
        res = receipts.ingest([msg("bm1", "donotreply@brandtmercer.example", "Brandt Mercer / Summer Program Application",
                                 "Hi Jordan, Thank you for submitting your application for the following position at "
                                 "Brandt Mercer: 2028 New York Summer Associate.", date="2026-10-01T21:55:03Z")], TODAY)
        self.assertEqual(res, [("bm1", "application", "confirmed")])
        row = self.apps()["brandt-ny"]
        self.assertEqual((row["applied"], row["confirmed"], row["confirm_ref"]), ("2026-10-01", "2026-10-01", "bm1"))
        self.assertEqual(receipts.ingest([msg("bm1", "donotreply@brandtmercer.example", "x", "y")], TODAY), [])   # read once

    def test_a_receipt_for_an_unticked_row_marks_it_applied(self):
        res = receipts.ingest([msg("hp1", "noreply@ats-mail.example", "Application received",
                                 "Thank you for applying to the 2028 Summer Associate Program in Washington, D.C.",
                                 name="Hartwell & Pike Recruiting", kind="application")], TODAY)
        self.assertEqual(res[0][2], "applied 2026-10-16, confirmed")
        self.assertEqual(self.apps()["hartwell-dc-ny"]["confirmed"], "2026-10-16")
        self.assertEqual(self.apps()["hartwell-1l"]["applied"], "")   # the 2028 program, not the 1L one

    def test_a_receipt_for_a_folded_track_matches_the_firms_row(self):
        # one application per firm: hartwell-1l was folded into hartwell-dc-ny
        self.write_apps([r for r in store.read(self.s.apps) if r["id"] != "hartwell-1l"])
        store.write(self.s.apps_merged, A.APP_COLS + A.MERGED_COLS,
                  [{"id": "hartwell-1l", "firm": "hartwell", "track": "1L-2027", "program": "1L Summer Associate",
                    "merged_into": "hartwell-dc-ny", "merged_on": "2026-11-04"}])
        res = receipts.ingest([msg("hp9", "noreply@ats-mail.example", "Application received",
                                 "Thank you for applying to our 1L Summer Associate program.",
                                 name="Hartwell & Pike Recruiting", kind="application")], TODAY)
        self.assertEqual(res[0][2], "applied 2026-10-16, confirmed")
        self.assertEqual(self.apps()["hartwell-dc-ny"]["confirmed"], "2026-10-16")

    def test_a_1l_receipt_finds_the_1l_program(self):
        receipts.ingest([msg("hp2", "x@hartwellpike.example", "Application received",
                           "Thank you for applying to our 1L Summer Program in Washington, DC.", kind="application")], TODAY)
        self.assertEqual(self.apps()["hartwell-1l"]["confirmed"], "2026-10-16")

    def test_a_firm_named_only_in_the_body_waits_for_you(self):
        res = receipts.ingest([msg("esp", "noreply@forms.example", "Thank you for your application to the Example Scholars Program",
                                 "Sponsors this year include Hartwell & Pike.")], TODAY)
        self.assertTrue(res[0][2].startswith("review"), res)
        self.assertEqual(self.apps()["hartwell-dc-ny"]["confirmed"], "")
        eye = receipts.needs_eye(TODAY)
        self.assertEqual([r["message_id"] for r in eye], ["esp"])
        receipts.resolve("esp", "ignore", TODAY)
        self.assertEqual(receipts.needs_eye(TODAY), [])

    def test_resolving_a_review_confirms_the_row_it_names(self):
        res = receipts.ingest([msg("hp3", "x@hartwellpike.example", "Application received", "Thank you for applying.")], TODAY)
        self.assertTrue(res[0][2].startswith("review: receipt for hartwell-dc-ny"), res)   # unlabeled, not ticked: ask
        self.assertEqual(self.apps()["hartwell-dc-ny"]["confirmed"], "")
        receipts.resolve("hp3", "hartwell-1l", TODAY)
        self.assertEqual(self.apps()["hartwell-1l"]["confirm_ref"], "hp3")
        self.assertEqual((self.apps()["hartwell-dc-ny"]["applied"], self.apps()["hartwell-dc-ny"]["confirmed"]), ("", ""))

    def test_an_application_started_and_never_sent_is_flagged(self):
        receipts.ingest([msg("qd1", "recruiting@quillonday.example", "Quillon Day / Career Opportunities",
                           "To continue your application, please click here to Apply.", date="2026-10-14T12:00:00Z")], TODAY)
        self.assertEqual([r["message_id"] for r in receipts.needs_eye(TODAY)], ["qd1"])
        self.assertEqual(receipts.needs_eye(datetime.date(2026, 10, 15)), [])   # a day or two of grace
        receipts.ingest([msg("qd2", "recruiting@quillonday.example", "Confirmation", "Your application has been received.",
                           date="2026-10-16T12:00:00Z", kind="application")], TODAY)
        self.assertEqual(receipts.needs_eye(TODAY), [])
        self.assertEqual(self.apps()["quillon-dc-1l"]["applied"], "2026-10-16")   # adopted from the other firms

    def test_a_finished_suited_assessment_ticks_the_checklist(self):
        receipts.ingest([msg("su1", "noreply@suited.example", "Thank you for completing your Suited assessment",
                           "Hartwell & Pike will receive your results.", name="Hartwell & Pike via Suited",
                           kind="assessment")], TODAY)
        self.assertEqual(checklist_done(self.apps()["hartwell-dc-ny"]), {"suited": "2026-10-16"})


class ReviewRegressions(DataCase):
    """Receipt cases that once misfired."""

    def setUp(self):
        super().setUp()
        base = {c: "" for c in A.APP_COLS}
        self.write_apps([
            dict(base, id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L Summer Associate", track="2L-2028"),
            dict(base, id="brandt-ny", firm="brandt", office="NY", program="2028 Summer Associate", track="2L-2028"),
        ])
        self.write_others([
            {"id": "hartwell-1l-diversity", "firm": "hartwell", "track": "1L-2027", "program": "1L Diversity Scholars Program"},
            {"id": "hartwell-1l", "firm": "hartwell", "track": "1L-2027", "program": "1L Summer Associate"},
            {"id": "quillon-dc", "firm": "quillon", "track": "2L-2028", "program": "2028 Summer Associate"}])

    def hp(self, mid, subject, body, date="2026-10-16T15:00:00Z", **label):
        return msg(mid, "recruiting@hartwellpike.example", subject, body, date=date, **label)

    def test_a_1l_receipt_goes_to_the_1l_program_not_the_2l_row(self):
        receipts.ingest([self.hp("a", "Application received", "Thank you for applying to our 1L Summer Associate program.",
                               kind="application")], TODAY)
        self.assertEqual(self.apps()["hartwell-dc-ny"]["applied"], "")
        self.assertEqual(self.apps()["hartwell-1l"]["confirm_ref"], "a")        # adopted from the other programs

    def test_a_fellowship_receipt_goes_to_the_fellowship_or_to_you(self):
        receipts.ingest([self.hp("b", "1L Diversity Scholars - Application Received", "Your application has been received.",
                               kind="application")], TODAY)
        self.assertEqual(self.apps()["hartwell-1l-diversity"]["confirm_ref"], "b")
        res = receipts.ingest([self.hp("c", "Ridley Fellowship application", "Your application has been received.",
                                     kind="application")], TODAY)
        self.assertTrue(res[0][2].startswith("review"), res)                  # no row names a "fellowship"

    def test_a_second_receipt_is_a_duplicate_not_a_new_application(self):
        A.set_applied("hartwell-dc-ny", "2026-10-15", TODAY)
        receipts.ingest([self.hp("d1", "Thank you for applying!", "Thank you for applying to Hartwell & Pike.")], TODAY)
        res = receipts.ingest([self.hp("d2", "Your application", "We have received your application materials.")], TODAY)
        self.assertEqual(res[0][2], "already confirmed")
        self.assertNotIn("hartwell-1l", self.apps())

    def test_registrations_signups_and_faqs_are_not_receipts(self):
        c = lambda subject, body: receipts.classify(msg("x", "x@hartwellpike.example", subject, body))[0]
        self.assertEqual(c("Confirmation", "Thank you for registering for our DC 1L Diversity Reception. We have received your submission."), "other")
        self.assertEqual(c("Welcome to the Hartwell Talent Community", "You have successfully submitted your profile to our talent community."), "other")
        self.assertEqual(c("Summer Program: What Happens Next", "Q: How do I know my application was received? A: Check the portal."), "other")
        self.assertEqual(c("Thank you for registering for Hartwell Diversity Day", "Thank you for your application"), "other")

    def test_decisions_and_invitations_are_news_not_receipts(self):
        c = lambda subject, body: receipts.classify(msg("x", "x@hartwellpike.example", subject, body))[0]
        self.assertEqual(c("Application Update", "Thank you for applying. We regret that we are unable to offer you a position."), "status")
        self.assertEqual(c("Vance Okafor - Interview Invitation", "We are pleased to invite you to interview."), "status")
        self.assertEqual(c("Event Canceled", "We regret to inform you that the reception is canceled."), "other")

    def test_more_receipt_wordings(self):
        c = lambda body: receipts.classify(msg("x", "x@hartwellpike.example", "Update", body))[0]
        for body in ("Your application for the 2028 Summer Associate Program has been received.",
                     "Thanks for submitting your application to Hartwell & Pike.",
                     "Your application to Hartwell & Pike has been submitted.",
                     "We have received your resume and transcript for the 2028 Summer Associate Program.",
                     "You have successfully applied to the 2028 Summer Associate position.",
                     "Your materials have been received and will be reviewed.",
                     "This email confirms that you applied to the 2028 Summer Associate Program."):
            self.assertEqual(c(body), "application", body)
        # a recruiter acknowledging a resume sent while networking is not an application
        self.assertEqual(c("We have received your resume. Thanks for reaching out!"), "other")
        self.assertEqual(receipts.classify(msg("x", "x@hartwellpike.example", "Application Received - 2028 Summer Associate Program", ""))[0], "application")

    def test_a_suited_invite_or_reminder_is_not_a_finished_assessment(self):
        c = lambda subject, body: receipts.classify(msg("x", "noreply@wearesuited.example", subject, body, name="Hartwell via Suited"))[0]
        self.assertEqual(c("Hartwell has invited you to take the Suited assessment", "Once you have completed it, Hartwell will see it."), "assessment_invite")
        self.assertEqual(c("Reminder", "You have not yet completed your Suited assessment."), "assessment_invite")
        self.assertEqual(c("Thank you for completing your Suited assessment", ""), "assessment")

    def test_dates_from_headers_and_never_in_the_future(self):
        receipts.ingest([msg("e1", "x@brandtmercer.example", "Application received", "Your application has been received.",
                           date="Fri, 16 Oct 2026 21:55:03 +0000", kind="application")], TODAY)
        self.assertEqual((self.apps()["brandt-ny"]["applied"], self.apps()["brandt-ny"]["confirmed"]), ("2026-10-16", "2026-10-16"))
        receipts.ingest([self.hp("e2", "Application received", "Your application has been received.", date="2026-10-20T15:00:00Z",
                               kind="application")], TODAY)
        self.assertEqual((self.apps()["hartwell-dc-ny"]["applied"], self.apps()["hartwell-dc-ny"]["confirmed"]), ("2026-10-17", "2026-10-17"))
        receipts.ingest([msg("e3", "x@brandtmercer.example", "Application received", "Your application has been received.", date="")], TODAY)

    def test_ignoring_or_unticking_takes_back_a_wrong_receipt(self):
        receipts.ingest([msg("f1", "x@quillonday.example", "Application received", "Your application has been received.", kind="application")], TODAY)
        self.assertIn("quillon-dc", self.apps())
        receipts.resolve("f1", "ignore", TODAY)
        self.assertNotIn("quillon-dc", self.apps())                            # adopted only for that receipt
        receipts.ingest([self.hp("f2", "Application received", "Your application has been received.", kind="application")], TODAY)
        A.set_applied("hartwell-dc-ny", "", TODAY)
        self.assertEqual(self.apps()["hartwell-dc-ny"]["confirmed"], "")          # set aside for a same-day Undo only
        self.assertTrue(self.apps()["hartwell-dc-ny"]["confirm_ref"].startswith("~f2@"))
        with self.assertRaises(ValueError):
            receipts.resolve("f2", "hartwell-dcc", TODAY)




class RecheckRegressions(DataCase):
    """More receipt cases that once misfired."""

    def setUp(self):
        super().setUp()
        base = {c: "" for c in A.APP_COLS}
        self.write_apps([
            dict(base, id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L Summer Associate", track="2L-2028"),
            dict(base, id="hartwell-1l", firm="hartwell", office="DC", program="1L Summer Associate", track="1L-2027"),
            dict(base, id="brandt-ny", firm="brandt", office="NY", program="2028 Summer Associate", track="2L-2028",
                 opens="2026-10-01"),
        ])
        self.write_others([
            {"id": "hartwell-fellowship", "firm": "hartwell", "track": "2L-2028", "program": "2028 Diversity Fellowship"},
            {"id": "quillon-dc", "firm": "quillon", "track": "2L-2028", "program": "2028 Summer Associate"}])

    def hp(self, mid, subject, body, date="2026-10-16T15:00:00Z", **label):
        return msg(mid, "recruiting@hartwellpike.example", subject, body, date=date, **label)

    def test_a_2027_interview_date_is_not_a_1l_cue(self):
        A.set_applied("hartwell-dc-ny", "2026-10-15", TODAY)
        receipts.ingest([self.hp("y1", "Application received", "Thank you for applying to our Summer Associate Program. "
                               "We will begin scheduling interviews in January 2027.")], TODAY)
        self.assertEqual(self.apps()["hartwell-dc-ny"]["confirm_ref"], "y1")
        self.assertEqual(self.apps()["hartwell-1l"]["applied"], "")

    def test_first_year_means_1l_and_never_falls_back_to_2l(self):
        receipts.ingest([self.hp("y2", "Application received", "Thank you for applying to our First-Year Summer Associate Program.",
                               kind="application")], TODAY)
        self.assertEqual(self.apps()["hartwell-1l"]["confirm_ref"], "y2")
        self.assertEqual(self.apps()["hartwell-dc-ny"]["applied"], "")

    def test_equal_opportunity_boilerplate_is_not_a_fellowship(self):
        receipts.ingest([self.hp("y3", "Application received", "Thank you for applying to our 2028 Summer Associate Program. "
                               "Hartwell & Pike is committed to diversity and inclusion.", kind="application")], TODAY)
        self.assertEqual(self.apps()["hartwell-dc-ny"]["confirm_ref"], "y3")
        self.assertNotIn("hartwell-fellowship", self.apps())

    def test_newest_first_batches_are_read_oldest_first(self):
        A.set_applied("hartwell-dc-ny", "2026-10-15", TODAY)
        res = receipts.ingest([self.hp("z2", "Your application", "We have received your application materials.", date="2026-10-16T18:00:00Z"),
                             self.hp("z1", "Thank you!", "Thank you for applying to Hartwell & Pike.", date="2026-10-15T14:00:00Z")], TODAY)
        self.assertEqual(dict((m, r) for m, _, r in res), {"z1": "confirmed", "z2": "already confirmed"})
        self.assertEqual(self.apps()["hartwell-1l"]["applied"], "")

    def test_process_wording_does_not_turn_a_receipt_into_news(self):
        c = lambda body: receipts.classify(self.hp("x", "Application received", body))[0]
        self.assertEqual(c("Your application has been received. If selected, we will contact you to schedule an interview."), "application")
        self.assertEqual(c("Thank you for applying. We regret that we cannot respond to every applicant individually."), "application")
        for body in ("Thank you for your application. We have decided not to move forward with your application.",
                     "Thank you for applying. We would like to invite you to our office for callback interviews.",
                     "Thank you for your application. We are delighted to offer you a position in our 2028 program."):
            self.assertEqual(c(body), "status", body)
        self.assertEqual(receipts.classify(self.hp("x", "Interview Invitation", "Thank you for your application. Please select a time below."))[0], "status")

    def test_events_signups_faqs_and_unfinished_applications(self):
        c = lambda subject, body: receipts.classify(self.hp("x", subject, body))[0]
        self.assertEqual(c("Confirmation", "Thank you for your application to attend our DC Schools Reception."), "other")
        self.assertEqual(c("Welcome!", "Thank you for joining the Hartwell Talent Community. We have received your resume."), "other")
        self.assertEqual(c("Your Questions, Answered", "How do I know my application was received? Your application is complete when you see it."), "other")
        self.assertEqual(c("Your application", "Thank you for your application. Your application is not yet complete. Please log in to finish your application."), "started")

    def test_suited_invites_in_other_words(self):
        c = lambda subject, body: receipts.classify(msg("x", "noreply@wearesuited.example", subject, body, name="Hartwell via Suited"))[0]
        self.assertEqual(c("Next steps: Suited assessment", "Thank you for taking the time to apply. We ask all candidates to complete a Suited assessment."), "assessment_invite")
        self.assertEqual(c("Your Suited assessment", "Thank you for your application. Hartwell uses Suited. Click below to get started."), "assessment_invite")

    def test_a_receipt_before_the_portal_opened_waits_for_you(self):
        res = receipts.ingest([msg("w1", "x@brandtmercer.example", "Application received", "Your application has been received.",
                                 date="2026-09-20T15:00:00Z")], TODAY)
        self.assertTrue(res[0][2].startswith("review: dated before"), res)

    def test_untick_then_undo_keeps_the_receipt(self):
        receipts.ingest([self.hp("u1", "Application received", "Thank you for applying to our 2028 Summer Associate Program.",
                               kind="application")], TODAY)
        A.set_applied("hartwell-dc-ny", "", TODAY)
        A.set_applied("hartwell-dc-ny", "2026-10-16", TODAY)
        self.assertEqual((self.apps()["hartwell-dc-ny"]["confirmed"], self.apps()["hartwell-dc-ny"]["confirm_ref"]), ("2026-10-16", "u1"))

    def test_ignoring_a_suited_result_reaches_the_side_file_and_spares_hand_ticks(self):
        receipts.ingest([msg("s1", "noreply@wearesuited.example", "Thank you for completing your Suited assessment", "",
                           name="Quillon Day via Suited", kind="assessment")], TODAY)
        self.assertIn("suited", checklist_done({"checklist": A.other_checks().get("quillon-dc", "")}))
        receipts.resolve("s1", "ignore", TODAY)
        self.assertNotIn("quillon-dc", A.other_checks())
        A.set_check("hartwell-dc-ny", "suited", "2026-10-10", TODAY)
        res = receipts.ingest([msg("s2", "noreply@wearesuited.example", "Thank you for completing your Suited assessment", "",
                                 name="Hartwell via Suited", kind="assessment")], TODAY)
        self.assertEqual(res[0][2], "suited already done")
        receipts.resolve("s2", "ignore", TODAY)
        self.assertEqual(checklist_done(self.apps()["hartwell-dc-ny"]), {"suited": "2026-10-10"})

    def test_a_second_program_started_and_never_sent_is_flagged(self):
        A.set_applied("hartwell-dc-ny", "2026-10-10", TODAY)
        receipts.ingest([self.hp("st", "Hartwell & Pike / Career Opportunities", "To continue your application, please click here to Apply. "
                               "1L Summer Associate - Washington, DC", date="2026-10-14T12:00:00Z")], TODAY)
        self.assertEqual([r["message_id"] for r in receipts.needs_eye(TODAY)], ["st"])





class LabelPolicy(DataCase):
    """A reader may label each message; the phrase rules alone may only
    confirm an application already ticked."""

    def setUp(self):
        super().setUp()
        base = {c: "" for c in A.APP_COLS}
        self.write_apps([
            dict(base, id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L Summer Associate", track="2L-2028"),
            dict(base, id="hartwell-1l", firm="hartwell", office="DC", program="1L Summer Associate", track="1L-2027")])
        self.write_others([
            {"id": "hartwell-ridley", "firm": "hartwell", "track": "2L-2028", "program": "Ridley Fellowship"}])

    def test_unlabeled_receipts_only_confirm_what_was_ticked(self):
        A.set_applied("hartwell-dc-ny", "2026-10-15", TODAY)
        res = receipts.ingest([msg("p1", "x@hartwellpike.example", "Application received", "Your application has been received.")], TODAY)
        self.assertEqual(res[0][2], "confirmed")
        res = receipts.ingest([msg("p2", "x@hartwellpike.example", "Thanks", "Thank you for applying to our 1L Summer Associate program.")], TODAY)
        self.assertTrue(res[0][2].startswith("review: receipt for hartwell-1l"), res)
        self.assertEqual(self.apps()["hartwell-1l"]["applied"], "")

    def test_the_readers_program_wins(self):
        res = receipts.ingest([msg("p3", "x@hartwellpike.example", "Thank you for your application", "Thank you for your application.",
                                 kind="application", program="Ridley Fellowship")], TODAY)
        self.assertEqual(self.apps()["hartwell-ridley"]["confirm_ref"], "p3")
        self.assertEqual(self.apps()["hartwell-dc-ny"]["applied"], "")

    def test_a_label_overrides_the_phrase_rules(self):
        res = receipts.ingest([msg("p4", "x@hartwellpike.example", "Your application", "Thank you for your application. After careful "
                                 "consideration we will not be moving forward.", kind="status")], TODAY)
        self.assertEqual(res[0][1], "status")
        self.assertEqual(self.apps()["hartwell-dc-ny"]["confirmed"], "")

    def test_an_unlabeled_suited_result_asks_first(self):
        res = receipts.ingest([msg("p5", "noreply@wearesuited.example", "Thank you for completing your Suited assessment", "",
                                 name="Hartwell via Suited")], TODAY)
        self.assertTrue(res[0][2].startswith("review: Suited finished"), res)
        self.assertEqual(checklist_done(self.apps()["hartwell-dc-ny"]), {})

    def test_a_later_reticks_does_not_bring_back_a_disowned_receipt(self):
        receipts.ingest([msg("p6", "x@hartwellpike.example", "Application received", "Thank you for applying to our 2028 program.",
                           kind="application")], TODAY)
        A.set_applied("hartwell-dc-ny", "", TODAY)
        A.set_applied("hartwell-dc-ny", "2026-10-17", TODAY + datetime.timedelta(days=5))
        self.assertEqual((self.apps()["hartwell-dc-ny"]["confirmed"], self.apps()["hartwell-dc-ny"]["confirm_ref"]), ("", ""))


class Queries(DataCase):
    cfg = {"receipt_skip_senders": ["events.example", "lists.school.example"]}

    def test_queries_leave_out_the_configured_senders(self):
        qs = receipts.confirm_queries(datetime.date(2026, 10, 1))
        self.assertEqual(len(qs), 6)
        for q in qs:
            self.assertIn("after:2026/10/01 -in:sent -in:drafts -from:events.example -from:lists.school.example ", q)
            self.assertLessEqual(q.count(" OR "), 4)            # five terms at most per search

    def test_the_window_starts_at_the_setting_then_two_days_before_the_last_read(self):
        self.assertEqual(receipts.confirm_since(TODAY), TODAY - datetime.timedelta(days=receipts.FIRST_WINDOW))
        self.s.save(receipts_since="2026-09-01")
        self.assertEqual(receipts.confirm_since(TODAY), datetime.date(2026, 9, 1))
        receipts.ingest([msg("q1", "x@hartwellpike.example", "Hello", "Nothing to see.")], TODAY)
        self.assertEqual(receipts.confirm_since(TODAY), TODAY - datetime.timedelta(days=2))


class AnotherCycle(DataCase):
    cfg = {"cycle": 2030}

    def test_track_cues_follow_the_cycle(self):
        self.write_apps([dict(id="hartwell-2l", firm="hartwell", program="2030 Summer Associate", track="2L-2030"),
                         dict(id="hartwell-1l", firm="hartwell", program="Summer Associate (first year)", track="1L-2029")])
        receipts.ingest([msg("c1", "x@hartwellpike.example", "Application received",
                             "Thank you for applying to our Summer 2029 program.", kind="application")], TODAY)
        receipts.ingest([msg("c2", "x@hartwellpike.example", "Application received",
                             "Thank you for applying to our 2030 Summer Associate Program.", kind="application")], TODAY)
        self.assertEqual((self.apps()["hartwell-1l"]["confirm_ref"], self.apps()["hartwell-2l"]["confirm_ref"]), ("c1", "c2"))


if __name__ == "__main__":
    unittest.main()
