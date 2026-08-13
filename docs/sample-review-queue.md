# Review queue

75 corrections, NZ$5,751.15 at stake.

**30 post automatically** (NZ$1,680.05) — rule-certain and under the NZ$150 review threshold. Nobody has to open them.

| Route | Corrections | Value |
|---|---:|---:|
| `escalate` | 0 | NZ$0.00 |
| `review` | 45 | NZ$4,071.10 |
| `auto` | 30 | NZ$1,680.05 |

## Needs a decision (45)

Either the judgement layer decided it, or it is large enough that certainty alone should not be enough to post it.

### TOB-6001-W04 — NZ$760.00

- **Do:** redate docket: +20 units of TOB-6001 (Cigarettes 20pk)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-06-28
- **Because:** docket D3592801 dated 2026-06-30 is after the 2026-06-28 count but its 20 units were on the shelf when the count happened; no delivery was booked to this period at all

### TOB-6001-W05 — NZ$760.00

- **Do:** redate docket: -20 units of TOB-6001 (Cigarettes 20pk)
- **Owner:** accounts payable
- **Cause:** `late_carryover` (confidence: rule)
- **Week ending:** 2026-07-05
- **Because:** 20 units invoiced this period were received and counted in the previous one (TOB-6001-W04)

### SNK-1077-W03 — NZ$216.00

- **Do:** redate docket: +48 units of SNK-1077 (Mixed nuts 200g)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-06-21
- **Because:** docket D7737315 dated 2026-06-22 is after the 2026-06-21 count but its 48 units were on the shelf when the count happened; no delivery was booked to this period at all

### SNK-1077-W04 — NZ$216.00

- **Do:** redate docket: -48 units of SNK-1077 (Mixed nuts 200g)
- **Owner:** accounts payable
- **Cause:** `late_carryover` (confidence: rule)
- **Week ending:** 2026-06-28
- **Because:** 48 units invoiced this period were received and counted in the previous one (SNK-1077-W03)

### TOB-6004-W04 — NZ$208.00

- **Do:** adjust stock count: -4 units of TOB-6004 (Rolling tobacco 30g)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: low)
- **Week ending:** 2026-06-28
- **Because:** Small shortfall on a line with no spoilage or theft profile and no recurring pattern.

### TOB-6004-W06 — NZ$208.00

- **Do:** adjust stock count: -4 units of TOB-6004 (Rolling tobacco 30g)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: low)
- **Week ending:** 2026-07-12
- **Because:** Small shortfall on a line with no spoilage or theft profile and no recurring pattern.

### BEV-0142-W01 — NZ$201.60

- **Do:** redate docket: +96 units of BEV-0142 (Energy drink 250ml)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-06-07
- **Because:** docket D5273179 dated 2026-06-08 is after the 2026-06-07 count but its 96 units were on the shelf when the count happened; no delivery was booked to this period at all

### BEV-0142-W02 — NZ$201.60

- **Do:** redate docket: -96 units of BEV-0142 (Energy drink 250ml)
- **Owner:** accounts payable
- **Cause:** `late_carryover` (confidence: rule)
- **Week ending:** 2026-06-14
- **Because:** 96 units invoiced this period were received and counted in the previous one (BEV-0142-W01)

### CHL-4015-W01 — NZ$179.20

- **Do:** adjust delivery record: +28 units of CHL-4015 (Yoghurt 6pk)
- **Owner:** goods-in
- **Cause:** `unit_mismatch` (confidence: rule)
- **Week ending:** 2026-06-07
- **Because:** docket D3770465 records 4 at uom=CASE; 4 x 8 units arrived, 4 were booked

### CHL-4008-W03 — NZ$171.60

- **Do:** adjust delivery record: +33 units of CHL-4008 (Cheese slices 250g)
- **Owner:** goods-in
- **Cause:** `unit_mismatch` (confidence: rule)
- **Week ending:** 2026-06-21
- **Because:** docket D5900651 records 3 at uom=CASE; 3 x 12 units arrived, 3 were booked

### TOB-6004-W03 — NZ$156.00

