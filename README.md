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
| `duplicate_scan` | yes | 98.5% | same line rung twice, one till, seconds apart |
| `short_delivery` | only with a GRN | 69% | invoiced quantity exceeds what was counted in |
| `miscount` | no | — | the stocktake itself is wrong |
| `unlogged_wastage` | no | — | damaged or expired stock discarded off-book |
| `shrinkage` | no | — | unexplained loss, typically high-value lines |

Recall is measured over 40 seeds, not asserted. `short_delivery` cannot beat
70% because that is how often a receiving note exists to prove it, and
`duplicate_scan` declines the pairs it cannot time — see *Baseline*.

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

Two columns of the POS export matter beyond the obvious: `till` and
`sale_time` are what separate a genuine re-ring from two customers buying the
same thing on the same day.

Six documents are emitted. `staff_notes.csv` is free text — what someone
wrote down about a SKU that week, deliberately unnormalised, covering 55% of
the weeks where something went wrong. `goods_received.csv` is the one that carries
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

One distinction worth noting: a *byte-identical* row appearing twice is an
export artifact and gets dropped, while a genuine till double-scan produces a
separate transaction and is kept. The second one is a real discrepancy the
system exists to catch, not noise to clean away.

Matching on the transaction id alone was not enough, and the integrity test
proved it — see *What the integrity test caught, twice*.

## Baseline

How far the rules get with no model involved, on the default seed:

```
overall accuracy  115/150  (76.7%)
rules committed        40  (100% precision)
left as residue        35  (23.3%)
```

Over 40 seeds — 1585 commitments, **zero misclassifications**:

| Cause | Recall (40 seeds) | Bounded by |
|---|---|---|
| `unit_mismatch` | 100% | — |
| `late_delivery` | 100% | — |
| `late_carryover` | 100% | — |
| `duplicate_scan` | 98.5% | pairs it cannot time |
| `short_delivery` | 69.0% | GRN coverage (70%) |

Accuracy ranges 59.3%–80.7% across seeds, mean 70.0%. The spread is the
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
  pair on till narrowed it; a later sweep found the coincidence still firing
  on one busy till, so the rule now also requires the two sales to be within
  two minutes of each other. A re-ring happens while the operator is still
  standing there. Sales with no recorded time cannot establish adjacency, so
  the rule declines them — which is the 1.5% of recall it gives up.

Both fixes add evidence rather than thresholds.

### What the integrity test caught, twice

**A clean week that sold stock it never had.** The check failed on
`FRZ-5001-W05: label=none but discrepancy=1`. A week opened with 11 units, received 6, and sold 18 — more
than ever existed — because the sales draw had a floor of 15 regardless of
stock on hand. The negative close was then floored at zero, and that clamp
manufactured a one-unit discrepancy in a case labelled clean.

Sales are now drawn against what is actually available once the planted
fault has taken its bite, and a negative close raises instead of clamping.
Silently flooring it corrupts the evaluation set rather than the run that
produced it, which is the more expensive failure: every accuracy figure
measured afterwards is quietly wrong.

**A real sale deleted as a duplicate.** Sweeping 40 seeds turned up a second
clean week carrying a −13 discrepancy. Two unrelated sales — different SKU,
date, quantity and till — had drawn the same random `transaction_id`, and
ingest dropped the second as an export artifact, deleting 13 units of real
revenue and inventing a shortfall in a week that balanced.

Deduplication now matches on the whole row, since a faulty export repeats a
row outright and every field agrees. Two rows sharing an id while disagreeing
on everything else are two real sales, and the generator no longer mints
colliding ids in the first place. Zero integrity violations across 60 seeds.

## The agent layer, and what measuring it showed

35 cases reach the agent on the default seed — mostly `miscount` (17) and
`unlogged_wastage` (16). They are numerically identical small negative gaps,
separable only with context.

Before building anything, the residue was measured for how much context is
*there to use* — the accuracy a perfect classifier could reach given every
available feature:

| Classifier over the residue | Accuracy |
|---|---|
| Majority class (always guess the mode) | 41.5% |
| Structured features only, Bayes-optimal | ~78% |
| Heuristic control, structure only | 75.0% |
| **Heuristic control + keyword-matched notes** | **83.4%** |
| **Ceiling if the informative notes were read** | **88.8%** |

Measured over 1798 residue cases across 40 seeds. End-to-end, rules plus the
control reconcile **95.0%** of all cases.

The first measurement said don't build it. On structured features alone the
control reached 75.0% against a 78% ceiling — three points of headroom, which
does not pay for a model call per case. That context is *structured*, and
structured context is what code is good at.

So the evidence changed rather than the prompt. Staff notes are the only
thing in this dataset that records what a person actually saw, and they are
written the way people write: `binned 5 butter, past date`, but also
`had to pull 4 yoghurt — wouldn't keep till Monday` and `third week running
we're down on paper`.

**A keyword list reads 57.8% of the notes and never misreads one.** The other
**418 — 23% of the whole residue — are phrased too obliquely for any word
list**, and that is precisely the 5.4 points between the control and the
ceiling. Recognising that *wouldn't keep till Monday* means spoilage, and
that *third week running* means recurrence, is the thing a language model
does and a regex cannot.

