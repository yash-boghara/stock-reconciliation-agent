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

# Share of deliveries that get a goods-received note booked against them.
# Deliberately not 1.0. A GRN is the only document that can prove a short
# delivery, and in a real store the receiving paperwork is the first thing
# to get skipped on a busy morning. A generator that files one every time
# would make short deliveries look fully detectable, and the rules layer
# would then be measured against a world that does not exist.
GRN_COVERAGE = 0.7

# Share of judgement-cause weeks where someone wrote a note about it. Staff
# notice most of what goes wrong and record about half of it.
NOTE_COVERAGE = 0.55

STAFF = ("J. Ruka", "priya s", "M Tanner", "Dave", "aroha", "S. Whitcombe")

# Notes are written the way people write them: no fixed vocabulary, the cause
# often implied rather than named. "Third week running the facing is short"
# says theft without using the word, and "wouldn't keep till Monday" says
# spoilage without saying expired. A keyword matcher can catch the blunt ones;
# the oblique ones are the point of having a reader at all.
NOTE_TEMPLATES: dict[Cause, tuple[str, ...]] = {
    Cause.UNLOGGED_WASTAGE: (
        "binned {n} {item}, past date",
        "chucked a tray of {item}, had turned",
        "{item} in the back was sweating, pulled it off the shelf",
        "had to pull {n} {item} — wouldn't keep till Monday",
        "chiller door left open overnight, {item} not right after",
        "dumped some {item}, smelled off",
        "{n} {item} damaged in the crate, not sellable",
    ),
    Cause.SHRINKAGE: (
        "{item} facing looks light again",
        "third week running we're down on {item}",
        "someone's helping themselves to the {item}",
        "{item} shelf keeps emptying faster than it sells",
        "front of shop {item} gone again, nothing rung up",
        "asked the team about the {item}, nobody knows",
        "{item} walking out the door, need to move it behind the counter",
    ),
    Cause.MISCOUNT: (
        "recount of {item} didn't match the first pass",
        "counted the {item} twice, got two numbers",
        "priya and I disagreed on the {item} count",
        "not confident on the {item} tally, was rushing",
        "{item} count done late, might be out",
        "lost my place counting the {item}",
    ),
    Cause.SHORT_DELIVERY: (
        "driver was light on the {item}, said Monday",
        "{item} order came up short, no paperwork for it",
        "checked the {item} off the truck, less than the docket",
        "short on {item} again from this supplier",
    ),
}

# Notes about anything else. Staff write about the whole shop, so a note
# existing is not evidence on its own.
NOISE_NOTES = (
    "cleaned down the chiller",
    "new planogram for the drinks bay",
    "price ticket wrong on {item}, fixed",
    "trolley wheel broken, put it out back",
    "{item} promo ends Sunday",
    "eftpos terminal slow all morning",
    "shelf edge labels reprinted for aisle 3",
)


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

def _pick_cause(rng: random.Random, sku: Sku, shrink_prone: set[str]) -> Cause:
    """Draw a cause, respecting where each one actually happens.

    The three judgement causes were previously drawn uniformly across the
    catalogue, which made them separable only by magnitude — and their
    magnitude ranges overlap almost entirely. A classifier given every
    available feature topped out barely above always-guess-the-majority, and
    never predicted shrinkage at all, because shrinkage was never the most
    likely cause at any magnitude.

    That was a property of the generator, not of the problem. In a real store
    spoilage lands on short-dated stock and theft lands on small valuable
    lines, repeatedly, on the same SKUs. Planting them that way is what makes
    context worth consulting — and what leaves miscount as the honestly hard
    class, since a bad count respects no pattern at all.
    """
    causes = list(CAUSE_WEIGHTS)
    weights = []
    for cause in causes:
        w = CAUSE_WEIGHTS[cause]
        if cause is Cause.UNLOGGED_WASTAGE:
            w *= 6.0 if sku.perishable else 0.25
        elif cause is Cause.SHRINKAGE:
            w *= 9.0 if sku.sku_id in shrink_prone else 0.05
        weights.append(w)
    return rng.choices(causes, weights=weights, k=1)[0]


