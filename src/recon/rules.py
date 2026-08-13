"""Deterministic checks for discrepancies with a structural signature.

Each rule here earns its place by being *cheaper and more reliable* than a
model. They do not guess. A rule fires only when the evidence explains the
discrepancy arithmetically — the docket quantity has to reconcile the gap
exactly, not merely point in the right direction. Anything a rule cannot
account for is left as residue and passed on, which is the population the
agent layer exists to serve.

The ordering below is deliberate: pair rules that consume evidence from an
adjacent period run before single-period rules, because a late invoice and
a miscount are indistinguishable once you look only at magnitude.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ingest import CaseEvidence, IngestResult
from .models import CATALOGUE_INDEX, Cause, ReconciliationCase


@dataclass(frozen=True)
class Finding:
    """A rule's verdict on one case.

    `cause is None` means no rule matched — the case is residue, not clean.
    Residue is the honest output here: claiming a cause the evidence does
    not support is worse than declining, because a wrong cause gets acted
    on and a declined one gets looked at.
    """

    case_id: str
    cause: Cause | None
    magnitude: int
    rule: str
    explanation: str

    @property
    def resolved(self) -> bool:
        return self.cause is not None


def _case_size(sku_id: str) -> int:
    sku = CATALOGUE_INDEX.get(sku_id)
    return sku.case_size if sku else 1


# ----------------------------------------------------------------------
# Individual rules
# ----------------------------------------------------------------------

def rule_balanced(case: ReconciliationCase, ev: CaseEvidence, prior) -> Finding | None:
    """No gap, nothing to explain."""
    if case.discrepancy != 0:
        return None
    return Finding(case.case_id, Cause.NONE, 0, "balanced",
                   "opening + delivered - sold equals the counted close")


def rule_unit_mismatch(case: ReconciliationCase, ev: CaseEvidence, prior) -> Finding | None:
    """Cases logged as eaches.

    The unit-of-measure column says CASE while the quantity column holds a
    case count, so the shelf received qty x case_size and the paperwork
    recorded qty. Requiring the arithmetic to land exactly is what stops
    this firing on a CASE docket that happens to sit beside a real loss.
    """
    for d in ev.deliveries:
        if d["uom"] != "CASE":
            continue
        size = _case_size(case.sku_id)
        implied = d["qty_received"] * (size - 1)
        if implied == case.discrepancy and implied != 0:
            return Finding(
                case.case_id, Cause.UNIT_MISMATCH, case.discrepancy, "unit_mismatch",
                f"docket {d['docket_no']} records {d['qty_received']} at uom=CASE; "
                f"{d['qty_received']} x {size} units arrived, {d['qty_received']} were booked",
            )
    return None


def rule_late_delivery(case: ReconciliationCase, ev: CaseEvidence, prior) -> Finding | None:
    """Stock arrived before the count; its paperwork is dated after.

    The surplus on the shelf equals a docket sitting just outside the
    window. Nothing else produces a positive gap that matches a real
    document to the unit.
    """
    if case.discrepancy <= 0:
        return None
    for d in ev.late_deliveries:
        if d["qty_received"] == case.discrepancy:
            return Finding(
                case.case_id, Cause.LATE_DELIVERY, case.discrepancy, "late_delivery",
                f"docket {d['docket_no']} dated {d['delivery_date']} is after the "
                f"{case.period_end} count but its {d['qty_received']} units were on "
                f"the shelf when the count happened",
            )
    return None


def rule_late_carryover(case: ReconciliationCase, ev: CaseEvidence, prior) -> Finding | None:
    """The second half of a late delivery.

    One late invoice dents two periods with opposite signs: a surplus when
    the stock arrives unpapered, a shortfall when the paperwork lands in the
    next window and double-books it. This rule only fires when the previous
    period for this SKU was itself resolved as a late delivery of the same
    size, which is what separates it from an ordinary shortfall.
    """
    if case.discrepancy >= 0 or prior is None:
        return None
    if prior.cause is not Cause.LATE_DELIVERY:
        return None
    if prior.magnitude != -case.discrepancy:
        return None
    return Finding(
        case.case_id, Cause.LATE_CARRYOVER, case.discrepancy, "late_carryover",
        f"{-case.discrepancy} units invoiced this period were received and counted "
        f"in the previous one ({prior.case_id})",
    )


def rule_duplicate_scan(case: ReconciliationCase, ev: CaseEvidence, prior) -> Finding | None:
    """A till that rang the same line twice.

    A genuine double-scan leaves two separate transactions agreeing on SKU,
    date and quantity. That pair is the signature; the inflated total on its
    own is not, because a miscount produces the same number.
    """
    if case.discrepancy <= 0:
        return None
    seen: dict[tuple, dict] = {}
    for sale in ev.sales:
        key = (sale["sale_date"], sale["qty"])
        twin = seen.get(key)
        if twin is not None and sale["qty"] == case.discrepancy:
            return Finding(
                case.case_id, Cause.DUPLICATE_SCAN, case.discrepancy, "duplicate_scan",
                f"transactions {twin['transaction_id']} and {sale['transaction_id']} "
                f"both record {sale['qty']} units on {sale['sale_date']}",
            )
        seen[key] = sale
    return None


# Pair rules first: they consume evidence from an adjacent period that the
# single-period rules cannot see, and would otherwise be masked by them.
RULES = (
    rule_balanced,
    rule_late_carryover,
    rule_unit_mismatch,
    rule_late_delivery,
    rule_duplicate_scan,
)


# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------

def classify(result: IngestResult) -> dict[str, Finding]:
    """Run the rules over every case, newest evidence carried forward.

    Cases are walked in SKU-then-date order so that a late delivery is
    already resolved by the time its carryover lands in the next period.
    """
    findings: dict[str, Finding] = {}
    prior_by_sku: dict[str, Finding] = {}

    for case in sorted(result.cases, key=lambda c: (c.sku_id, c.period_start)):
        ev = result.evidence.get(case.case_id, CaseEvidence())
        prior = prior_by_sku.get(case.sku_id)

        finding = None
        for rule in RULES:
            finding = rule(case, ev, prior)
            if finding is not None:
                break
        if finding is None:
            finding = Finding(
                case.case_id, None, case.discrepancy, "unresolved",
                f"discrepancy of {case.discrepancy} units with no structural "
                f"signature in the source rows",
            )

        findings[case.case_id] = finding
        prior_by_sku[case.sku_id] = finding

    return findings


if __name__ == "__main__":
    from pathlib import Path

    from .ingest import build_cases

    root = Path(__file__).resolve().parents[2]
    res = build_cases(root / "data" / "raw")
    found = classify(res)

    resolved = [f for f in found.values() if f.resolved and f.cause is not Cause.NONE]
    clean = [f for f in found.values() if f.cause is Cause.NONE]
    residue = [f for f in found.values() if not f.resolved]

    print(f"cases            : {len(found)}")
    print(f"clean            : {len(clean)}")
    print(f"resolved by rules: {len(resolved)}")
    print(f"residue          : {len(residue)}")
    for f in resolved[:5]:
        print(f"  [{f.rule}] {f.case_id}: {f.explanation}")
