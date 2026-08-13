"""Turn a named cause into something a person can act on.

Naming the cause is not the deliverable. A stocktake discrepancy is only
closed when somebody posts an adjustment, claims money back from a supplier,
or writes off stock — and those are different actions with different owners,
even when the number in the gap is identical.

Two ideas carry this module.

**The action follows the cause, not the magnitude.** Four units short because
a pallet was invoiced and never arrived is money owed by a supplier. Four
units short because they spoiled is a write-off. Four units short because the
count was wrong is a correction to the count. Same arithmetic, three
different desks.

**Routing is what the precision figure was for.** The rules layer commits
only when the evidence reconciles exactly, and it has not named a wrong cause
in 1585 commitments across 40 seeds. That is what earns those corrections the
right to post without a human. The judgement layer has no such record, so its
output is a queue, ordered by what is at stake.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .agent import Verdict
from .ingest import IngestResult
from .models import CATALOGUE_INDEX, Cause, ReconciliationCase
from .rules import Finding

# Above this, a correction goes to a person no matter how certain the rule is.
# Certainty is not the only thing that matters — a large adjustment posted
# unattended is how a control failure becomes an audit finding.
REVIEW_THRESHOLD_NZD = 150.0


class Action(str, Enum):
    """What actually has to happen, and therefore whose job it is."""

    ADJUST_DELIVERY_RECORD = "adjust_delivery_record"
    REDATE_DOCKET = "redate_docket"
    VOID_DUPLICATE_SALE = "void_duplicate_sale"
    RAISE_SUPPLIER_CLAIM = "raise_supplier_claim"
    POST_WASTAGE_ENTRY = "post_wastage_entry"
    POST_SHRINKAGE_ENTRY = "post_shrinkage_entry"
    ADJUST_STOCK_COUNT = "adjust_stock_count"


class Route(str, Enum):
    AUTO = "auto"          # rule-certain and small enough to post unattended
    REVIEW = "review"      # a person decides
    ESCALATE = "escalate"  # a person decides, and someone else needs telling


ACTION_FOR: dict[Cause, Action] = {
    Cause.UNIT_MISMATCH: Action.ADJUST_DELIVERY_RECORD,
    Cause.LATE_DELIVERY: Action.REDATE_DOCKET,
    Cause.LATE_CARRYOVER: Action.REDATE_DOCKET,
    Cause.DUPLICATE_SCAN: Action.VOID_DUPLICATE_SALE,
    Cause.SHORT_DELIVERY: Action.RAISE_SUPPLIER_CLAIM,
    Cause.UNLOGGED_WASTAGE: Action.POST_WASTAGE_ENTRY,
    Cause.SHRINKAGE: Action.POST_SHRINKAGE_ENTRY,
    Cause.MISCOUNT: Action.ADJUST_STOCK_COUNT,
}

# Who picks the work up. Written into the correction so a queue can be split
# by desk rather than every discrepancy landing on one person.
OWNER_FOR: dict[Action, str] = {
    Action.ADJUST_DELIVERY_RECORD: "goods-in",
    Action.REDATE_DOCKET: "accounts payable",
    Action.VOID_DUPLICATE_SALE: "duty manager",
    Action.RAISE_SUPPLIER_CLAIM: "accounts payable",
    Action.POST_WASTAGE_ENTRY: "department manager",
    Action.POST_SHRINKAGE_ENTRY: "loss prevention",
    Action.ADJUST_STOCK_COUNT: "stock controller",
}


@dataclass(frozen=True)
class Correction:
    """One posting, with the evidence that justifies it attached.

    `units` is signed the way the adjustment posts: negative writes stock
    off, positive puts it back. `value_nzd` is what it is worth, which is
    what decides the order a human works through the queue — a four-unit gap
    on tobacco outranks a forty-unit gap on bottled water.
    """

    case_id: str
    sku_id: str
    description: str
    period_end: str
    cause: Cause
    action: Action
    owner: str
    units: int
    value_nzd: float
    route: Route
    confidence: str
    basis: str          # which layer decided, and on what evidence

    @property
    def headline(self) -> str:
        verb = self.action.value.replace("_", " ")
        return f"{verb}: {self.units:+d} units of {self.sku_id} ({self.description})"


def _route(cause: Cause, value: float, from_rules: bool) -> Route:
    """Decide who, if anyone, has to look at this.

    Shrinkage always reaches a person even when the evidence is strong: the
    correction is small but the finding is that stock is being stolen, and
    that is not a stock-ledger event, it is a security one.
    """
    if cause is Cause.SHRINKAGE:
        return Route.ESCALATE
    if not from_rules:
        return Route.REVIEW
    if value >= REVIEW_THRESHOLD_NZD:
        return Route.REVIEW
    return Route.AUTO


def build_correction(
    case: ReconciliationCase,
    cause: Cause,
    *,
    from_rules: bool,
    confidence: str,
    basis: str,
) -> Correction | None:
    """One correction, or None when there is nothing to post."""
    if cause is Cause.NONE or case.discrepancy == 0:
        return None

    sku = CATALOGUE_INDEX[case.sku_id]
    action = ACTION_FOR[cause]
    value = round(abs(case.discrepancy) * sku.unit_cost_nzd, 2)
    return Correction(
        case_id=case.case_id,
        sku_id=case.sku_id,
        description=sku.description,
        period_end=case.period_end.isoformat(),
        cause=cause,
        action=action,
        owner=OWNER_FOR[action],
        units=case.discrepancy,
        value_nzd=value,
        route=_route(cause, value, from_rules),
        confidence=confidence,
        basis=basis,
    )


def build_queue(
    result: IngestResult,
    findings: dict[str, Finding],
    verdicts: dict[str, Verdict] | None = None,
) -> list[Correction]:
    """Every correction the run produced, worst money first.

    Cases the judgement layer never saw are skipped rather than guessed at.
    An unexplained discrepancy with no verdict is not a correction; it is an
    open item, and pretending otherwise would post something nobody decided.
    """
    verdicts = verdicts or {}
    corrections: list[Correction] = []

    for case in result.cases:
        finding = findings[case.case_id]
        if finding.resolved:
            correction = build_correction(
                case, finding.cause,
                from_rules=True,
                confidence="rule",
                basis=finding.explanation,
            )
        else:
            verdict = verdicts.get(case.case_id)
            if verdict is None:
                continue
            correction = build_correction(
                case, verdict.cause,
                from_rules=False,
                confidence=verdict.confidence,
                basis=verdict.rationale,
            )
        if correction is not None:
            corrections.append(correction)

    corrections.sort(key=lambda c: (-c.value_nzd, c.case_id))
    return corrections


def summarise(queue: list[Correction]) -> dict:
    totals: dict = {
        "corrections": len(queue),
        "value_nzd": round(sum(c.value_nzd for c in queue), 2),
        "by_route": {},
        "by_owner": {},
    }
    for correction in queue:
        route = totals["by_route"].setdefault(
            correction.route.value, {"count": 0, "value_nzd": 0.0})
        route["count"] += 1
        route["value_nzd"] = round(route["value_nzd"] + correction.value_nzd, 2)
        owner = totals["by_owner"].setdefault(correction.owner, 0)
        totals["by_owner"][correction.owner] = owner + 1
    return totals


def render(queue: list[Correction], summary: dict) -> str:
    """The queue as a person would read it, worst money first."""
    auto = summary["by_route"].get("auto", {"count": 0, "value_nzd": 0.0})
    lines = [
        "# Review queue",
        "",
        f"{summary['corrections']} corrections, "
        f"NZ${summary['value_nzd']:,.2f} at stake.",
        "",
        f"**{auto['count']} post automatically** "
        f"(NZ${auto['value_nzd']:,.2f}) — rule-certain and under the "
        f"NZ${REVIEW_THRESHOLD_NZD:,.0f} review threshold. Nobody has to open "
        "them.",
        "",
        "| Route | Corrections | Value |",
        "|---|---:|---:|",
    ]
    # Every route, including the empty ones — a reader should be able to see
    # that escalation exists and simply did not fire this week.
    for route in ("escalate", "review", "auto"):
        entry = summary["by_route"].get(route, {"count": 0, "value_nzd": 0.0})
        lines.append(
            f"| `{route}` | {entry['count']} | NZ${entry['value_nzd']:,.2f} |")

    for route, heading, blurb in (
        (Route.ESCALATE, "Escalated",
         "Small corrections, but the finding is that stock is walking out. "
         "Loss prevention sees these whatever the value."),
        (Route.REVIEW, "Needs a decision",
         "Either the judgement layer decided it, or it is large enough that "
         "certainty alone should not be enough to post it."),
        (Route.AUTO, "Posting automatically",
         "Rule-certain, evidence reconciles exactly, under threshold. Listed "
         "for the audit trail, not for action."),
    ):
        rows = [c for c in queue if c.route is route]
        if not rows:
            continue
        lines += ["", f"## {heading} ({len(rows)})", "", blurb, ""]
        for c in rows:
            lines += [
                f"### {c.case_id} — NZ${c.value_nzd:,.2f}",
                "",
                f"- **Do:** {c.headline}",
                f"- **Owner:** {c.owner}",
                f"- **Cause:** `{c.cause.value}` (confidence: {c.confidence})",
                f"- **Week ending:** {c.period_end}",
                f"- **Because:** {c.basis}",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    import json
    from pathlib import Path

    from .agent import classify_residue
    from .generate import generate
    from .ingest import build_cases
    from .rules import classify

    root = Path(__file__).resolve().parents[2]
    raw = root / "data" / "raw"
    if not (raw / "stock_counts.csv").exists():
        generate(raw)

    result = build_cases(raw)
    findings = classify(result)
    verdicts = classify_residue(result, findings)
    queue = build_queue(result, findings, verdicts)
    summary = summarise(queue)

    print(f"corrections   : {summary['corrections']}")
    print(f"value at stake: NZ${summary['value_nzd']:,.2f}")
    for route, entry in sorted(summary["by_route"].items()):
        print(f"  {route:<9} {entry['count']:>3}  NZ${entry['value_nzd']:>9,.2f}")
    print("\nby owner:")
    for owner, count in sorted(summary["by_owner"].items(), key=lambda kv: -kv[1]):
        print(f"  {owner:<20}{count:>3}")

    out = root / "docs" / "sample-review-queue.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(queue, summary))
    (root / "data" / "review_queue.json").write_text(json.dumps(
        {"summary": summary, "corrections": [vars(c) | {
            "cause": c.cause.value, "action": c.action.value, "route": c.route.value,
        } for c in queue]}, indent=2, default=str))
    print(f"\nqueue written to {out.relative_to(root)}")
