"""Materials checklists read from the free-text notes on career pages."""

import unittest

import helpers  # noqa: F401  (puts the package on the path)

from apptracker import checklist


class MaterialsChecklist(unittest.TestCase):
    """checklist.checklist_needs: the free-text materials notes the sweeps wrote, read
    into one checklist item per thing to gather."""

    def needs(self, materials, letter_required="?", **kw):
        return dict(checklist.checklist_needs(dict(materials=materials, letter_required=letter_required, **kw)))

    def test_a_plain_list_with_one_item_that_follows(self):
        got = self.needs("Resume, undergraduate transcript, cover letter (required), and law school transcript once "
                         "available. The Suited assessment is required. No writing sample is listed.", "y")
        self.assertEqual(got, {"resume": "req", "cover_letter": "req", "undergrad": "req",
                               "law_transcript": "later", "suited": "req"})

    def test_negations_cover_the_whole_list_and_eg_does_not_break_it(self):
        got = self.needs("Required on the portal: resume, law school transcript, undergraduate transcript. Cover letter "
                         "optional ('not required, but welcome'). Writing samples and references not required. "
                         "No assessment (e.g. Suited) mentioned.", "optional")
        self.assertEqual(got, {"resume": "req", "cover_letter": "opt", "undergrad": "req", "law_transcript": "later"})
        self.assertNotIn("suited", self.needs("No writing sample or Suited-type assessment is listed."))
        self.assertNotIn("suited", self.needs("No mention of Suited or another assessment."))

    def test_an_optional_item_does_not_make_the_list_before_it_optional(self):
        got = self.needs("Cover letter, resume, undergraduate and law school transcripts, and an optional one-minute "
                         "video introduction.", "y")
        self.assertEqual((got["undergrad"], got["video"]), ("req", "opt"))

    def test_a_predicate_after_a_list_covers_every_item(self):
        got = self.needs("Cover letter, resume, undergraduate transcript. The law school transcript, writing sample, "
                         "and list of references may be submitted later.", "y")
        self.assertEqual((got["writing_sample"], got["references"], got["undergrad"]), ("later", "later", "req"))
        got = self.needs("Resume and undergraduate transcript, with fall 2026 grades sent later as a supplement once "
                         "available.", "n")
        self.assertEqual((got["undergrad"], got["law_transcript"]), ("req", "later"))
        self.assertNotIn("cover_letter", got)                      # the ledger says no letter

    def test_a_graduate_transcript_is_not_his_and_if_any_stays_with_it(self):
        got = self.needs("Current resume, undergraduate transcript (unofficial OK), graduate transcripts if any, and "
                         "a law school transcript after first-term grades.")
        self.assertEqual((got["undergrad"], got["law_transcript"], got["cover_letter"]), ("req", "later", "unknown"))
        self.assertNotIn("_grad", got)

    def test_grades_only_block_applying_when_the_firm_says_so(self):
        self.assertEqual(self.needs("Cover letter, resume and law school transcript.", "y")["law_transcript"], "later")
        self.assertEqual(self.needs("Complete first-semester law school transcript, required before applying.")["law_transcript"], "req")

    def test_an_unstated_cover_letter_is_flagged_not_dropped(self):
        got = self.needs("Cover letter and writing sample requirements are unknown.")
        self.assertEqual(got["cover_letter"], "unknown")
        self.assertNotIn("writing_sample", got)

    def test_a_hand_set_list_wins_and_done_items_round_trip(self):
        a = {"materials": "Resume, cover letter.", "letter_required": "y", "needs": "resume;suited:opt;bogus"}
        self.assertEqual(checklist.checklist_needs(a), [("resume", "req"), ("suited", "opt")])
        self.assertEqual(checklist.checklist_done({"checklist": "suited=2026-11-02;resume=2026-11-01;x=1"}),
                         {"suited": "2026-11-02", "resume": "2026-11-01"})
        self.assertEqual(checklist.checklist_str({"suited": "2026-11-02", "resume": "2026-11-01"}),
                         "resume=2026-11-01;suited=2026-11-02")

    def test_guesses_are_marked(self):
        self.assertTrue(checklist.materials_unsure({"materials": "Last cycle: resume and cover letter."}))
        self.assertFalse(checklist.materials_unsure({"materials": "Resume and cover letter."}))
        self.assertFalse(checklist.materials_unsure({"materials": "Last cycle: resume.", "needs": "resume"}))