That is a quantified case for a model rather than an assumed one — and it is
5.4 points on the residue, which is about 1.3 points end-to-end. Whether that
pays is a cost decision, and it tilts sharply as the free-text share grows:
a real store's evidence is far more note and far less spreadsheet.

The agent is implemented and correct — three schema-validated tools, prompt
caching on the shared prefix, structured verdicts, per-case token accounting
— and stays off by default:

```bash
python3 -m src.recon.agent                   # heuristic control (free, offline)
RECON_USE_MODEL=1 python3 -m src.recon.agent  # same harness, via Claude

# Only the cases whose notes defeat a keyword list — a quarter of the calls,
# and the only cases where the two can disagree on evidence rather than luck.
RECON_ONLY_CONTESTED=1 RECON_USE_MODEL=1 python3 -m src.recon.agent
```

Both paths print every case against the control and the truth, and write the
full record to `data/agent_verdicts.json`. A run that reports a summary and
five example rows makes the next question cost another run.

The control is not a mock. It answers the same tool calls against the same
evidence, so CI exercises the whole harness on every push without an API key,
and the number it produces is the bar the model has to clear.

### What running it actually showed

Claude scored **7/9 on the contested cases — identical to the control, on
every case, including both misses**. It called all three tools every time, so
retrieval was not the problem. The measurement did not show a model advantage.

It did something more useful. Both misses came with rationales, and both
rationales were right about the evidence:

- On one case the model said *"the staff note is irrelevant (drinks bay
  planogram)"*. It was: **9% of contested cases carry a pure noise note**, so
  there was nothing to read and nobody could have won it.
- On the other it declined to trust a note claiming a three-week run of
  losses, because *"history shows zero unexplained negative weeks, so the
  staff note isn't corroborated by the record"*. That was also true —
  **half the recurrence-claiming notes contradicted the record**, because the
  generator wrote "third week running" without checking whether the record
  carried a run.

The second one is a broken evaluation signal: a model that trusts the note
scores well, and a model that cross-checks it scores badly. That inverts what
the eval is supposed to reward. Recurrence notes are now only emitted once the
record actually shows the pattern, and a test pins it.

So the model earned its keep here by auditing the dataset rather than by
beating the baseline — which is worth more than the 5.4 points would have
been. A note on scale, though: 9 contested cases cannot resolve a 5.4-point
effect. That comparison is directional at best, and calling the tie a result
would be reading noise.

One artifact worth recording: a returned `rationale` came back with stray
tokens appended (`</parameter>|<br>...`). The `cause` field was unaffected
because it is schema-constrained to an enum — which is the argument for
constraining the field that drives the decision and treating free text as
advisory.

### An earlier version of this residue was unmeasurable

The first pass planted the three judgement causes uniformly across the
catalogue, distinguished only by magnitude — and their magnitude ranges
overlap almost entirely. Measured, that residue had a Bayes ceiling of
**61.3%** against a 43.5% majority baseline, and an optimal classifier
*never predicted shrinkage at all*, because shrinkage was never the most
likely cause at any magnitude. The `high_value` flag was pure noise: 26% of
shrinkage cases against a 24% base rate, despite a taxonomy note claiming
theft concentrates on high-value lines.

So the generator, not the agent, was the limit. Spoilage now lands on
short-dated stock and scales with volume handled; theft lands on a fixed set
of theft-prone lines and recurs across weeks. `miscount` deliberately got no
pattern at all — it is the residual explanation, and it should be the hard
one. Ceiling moved 61.3% → 78%, and shrinkage became predictable.

## Status

Built:

- Domain model and cause taxonomy
- Synthetic data generator with planted ground truth, five source documents
  including goods-received notes at realistic partial coverage
- Ingestion and normalisation layer with quarantine
- Deterministic rules layer, with pair rules spanning adjacent periods
- Evaluation harness reporting per-cause precision and recall
- Free-text staff notes, and the measurement showing they are where a reader
  earns its place
- Agent layer over the residue: three schema-validated retrieval tools,
  prompt caching, structured verdicts, token accounting, and a no-model
  control that doubles as the offline test double
- 49 tests: dataset integrity, generator invariants, per-rule declining
  cases, a multi-seed precision check, a label-leakage guard, and pinned
  baselines for both layers
- CI running the whole pipeline on every push

Next:

- Run the model path against the control and record the delta (needs an API
  key; the harness and the bar are both in place)
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
python3 -m src.recon.agent             # classifies the residue (control)
python3 -m unittest discover -s tests -t .
```

Standard library only — generator, ingestion, rules, evaluation, the
heuristic control, and all 49 tests. That is what keeps CI free and offline.

The agent's model path is the one exception:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-agent.txt
export ANTHROPIC_API_KEY=sk-ant-...        # from console.anthropic.com
RECON_USE_MODEL=1 python3 -m src.recon.agent
```

Run it from the repository root — `python3 -m src.recon.agent` resolves
`src/` relative to the working directory.