- **Do:** raise supplier claim: -3 units of TOB-6004 (Rolling tobacco 30g)
- **Owner:** accounts payable
- **Cause:** `short_delivery` (confidence: rule)
- **Week ending:** 2026-06-21
- **Because:** docket D2104020 invoices 60 units but GRN G171103 counted 57 off the truck; 3 short

### SNK-1001-W06 — NZ$153.00

- **Do:** adjust delivery record: +85 units of SNK-1001 (Potato chips 150g)
- **Owner:** goods-in
- **Cause:** `unit_mismatch` (confidence: rule)
- **Week ending:** 2026-07-12
- **Because:** docket D6098978 records 5 at uom=CASE; 5 x 18 units arrived, 5 were booked

### TOB-6004-W01 — NZ$104.00

- **Do:** adjust stock count: +2 units of TOB-6004 (Rolling tobacco 30g)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-07
- **Because:** Positive discrepancy; only a miscount overstates a close once the structural causes are excluded.

### FRZ-5001-W04 — NZ$45.00

- **Do:** adjust stock count: +6 units of FRZ-5001 (Ice cream 2L)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-28
- **Because:** Staff note: "not confident on the ice tally, was rushing"

### GRO-7020-W03 — NZ$43.20

- **Do:** post wastage entry: -6 units of GRO-7020 (Eggs 12pk)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: medium)
- **Week ending:** 2026-06-21
- **Because:** Short-dated line; spoilage is the standing explanation for a recurring small shortfall.

### FRZ-5001-W03 — NZ$37.50

- **Do:** adjust stock count: -5 units of FRZ-5001 (Ice cream 2L)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: low)
- **Week ending:** 2026-06-21
- **Because:** Small shortfall on a line with no spoilage or theft profile and no recurring pattern.

### GRO-7020-W06 — NZ$36.00

- **Do:** adjust stock count: +5 units of GRO-7020 (Eggs 12pk)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-07-12
- **Because:** Positive discrepancy; only a miscount overstates a close once the structural causes are excluded.

### CHL-4033-W01 — NZ$34.50

- **Do:** post wastage entry: -5 units of CHL-4033 (Butter 500g)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: high)
- **Week ending:** 2026-06-07
- **Because:** Staff note: "binned 5 butter, past date"

### CHL-4015-W03 — NZ$32.00

- **Do:** adjust stock count: -5 units of CHL-4015 (Yoghurt 6pk)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-21
- **Because:** Staff note: "counted the yoghurt twice, got two numbers"

### CHL-4015-W04 — NZ$32.00

- **Do:** adjust stock count: +5 units of CHL-4015 (Yoghurt 6pk)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-28
- **Because:** Positive discrepancy; only a miscount overstates a close once the structural causes are excluded.

### CHL-4008-W04 — NZ$26.00

- **Do:** adjust stock count: -5 units of CHL-4008 (Cheese slices 250g)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-28
- **Because:** Staff note: "counted the cheese twice, got two numbers"

### CHL-4015-W06 — NZ$25.60

- **Do:** post wastage entry: -4 units of CHL-4015 (Yoghurt 6pk)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: medium)
- **Week ending:** 2026-07-12
- **Because:** Short-dated line; spoilage is the standing explanation for a recurring small shortfall.

### CHL-4002-W03 — NZ$24.60

- **Do:** adjust stock count: -6 units of CHL-4002 (Milk 2L)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-21
- **Because:** Staff note: "not confident on the milk tally, was rushing"

### GRO-7020-W04 — NZ$21.60

- **Do:** post wastage entry: -3 units of GRO-7020 (Eggs 12pk)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: medium)
- **Week ending:** 2026-06-28
- **Because:** Short-dated line; spoilage is the standing explanation for a recurring small shortfall.

### CHL-4008-W02 — NZ$20.80

- **Do:** post wastage entry: -4 units of CHL-4008 (Cheese slices 250g)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: medium)
- **Week ending:** 2026-06-14
- **Because:** Short-dated line; spoilage is the standing explanation for a recurring small shortfall.

### FRZ-5010-W02 — NZ$14.40

