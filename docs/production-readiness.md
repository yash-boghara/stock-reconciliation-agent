# Production readiness

An honest account of the distance between this repository and something
running against a real retailer's data, written so that the gap is a plan
rather than a surprise.

Nothing here is aspirational. Where a limit is quoted it was measured, and
where it is extrapolated it says so.

---

## What already holds up

Worth stating plainly, because the list below is long and the answer is not
"start again":

- **The domain model and rules layer.** Precision is 100% over 3,891
  committed causes across 100 seeds. The rules are evidence-driven and
  decline rather than guess, which is the property that lets anything post
  unattended.
- **The routing and the decision log.** Auto-post gating, the value
  threshold, escalation, and a SQLite audit trail of who decided what and
  when. This is the shape a control-conscious system needs, already built.
- **The evaluation harness.** Wilson intervals, McNemar for paired
  comparisons, held-out ceiling estimation, per-tool ablation. It is the
  reason every number here is checkable.
- **The agent layer.** Schema-constrained verdicts, three retrieval tools,
  prompt caching, selective retries, cost and latency accounting.

The pipeline is roughly a quarter of a production system. The rest is
integration, controls, and replacing the measurement scaffolding that only
works because the data is synthetic.

---

## What breaks, in order of how much it hurts

### 1. The evaluation stops existing

This is the deepest problem and the one most easily missed, because
everything still *runs*.

Every accuracy figure in this project — 100% rules precision, 84.1% on the
residue, the 89.5% ceiling — is measured against `labels.csv`, which exists
only because a generator planted each cause. **In production there are no
labels.** The harness does not degrade gracefully; it has nothing to score
against.

What replaces it:

- **Reviewer agreement**, already built (`review stats`). It answers "did the
  person who had to act on this agree with us", which is the accuracy signal
  that survives contact with a real store. It is also biased: reviewers
  anchor on the drafted cause, so agreement overstates correctness.
- **A periodically adjudicated sample.** Roughly 30 cases a week, decided by
  someone who has not seen the system's answer, is enough to keep precision
  measurable with a usable interval. Without this you are flying blind the
  moment you go live, and no amount of test coverage substitutes.
- **Drift alarms** on the things that move before accuracy does: rejection
  rate, amendment rate, the share of cases reaching the residue, and the
  distribution of causes.

**Do this first.** Everything else is engineering; this is the difference
between a system you can trust and one you merely hope about.

### 2. Ingestion is a fiction

The generator produces deliberately messy but *structurally consistent*
input. Real exports are worse in ways that cannot be anticipated from a
synthetic file:

- Per-client schema mapping, and a new mapping every time a client changes
  their POS.
- **Late-arriving data.** A docket lands three days after the week closed —
  which this system models as a cause, but does not handle as an operational
  event requiring recomputation.
- **Restatements.** Someone re-runs a stocktake and last week changes.
  Corrections already posted against the old numbers have to be reconciled.
- Timezones and period boundaries. A store closing at 11pm Sunday does not
  align to UTC weeks, and getting this wrong silently shifts sales between
  periods — which manufactures discrepancies, the exact failure the
  integrity test exists to catch.
- Partial and duplicate files, encoding drift, and a supplier who sends the
  same docket twice with different totals.

The quarantine design is right and already in place. What is missing is
everything about *operating* an ingest: idempotent reloads, watermarks, and
an alert when a source goes quiet.

### 3. Posting is a print statement

"Auto-post" writes to a log. It does not write to a ledger.

Real posting needs the ERP integration and — more importantly — **a reversal
path**. The first incorrect auto-post is not a risk, it is a certainty; the
question is whether it can be undone in one command with an audit record, or
whether it becomes an afternoon of manual journal entries. Build the reversal
before the posting.

It also needs the auto-post threshold to be a signed-off policy rather than a
constant in a Python file, and a kill switch that stops unattended posting
without stopping the pipeline.

### 4. Identity is an honour system

`review approve CASE --by "priya s"` takes that name on trust. Anything
touching a ledger needs real authentication, and per-role permissions —
specifically, who may approve above the value threshold, and who may change
the threshold.

### 5. Memory, not compute

Measured, ingesting one store's data with everything held in memory:

| Volume | POS rows | Peak memory | Ingest time |
|---|---:|---:|---:|
| 104 weeks, 25 SKUs (measured) | 12,464 | 18 MB | 0.15 s |
| 1 store, 1 week (extrapolated) | ~400,000 | ~0.6 GB | ~5 s |
| 1 store, 1 year (extrapolated) | ~20,000,000 | **~29 GB** | ~4 min |

Cost scales at roughly **1,450 bytes of resident memory per POS row**, and
compute is linear and cheap — 4 minutes for a store-year is fine.

So the wall is memory, and it is a design property rather than a tuning
problem: `build_cases` materialises every row before assembling anything. A
week at a time fits comfortably on a normal machine; a year does not, and a
chain is not close.

The fix is streaming ingest plus a real database, with cases assembled per
SKU-period rather than by loading the world. That is a rewrite of one module,
not of the system — the layers above it already work case by case.

---

## Operational gaps

Smaller individually, but each one is a 3am problem the first time it bites:

- **Configuration and secrets** per environment. The API key is currently an
  environment variable read at the point of use.
- **Structured logging and metrics.** The pipeline prints; it does not emit.
- **Cost controls.** A spend cap and a per-run ceiling on model calls. Cost
  is measured at **$0.0147 per case** — cheap until a bad loop makes it not.
- **Scheduling and backfill.** Weekly runs, plus the ability to re-run a
  closed period without duplicating corrections. The decision log replaces a
  run rather than appending, which is the right primitive; it has not been
  exercised against a real reprocessing.

---

## How I would sequence it

1. **Shadow mode.** Run against real data, post nothing, show the queue to
   one reviewer. This exercises ingestion against reality and starts
   accumulating agreement data, at zero risk.
2. **Adjudicated sample.** Stand up the weekly hand-labelled sample from day
   one of shadow mode, so precision is measurable before anything is trusted.
3. **Reversal path, then posting.** Wire the ERP write only once undo works.
4. **Auto-post the safest slice.** Begin with a single rule and a value
   threshold well below the modelled one, widen on evidence.
5. **Scale the ingest** when volume demands it, not before.

Steps 1 and 2 answer the question that matters — does this work on real data
— and neither requires the risky parts.

---

## What I would not build

- **A web interface**, until a reviewer has used the command line and said
  what is missing. The interesting constraints are in the decision record,
  not the form.
- **Retrieval over historical resolutions.** The natural next tool, but it
  needs a corpus of real decisions to retrieve from. Building it against
  synthetic history would measure the generator.
- **A model in the auto-post path.** The measured gap between the rules layer
  (100%) and a high-confidence judgement (99.5%) is the gap between proved
  and usually right. Widening what posts unattended should come from a longer
  clean record, not from a better prompt.
- **Fine-tuning.** No training set worth the name, and the ceiling analysis
  puts the remaining headroom in reading free text — which a general model
  already does well.

---

## Honest effort

For one retailer, one store, shadow mode: **a few weeks**, dominated by
ingestion and the adjudication process rather than by anything in this
repository.

To posting, with reversal, auth, and controls: **a quarter**, most of it
integration and sign-off rather than code.

Chain scale: a different project, and one that should be started only after
the single-store version has a measured agreement rate worth defending.
