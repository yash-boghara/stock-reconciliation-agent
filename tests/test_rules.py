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

import tempfile
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
    rule_duplicate_scan,
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


class TestConfusionsFoundBySeedSweep(unittest.TestCase):
    """Both of these were reported as confident, wrong causes until a sweep
    over 30 seeds surfaced them. A single seed showed 100% precision and
    hid the lot, which is the argument for not trusting one dataset."""

    def test_routine_next_week_docket_is_not_a_late_delivery(self):
        # A docket dated two days after the count is usually just next
        # week's delivery. If this week already booked one, and no receiving
        # note places the stock here before the count, it explains nothing.
        case = make_case(delivered_units=24, sold_units=10,
                         closing_count=100 + 24 - 10 + 6)
        self.assertEqual(case.discrepancy, 6)
        ev = CaseEvidence(
            deliveries=[{"docket_no": "D-own", "uom": "EACH", "qty_received": 24,
                         "delivery_date": MONDAY}],
            late_deliveries=[{"docket_no": "D-next", "uom": "EACH", "qty_received": 6,
                              "delivery_date": SUNDAY + timedelta(days=2)}],
        )
        self.assertIsNone(rule_late_delivery(case, ev, None))

    def test_receiving_note_rescues_a_genuine_late_delivery(self):
        # Same shape, but the GRN says those units were counted off the
        # truck before the stocktake. Now the docket does explain the gap.
        case = make_case(delivered_units=24, sold_units=10,
                         closing_count=100 + 24 - 10 + 6)
        ev = CaseEvidence(
            deliveries=[{"docket_no": "D-own", "uom": "EACH", "qty_received": 24,
                         "delivery_date": MONDAY}],
            late_deliveries=[{"docket_no": "D-late", "uom": "EACH", "qty_received": 6,
                              "delivery_date": SUNDAY + timedelta(days=2)}],
            goods_received={"D-late": {"grn_no": "G1", "docket_no": "D-late",
                                       "received_date": SUNDAY - timedelta(days=1),
                                       "qty_counted": 6}},
        )
        finding = rule_late_delivery(case, ev, None)
        self.assertIsNotNone(finding)
        self.assertIs(finding.cause, Cause.LATE_DELIVERY)

    def test_same_quantity_on_different_tills_is_not_a_double_scan(self):
        # Two customers, two tills, same item, same day, same quantity.
        # Ordinary trade — and it was being called a double-scan whenever
        # the quantity happened to match the discrepancy.
        case = make_case(sold_units=16, closing_count=100 - 16 + 8)
        self.assertEqual(case.discrepancy, 8)
        coincidence = CaseEvidence(sales=[
            {"transaction_id": "T1", "sale_date": MONDAY, "qty": 8, "till": "1", "at": 36000},
            {"transaction_id": "T2", "sale_date": MONDAY, "qty": 8, "till": "3", "at": 36012},
        ])
        self.assertIsNone(rule_duplicate_scan(case, coincidence, None))

        # Same till, but hours apart — two customers, not one re-ring.
        far_apart = CaseEvidence(sales=[
            {"transaction_id": "T1", "sale_date": MONDAY, "qty": 8, "till": "2", "at": 32400},
            {"transaction_id": "T2", "sale_date": MONDAY, "qty": 8, "till": "2", "at": 61200},
        ])
        self.assertIsNone(rule_duplicate_scan(case, far_apart, None))

        # A till with no recorded clock cannot establish adjacency at all.
        untimed = CaseEvidence(sales=[
            {"transaction_id": "T1", "sale_date": MONDAY, "qty": 8, "till": "2", "at": None},
            {"transaction_id": "T2", "sale_date": MONDAY, "qty": 8, "till": "2", "at": None},
        ])
        self.assertIsNone(rule_duplicate_scan(case, untimed, None))

        same_till = CaseEvidence(sales=[
            {"transaction_id": "T1", "sale_date": MONDAY, "qty": 8, "till": "2", "at": 36000},
            {"transaction_id": "T2", "sale_date": MONDAY, "qty": 8, "till": "2", "at": 36018},
        ])
        finding = rule_duplicate_scan(case, same_till, None)
        self.assertIsNotNone(finding)
        self.assertIs(finding.cause, Cause.DUPLICATE_SCAN)


class TestGeneratorInvariants(unittest.TestCase):
    """The generator must not produce arithmetic it cannot stand behind."""

    def test_no_week_sells_stock_that_never_existed(self):
        # A negative close used to be floored at zero, which invented a
        # discrepancy in a case labelled clean. The generator now refuses
        # to emit one, so this asserts across seeds rather than just ours.
        for seed in (1, 2, 3, 7, 11, 20260814):
            with self.subTest(seed=seed):
                with tempfile.TemporaryDirectory() as tmp:
                    generate(Path(tmp), seed=seed)   # raises on a negative close
                    result = build_cases(Path(tmp))
                    for case in result.cases:
                        self.assertGreaterEqual(case.closing_count, 0)

    def test_clean_cases_reconcile_exactly_across_seeds(self):
        for seed in (1, 2, 3, 7, 11):
            with self.subTest(seed=seed):
                with tempfile.TemporaryDirectory() as tmp:
                    generate(Path(tmp), seed=seed)
                    result = build_cases(Path(tmp))
                    labels = load_labels(Path(tmp))
                    for case in result.cases:
                        if labels[case.case_id] == "none":
                            self.assertEqual(case.discrepancy, 0, case.case_id)


class TestPrecisionAcrossSeeds(unittest.TestCase):
    """Precision is the promise. One seed cannot demonstrate it."""

    def test_rules_never_name_a_wrong_cause_on_any_seed(self):
        wrong = []
        for seed in range(1, 13):
            with tempfile.TemporaryDirectory() as tmp:
                generate(Path(tmp), seed=seed)
                result = build_cases(Path(tmp))
                labels = load_labels(Path(tmp))
                for cid, finding in classify(result).items():
                    if finding.resolved and finding.cause.value != labels[cid]:
                        wrong.append((seed, cid, finding.cause.value, labels[cid]))
        self.assertEqual(wrong, [], f"misclassified: {wrong[:5]}")


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
        self.assertEqual(correct, 115, "baseline moved; record the new figure")

    def test_residue_is_left_for_the_agent(self):
        residue = [f for f in self.findings.values() if not f.resolved]
        self.assertEqual(len(residue), 35)

    def test_short_delivery_recall_is_capped_by_receiving_notes(self):
        """Recall here is bounded by how often a GRN was filed, not by the
        rule. Every short delivery with a receiving note behind it is
        caught; the rest are unprovable and belong in the residue."""
        provable = unprovable = 0
        for cid, truth in self.labels.items():
            if truth != "short_delivery":
                continue
            ev = self.result.evidence[cid]
            if any(d["docket_no"] in ev.goods_received for d in ev.deliveries):
                provable += 1
                self.assertTrue(self.findings[cid].resolved, f"{cid} had a GRN")
            else:
                unprovable += 1
                self.assertFalse(self.findings[cid].resolved, f"{cid} had no GRN")
        self.assertGreater(provable, 0)
        self.assertGreater(unprovable, 0, "seed no longer exercises the unprovable path")

    def test_judgement_causes_are_never_claimed_by_rules(self):
        """The taxonomy says these need context, not arithmetic. A rule
        claiming one means a rule is overreaching."""
        for cid, finding in self.findings.items():
            if self.labels[cid] in {"miscount", "unlogged_wastage", "shrinkage"}:
                self.assertFalse(finding.resolved, f"{cid} claimed by {finding.rule}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
