"""Tests for the correction layer.

This is the layer that decides what a human never has to look at, so its
failure mode is not a wrong number — it is a wrong *routing*. Posting an
unreviewed adjustment because a judgement call was mistaken for a rule is
the mistake that matters, and most of these tests exist to make it loud.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path

from src.recon.agent import Verdict, classify_residue
from src.recon.correct import (
    ACTION_FOR,
    OWNER_FOR,
    REVIEW_THRESHOLD_NZD,
    Action,
    Route,
    build_correction,
    build_queue,
    render,
    summarise,
)
from src.recon.generate import generate
from src.recon.ingest import build_cases
from src.recon.models import CATALOGUE_INDEX, Cause, ReconciliationCase
from src.recon.rules import classify

DATA = Path(__file__).resolve().parents[1] / "data" / "raw"


def setUpModule():
    generate(DATA)


def make_case(sku_id="BEV-0210", discrepancy=-4, **kw) -> ReconciliationCase:
    base = dict(
        case_id=f"{sku_id}-W01",
        sku_id=sku_id,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 7),
        opening_count=100,
        closing_count=100 + discrepancy,
        delivered_units=0,
        sold_units=0,
    )
    base.update(kw)
    return ReconciliationCase(**base)


class TestActionMapping(unittest.TestCase):
    """The same gap means different work depending on why it happened."""

    def test_every_cause_maps_to_an_action_with_an_owner(self):
        for cause in Cause:
            if cause is Cause.NONE:
                continue
            self.assertIn(cause, ACTION_FOR, f"{cause.value} has no action")
            self.assertIn(ACTION_FOR[cause], OWNER_FOR)

    def test_identical_shortfalls_produce_different_work(self):
        """Four units short is a supplier claim, a write-off, or a count
        correction — three desks, one number."""
        case = make_case(discrepancy=-4)
        actions = {}
        for cause in (Cause.SHORT_DELIVERY, Cause.UNLOGGED_WASTAGE, Cause.MISCOUNT):
            correction = build_correction(
                case, cause, from_rules=False, confidence="medium", basis="x")
            actions[cause] = (correction.action, correction.owner)
        self.assertEqual(len(set(actions.values())), 3, actions)
        self.assertEqual(actions[Cause.SHORT_DELIVERY][0],
                         Action.RAISE_SUPPLIER_CLAIM)

    def test_a_balanced_case_produces_nothing_to_post(self):
        clean = make_case(discrepancy=0)
        self.assertIsNone(build_correction(
            clean, Cause.NONE, from_rules=True, confidence="rule", basis=""))


class TestRouting(unittest.TestCase):
    """Who has to look at this, and why."""

    def test_judgement_calls_never_post_unattended(self):
        """The rules layer earned auto-posting with 1585 clean commitments.
        The judgement layer has no such record and does not inherit it."""
        for cause in (Cause.MISCOUNT, Cause.UNLOGGED_WASTAGE, Cause.SHORT_DELIVERY):
            correction = build_correction(
                make_case(discrepancy=-2), cause,
                from_rules=False, confidence="high", basis="x")
            self.assertIsNot(correction.route, Route.AUTO,
                             f"{cause.value} from the agent must not auto-post")

    def test_small_rule_certain_corrections_post_automatically(self):
        correction = build_correction(
            make_case(sku_id="BEV-0210", discrepancy=-4),  # $0.95/unit
            Cause.DUPLICATE_SCAN, from_rules=True, confidence="rule", basis="x")
        self.assertIs(correction.route, Route.AUTO)
        self.assertLess(correction.value_nzd, REVIEW_THRESHOLD_NZD)

    def test_value_overrides_certainty(self):
        """Certainty is not the only control. A large adjustment posted
        unattended is how a control failure becomes an audit finding."""
        correction = build_correction(
            make_case(sku_id="TOB-6004", discrepancy=-10),  # $52/unit = $520
            Cause.DUPLICATE_SCAN, from_rules=True, confidence="rule", basis="x")
        self.assertGreaterEqual(correction.value_nzd, REVIEW_THRESHOLD_NZD)
        self.assertIs(correction.route, Route.REVIEW)

    def test_shrinkage_always_escalates_however_small(self):
        """The correction is trivial; the finding is that stock is being
        stolen. That is a security event, not a ledger one."""
        correction = build_correction(
            make_case(sku_id="SNK-1044", discrepancy=-1),  # $1.20
            Cause.SHRINKAGE, from_rules=True, confidence="rule", basis="x")
        self.assertIs(correction.route, Route.ESCALATE)
        self.assertEqual(correction.owner, "loss prevention")


class TestQueue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_cases(DATA)
        cls.findings = classify(cls.result)
        cls.verdicts = classify_residue(cls.result, cls.findings)
        cls.queue = build_queue(cls.result, cls.findings, cls.verdicts)
        cls.summary = summarise(cls.queue)

    def test_one_correction_per_discrepancy_and_none_for_clean_weeks(self):
        flagged = [c for c in self.result.cases if c.discrepancy != 0]
        self.assertEqual(len(self.queue), len(flagged))

    def test_ordered_by_money_at_stake(self):
        values = [c.value_nzd for c in self.queue]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_every_correction_carries_its_evidence(self):
        """A queue entry a reviewer cannot audit is a queue entry they have
        to redo from scratch."""
        for correction in self.queue:
            self.assertTrue(correction.basis.strip(), correction.case_id)

    def test_an_unexplained_case_is_an_open_item_not_a_correction(self):
        """With no verdict there is nothing anyone decided, and posting a
        guess would put an unowned adjustment into the ledger."""
        queue = build_queue(self.result, self.findings, verdicts=None)
        resolved = {c.case_id for c in self.result.cases
                    if self.findings[c.case_id].resolved and c.discrepancy != 0}
        self.assertEqual({c.case_id for c in queue}, resolved)

    def test_summary_totals_reconcile_with_the_queue(self):
        self.assertEqual(
            sum(e["count"] for e in self.summary["by_route"].values()),
            len(self.queue))
        self.assertAlmostEqual(
            sum(e["value_nzd"] for e in self.summary["by_route"].values()),
            self.summary["value_nzd"], places=2)

    def test_auto_posted_work_is_only_ever_rule_certain(self):
        """The single routing mistake that actually costs money."""
        for correction in self.queue:
            if correction.route is Route.AUTO:
                self.assertEqual(correction.confidence, "rule", correction.case_id)
                self.assertIs(self.findings[correction.case_id].resolved, True)

    def test_rendered_queue_shows_every_route_including_empty_ones(self):
        text = render(self.queue, self.summary)
        for route in ("escalate", "review", "auto"):
            self.assertIn(f"`{route}`", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
