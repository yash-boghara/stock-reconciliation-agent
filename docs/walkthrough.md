# Walkthrough: four messy rows to a posted correction

One discrepancy, followed the whole way. Every figure and quoted row below is
real output from the default seed — reproduce any step with the command shown
beside it.

The case is **`SNK-1001-W03`**: potato chips, week ending 21 June 2026. It
ends as a NZ$122.40 adjustment that posts itself, and nobody ever opens it.

---

## 1. What actually arrives

Four systems, four spellings of one SKU, three date formats.

```
deliveries.csv
docket_no,delivery_date,supplier,sku,qty_received,uom,unit_cost
D9209205,19/06/2026,HARBOUR SNACK CO,  SNK 1001 ,4.0,CASE,1.80

stock_counts.csv
count_id,count_date,sku,opening_qty,closing_qty,counted_by
SNK-1001-W03,21-Jun-2026,  SNK 1001 ,87,71,

pos_sales.csv
transaction_id,sale_date,sale_time,sku,qty,unit_price,till
T43042462,2026-06-01,09:45:56,snk-1001,9,2.4300,
T63209874,01-Jun-2026,16:31:25,SNK-1001, 14 ,2.43,2
T55561863,2026-06-05,11:28:26,0SNK-1001,13,2.43,
```

`  SNK 1001 `, `snk-1001`, `SNK-1001`, `0SNK-1001` — one product. `19/06/2026`
is 19 June, NZ convention, not 6 July. `4.0` is a count, not a measurement.
` 14 ` has been through a spreadsheet. Two rows have no till recorded.

## 2. Normalisation, which refuses to guess

```bash
python3 -m src.recon.ingest
```

Every field is folded to a canonical form: SKU to `SNK-1001`, dates to
`2026-06-19`, `4.0` to `4`. Three rules govern it.

**Unrecognised input is quarantined, not coerced.** A SKU that does not match
the catalogue raises rather than snapping to its nearest neighbour, because a
row guessed wrong here becomes a phantom discrepancy three layers up — and
then something downstream spends effort explaining a bug.

**A fractional quantity is an error, not a rounding problem.** `12.4` units
means the upstream export is wrong and should be seen.

**Only byte-identical rows are duplicates.** 14 rows are dropped as export
artifacts this run. Two *different* sales that happen to share a transaction
id are two real sales — matching on the id alone once deleted 13 units of
revenue and invented a shortfall in a week that balanced.

On this dataset: **0 rows rejected, 14 duplicates dropped.**

## 3. The case, and the arithmetic

```bash
python3 -m src.recon.rules
```

The four sources collapse into one week for one SKU:

```
opening_count   87
delivered        4     (as booked)
sold            88
expected close  87 + 4 - 88  =  3
actual close    71
discrepancy     71 - 3       = +68
```

Sixty-eight units more on the shelf than the paperwork can account for. At
this point the system knows *that* something is wrong and nothing about
*why* — and every cause looks the same from here.

## 4. The rule that fires, and what it had to prove

`rule_unit_mismatch` sees a docket booked as `uom=CASE` with a quantity of 4.
Potato chips ship 18 to a case, so 4 cases is 72 units on the shelf against 4
units in the ledger — 68 unbooked.

**It does not stop there.** The rule requires the arithmetic to reconcile
exactly:

```
qty × (case_size − 1)  =  4 × 17  =  68  =  discrepancy   ✓
```

If those disagreed by even one unit, the rule declines and the case falls to
the judgement layer. A `CASE` docket sitting beside a discrepancy it cannot
explain is a coincidence, and firing on it would be a guess wearing a rule's
authority.

That discipline is the whole reason the next step is allowed to happen: the
rules layer has committed to a cause **3,891 times across 100 seeds without
once being wrong.**

## 5. From cause to work

```bash
python3 -m src.recon.correct
```

A cause is not a deliverable. The correction is:

```
do        : adjust delivery record: +68 units of SNK-1001 (Potato chips 150g)
owner     : goods-in
value     : NZ$122.40          (68 units × $1.80)
because   : docket D9209205 records 4 at uom=CASE;
            4 × 18 units arrived, 4 were booked
```

The **action follows the cause, not the number**. Sixty-eight units adrift
because a case was booked as an each is a goods-in correction. The same 68
units missing because a supplier short-shipped would be an accounts-payable
claim; because they spoiled, a write-off. One arithmetic, three desks.

## 6. Why nobody sees it

Two gates decide. It is **rule-certain**, so its provenance is a proof rather
than a judgement. And at NZ$122.40 it is under the NZ$150 review threshold,
so the size does not warrant a second pair of eyes.

Route: **`auto`**. It posts, it is written to the decision log as a decision
taken by the system, and no human opens it.

Certainty alone is not enough. The same rule on 20 units of cigarettes is
NZ$760 and goes to a person regardless — a large adjustment posted unattended
is how a control failure becomes an audit finding.

---

## The contrast: a $2.10 correction that a human must see

`BEV-0142-W03` is a **one unit** discrepancy on energy drinks. No rule
explains it, so it reaches the judgement layer, which retrieves a staff note:

> *"recount of energy didn't match the first pass"* — M Tanner, 20 June

Verdict: `miscount`, high confidence, citing that note. Correct.

```
do        : adjust stock count: -1 units of BEV-0142 (Energy drink 250ml)
owner     : stock controller
value     : NZ$2.10
route     : review
```

**NZ$122.40 posts itself and NZ$2.10 needs a person.** Not because of the
money — because of where the answer came from. The rules layer earned
unattended posting with 3,891 clean commitments; the judgement layer has no
such record and does not inherit one. Its confidence is well calibrated
(99.5% at `high`), which is good enough to rank a queue and not good enough
to post to a ledger.

---

## The whole funnel, one run

```
150 cases
├─  75 balanced           nothing to do
└─  75 discrepancies
    ├─ 40 rules explain       100% precision, no model involved
    └─ 35 judgement           the residue the rules decline

75 corrections, NZ$5,751.15 at stake
├─ 30 auto      rule-certain and under threshold — nobody opens them
└─ 45 review    10 rule-certain but large + 35 judgement calls
```

Half the weeks reconcile cleanly. Of the half that do not, arithmetic settles
53% outright. **Two-fifths of all the work leaves the building without a
person touching it**, and the rest arrives on the right desk, ordered by money
at stake, with its evidence attached.

## Where the model fits, and why it is not in this story

It never sees `SNK-1001-W03`. That case has a structural signature, and a
language model asked to confirm arithmetic already proved exactly would be
slower, dearer, and less reliable.

It only sees the 35. Of those, the ones it can decide better than a
twenty-line control are the ~24% carrying a staff note phrased beyond a
keyword list — *"wouldn't keep till Monday"*, *"third week running"*. That is
a measured 5.4 points, not an assumption, and it cost **$0.0147 a case** to
find out.

Full numbers with confidence intervals: **[evaluation.md](evaluation.md)**.
Why the agent is built this way: **[agent-design.md](agent-design.md)**. What
measuring it turned up, including three dataset bugs it caught:
**[../FINDINGS.md](../FINDINGS.md)**.

## Run the whole thing

```bash
python3 -m src.recon.generate     # six messy CSVs
python3 -m src.recon.ingest       # normalise, quarantine, assemble cases
python3 -m src.recon.rules        # the structural causes
python3 -m src.recon.agent        # the residue (no API key needed)
python3 -m src.recon.correct      # corrections, routing, decision log
python3 -m src.recon.review list  # work the queue
```

Standard library only. No key, no network, about two seconds.
