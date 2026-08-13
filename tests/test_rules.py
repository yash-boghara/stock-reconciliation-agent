"""Tests for the deterministic rules layer and the measured baseline.

Two kinds of test live here. The first kind pins each rule's behaviour on a
hand-built case, including the cases where it must *decline* — a rule that
fires on weak evidence is the failure mode that matters, because a wrong
cause reaches a human wearing the same confidence as a right one.

The second kind pins the baseline itself. If a change to the rules or the
generator moves those numbers, that should be a deliberate act with a new
number recorded, not a silent drift discovered later.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path

from src.recon.evaluate import load_labels, score
from src.recon.generate import generate
from src.recon.ingest import CaseEvidence, build_cases
from src.recon.models import Cause, ReconciliationCase
from src.recon.rules import (
    Finding,
    classify,
    rule_late_carryover,
    rule_late_delivery,
    rule_unit_mismatch,
)

DATA = Path(__file__).resolve().parents[1] / "data" / "raw"

MONDAY = date(2026, 6, 1)
SUNDAY = MONDAY + timedelta(days=6)


def make_case(**kw) -> ReconciliationCase:
    base = dict(
        case_id="BEV-0142-W01",
        sku_id="BEV-0142",          # case_size 24
        period_start=MONDAY,
        period_end=SUNDAY,
        opening_count=100,
        closing_count=100,
        delivered_units=0,
        sold_units=0,
    )
    base.update(kw)
    return ReconciliationCase(**base)


class TestUnitMismatch(unittest.TestCase):
    """3 cases of 24 arrive, 3 units get booked: a surplus of 3 x 23."""

    def setUp(self):
        self.docket = {"docket_no": "D1", "uom": "CASE", "qty_received": 3,
                       "delivery_date": MONDAY}
        self.case = make_case(delivered_units=3, sold_units=20,
                              closing_count=100 + 72 - 20)

    def test_fires_when_arithmetic_agrees(self):
        finding = rule_unit_mismatch(self.case, CaseEvidence(deliveries=[self.docket]), None)
        self.assertIsNotNone(finding)
        self.assertIs(finding.cause, Cause.UNIT_MISMATCH)
        self.assertEqual(finding.magnitude, 69)

    def test_declines_when_arithmetic_does_not_agree(self):
        # A CASE docket sitting beside a discrepancy it cannot explain is
        # not evidence of a unit mismatch. Firing here would be a guess.
        off_by_five = make_case(delivered_units=3, sold_units=20,
                                closing_count=100 + 72 - 20 - 5)
        self.assertIsNone(
            rule_unit_mismatch(off_by_five, CaseEvidence(deliveries=[self.docket]), None)
        )

    def test_declines_when_uom_is_eaches(self):
        each = dict(self.docket, uom="EACH")
        self.assertIsNone(
            rule_unit_mismatch(self.case, CaseEvidence(deliveries=[each]), None)
        )


class TestLateDeliveryPair(unittest.TestCase):
    """One late invoice, two periods, opposite signs."""

    def setUp(self):
        self.late_docket = {"docket_no": "D2", "uom": "EACH", "qty_received": 48,
                            "delivery_date": SUNDAY + timedelta(days=2)}

    def test_late_delivery_fires_on_matching_docket(self):
        case = make_case(sold_units=10, closing_count=100 + 48 - 10)
        finding = rule_late_delivery(
            case, CaseEvidence(late_deliveries=[self.late_docket]), None)
        self.assertIsNotNone(finding)
        self.assertIs(finding.cause, Cause.LATE_DELIVERY)
        self.assertEqual(finding.magnitude, 48)

    def test_late_delivery_declines_when_quantity_differs(self):
        case = make_case(sold_units=10, closing_count=100 + 30 - 10)
        self.assertIsNone(
            rule_late_delivery(case, CaseEvidence(late_deliveries=[self.late_docket]), None)
        )

    def test_carryover_needs_the_matching_first_half(self):
        second = make_case(case_id="BEV-0142-W02", delivered_units=48,
                           sold_units=10, closing_count=100 - 10)
        self.assertEqual(second.discrepancy, -48)

        prior = Finding("BEV-0142-W01", Cause.LATE_DELIVERY, 48, "late_delivery", "")
        finding = rule_late_carryover(second, CaseEvidence(), prior)
        self.assertIsNotNone(finding)
        self.assertIs(finding.cause, Cause.LATE_CARRYOVER)

    def test_carryover_declines_without_a_prior_late_delivery(self):
        # An identical shortfall with no late invoice behind it is an
        # ordinary loss, and belongs in the residue for the agent.
        second = make_case(case_id="BEV-0142-W02", delivered_units=48,
                           sold_units=10, closing_count=100 - 10)
        self.assertIsNone(rule_late_carryover(second, CaseEvidence(), None))

        wrong_size = Finding("BEV-0142-W01", Cause.LATE_DELIVERY, 12, "late_delivery", "")
        self.assertIsNone(rule_late_carryover(second, CaseEvidence(), wrong_size))


class TestBaseline(unittest.TestCase):
    """The measured baseline, pinned so it cannot drift unnoticed."""

    @classmethod
    def setUpClass(cls):
        generate(DATA)
        cls.result = build_cases(DATA)
        cls.findings = classify(cls.result)
        cls.labels = load_labels(DATA)
        cls.scores = score(cls.labels, cls.findings)

    def test_rules_never_name_the_wrong_cause(self):
        """Precision is the property worth defending. Recall can improve
        later; a confident wrong answer costs a human's trust now."""
        wrong = [
            (cid, f.cause.value, self.labels[cid])
            for cid, f in self.findings.items()
            if f.resolved and f.cause.value != self.labels[cid]
        ]
        self.assertEqual(wrong, [], f"rules misclassified: {wrong[:5]}")

    def test_structural_causes_are_fully_recovered(self):
        for cause in ("unit_mismatch", "late_delivery", "late_carryover"):
            with self.subTest(cause=cause):
                self.assertEqual(self.scores[cause].recall, 1.0)

    def test_clean_cases_are_not_flagged(self):
        self.assertEqual(self.scores["none"].precision, 1.0)
        self.assertEqual(self.scores["none"].recall, 1.0)

    def test_baseline_accuracy_holds(self):
        correct = sum(s.correct for s in self.scores.values())
        self.assertEqual(correct, 89, "baseline moved; record the new figure")

    def test_residue_is_left_for_the_agent(self):
        residue = [f for f in self.findings.values() if not f.resolved]
        self.assertEqual(len(residue), 61)

    def test_judgement_causes_are_never_claimed_by_rules(self):
        """The taxonomy says these need context, not arithmetic. A rule
        claiming one means a rule is overreaching."""
        for cid, finding in self.findings.items():
            if self.labels[cid] in {"miscount", "unlogged_wastage", "shrinkage"}:
                self.assertFalse(finding.resolved, f"{cid} claimed by {finding.rule}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
