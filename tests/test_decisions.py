"""Tests for the decision log.

This table is the audit trail for adjustments posted to a stock ledger, some
of them without a human. The failure that matters is not a crash — it is a
log that quietly disagrees with what actually happened: a duplicated run
inflating every rate computed off it, a rejected correction counted as
agreement, or an amendment that loses what the system originally said.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from src.recon.agent import classify_residue
from src.recon.correct import Route, build_queue
from src.recon.decisions import (
    Outcome,
    agreement,
    open_log,
    pending,
    record_decision,
    record_run,
    resolutions,
)
from src.recon.generate import generate
from src.recon.ingest import build_cases
from src.recon.rules import classify

DATA = Path(__file__).resolve().parents[1] / "data" / "raw"


def setUpModule():
    generate(DATA)


class TestDecisionLog(unittest.TestCase):
    def setUp(self):
        result = build_cases(DATA)
        findings = classify(result)
        self.queue = build_queue(result, findings, classify_residue(result, findings))
        self.conn = open_log()
        record_run(self.conn, "run-1", self.queue, seed=20260814)

    def tearDown(self):
        self.conn.close()

    def test_auto_posted_corrections_are_decisions_too(self):
        """They are adjustments made without a human. A ledger that records
        only the reviewed half is not an audit trail."""
        auto = [c for c in self.queue if c.route is Route.AUTO]
        posted = self.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE decided_by = 'system'"
        ).fetchone()[0]
        self.assertEqual(posted, len(auto))
        self.assertGreater(posted, 0)

    def test_only_reviewable_work_is_pending(self):
        expected = [c for c in self.queue if c.route is not Route.AUTO]
        self.assertEqual(len(pending(self.conn, "run-1")), len(expected))

    def test_pending_is_ordered_by_money(self):
        values = [row["value_nzd"] for row in pending(self.conn, "run-1")]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_a_decision_removes_it_from_the_queue(self):
        first = pending(self.conn, "run-1")[0]["case_id"]
        record_decision(self.conn, "run-1", first, Outcome.APPROVED,
                        decided_by="priya s")
        self.assertNotIn(first,
                         [r["case_id"] for r in pending(self.conn, "run-1")])

    def test_re_recording_a_run_replaces_rather_than_duplicates(self):
        """A run is a deterministic function of its input, so a second write
        is a re-run. Accumulating copies would corrupt every rate computed
        off this table."""
        record_run(self.conn, "run-1", self.queue, seed=20260814)
        rows = self.conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
        self.assertEqual(rows, len(self.queue))

    def test_a_decision_on_an_unknown_case_is_refused(self):
        with self.assertRaises(KeyError):
            record_decision(self.conn, "run-1", "NOT-A-CASE", Outcome.APPROVED,
                            decided_by="priya s")

    def test_an_amendment_must_say_what_it_was_amended_to(self):
        case_id = pending(self.conn, "run-1")[0]["case_id"]
        with self.assertRaises(ValueError):
            record_decision(self.conn, "run-1", case_id, Outcome.AMENDED,
                            decided_by="priya s")

    def test_a_plain_approval_cannot_smuggle_an_amended_cause(self):
        case_id = pending(self.conn, "run-1")[0]["case_id"]
        with self.assertRaises(ValueError):
            record_decision(self.conn, "run-1", case_id, Outcome.APPROVED,
                            decided_by="priya s", amended_cause="miscount")


class TestResolutionsAndAgreement(unittest.TestCase):
    def setUp(self):
        result = build_cases(DATA)
        findings = classify(result)
        self.queue = build_queue(result, findings, classify_residue(result, findings))
        self.conn = open_log()
        record_run(self.conn, "run-1", self.queue, seed=20260814)
        self.open_cases = [r["case_id"] for r in pending(self.conn, "run-1")]

    def tearDown(self):
        self.conn.close()

    def test_an_amendment_keeps_both_what_was_drafted_and_what_was_posted(self):
        """Overwriting the draft would erase the evidence that the system
        got it wrong, which is the only signal worth having here."""
        case_id = self.open_cases[0]
        drafted = self.conn.execute(
            "SELECT cause FROM corrections WHERE case_id = ?",
            (case_id,)).fetchone()["cause"]
        record_decision(self.conn, "run-1", case_id, Outcome.AMENDED,
                        decided_by="priya s", amended_cause="miscount")

        resolution = next(r for r in resolutions(self.conn) if r.case_id == case_id)
        self.assertEqual(resolution.drafted_cause, drafted)
        self.assertEqual(resolution.final_cause, "miscount")

    def test_rejected_corrections_are_not_resolutions(self):
        """Nothing was posted, so there is nothing for a future retrieval
        step to learn from."""
        case_id = self.open_cases[0]
        record_decision(self.conn, "run-1", case_id, Outcome.REJECTED,
                        decided_by="priya s")
        self.assertNotIn(case_id, [r.case_id for r in resolutions(self.conn)])

    def test_resolutions_can_be_scoped_to_one_sku(self):
        sku = pending(self.conn, "run-1")[0]["sku_id"]
        for case_id in self.open_cases:
            record_decision(self.conn, "run-1", case_id, Outcome.APPROVED,
                            decided_by="priya s")
        scoped = resolutions(self.conn, sku_id=sku)
        self.assertGreater(len(scoped), 0)
        self.assertTrue(all(r.sku_id == sku for r in scoped))

    def test_agreement_ignores_work_no_human_touched(self):
        """Counting auto-posted rows as agreement would measure the routing
        policy, not the judgement."""
        record_decision(self.conn, "run-1", self.open_cases[0],
                        Outcome.APPROVED, decided_by="priya s")
        record_decision(self.conn, "run-1", self.open_cases[1],
                        Outcome.REJECTED, decided_by="priya s")

        stats = agreement(self.conn)
        self.assertEqual(stats["reviewed"], 2)
        self.assertEqual(stats["approved"], 1)
        self.assertAlmostEqual(stats["agreement_rate"], 0.5)

    def test_agreement_is_none_before_anyone_has_reviewed_anything(self):
        """Zero reviews is not zero agreement, and reporting 0.0 would read
        as the system being wrong about everything."""
        self.assertIsNone(agreement(self.conn)["agreement_rate"])


class TestTheCommandLinePath(unittest.TestCase):
    """Run it the way a user runs it.

    Every unit test here passed while the CLI was silently logging zero
    auto-posted corrections. `python3 -m src.recon.correct` gives that module
    a second identity as `__main__`, so the `Route` enum a caller holds and
    the one `decisions` imports were different class objects — and an
    identity check between them is quietly always False. Importing the code
    cannot reproduce that; only running it can.
    """

    def test_the_log_agrees_with_the_summary_it_printed(self):
        import re
        import subprocess

        root = Path(__file__).resolve().parents[1]
        db = root / "data" / "decisions.db"
        if db.exists():
            db.unlink()

        result = subprocess.run(
            [sys.executable, "-m", "src.recon.correct"],
            cwd=root, capture_output=True, text=True, check=True)

        summary_auto = int(re.search(r"^\s*auto\s+(\d+)", result.stdout,
                                     re.MULTILINE).group(1))
        logged_auto = int(re.search(r"auto-posted\s*:\s*(\d+)", result.stdout).group(1))
        self.assertEqual(
            logged_auto, summary_auto,
            "the decision log disagrees with the queue the same run printed")
        self.assertGreater(summary_auto, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
