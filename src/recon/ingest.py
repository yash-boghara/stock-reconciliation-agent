"""Normalise messy exports into reconciliation cases.

Every field arriving from a real POS or supplier system is untrusted:
SKU spellings drift, dates come in three formats, quantities arrive as
floats or padded strings, and a bad export duplicates rows outright.

This module is deliberately strict. Anything it cannot parse is rejected
into a quarantine list rather than silently coerced — a row guessed wrong
here becomes a phantom discrepancy three layers up, and the agent then
spends tokens explaining a bug.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import CATALOGUE_INDEX, ReconciliationCase

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%d/%m/%y")
SKU_PATTERN = re.compile(r"^0?([A-Z]{3})[\s-]?(\d{4})$")

# How far after a count a docket can land and still describe stock that was
# physically on the shelf when that count happened.
LATE_DOCKET_WINDOW = timedelta(days=3)


@dataclass
class Rejection:
    source: str
    row: dict
    reason: str


@dataclass
class CaseEvidence:
    """The rows behind one case, kept so downstream layers can inspect the
    *shape* of a discrepancy and not just its size.

    `late_deliveries` holds dockets dated after this period's count — those
    rows belong to the next period by the attribution rule, but they are the
    evidence that explains a positive discrepancy here. A rules layer that
    only sees aggregates cannot tell a late invoice from a miscount, because
    numerically they are identical.
    """

    sales: list[dict] = field(default_factory=list)
    deliveries: list[dict] = field(default_factory=list)
    late_deliveries: list[dict] = field(default_factory=list)
    goods_received: dict[str, dict] = field(default_factory=dict)  # by docket_no


@dataclass
class IngestResult:
    cases: list[ReconciliationCase] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    duplicates_dropped: int = 0
    evidence: dict[str, CaseEvidence] = field(default_factory=dict)

    @property
    def rejection_rate(self) -> float:
        total = len(self.cases) + len(self.rejections)
        return len(self.rejections) / total if total else 0.0


# ----------------------------------------------------------------------
# Field-level normalisation
# ----------------------------------------------------------------------

def normalise_sku(raw: str) -> str:
    """Fold every observed spelling back to canonical AAA-0000 form.

    Raises ValueError rather than guessing — an unrecognised SKU that gets
    mapped to a neighbour silently corrupts two cases, not one.
    """
    if raw is None:
        raise ValueError("missing sku")
    candidate = raw.strip().upper().replace("_", "-")
    m = SKU_PATTERN.match(candidate)
    if not m:
        raise ValueError(f"unrecognised sku format: {raw!r}")
    canonical = f"{m.group(1)}-{m.group(2)}"
    if canonical not in CATALOGUE_INDEX:
        raise ValueError(f"sku not in catalogue: {canonical}")
    return canonical


def normalise_date(raw: str) -> date:
    if raw is None or not raw.strip():
        raise ValueError("missing date")
    text = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {raw!r}")


def normalise_qty(raw: str) -> int:
    """Accept '12', '12.0', ' 12 '. Reject '12.4' — a fractional unit count
    means the upstream export is wrong and should be seen, not rounded."""
    if raw is None or not str(raw).strip():
        raise ValueError("missing quantity")
    text = str(raw).strip()
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"non-numeric quantity: {raw!r}") from None
    if abs(value - round(value)) > 1e-9:
        raise ValueError(f"fractional unit quantity: {raw!r}")
    return int(round(value))


def normalise_time(raw: str | None) -> int | None:
    """Seconds past midnight, or None when the till did not record one.

    None is not an error — plenty of exports omit it — but it does mean any
    check that depends on two sales being seconds apart has to decline.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parts = [int(p) for p in text.split(":")]
    except ValueError:
        return None
    if len(parts) != 3:
        return None
    hours, minutes, seconds = parts
    return hours * 3600 + minutes * 60 + seconds


def normalise_uom(raw: str | None) -> str:
    """Blank unit-of-measure is the norm, not an error — most systems omit
    it and mean eaches. CASE is the meaningful signal."""
    text = (raw or "").strip().upper()
    if text in {"CASE", "CTN", "CS"}:
        return "CASE"
    return "EACH"


# ----------------------------------------------------------------------
# File loading
# ----------------------------------------------------------------------

def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_pos(path: Path, result: IngestResult) -> list[dict]:
    """Sales, deduplicated by transaction id.

    Note the distinction that matters: an identical transaction_id appearing
    twice is an export artifact and is dropped. A genuine till double-scan
    produces a *separate* transaction id and is kept — that is a real
    discrepancy the system is supposed to catch, not noise to clean away.
    """
    rows, seen = [], set()
    for raw in _read(path):
        # Match on the whole row, not the transaction id alone. A faulty export
        # repeats a row outright, so every field agrees. Two rows sharing an id
        # while disagreeing on SKU, date or quantity are two real sales whose
        # ids collided — dropping the second silently deletes revenue and
        # invents a shortfall three layers up, in a week that actually
        # balanced. Keep both and let the discrepancy stay honest.
        fingerprint = tuple(sorted(raw.items()))
        if fingerprint in seen:
            result.duplicates_dropped += 1
            continue
        seen.add(fingerprint)
        try:
            rows.append({
                "transaction_id": (raw.get("transaction_id") or "").strip(),
                "sale_date": normalise_date(raw["sale_date"]),
                "sku_id": normalise_sku(raw["sku"]),
                "qty": normalise_qty(raw["qty"]),
                "till": (raw.get("till") or "").strip(),
                "at": normalise_time(raw.get("sale_time")),
            })
        except (ValueError, KeyError) as exc:
            result.rejections.append(Rejection("pos_sales", raw, str(exc)))
    return rows


