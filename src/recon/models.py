"""Core domain types for stock reconciliation.

The reconciliation identity we test against, per SKU per period:

    expected_closing = opening_count + delivered - sold
    discrepancy      = actual_closing - expected_closing

A non-zero discrepancy has a cause. Naming that cause correctly is the
task the system is evaluated on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Cause(str, Enum):
    """Taxonomy of discrepancy causes.

    Split deliberately into two groups. RULE_RESOLVABLE causes have a
    structural signature a deterministic check can find. JUDGEMENT causes
    all look alike numerically (small negative) and can only be separated
    using context: item value, history for that SKU, wastage patterns.

    That boundary is the point of the project. Rules should handle the
    first group; the agent only earns its place on the second.
    """

    NONE = "none"

    # Structurally detectable
    UNIT_MISMATCH = "unit_mismatch"          # cases logged as eaches
    LATE_DELIVERY = "late_delivery"          # stock arrived, paperwork didn't
    LATE_CARRYOVER = "late_carryover"        # last period's late paperwork, landing now
    DUPLICATE_SCAN = "duplicate_scan"        # POS counted a sale twice
    SHORT_DELIVERY = "short_delivery"        # supplier sent fewer than invoiced

    # Numerically ambiguous — require judgement
    MISCOUNT = "miscount"                    # stocktake itself is wrong
    UNLOGGED_WASTAGE = "unlogged_wastage"    # damaged/expired, never recorded
    SHRINKAGE = "shrinkage"                  # theft

    @property
    def rule_resolvable(self) -> bool:
        return self in {
            Cause.UNIT_MISMATCH,
            Cause.LATE_DELIVERY,
            Cause.LATE_CARRYOVER,
            Cause.DUPLICATE_SCAN,
            Cause.SHORT_DELIVERY,
        }


@dataclass(frozen=True)
class Sku:
    sku_id: str          # canonical form, e.g. "BEV-0142"
    description: str
    supplier: str
    case_size: int       # units per case as shipped
    unit_cost_nzd: float
    high_value: bool     # theft-prone: tobacco, energy drinks, batteries
    perishable: bool     # short shelf life, so spoilage is a live risk


@dataclass(frozen=True)
class ReconciliationCase:
    """One SKU over one period — the unit the system reasons about."""

    case_id: str
    sku_id: str
    period_start: date
    period_end: date
    opening_count: int
    closing_count: int
    delivered_units: int   # as recorded in the delivery paperwork
    sold_units: int        # as recorded by the POS

    @property
    def expected_closing(self) -> int:
        return self.opening_count + self.delivered_units - self.sold_units

    @property
    def discrepancy(self) -> int:
        return self.closing_count - self.expected_closing


@dataclass(frozen=True)
class Label:
    """Ground truth for one case. Written to a separate file that the
    reconciliation pipeline never reads — it exists only for evaluation."""

    case_id: str
    cause: Cause
    magnitude: int
    note: str


# high_value and perishable are the two properties that separate the causes
# rules cannot reach. Theft concentrates on small, valuable, easily pocketed
# lines; spoilage concentrates on short-dated ones. A miscount respects
# neither — which is what makes it the genuinely hard class.
CATALOGUE: list[Sku] = [
    Sku("BEV-0142", "Energy drink 250ml", "Coastline Beverages", 24, 2.10, True, False),
    Sku("BEV-0143", "Energy drink 500ml", "Coastline Beverages", 12, 3.40, True, False),
    Sku("BEV-0210", "Bottled water 750ml", "Coastline Beverages", 12, 0.95, False, False),
    Sku("BEV-0288", "Cola 1.5L", "Coastline Beverages", 8, 2.60, False, False),
    Sku("SNK-1001", "Potato chips 150g", "Harbour Snack Co", 18, 1.80, False, False),
    Sku("SNK-1044", "Chocolate bar 50g", "Harbour Snack Co", 36, 1.20, True, False),
    Sku("SNK-1077", "Mixed nuts 200g", "Harbour Snack Co", 12, 4.50, False, False),
    Sku("SNK-1090", "Biscuits 250g", "Harbour Snack Co", 20, 2.35, False, False),
    Sku("DRY-2003", "Instant noodles", "Ridgeline Wholesale", 24, 0.85, False, False),
    Sku("DRY-2019", "Rice 1kg", "Ridgeline Wholesale", 10, 3.10, False, False),
    Sku("DRY-2044", "Pasta sauce 500g", "Ridgeline Wholesale", 12, 2.95, False, False),
    Sku("DRY-2071", "Breakfast cereal 500g", "Ridgeline Wholesale", 8, 4.20, False, False),
    Sku("HHD-3011", "AA batteries 4pk", "Ridgeline Wholesale", 20, 5.60, True, False),
    Sku("HHD-3025", "Dish soap 500ml", "Ridgeline Wholesale", 12, 2.80, False, False),
    Sku("HHD-3060", "Paper towels 2pk", "Ridgeline Wholesale", 9, 3.75, False, False),
    Sku("CHL-4002", "Milk 2L", "Vallance Dairy", 6, 4.10, False, True),
    Sku("CHL-4008", "Cheese slices 250g", "Vallance Dairy", 12, 5.20, False, True),
    Sku("CHL-4015", "Yoghurt 6pk", "Vallance Dairy", 8, 6.40, False, True),
    Sku("CHL-4033", "Butter 500g", "Vallance Dairy", 10, 6.90, False, True),
    Sku("FRZ-5001", "Ice cream 2L", "Vallance Dairy", 6, 7.50, False, False),
    Sku("FRZ-5010", "Frozen chips 1kg", "Vallance Dairy", 8, 4.80, False, False),
    Sku("TOB-6001", "Cigarettes 20pk", "Ridgeline Wholesale", 10, 38.00, True, False),
    Sku("TOB-6004", "Rolling tobacco 30g", "Ridgeline Wholesale", 12, 52.00, True, False),
    Sku("GRO-7001", "Bread loaf", "Harbour Snack Co", 12, 2.40, False, True),
    Sku("GRO-7020", "Eggs 12pk", "Vallance Dairy", 6, 7.20, False, True),
]


CATALOGUE_INDEX: dict[str, Sku] = {s.sku_id: s for s in CATALOGUE}