- **Do:** adjust stock count: +3 units of FRZ-5010 (Frozen chips 1kg)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-14
- **Because:** Positive discrepancy; only a miscount overstates a close once the structural causes are excluded.

### SNK-1077-W01 — NZ$13.50

- **Do:** adjust stock count: -3 units of SNK-1077 (Mixed nuts 200g)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-07
- **Because:** Staff note: "counted the mixed twice, got two numbers"

### CHL-4015-W02 — NZ$12.80

- **Do:** post wastage entry: -2 units of CHL-4015 (Yoghurt 6pk)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: medium)
- **Week ending:** 2026-06-14
- **Because:** Short-dated line; spoilage is the standing explanation for a recurring small shortfall.

### CHL-4002-W02 — NZ$12.30

- **Do:** post wastage entry: -3 units of CHL-4002 (Milk 2L)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: high)
- **Week ending:** 2026-06-14
- **Because:** Staff note: "chucked a tray of milk, had turned"

### HHD-3011-W04 — NZ$11.20

- **Do:** adjust stock count: +2 units of HHD-3011 (AA batteries 4pk)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-28
- **Because:** Positive discrepancy; only a miscount overstates a close once the structural causes are excluded.

### FRZ-5010-W04 — NZ$9.60

- **Do:** adjust stock count: +2 units of FRZ-5010 (Frozen chips 1kg)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-28
- **Because:** Positive discrepancy; only a miscount overstates a close once the structural causes are excluded.

### GRO-7001-W01 — NZ$9.60

- **Do:** post wastage entry: -4 units of GRO-7001 (Bread loaf)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: medium)
- **Week ending:** 2026-06-07
- **Because:** Short-dated line; spoilage is the standing explanation for a recurring small shortfall.

### SNK-1090-W03 — NZ$9.40

- **Do:** raise supplier claim: -4 units of SNK-1090 (Biscuits 250g)
- **Owner:** accounts payable
- **Cause:** `short_delivery` (confidence: high)
- **Week ending:** 2026-06-21
- **Because:** Staff note: "checked the biscuits off the truck, less than the docket"

### HHD-3060-W01 — NZ$7.50

- **Do:** adjust stock count: -2 units of HHD-3060 (Paper towels 2pk)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: low)
- **Week ending:** 2026-06-07
- **Because:** Small shortfall on a line with no spoilage or theft profile and no recurring pattern.

### GRO-7001-W02 — NZ$7.20

- **Do:** post wastage entry: -3 units of GRO-7001 (Bread loaf)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: medium)
- **Week ending:** 2026-06-14
- **Because:** Short-dated line; spoilage is the standing explanation for a recurring small shortfall.

### GRO-7001-W03 — NZ$7.20

- **Do:** post wastage entry: -3 units of GRO-7001 (Bread loaf)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: high)
- **Week ending:** 2026-06-21
- **Because:** Staff note: "dumped some bread, smelled off"

### GRO-7001-W04 — NZ$7.20

- **Do:** post wastage entry: -3 units of GRO-7001 (Bread loaf)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: medium)
- **Week ending:** 2026-06-28
- **Because:** Short-dated line; spoilage is the standing explanation for a recurring small shortfall.

### GRO-7001-W06 — NZ$7.20

- **Do:** post wastage entry: -3 units of GRO-7001 (Bread loaf)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: high)
- **Week ending:** 2026-07-12
- **Because:** Staff note: "chucked a tray of bread, had turned"

### BEV-0142-W05 — NZ$6.30

- **Do:** post wastage entry: -3 units of BEV-0142 (Energy drink 250ml)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: high)
- **Week ending:** 2026-07-05
- **Because:** Staff note: "chucked a tray of energy, had turned"

### DRY-2019-W02 — NZ$6.20

- **Do:** adjust stock count: -2 units of DRY-2019 (Rice 1kg)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: low)
- **Week ending:** 2026-06-14
- **Because:** Small shortfall on a line with no spoilage or theft profile and no recurring pattern.

### DRY-2019-W05 — NZ$6.20

- **Do:** post wastage entry: -2 units of DRY-2019 (Rice 1kg)
- **Owner:** department manager
- **Cause:** `unlogged_wastage` (confidence: high)
- **Week ending:** 2026-07-05
- **Because:** Staff note: "dumped some rice, smelled off"

