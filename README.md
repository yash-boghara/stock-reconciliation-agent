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

| Cause | Rule-resolvable | Signature |
|---|---|---|
| `unit_mismatch` | yes | delivery logged in cases, counted as eaches |
| `late_delivery` | yes | stock received before count, invoice dated after |
| `late_carryover` | yes | previous period's late invoice landing now |
| `duplicate_scan` | yes | same sale recorded twice at the till |
| `short_delivery` | yes | invoiced quantity exceeds what arrived |
| `miscount` | no | the stocktake itself is wrong |
| `unlogged_wastage` | no | damaged or expired stock discarded off-book |
| `shrinkage` | no | unexplained loss, typically high-value lines |

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

## Status

Built:

- Domain model and cause taxonomy
- Synthetic data generator with planted ground truth
- Ingestion and normalisation layer with quarantine
- 12 tests, including a dataset-integrity check asserting every planted
  label agrees with the discrepancy the pipeline observes

Next:

- Deterministic rules layer, and a measured baseline of how far it gets alone
- Evaluation harness reporting per-cause accuracy, wired into CI
- Agent layer over the ambiguous residue, with narrow schema-validated tools
- Retrieval over resolved historical cases (pgvector)
- Postgres persistence, containerised API, review interface, cost tracking

## Running it

```bash
python3 -m src.recon.generate          # writes data/raw/
python3 -m src.recon.ingest            # assembles cases, reports rejections
python3 -m unittest discover -s tests -t .
```

No third-party dependencies yet; standard library only.
