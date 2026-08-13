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

| Cause | Rule-resolvable | Caught | Signature |
|---|---|---|---|
| `unit_mismatch` | yes | yes | delivery logged in cases, counted as eaches |
| `late_delivery` | yes | yes | stock received before count, invoice dated after |
| `late_carryover` | yes | yes | previous period's late invoice landing now |
| `duplicate_scan` | in principle | no | same sale recorded twice at the till |
| `short_delivery` | in principle | no | invoiced quantity exceeds what arrived |
| `miscount` | no | — | the stocktake itself is wrong |
| `unlogged_wastage` | no | — | damaged or expired stock discarded off-book |
| `shrinkage` | no | — | unexplained loss, typically high-value lines |

The `Caught` column is a measurement, not an intention, and the two causes
it marks `no` are the interesting part — see *Baseline* below.

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

Current dataset: 150 cases over 6 weeks and 25 SKUs — 62 clean, 88 with a
planted cause.

## Ingestion

Normalisation is strict. Unparseable rows are quarantined rather than
coerced, because a row guessed wrong here becomes a phantom discrepancy
three layers up, and the agent then burns tokens explaining a bug.

One distinction worth noting: an identical `transaction_id` appearing twice
is an export artifact and gets dropped, while a genuine till double-scan
produces a *separate* transaction and is kept. The second one is a real
discrepancy the system exists to catch, not noise to clean away.

## Baseline

How far the rules get with no model involved, over all 150 cases:

```
overall accuracy   89/150  (59.3%)
rules committed        27  (100% precision, zero misclassifications)
left as residue        61  (40.7%)
```

Per cause:

| Cause | Support | Precision | Recall |
|---|---|---|---|
| `none` | 62 | 100% | 100% |
| `late_delivery` | 12 | 100% | 100% |
| `late_carryover` | 11 | 100% | 100% |
| `unit_mismatch` | 4 | 100% | 100% |
| `duplicate_scan` | 14 | — | 0% |
| `short_delivery` | 9 | — | 0% |

Every cause with a structural signature is recovered completely, and no
rule ever names a wrong cause. Precision is the property under test: recall
can be improved later, but a confident wrong answer spends a reviewer's
trust now, so rules decline rather than guess.

The two zeroes are a finding, not an omission. Neither cause leaves a
signature in the data as currently generated:

- **`duplicate_scan`** — the generator inflates a week's sales total rather
  than emitting the second transaction. A real double-scan produces two
  rows agreeing on SKU, date and quantity, and the rule looks for exactly
  that pair. The pair is never written, so the rule correctly never fires.
- **`short_delivery`** — only the invoice is recorded. Catching a short
  delivery means comparing an invoice against a goods-received note, and
  the dataset has no receiving document to compare against.

Both are fixable in the generator, and both are *supposed* to be
rule-resolvable, so 23 of the 61 residue cases are currently polluting the
population the agent is meant to serve. The honest residue — the cases that
genuinely need judgement — is 38.

## Status

Built:

- Domain model and cause taxonomy
- Synthetic data generator with planted ground truth
- Ingestion and normalisation layer with quarantine
- Deterministic rules layer, with pair rules spanning adjacent periods
- Evaluation harness reporting per-cause precision and recall
- 25 tests, including a dataset-integrity check asserting every planted
  label agrees with the discrepancy the pipeline observes, and a pinned
  baseline that fails if accuracy drifts

Next:

- Emit a faithful `duplicate_scan` pair and a goods-received document, so
  the two unmeasured causes become measurable
- Wire the evaluation harness into CI
- Agent layer over the ambiguous residue, with narrow schema-validated tools
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