def generate(out_dir: Path, seed: int = SEED) -> dict[str, int]:
    rng = random.Random(seed)
    # Whether a GRN was filed is drawn from its own stream so it stays
    # independent of what went wrong that week. The shared stream measures
    # clean today (69.5% over 20 seeds, against a configured 70%), but each
    # cause consumes a different number of draws before this point, so the
    # independence is incidental rather than guaranteed — adding a cause
    # that draws differently could couple coverage to cause without anyone
    # noticing. Recall on short_delivery is bounded by this rate, which
    # makes it exactly the wrong quantity to leave resting on coincidence.
    grn_rng = random.Random(seed ^ 0x9E3779B9)
    # Whether anyone wrote a note is its own stream too, for the same reason
    # GRN coverage is: note coverage must not depend on what went wrong.
    note_rng = random.Random(seed ^ 0x85EBCA6B)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Transaction ids must be unique by construction. Drawn independently they
    # collide about once every few datasets (roughly 900 rows over 9e7 values),
    # and a collision plants a fault the taxonomy has no label for — so the
    # eval set would contain a discrepancy that is neither clean nor any
    # planted cause.
    issued_txn_ids: set[str] = set()

    def next_txn_id() -> str:
        while True:
            candidate = f"T{rng.randint(10**7, 10**8 - 1)}"
            if candidate not in issued_txn_ids:
                issued_txn_ids.add(candidate)
                return candidate

    pos_rows: list[dict] = []
    delivery_rows: list[dict] = []
    grn_rows: list[dict] = []
    note_rows: list[dict] = []
    count_rows: list[dict] = []
    labels: list[Label] = []

    # Opening stock per SKU, carried forward week to week.
    on_hand = {s.sku_id: rng.randint(40, 220) for s in CATALOGUE}

    # A store's theft problem sits on particular lines and stays there — the
    # same tobacco and battery facings walk out week after week. Fixing the
    # set per run is what makes a SKU's own history worth retrieving, rather
    # than every high-value line being equally suspect forever.
    shrink_prone = set(rng.sample(
        [s.sku_id for s in CATALOGUE if s.high_value],
        k=max(2, len([s for s in CATALOGUE if s.high_value]) // 2),
    ))
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

            cases_in = rng.randint(1, 5)
            delivered_actual = cases_in * sku.case_size

            carryover = pending_carryover.pop(sku.sku_id, 0)
            cause = (Cause.LATE_CARRYOVER if carryover
                     else _pick_cause(rng, sku, shrink_prone))
            magnitude = -carryover
            note = (
                f"{carryover} units invoiced this period were received and"
                " counted in the previous one"
                if carryover else ""
            )

            # Values as they will be RECORDED (which is not always reality).
            delivered_recorded = delivered_actual
            delivery_date = p_start + timedelta(days=rng.randint(0, 5))
            defer_delivery = False
            plant_duplicate = False

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
                # Resolved during POS emission below: a double-scan is a
                # real second transaction, not an inflated weekly total.
                # Its size is whichever line the till rang twice, so the
                # magnitude is not known until that line is chosen.
                plant_duplicate = True

            elif cause is Cause.SHORT_DELIVERY:
                short = rng.randint(2, max(3, sku.case_size // 2))
                delivered_actual -= short               # invoice says more than arrived
                magnitude = -short
                note = f"invoiced {delivered_recorded}, {short} units not received"

            elif cause is Cause.MISCOUNT:
                magnitude = rng.choice([-1, 1]) * rng.randint(1, 6)
                note = "stocktake error"

            elif cause is Cause.UNLOGGED_WASTAGE:
                # Spoilage scales with how much stock passed through the
                # chiller that week, but only loosely — the ranges still
                # overlap miscount and shrinkage, so magnitude alone stays
                # ambiguous and the SKU's own profile has to do the work.
                handled = opening + delivered_actual
                magnitude = -rng.randint(2, max(4, min(12, handled // 25)))
                note = "damaged or expired stock discarded without a wastage entry"

            elif cause is Cause.SHRINKAGE:
                magnitude = -rng.randint(1, 5)
                note = "unexplained loss on a high-value line"

            # Sales are drawn last, against what will actually be on the
            # shelf once the planted fault has taken its bite. Drawing them
            # first lets a week sell more units than ever existed; the old
            # code then clamped the close at zero, which quietly turned a
            # clean week into a one-unit discrepancy and made a case
            # labelled `none` look broken to every layer downstream.
            # Only faults that remove physical stock reduce what can be
            # sold. A short delivery already shrank delivered_actual, and a
            # late carryover is a paperwork effect that never touched the
            # shelf — counting either here would deduct it twice.
            shrink = magnitude if cause in {
                Cause.MISCOUNT, Cause.UNLOGGED_WASTAGE, Cause.SHRINKAGE
            } and magnitude < 0 else 0
            available = opening + delivered_actual + shrink
            ceiling = max(0, min(95, available))
            sold = rng.randint(min(15, ceiling), ceiling)
            sold_recorded = sold

            closing = opening + delivered_actual - sold
            if cause in {Cause.MISCOUNT, Cause.UNLOGGED_WASTAGE, Cause.SHRINKAGE}:
                closing += magnitude
            if closing < 0:
                # Guard, not a clamp. A negative close means the planted
                # arithmetic contradicts itself, and silently flooring it
                # would push a discrepancy into a case whose label says
                # there is none — corrupting the evaluation set rather
                # than the run that produced it.
                raise AssertionError(
                    f"{case_id}: negative close ({closing}) from opening={opening}, "
                    f"delivered={delivered_actual}, sold={sold}, cause={cause.value}"
                )

            # --- emit POS rows -------------------------------------------------
            remaining = sold_recorded
            emitted: list[tuple[dict, int]] = []
            while remaining > 0:
                qty = min(remaining, rng.randint(3, 14))
                remaining -= qty
                sale_date = p_start + timedelta(days=rng.randint(0, 6))
                seconds = rng.randint(8 * 3600, 20 * 3600)  # trading hours
                row = {
                    "transaction_id": next_txn_id(),
                    "sale_date": messy_date(sale_date, rng),
                    "sale_time": f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}",
                    "sku": messy_sku(sku.sku_id, rng),
                    "qty": messy_qty(qty, rng),
                    "unit_price": messy_money(sku.unit_cost_nzd * 1.35, rng),
                    "till": rng.choice(["1", "2", "3", ""]),
                }
                pos_rows.append(row)
                emitted.append((row, qty))
                if rng.random() < 0.015:          # bad export duplicates a row
                    pos_rows.append(dict(row))

            if plant_duplicate and emitted:
                # A genuine double-scan: the operator rings the same line
                # twice, so the till writes a *separate* transaction that
                # agrees on SKU, date and quantity. That pair is the only
                # honest signature. Note the contrast with the bad-export
                # duplicate above, which reuses the transaction id and is
                # noise the ingest layer is right to drop.
                twin, qty = emitted[rng.randrange(len(emitted))]
                rescan = dict(twin)
                rescan["transaction_id"] = next_txn_id()
                h, m, sec = (int(x) for x in twin["sale_time"].split(":"))
                moment = h * 3600 + m * 60 + sec + rng.randint(4, 40)
                rescan["sale_time"] = (
                    f"{moment // 3600:02d}:{moment // 60 % 60:02d}:{moment % 60:02d}")
                rescan["sku"] = messy_sku(sku.sku_id, rng)
                pos_rows.append(rescan)
                sold_recorded += qty
                magnitude = qty
                note = f"{qty} units rung twice at the till on the same day"

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
                docket_no = f"D{rng.randint(10**6, 10**7 - 1)}"
                delivery_rows.append({
                    "docket_no": docket_no,
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

                # The receiving note records what was physically counted off
                # the truck, dated when the truck arrived — which is not the
                # invoice date when the paperwork runs late. Where invoice and
                # GRN disagree, the GRN is the one that touched the stock.
                if grn_rng.random() < GRN_COVERAGE:
                    grn_rows.append({
                        "grn_no": f"G{grn_rng.randint(10**5, 10**6 - 1)}",
                        "docket_no": docket_no,
                        "received_date": messy_date(delivery_date, grn_rng),
                        "sku": messy_sku(sku.sku_id, grn_rng),
                        "qty_counted": messy_qty(delivered_actual, grn_rng),
                        "checked_by": grn_rng.choice(
                            ["J. Ruka", "priya s", "M Tanner", ""]),
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

            # --- emit a staff note -----------------------------------------
            # Written by whoever was on that day, about the SKU, inside the
            # period. It records what a person noticed, which is not always
            # what the arithmetic shows.
            item = sku.description.split(" ")[0].lower()
            if (cause in NOTE_TEMPLATES
                    and note_rng.random() < NOTE_COVERAGE):
                template = note_rng.choice(NOTE_TEMPLATES[cause])
                note_rows.append({
                    "note_id": f"N{note_rng.randint(10**5, 10**6 - 1)}",
                    "note_date": messy_date(
                        p_start + timedelta(days=note_rng.randint(0, 6)), note_rng),
                    "sku": messy_sku(sku.sku_id, note_rng),
                    "author": note_rng.choice(STAFF),
                    "text": template.format(n=abs(magnitude) or 1, item=item),
                })
            elif note_rng.random() < 0.06:
                note_rows.append({
                    "note_id": f"N{note_rng.randint(10**5, 10**6 - 1)}",
                    "note_date": messy_date(
                        p_start + timedelta(days=note_rng.randint(0, 6)), note_rng),
                    "sku": messy_sku(sku.sku_id, note_rng),
                    "author": note_rng.choice(STAFF),
                    "text": note_rng.choice(NOISE_NOTES).format(item=item),
                })

            labels.append(Label(case_id, cause, magnitude, note))
            on_hand[sku.sku_id] = closing

    _write(out_dir / "pos_sales.csv", pos_rows)
    _write(out_dir / "deliveries.csv", delivery_rows)
    _write(out_dir / "goods_received.csv", grn_rows)
    _write(out_dir / "staff_notes.csv", note_rows)
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
        "grn_rows": len(grn_rows),
        "note_rows": len(note_rows),
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