### SNK-1044-W03 — NZ$3.60

- **Do:** adjust stock count: -3 units of SNK-1044 (Chocolate bar 50g)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: low)
- **Week ending:** 2026-06-21
- **Because:** Small shortfall on a line with no spoilage or theft profile and no recurring pattern.

### BEV-0142-W03 — NZ$2.10

- **Do:** adjust stock count: -1 units of BEV-0142 (Energy drink 250ml)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-21
- **Because:** Staff note: "recount of energy didn't match the first pass"

### BEV-0142-W04 — NZ$2.10

- **Do:** adjust stock count: +1 units of BEV-0142 (Energy drink 250ml)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: high)
- **Week ending:** 2026-06-28
- **Because:** Positive discrepancy; only a miscount overstates a close once the structural causes are excluded.

### DRY-2003-W04 — NZ$1.70

- **Do:** adjust stock count: -2 units of DRY-2003 (Instant noodles)
- **Owner:** stock controller
- **Cause:** `miscount` (confidence: low)
- **Week ending:** 2026-06-28
- **Because:** Small shortfall on a line with no spoilage or theft profile and no recurring pattern.


## Posting automatically (30)

Rule-certain, evidence reconciles exactly, under threshold. Listed for the audit trail, not for action.

### DRY-2044-W01 — NZ$141.60

- **Do:** redate docket: +48 units of DRY-2044 (Pasta sauce 500g)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-06-07
- **Because:** docket D1663953 dated 2026-06-10 is after the 2026-06-07 count but its 48 units were on the shelf when the count happened; GRN G461254 counted them in on 2026-06-03

### DRY-2044-W02 — NZ$141.60

- **Do:** redate docket: -48 units of DRY-2044 (Pasta sauce 500g)
- **Owner:** accounts payable
- **Cause:** `late_carryover` (confidence: rule)
- **Week ending:** 2026-06-14
- **Because:** 48 units invoiced this period were received and counted in the previous one (DRY-2044-W01)

### CHL-4002-W06 — NZ$123.00

- **Do:** redate docket: +30 units of CHL-4002 (Milk 2L)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-07-12
- **Because:** docket D7293150 dated 2026-07-13 is after the 2026-07-12 count but its 30 units were on the shelf when the count happened; no delivery was booked to this period at all

### SNK-1001-W03 — NZ$122.40

- **Do:** adjust delivery record: +68 units of SNK-1001 (Potato chips 150g)
- **Owner:** goods-in
- **Cause:** `unit_mismatch` (confidence: rule)
- **Week ending:** 2026-06-21
- **Because:** docket D9209205 records 4 at uom=CASE; 4 x 18 units arrived, 4 were booked

### HHD-3011-W06 — NZ$112.00

- **Do:** redate docket: +20 units of HHD-3011 (AA batteries 4pk)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-07-12
- **Because:** docket D3478527 dated 2026-07-15 is after the 2026-07-12 count but its 20 units were on the shelf when the count happened; no delivery was booked to this period at all

### SNK-1001-W01 — NZ$97.20

- **Do:** redate docket: +54 units of SNK-1001 (Potato chips 150g)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-06-07
- **Because:** docket D9000165 dated 2026-06-10 is after the 2026-06-07 count but its 54 units were on the shelf when the count happened; GRN G946965 counted them in on 2026-06-02

### SNK-1001-W02 — NZ$97.20

- **Do:** redate docket: -54 units of SNK-1001 (Potato chips 150g)
- **Owner:** accounts payable
- **Cause:** `late_carryover` (confidence: rule)
- **Week ending:** 2026-06-14
- **Because:** 54 units invoiced this period were received and counted in the previous one (SNK-1001-W01)

### SNK-1090-W01 — NZ$94.00

- **Do:** redate docket: +40 units of SNK-1090 (Biscuits 250g)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-06-07
- **Because:** docket D6174816 dated 2026-06-08 is after the 2026-06-07 count but its 40 units were on the shelf when the count happened; GRN G516429 counted them in on 2026-06-03

