"""Tests for the review command line.

A reviewer works this queue under interruption, so the properties that matter
are that every command is safe to repeat, that a refusal explains itself, and
that a mistyped cause is caught before it reaches the ledger rather than
after.

Exit codes are asserted throughout: this is a tool that will end up in a
script, and a command that fails silently with status 0 is worse than one
that crashes.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from src.recon.agent import classify_residue
from src.recon.correct import build_queue
from src.recon.decisions import open_log, pending, record_run
from src.recon.generate import generate
from src.recon.ingest import build_cases
from src.recon.review import main
from src.recon.rules import classify

DATA = Path(__file__).resolve().parents[1] / "data" / "raw"


def setUpModule():
    generate(DATA)


class ReviewTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Path(self.tmp.name) / "decisions.db"

        result = build_cases(DATA)
        findings = classify(result)
        queue = build_queue(result, findings, classify_residue(result, findings))
        conn = open_log(self.db)
        record_run(conn, "run-1", queue, seed=20260814)
        self.open_cases = [r["case_id"] for r in pending(conn, "run-1")]
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--db", str(self.db), *argv])
        return code, out.getvalue()


class TestListingAndShowing(ReviewTestCase):
    def test_list_shows_the_queue_worst_money_first(self):
        code, output = self.run_cli("list", "--limit", "3")
        self.assertEqual(code, 0)
        self.assertIn("awaiting a decision", output)
        values = [float(line.split()[1].replace(",", ""))
                  for line in output.splitlines()
                  if line.startswith(tuple(c[:3] for c in self.open_cases))]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_show_includes_the_evidence(self):
        """A reviewer who has to go and reconstruct the reasoning is a
        reviewer who redoes the work."""
        code, output = self.run_cli("show", self.open_cases[0])
        self.assertEqual(code, 0)
        self.assertIn("because", output)
        self.assertIn("awaiting a decision", output)

    def test_show_on_an_unknown_case_fails_rather_than_printing_nothing(self):
        code, output = self.run_cli("show", "NOT-A-CASE")
        self.assertEqual(code, 1)
        self.assertIn("no correction", output)


class TestDeciding(ReviewTestCase):
    def test_approving_clears_it_from_the_queue(self):
        case_id = self.open_cases[0]
        code, output = self.run_cli("approve", case_id, "--by", "priya s")
        self.assertEqual(code, 0)
        self.assertIn("approved", output)

        _, listing = self.run_cli("list", "--limit", "100")
        self.assertNotIn(case_id, listing)

    def test_amending_records_the_cause_that_was_actually_posted(self):
        case_id = self.open_cases[0]
        code, _ = self.run_cli("amend", case_id, "--cause", "miscount",
                               "--by", "priya s")
        self.assertEqual(code, 0)

        _, shown = self.run_cli("show", case_id)
        self.assertIn("amended", shown)
        self.assertIn("miscount", shown)

    def test_a_mistyped_cause_is_refused_before_it_reaches_the_ledger(self):
        """The ledger has no way to interpret a cause nothing else knows
        about, and a typo here is silent until someone reads the table."""
        case_id = self.open_cases[0]
        code, output = self.run_cli("amend", case_id, "--cause", "misscount",
                                    "--by", "priya s")
        self.assertEqual(code, 1)
        self.assertIn("unknown cause", output)

        _, shown = self.run_cli("show", case_id)
        self.assertIn("awaiting a decision", shown,
                      "a refused amendment must not record anything")

    def test_rejecting_keeps_the_reason(self):
        case_id = self.open_cases[0]
        self.run_cli("reject", case_id, "--by", "priya s",
                     "--note", "duplicate of last week's claim")
        _, shown = self.run_cli("show", case_id)
        self.assertIn("rejected", shown)
        self.assertIn("duplicate of last week", shown)

    def test_deciding_an_unknown_case_fails_clearly(self):
        code, output = self.run_cli("approve", "NOT-A-CASE", "--by", "priya s")
        self.assertEqual(code, 1)
        self.assertIn("not in run", output)

    def test_a_decision_can_be_revised(self):
        """A reviewer who clicks the wrong button must be able to fix it;
        the log keeps the current decision, not an argument about it."""
        case_id = self.open_cases[0]
        self.run_cli("approve", case_id, "--by", "priya s")
        code, _ = self.run_cli("amend", case_id, "--cause", "shrinkage",
                               "--by", "m tanner")
        self.assertEqual(code, 0)

        _, shown = self.run_cli("show", case_id)
        self.assertIn("amended", shown)
        self.assertIn("m tanner", shown)
        self.assertNotIn("approved", shown)


class TestStats(ReviewTestCase):
    def test_stats_before_any_review_says_so(self):
        code, output = self.run_cli("stats")
        self.assertEqual(code, 0)
        self.assertIn("nobody has reviewed anything", output)

    def test_stats_report_agreement_after_decisions(self):
        self.run_cli("approve", self.open_cases[0], "--by", "priya s")
        self.run_cli("reject", self.open_cases[1], "--by", "priya s")
        code, output = self.run_cli("stats")
        self.assertEqual(code, 0)
        self.assertIn("reviewed  : 2", output)
        self.assertIn("50% agreement", output)


class TestMissingLog(unittest.TestCase):
    def test_a_missing_database_explains_what_to_run(self):
        with TemporaryDirectory() as tmp:
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--db", str(Path(tmp) / "nope.db"), "list"])
            self.assertEqual(code, 1)
            self.assertIn("src.recon.correct", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