class ParserRegressions(unittest.TestCase):
    def needs(self, materials, letter_required="?", **kw):
        return dict(checklist.checklist_needs(dict(materials=materials, letter_required=letter_required, **kw)))

    def test_a_hedge_in_front_of_one_item_stays_with_it(self):
        got = self.needs("Online application, cover letter, resume, law school transcript (update with first-semester "
                         "grades), optional undergraduate transcript, Suited assessment", "y")
        self.assertEqual((got["undergrad"], got["suited"]), ("opt", "req"))
        self.assertEqual(self.needs("Resume, optional writing sample, cover letter", "?")["cover_letter"], "req")

    def test_grades_first_reads_only_sentences_about_grades(self):
        self.assertEqual(self.needs("Resume and a transcript; apply once the first-semester transcript was available.")["law_transcript"], "req")
        self.assertEqual(self.needs("Resume and law school transcript. Complete the Suited assessment before applying.")["law_transcript"], "later")

    def test_conditions_scopes_and_dropped_requirements(self):
        self.assertEqual(self.needs("A cover letter is required. A writing sample is evaluated at the interview stage.", "y")["writing_sample"], "later")
        self.assertNotIn("writing_sample", self.needs("If a writing sample is required before finals, OCS suggests a placeholder."))
        self.assertNotIn("undergrad", self.needs("Resume, writing sample, and an undergraduate transcript for IP candidates."))
        self.assertNotIn("statement", self.needs("Last cycle required a personal statement, but the current flyer and page drop that requirement.", "n"))
        self.assertEqual(self.needs("Resume, law professor reference, cover letter")["references"], "req")

    def test_hand_set_lists_are_read_forgivingly(self):
        self.assertEqual(checklist.checklist_needs({"needs": "Resume; cover_letter : optional;suited:none;video:weird"}),
                         [("resume", "req"), ("cover_letter", "opt"), ("video", "unknown")])


class ParserRecheck(unittest.TestCase):
    def needs(self, materials, letter_required="y"):
        return dict(checklist.checklist_needs({"materials": materials, "letter_required": letter_required}))

    def test_two_word_items_take_their_hedge(self):
        self.assertEqual(self.needs("The firm encourages the Suited assessment, using the same email.")["suited"], "opt")
        self.assertEqual(self.needs("Resume, cover letter, Suited assessment (optional)")["suited"], "opt")

    def test_negations_and_hedges_in_parentheses_dashes_and_labels(self):
        self.assertNotIn("suited", self.needs("The page lists no writing sample, no assessment (no Suited), and no portal."))
        self.assertNotIn("writing_sample", self.needs("Resume, cover letter - no writing sample."))
        got = self.needs("Required: resume, cover letter. Optional: writing sample, references.")
        self.assertEqual((got["writing_sample"], got["references"]), ("opt", "opt"))
        got = self.needs("Writing sample and references (both optional).")
        self.assertEqual((got["writing_sample"], got["references"]), ("opt", "opt"))

    def test_timing_words(self):
        self.assertEqual(self.needs("Resume, undergraduate transcript as soon as possible; law school transcript once available")["undergrad"], "req")
        self.assertEqual(self.needs("Include a writing sample when applying.")["writing_sample"], "req")
        self.assertEqual(self.needs("A writing sample is requested at callback.")["writing_sample"], "later")
        self.assertEqual(self.needs("Application complete once first full-year transcript received.", "?")["law_transcript"], "req")
        self.assertEqual(self.needs("Submit your resume and transcript, and complete the Suited assessment before applying.")["law_transcript"], "later")

    def test_scopes_drops_and_references(self):
        self.assertNotIn("writing_sample", self.needs("Writing sample for litigation candidates only."))
        self.assertNotIn("statement", self.needs("The personal statement was dropped for 2028.", "n"))
        self.assertNotIn("references", self.needs("Resume and cover letter (reference the office you prefer)."))
        self.assertEqual(self.needs("Resume, cover letter, two recommendation letters.")["references"], "req")

    def test_clipped_notes_drop_only_the_cut_off_word(self):
        note = ("Resume and cover letter. " * 9 + "Undergraduate and any graduate transcri")[:240]
        self.assertEqual(len(note), 240)
        self.assertNotIn("undergrad", self.needs(note))          # "transcri" was cut off
        kept = ("Resume, transcripts, a writing sample, and a statement of interest of up to 25" + " " * 0)
        kept = ("x" * (240 - len(kept))) + kept
        self.assertIn("statement", self.needs(kept))             # a whole item before the cut stays

    def test_hand_set_lists_with_labels_and_commas(self):
        self.assertEqual(checklist.checklist_needs({"needs": "resume, cover letter:opt, writing sample:later, suited: not required"}),
                         [("resume", "req"), ("cover_letter", "opt"), ("writing_sample", "later")])


if __name__ == "__main__":
    unittest.main()