### SNK-1090-W02 — NZ$94.00

- **Do:** redate docket: -40 units of SNK-1090 (Biscuits 250g)
- **Owner:** accounts payable
- **Cause:** `late_carryover` (confidence: rule)
- **Week ending:** 2026-06-14
- **Because:** 40 units invoiced this period were received and counted in the previous one (SNK-1090-W01)

### TOB-6001-W01 — NZ$76.00

- **Do:** raise supplier claim: -2 units of TOB-6001 (Cigarettes 20pk)
- **Owner:** accounts payable
- **Cause:** `short_delivery` (confidence: rule)
- **Week ending:** 2026-06-07
- **Because:** docket D3509995 invoices 40 units but GRN G716007 counted 38 off the truck; 2 short

### HHD-3011-W03 — NZ$72.80

- **Do:** void duplicate sale: +13 units of HHD-3011 (AA batteries 4pk)
- **Owner:** duty manager
- **Cause:** `duplicate_scan` (confidence: rule)
- **Week ending:** 2026-06-21
- **Because:** transactions T65538827 and T73700871 both record 13 units on 2026-06-17

### GRO-7020-W05 — NZ$72.00

- **Do:** adjust delivery record: +10 units of GRO-7020 (Eggs 12pk)
- **Owner:** goods-in
- **Cause:** `unit_mismatch` (confidence: rule)
- **Week ending:** 2026-07-05
- **Because:** docket D6015017 records 2 at uom=CASE; 2 x 6 units arrived, 2 were booked

### BEV-0210-W03 — NZ$57.00

- **Do:** redate docket: +60 units of BEV-0210 (Bottled water 750ml)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-06-21
- **Because:** docket D7626925 dated 2026-06-24 is after the 2026-06-21 count but its 60 units were on the shelf when the count happened; GRN G996025 counted them in on 2026-06-15

### BEV-0210-W04 — NZ$57.00

- **Do:** redate docket: -60 units of BEV-0210 (Bottled water 750ml)
- **Owner:** accounts payable
- **Cause:** `late_carryover` (confidence: rule)
- **Week ending:** 2026-06-28
- **Because:** 60 units invoiced this period were received and counted in the previous one (BEV-0210-W03)

### CHL-4033-W06 — NZ$55.20

- **Do:** void duplicate sale: +8 units of CHL-4033 (Butter 500g)
- **Owner:** duty manager
- **Cause:** `duplicate_scan` (confidence: rule)
- **Week ending:** 2026-07-12
- **Because:** transactions T24167560 and T48599996 both record 8 units on 2026-07-12

### BEV-0210-W05 — NZ$41.80

- **Do:** adjust delivery record: +44 units of BEV-0210 (Bottled water 750ml)
- **Owner:** goods-in
- **Cause:** `unit_mismatch` (confidence: rule)
- **Week ending:** 2026-07-05
- **Because:** docket D7011688 records 4 at uom=CASE; 4 x 12 units arrived, 4 were booked

### CHL-4008-W01 — NZ$36.40

- **Do:** void duplicate sale: +7 units of CHL-4008 (Cheese slices 250g)
- **Owner:** duty manager
- **Cause:** `duplicate_scan` (confidence: rule)
- **Week ending:** 2026-06-07
- **Because:** transactions T50351048 and T53671030 both record 7 units on 2026-06-03

### DRY-2071-W04 — NZ$33.60

- **Do:** redate docket: +8 units of DRY-2071 (Breakfast cereal 500g)
- **Owner:** accounts payable
- **Cause:** `late_delivery` (confidence: rule)
- **Week ending:** 2026-06-28
- **Because:** docket D5988828 dated 2026-07-01 is after the 2026-06-28 count but its 8 units were on the shelf when the count happened; no delivery was booked to this period at all

### DRY-2071-W05 — NZ$33.60

- **Do:** redate docket: -8 units of DRY-2071 (Breakfast cereal 500g)
- **Owner:** accounts payable
- **Cause:** `late_carryover` (confidence: rule)
- **Week ending:** 2026-07-05
- **Because:** 8 units invoiced this period were received and counted in the previous one (DRY-2071-W04)