def load_deliveries(path: Path, result: IngestResult) -> list[dict]:
    rows = []
    for raw in _read(path):
        try:
            sku_id = normalise_sku(raw["sku"])
            rows.append({
                "docket_no": (raw.get("docket_no") or "").strip(),
                "delivery_date": normalise_date(raw["delivery_date"]),
                "supplier": (raw.get("supplier") or "").strip().title(),
                "sku_id": sku_id,
                "qty_received": normalise_qty(raw["qty_received"]),
                "uom": normalise_uom(raw.get("uom")),
            })
        except (ValueError, KeyError) as exc:
            result.rejections.append(Rejection("deliveries", raw, str(exc)))
    return rows


def load_goods_received(path: Path, result: IngestResult) -> list[dict]:
    """Receiving notes, keyed back to the delivery docket they check.

    Absent entirely on a store that never files them, so a missing file is
    not an error — it is a store whose short deliveries are unprovable.
    """
    if not path.exists():
        return []
    rows = []
    for raw in _read(path):
        try:
            rows.append({
                "grn_no": (raw.get("grn_no") or "").strip(),
                "docket_no": (raw.get("docket_no") or "").strip(),
                "received_date": normalise_date(raw["received_date"]),
                "sku_id": normalise_sku(raw["sku"]),
                "qty_counted": normalise_qty(raw["qty_counted"]),
            })
        except (ValueError, KeyError) as exc:
            result.rejections.append(Rejection("goods_received", raw, str(exc)))
    return rows


def load_counts(path: Path, result: IngestResult) -> list[dict]:
    rows = []
    for raw in _read(path):
        try:
            rows.append({
                "count_id": (raw.get("count_id") or "").strip(),
                "count_date": normalise_date(raw["count_date"]),
                "sku_id": normalise_sku(raw["sku"]),
                "opening_qty": normalise_qty(raw["opening_qty"]),
                "closing_qty": normalise_qty(raw["closing_qty"]),
            })
        except (ValueError, KeyError) as exc:
            result.rejections.append(Rejection("stock_counts", raw, str(exc)))
    return rows


# ----------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------

def build_cases(raw_dir: Path) -> IngestResult:
    """Assemble one ReconciliationCase per stocktake row.

    Deliveries and sales are attributed to the period whose window contains
    their recorded date. That is intentionally literal: a delivery whose
    paperwork is dated after the count belongs to the next period, which is
    exactly how a late-delivery discrepancy comes into existence. Fixing it
    here would hide the very thing the system exists to find.
    """
    result = IngestResult()

    pos = load_pos(raw_dir / "pos_sales.csv", result)
    deliveries = load_deliveries(raw_dir / "deliveries.csv", result)
    grns = load_goods_received(raw_dir / "goods_received.csv", result)
    counts = load_counts(raw_dir / "stock_counts.csv", result)

    grn_by_docket = {g["docket_no"]: g for g in grns if g["docket_no"]}

    # Bucket by SKU once. Scanning every row per case is O(cases x rows),
    # and the rules layer walks this same data again for each check.
    sales_by_sku: dict[str, list[dict]] = {}
    for p in pos:
        sales_by_sku.setdefault(p["sku_id"], []).append(p)
    deliveries_by_sku: dict[str, list[dict]] = {}
    for d in deliveries:
        deliveries_by_sku.setdefault(d["sku_id"], []).append(d)

    for c in sorted(counts, key=lambda r: (r["sku_id"], r["count_date"])):
        period_end = c["count_date"]
        period_start = period_end - timedelta(days=6)
        sku_id = c["sku_id"]

        evidence = CaseEvidence()
        for p in sales_by_sku.get(sku_id, ()):
            if period_start <= p["sale_date"] <= period_end:
                evidence.sales.append(p)
        for d in deliveries_by_sku.get(sku_id, ()):
            if period_start <= d["delivery_date"] <= period_end:
                evidence.deliveries.append(d)
            elif period_end < d["delivery_date"] <= period_end + LATE_DOCKET_WINDOW:
                evidence.late_deliveries.append(d)
            else:
                continue
            grn = grn_by_docket.get(d["docket_no"])
            if grn is not None:
                evidence.goods_received[d["docket_no"]] = grn

        result.cases.append(ReconciliationCase(
            case_id=c["count_id"],
            sku_id=sku_id,
            period_start=period_start,
            period_end=period_end,
            opening_count=c["opening_qty"],
            closing_count=c["closing_qty"],
            delivered_units=sum(d["qty_received"] for d in evidence.deliveries),
            sold_units=sum(p["qty"] for p in evidence.sales),
        ))
        result.evidence[c["count_id"]] = evidence

    return result


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    res = build_cases(root / "data" / "raw")
    flagged = [c for c in res.cases if c.discrepancy != 0]
    print(f"cases assembled     : {len(res.cases)}")
    print(f"duplicate rows dropped: {res.duplicates_dropped}")
    print(f"rejected rows       : {len(res.rejections)}")
    print(f"cases with a discrepancy: {len(flagged)}")
    for r in res.rejections[:5]:
        print(f"  rejected [{r.source}] {r.reason}")
