# Stock Reconciliation Agent

Reconciles retail inventory discrepancies between point-of-sale exports,
supplier delivery records, and weekly stocktakes — then explains *why* each
discrepancy happened and drafts a correction for human approval.

The reconciliation identity, per SKU per week:

```
expected_closing = opening_count + delivered - sold
discrepancy      = actual_closing - expected_closing
```

A non-zero discrepancy always has a cause. Naming that cause correctly is
the task the system is measured on.

## Design position

Most of this problem is not an AI problem, and the architecture says so.

A deterministic rules layer handles causes with a structural signature —
cases logged as eaches, paperwork dated outside the count window, a till
double-scan, an invoice that overstates what arrived. These are found with
SQL and arithmetic, and using a language model for them would be slower,
costlier, and less reliable.

The LLM agent is reserved for the residue: cases that are numerically
identical but causally different. A shortfall of four units on a chocolate
line looks exactly like a shortfall of four units on a tobacco line, but
one is probably wastage and the other probably shrinkage. Separating them
needs context — item value, prior resolutions for that SKU and supplier,
wastage patterns — not better arithmetic.

Measuring how far the rules get on their own, before any model is involved,
is a deliberate part of the project rather than a preliminary.

## Cause taxonomy

| Cause | Rule-resolvable | Recall | Signature |
|---|---|---|---|
| `unit_mismatch` | yes | 100% | delivery logged in cases, counted as eaches |
| `late_delivery` | yes | 100% | stock received before count, invoice dated after |
| `late_carryover` | yes | 100% | previous period's late invoice landing now |
| `duplicate_scan` | yes | 100% | same line rung twice, one till, one day |
| `short_delivery` | only with a GRN | 70% | invoiced quantity exceeds what was counted in |
| `miscount` | no | — | the stocktake itself is wrong |
| `unlogged_wastage` | no | — | damaged or expired stock discarded off-book |
| `shrinkage` | no | — | unexplained loss, typically high-value lines |

Recall is measured over 30 seeds, not asserted. `short_delivery` is the
honest entry: it cannot beat 70% because that is how often a receiving note
exists to prove it — see *Baseline*.

`late_delivery` and `late_carryover` are two halves of one fault: a single
late invoice produces discrepancies in consecutive weeks with opposite
signs. The taxonomy originally lacked the second half, and the dataset
integrity test is what surfaced it.

## Data

Synthetic, and deliberately messy — SKU spellings drift between systems,
dates arrive in NZ (`03/06/2026`), ISO, and abbreviated-month formats,
quantities appear as `12`, `12.0`, and `" 12 "`, and a faulty export
duplicates rows outright.

Ground truth comes free: the generator *plants* each discrepancy with a
known cause and writes labels to a separate file the pipeline never reads.
That produces a 150-case labelled evaluation set without hand-labelling,
and it regenerates deterministically from a fixed seed so accuracy figures
across runs are comparable.

Current dataset: 150 cases over 6 weeks and 25 SKUs — 71 clean, 79 with a
planted cause.

Five documents are emitted. `goods_received.csv` is the one that carries
weight: it records what was counted off the truck, and it exists for only
70% of deliveries. That figure is deliberate. A GRN is the only document
that can prove a short delivery, and receiving paperwork is the first thing
skipped on a busy morning — filing one every time would make short
deliveries look fully detectable and measure the rules against a world that
does not exist.

## Ingestion

Normalisation is strict. Unparseable rows are quarantined rather than
coerced, because a row guessed wrong here becomes a phantom discrepancy
three layers up, and the agent then burns tokens explaining a bug.

One distinction worth noting: an identical `transaction_id` appearing twice
is an export artifact and gets dropped, while a genuine till double-scan
produces a *separate* transaction and is kept. The second one is a real
discrepancy the system exists to catch, not noise to clean away.

## Baseline

How far the rules get with no model involved, on the default seed:

```
overall accuracy  108/150  (72.0%)
rules committed        37  (100% precision)
left as residue        42  (28.0%)
```

Over 30 seeds — 1226 commitments, **zero misclassifications**:

| Cause | Recall (30 seeds) | Bounded by |
|---|---|---|
| `unit_mismatch` | 100% | — |
| `late_delivery` | 100% | — |
| `late_carryover` | 100% | — |
| `duplicate_scan` | 100% | — |
| `short_delivery` | 69.5% | GRN coverage (70%) |

Accuracy ranges 63.3%–76.7% across seeds, mean 70.8%. The spread is the
cause mix moving, not the rules wobbling.

Precision is the property under test. Recall can be improved later; a
confident wrong answer spends a reviewer's trust now, so every rule
requires the evidence to reconcile the gap *exactly* and declines
otherwise. `short_delivery` stops at 70% because that is how often a
receiving note was filed, and without one an invoice is a single number
with nothing to contradict it. That ceiling is a property of the world, not
a bug to tune away.

### What one seed hid

An earlier version of this table read 100% precision on the default seed.
A sweep across 30 seeds found 8 misclassifications the single seed had
concealed, in two distinct channels:

- **A routine docket read as a late invoice.** The window that catches late
  paperwork also catches *next week's ordinary delivery*, which sits one to
  three days past the count for innocent reasons. Matching on quantity
  alone let it explain a gap it had nothing to do with. The rule now
  requires either that no delivery was booked to the period at all, or a
  receiving note placing the stock on the shelf before the count.
- **Ordinary trade read as a double-scan.** Two customers buying the same
  quantity of the same item on the same day is not a till error. Keying the
  pair on till as well as date and quantity separates a re-ring from a
  coincidence, because an operator re-rings on the till in front of them.

Both fixes add evidence rather than thresholds, and neither costs recall.

### What the integrity test caught

The dataset-integrity check failed on `FRZ-5001-W05: label=none but
discrepancy=1`. A week opened with 11 units, received 6, and sold 18 — more
than ever existed — because the sales draw had a floor of 15 regardless of
stock on hand. The negative close was then floored at zero, and that clamp
manufactured a one-unit discrepancy in a case labelled clean.

Sales are now drawn against what is actually available once the planted
fault has taken its bite, and a negative close raises instead of clamping.
Silently flooring it corrupts the evaluation set rather than the run that
produced it, which is the more expensive failure: every accuracy figure
measured afterwards is quietly wrong.

## Residue

42 cases reach the agent layer on the default seed:

| Cause | Cases | Why rules cannot close it |
|---|---|---|
| `unlogged_wastage` | 25 | no record exists of stock discarded off-book |
| `miscount` | 13 | the count is wrong; nothing else disagrees |
| `shrinkage` | 3 | absence of evidence is the evidence |
| `short_delivery` | 1 | no receiving note was filed |

The first three are numerically identical — a small negative gap — and can
only be separated with context: item value, prior resolutions for the SKU
and supplier, wastage patterns on the line. That is the agent's job, and
the population is now clean enough to state it precisely.

## Status

Built:

- Domain model and cause taxonomy
- Synthetic data generator with planted ground truth, five source documents
  including goods-received notes at realistic partial coverage
- Ingestion and normalisation layer with quarantine
- Deterministic rules layer, with pair rules spanning adjacent periods
- Evaluation harness reporting per-cause precision and recall
- 32 tests: dataset integrity, generator invariants, per-rule declining
  cases, a multi-seed precision check, and a pinned baseline
- CI running the whole pipeline on every push

Next:

- Agent layer over the ambiguous residue, with narrow schema-validated tools
- Retrieval over resolved historical cases (pgvector)
- Postgres persistence, containerised API, review interface, cost tracking
- Retrieval over resolved historical cases (pgvector)
- Postgres persistence, containerised API, review interface, cost tracking

## Running it

```bash
python3 -m src.recon.generate          # writes data/raw/
python3 -m src.recon.ingest            # assembles cases, reports rejections
python3 -m src.recon.rules             # classifies what the rules can
python3 -m src.recon.evaluate          # scores rules against ground truth
python3 -m unittest discover -s tests -t .
```

No third-party dependencies yet; standard library only.