### SNK-1044-W04 — NZ$15.60

- **Do:** void duplicate sale: +13 units of SNK-1044 (Chocolate bar 50g)
- **Owner:** duty manager
- **Cause:** `duplicate_scan` (confidence: rule)
- **Week ending:** 2026-06-28
- **Because:** transactions T33608669 and T39607370 both record 13 units on 2026-06-26

### HHD-3060-W06 — NZ$15.00

- **Do:** void duplicate sale: +4 units of HHD-3060 (Paper towels 2pk)
- **Owner:** duty manager
- **Cause:** `duplicate_scan` (confidence: rule)
- **Week ending:** 2026-07-12
- **Because:** transactions T11318919 and T35914420 both record 4 units on 2026-07-11

### HHD-3025-W03 — NZ$14.00

- **Do:** raise supplier claim: -5 units of HHD-3025 (Dish soap 500ml)
- **Owner:** accounts payable
- **Cause:** `short_delivery` (confidence: rule)
- **Week ending:** 2026-06-21
- **Because:** docket D5975447 invoices 60 units but GRN G374216 counted 55 off the truck; 5 short

### SNK-1044-W06 — NZ$13.20

- **Do:** raise supplier claim: -11 units of SNK-1044 (Chocolate bar 50g)
- **Owner:** accounts payable
- **Cause:** `short_delivery` (confidence: rule)
- **Week ending:** 2026-07-12
- **Because:** docket D7999897 invoices 72 units but GRN G456203 counted 61 off the truck; 11 short

### GRO-7001-W05 — NZ$12.00

- **Do:** raise supplier claim: -5 units of GRO-7001 (Bread loaf)
- **Owner:** accounts payable
- **Cause:** `short_delivery` (confidence: rule)
- **Week ending:** 2026-07-05
- **Because:** docket D4057759 invoices 24 units but GRN G660519 counted 19 off the truck; 5 short

### BEV-0288-W02 — NZ$10.40

- **Do:** void duplicate sale: +4 units of BEV-0288 (Cola 1.5L)
- **Owner:** duty manager
- **Cause:** `duplicate_scan` (confidence: rule)
- **Week ending:** 2026-06-14
- **Because:** transactions T36028811 and T88812207 both record 4 units on 2026-06-10

### BEV-0143-W05 — NZ$10.20

- **Do:** void duplicate sale: +3 units of BEV-0143 (Energy drink 500ml)
- **Owner:** duty manager
- **Cause:** `duplicate_scan` (confidence: rule)
- **Week ending:** 2026-07-05
- **Because:** transactions T86915521 and T47646262 both record 3 units on 2026-07-01

### FRZ-5010-W03 — NZ$9.60

- **Do:** raise supplier claim: -2 units of FRZ-5010 (Frozen chips 1kg)
- **Owner:** accounts payable
- **Cause:** `short_delivery` (confidence: rule)
- **Week ending:** 2026-06-21
- **Because:** docket D4293135 invoices 8 units but GRN G435898 counted 6 off the truck; 2 short

### FRZ-5010-W06 — NZ$9.60

- **Do:** raise supplier claim: -2 units of FRZ-5010 (Frozen chips 1kg)
- **Owner:** accounts payable
- **Cause:** `short_delivery` (confidence: rule)
- **Week ending:** 2026-07-12
- **Because:** docket D3555033 invoices 32 units but GRN G789998 counted 30 off the truck; 2 short

### BEV-0210-W02 — NZ$9.50

- **Do:** void duplicate sale: +10 units of BEV-0210 (Bottled water 750ml)
- **Owner:** duty manager
- **Cause:** `duplicate_scan` (confidence: rule)
- **Week ending:** 2026-06-14
- **Because:** transactions T13975571 and T29711700 both record 10 units on 2026-06-09

### DRY-2003-W03 — NZ$2.55

- **Do:** void duplicate sale: +3 units of DRY-2003 (Instant noodles)
- **Owner:** duty manager
- **Cause:** `duplicate_scan` (confidence: rule)
- **Week ending:** 2026-06-21
- **Because:** transactions T75873303 and T14137031 both record 3 units on 2026-06-17
