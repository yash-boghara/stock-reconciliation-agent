"""Generate messy retail data with planted, known discrepancies.

Emits four files into data/raw:

    pos_sales.csv     messy POS export
    deliveries.csv    messy supplier delivery records
    stock_counts.csv  messy weekly stocktake
    labels.csv        ground truth — NEVER read by the pipeline

The mess is deliberate and mirrors what real exports look like: SKU
formats drift between systems, dates come in NZ and ISO flavours, fields
go missing, rows get duplicated by a bad export.

Deterministic under a fixed seed so evaluation runs are comparable.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from .models import CATALOGUE, Cause, Label, Sku

SEED = 20260814
PERIOD_WEEKS = 6
START = date(2026, 6, 1)  # a Monday


# How often each cause is planted. NONE dominates because most weeks in a
# real store reconcile cleanly, and an eval set where every case is broken
# teaches the system the wrong prior.
CAUSE_WEIGHTS: dict[Cause, float] = {
    Cause.NONE: 0.46,
    Cause.MISCOUNT: 0.13,
    Cause.UNLOGGED_WASTAGE: 0.11,
    Cause.SHORT_DELIVERY: 0.09,
    Cause.DUPLICATE_SCAN: 0.07,
    Cause.UNIT_MISMATCH: 0.06,
    Cause.LATE_DELIVERY: 0.05,
    Cause.SHRINKAGE: 0.03,
}


# ----------------------------------------------------------------------
# Mess injection
# ----------------------------------------------------------------------

def messy_sku(sku_id: str, rng: random.Random) -> str:
    """Same SKU, as five different systems would spell it."""
    style = rng.random()
    if style < 0.55:
        return sku_id
    if style < 0.70:
        return sku_id.replace("-", "").lower()
    if style < 0.82:
        return f"  {sku_id.replace('-', ' ')} "
    if style < 0.92:
        return sku_id.lower()
    return f"0{sku_id}"


def messy_date(d: date, rng: random.Random) -> str:
    style = rng.random()
    if style < 0.5:
        return d.isoformat()
    if style < 0.85:
        return d.strftime("%d/%m/%Y")     # NZ convention
    return d.strftime("%d-%b-%Y")


def messy_qty(q: int, rng: random.Random) -> str:
    r = rng.random()
    if r < 0.80:
        return str(q)
    if r < 0.94:
        return f"{q}.0"
    return f" {q} "


def messy_money(v: float, rng: random.Random) -> str:
    r = rng.random()
    if r < 0.6:
        return f"{v:.2f}"
    if r < 0.85:
        return f"${v:,.2f}"
    return f"{v:.4f}"


# ----------------------------------------------------------------------
# Generation
# ----------------------------------------------------------------------

def _pick_cause(rng: random.Random) -> Cause:
    causes = list(CAUSE_WEIGHTS)
    weights = [CAUSE_WEIGHTS[c] for c in causes]
    return rng.choices(causes, weights=weights, k=1)[0]


def generate(out_dir: Path, seed: int = SEED) -> dict[str, int]:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    pos_rows: list[dict] = []
    delivery_rows: list[dict] = []
    count_rows: list[dict] = []
    labels: list[Label] = []

    # Opening stock per SKU, carried forward week to week.
    on_hand = {s.sku_id: rng.randint(40, 220) for s in CATALOGUE}
    # SKUs whose late paperwork lands in the following period. One planted
    # fault produces a discrepancy in two consecutive weeks with opposite
    # signs; both halves need a label or the eval set contradicts itself.
    pending_carryover: dict[str, int] = {}

    for week in range(PERIOD_WEEKS):
        p_start = START + timedelta(days=7 * week)
        p_end = p_start + timedelta(days=6)

        for sku in CATALOGUE:
            case_id = f"{sku.sku_id}-W{week + 1:02d}"
            opening = on_hand[sku.sku_id]

            # Baseline trade for the week.
            sold = rng.randint(15, min(95, max(20, opening - 5)))
            cases_in = rng.randint(1, 5)
            delivered_actual = cases_in * sku.case_size

            carryover = pending_carryover.pop(sku.sku_id, 0)
            cause = Cause.LATE_CARRYOVER if carryover else _pick_cause(rng)
            magnitude = -carryover
            note = (
                f"{carryover} units invoiced this period were received and"
                " counted in the previous one"
                if carryover else ""
            )

            # Values as they will be RECORDED (which is not always reality).
            delivered_recorded = delivered_actual
            sold_recorded = sold
            delivery_date = p_start + timedelta(days=rng.randint(0, 5))
            defer_delivery = False

            if cause is Cause.UNIT_MISMATCH:
                delivered_recorded = cases_in           # cases logged as eaches
                magnitude = delivered_actual - cases_in
                note = f"{cases_in} cases of {sku.case_size} logged as {cases_in} units"

            elif cause is Cause.LATE_DELIVERY:
                defer_delivery = True                   # paperwork lands next week
                delivered_recorded = 0
                magnitude = delivered_actual
                pending_carryover[sku.sku_id] = delivered_actual
                note = "stock received before count, invoice dated after period end"

            elif cause is Cause.DUPLICATE_SCAN:
                dup = rng.randint(3, 12)
                sold_recorded = sold + dup              # POS double-counted
                magnitude = dup
                note = f"{dup} units scanned twice at POS"

            elif cause is Cause.SHORT_DELIVERY:
                short = rng.randint(2, max(3, sku.case_size // 2))
                delivered_actual -= short               # invoice says more than arrived
                magnitude = -short
                note = f"invoiced {delivered_recorded}, {short} units not received"

            elif cause is Cause.MISCOUNT:
                magnitude = rng.choice([-1, 1]) * rng.randint(1, 6)
                note = "stocktake error"

            elif cause is Cause.UNLOGGED_WASTAGE:
                magnitude = -rng.randint(2, 9)
                note = "damaged or expired stock discarded without a wastage entry"

            elif cause is Cause.SHRINKAGE:
                magnitude = -rng.randint(1, 5)
                note = "unexplained loss on a high-value line"

            closing = opening + delivered_actual - sold
            if cause in {Cause.MISCOUNT, Cause.UNLOGGED_WASTAGE, Cause.SHRINKAGE}:
                closing += magnitude
            closing = max(closing, 0)

            # --- emit POS rows -------------------------------------------------
            remaining = sold_recorded
            while remaining > 0:
                qty = min(remaining, rng.randint(3, 14))
                remaining -= qty
                sale_date = p_start + timedelta(days=rng.randint(0, 6))
                row = {
                    "transaction_id": f"T{rng.randint(10**7, 10**8 - 1)}",
                    "sale_date": messy_date(sale_date, rng),
                    "sku": messy_sku(sku.sku_id, rng),
                    "qty": messy_qty(qty, rng),
                    "unit_price": messy_money(sku.unit_cost_nzd * 1.35, rng),
                    "till": rng.choice(["1", "2", "3", ""]),
                }
                pos_rows.append(row)
                if rng.random() < 0.015:          # bad export duplicates a row
                    pos_rows.append(dict(row))

            # --- emit delivery row ---------------------------------------------
            if delivered_recorded > 0 or defer_delivery:
                recorded_date = (
                    p_end + timedelta(days=rng.randint(1, 3))
                    if defer_delivery
                    else delivery_date
                )
                qty_field = (
                    delivered_actual if defer_delivery else delivered_recorded
                )
                delivery_rows.append({
                    "docket_no": f"D{rng.randint(10**6, 10**7 - 1)}",
                    "delivery_date": messy_date(recorded_date, rng),
                    "supplier": rng.choice([
                        sku.supplier, sku.supplier.upper(), f" {sku.supplier}"
                    ]),
                    "sku": messy_sku(sku.sku_id, rng),
                    "qty_received": messy_qty(qty_field, rng),
                    "uom": "CASE" if cause is Cause.UNIT_MISMATCH else rng.choice(
                        ["EACH", "EA", ""]
                    ),
                    "unit_cost": messy_money(sku.unit_cost_nzd, rng),
                })

            # --- emit stock count row -------------------------------------------
            count_rows.append({
                "count_id": case_id,
                "count_date": messy_date(p_end, rng),
                "sku": messy_sku(sku.sku_id, rng),
                "opening_qty": messy_qty(opening, rng),
                "closing_qty": messy_qty(closing, rng),
                "counted_by": rng.choice(["J. Ruka", "priya s", "M Tanner", ""]),
            })

            labels.append(Label(case_id, cause, magnitude, note))
            on_hand[sku.sku_id] = closing

    _write(out_dir / "pos_sales.csv", pos_rows)
    _write(out_dir / "deliveries.csv", delivery_rows)
    _write(out_dir / "stock_counts.csv", count_rows)
    _write(
        out_dir / "labels.csv",
        [
            {
                "case_id": lb.case_id,
                "cause": lb.cause.value,
                "magnitude": lb.magnitude,
                "note": lb.note,
            }
            for lb in labels
        ],
    )

    return {
        "pos_rows": len(pos_rows),
        "delivery_rows": len(delivery_rows),
        "count_rows": len(count_rows),
        "cases": len(labels),
    }


def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    stats = generate(Path(__file__).resolve().parents[2] / "data" / "raw")
    for k, v in stats.items():
        print(f"{k}: {v}")
