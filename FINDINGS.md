# Findings

What measuring this system actually turned up. Most of it is the dataset
being wrong in ways that would have flattered the results, which is the
failure mode a synthetic evaluation is most prone to and least likely to
notice.

---

## The residue had no signal in it

Before building the agent layer, the residue was measured for how much
context existed to use — the accuracy a perfect classifier could reach given
every available feature.

| Classifier over the residue | Accuracy |
|---|---|
| Majority class (always guess the mode) | 43.5% |
| Bayes-optimal, all features | **61.3%** |

Worse than the number: an optimal classifier **never predicted shrinkage at
any magnitude**, because shrinkage was never the most likely cause anywhere
in the range. Its recall was structurally zero.

The cause was the generator. The three judgement causes were planted
uniformly across the catalogue and separated only by magnitude, and their
magnitude ranges overlap almost entirely. The `high_value` flag was pure
noise — 26% of shrinkage cases against a 24% base rate — despite a taxonomy
note claiming theft concentrates on high-value lines.

So the generator was the limit, not the agent. Spoilage now lands on
short-dated stock and scales with volume handled; theft lands on a fixed set
of theft-prone lines and recurs across weeks. `miscount` deliberately got no
pattern at all — it is the residual explanation, and it should be the hard
one.

Ceiling moved **61.3% → 78%**, and shrinkage became predictable.

---

## A 20-line control reached the ceiling

With the residue fixed, the obvious next step was an LLM. Measuring first
said otherwise.

| Classifier over the residue | Accuracy |
|---|---|
| Majority class | 41.5% |
| Structured features, Bayes-optimal | ~78% |
| Heuristic control, structured features only | **75.0%** |

A deterministic function landed within three points of information-theoretic
optimal. The context separating these causes — is the line short-dated, is it
theft-prone, has it lost stock before — is *structured*, and structured
context is what code is good at. A model call per case bought at most three
points.

That is the finding the project exists to produce: measure the cheap layer
before assuming the expensive one is needed.

---

## Free text is where a reader earns its place

So the evidence changed rather than the prompt. `staff_notes.csv` records
what a person wrote about a SKU that week — `binned 5 butter, past date`, but
also `had to pull 4 yoghurt — wouldn't keep till Monday` and `third week
running we're down on paper`.

| Classifier over the residue | Accuracy | 95% interval |
|---|---|---|
| Heuristic control, structure only | 76.0% | 74.7 – 77.2 |
| **Control + keyword-matched notes** | **84.1%** | 83.0 – 85.1 |
| **Ceiling if the informative notes were read** | **89.5%** | 88.6 – 90.4 |

Measured over 100 seeds / 4,655 residue cases. The intervals on the last two
rows do not overlap, so the gap is a real effect rather than a plausible one.

A keyword list reads 57.6% of notes and never misreads one. Another **23% of
the residue carries a note that says something about the cause but is phrased
beyond any word list**, and that is precisely the 5.4 points between the
control and the ceiling. A further 3% of notes are pure noise, which the
ceiling correctly refuses to credit to anyone.

Recognising that *wouldn't keep till Monday* means spoilage, and that *third
week running* means recurrence, is what a language model does and a regex
cannot. That is a quantified case for a model rather than an assumed one.

---

## Running the model audited the dataset instead of beating it

On the contested cases — the only ones where the two can disagree on
evidence rather than luck — **Claude scored 7/9 and the control scored 7/9,
identical on every case, both misses included**. It called all three tools
every time, so retrieval was not the problem.

Nine cases cannot resolve a 5.4-point effect, so that tie is noise, not a
result. The rationales were the valuable part, because both misses came with
reasoning that was right about the evidence:

- *"The staff note is irrelevant (drinks bay planogram)"* — correct. **9% of
  contested cases carry a pure noise note**, so nothing could be read and
  nobody could have won it.
- *"History shows zero unexplained negative weeks, so the staff note isn't
  corroborated by the record"* — also correct, and serious. **Half the
  recurrence-claiming notes contradicted the record**, because the generator
  wrote *third week running* without checking whether a run existed.

The second inverted the evaluation: trusting an uncorroborated note scored
better than auditing it, which is the opposite of what the eval should
reward. Recurrence phrasings are now only emitted once the record carries the
pattern, with a test pinning it across four seeds.

One artifact worth recording: a returned `rationale` came back with stray
tokens appended (`</parameter>|<br>...`). The `cause` field was unaffected
because it is schema-constrained to an enum — an argument for constraining
the field that drives the decision and treating free text as advisory.

---

## What one seed hid

An early version of the rules table read 100% precision on the default seed.
A sweep across 30 seeds found 8 misclassifications it had concealed, in two
channels:

- **A routine docket read as a late invoice.** The window that catches late
  paperwork also catches next week's ordinary delivery, which sits one to
  three days past the count for innocent reasons. The rule now requires
  either that no delivery was booked to the period at all, or a receiving
  note placing the stock on the shelf before the count.
- **Ordinary trade read as a double-scan.** Two customers buying the same
  quantity on the same day is not a till error. Keying on till narrowed it; a
  later sweep found it still firing on one busy till, so the rule now also
  requires the two sales to be within two minutes. A re-ring happens while
  the operator is still standing there. Sales with no recorded time cannot
  establish adjacency, so the rule declines them — the 1.5% of recall it
  gives up.

Both fixes add evidence rather than thresholds.

---

## What the integrity test caught, three times

The dataset-integrity check asserts that every planted label agrees with the
discrepancy the pipeline observes. It failed three times, each time on a
defect that would have quietly corrupted every downstream number.

**A clean week that sold stock it never had.** `FRZ-5001-W05` opened with 11
units, received 6, and sold 18 — more than ever existed — because the sales
draw had a floor of 15 regardless of stock on hand. The negative close was
floored at zero, and that clamp manufactured a one-unit discrepancy in a case
labelled clean. Sales are now drawn against what is actually available once
the planted fault has taken its bite, and a negative close raises instead of
clamping.

**A real sale deleted as a duplicate.** Sweeping 40 seeds turned up a second
clean week carrying a −13 discrepancy. Two unrelated sales — different SKU,
date, quantity and till — had drawn the same random `transaction_id`, and
ingest dropped the second as an export artifact, deleting 13 units of real
revenue. Deduplication now matches on the whole row, since a faulty export
repeats a row outright and every field agrees. Ids are unique by
construction. Zero violations across 60 seeds.

**A note that contradicted the record**, above.

---

## Things that stayed wrong until measured

- `short_delivery` recall cannot exceed **70%**, because that is how often a
  goods-received note exists to prove it. Without one, an invoice is a single
  number with nothing to contradict it. That ceiling is a property of the
  world, not a bug to tune away.
- GRN coverage was briefly suspected of correlating with cause. It measured
  clean (69.5% over 20 seeds against a configured 70%) — **the correlation
  was an error in the measuring script, not the generator.** Reported here
  because a wrong diagnosis that gets corrected is still part of the record.
