"""The evaluation harness: every number this project claims, reproducible.

A README figure nobody can regenerate is an assertion. This module is the
answer to "how do you know?" — it runs the whole pipeline across many seeds
and reports each claim with an interval around it, so a reader can see not
just the estimate but how much of it is noise.

Three things it does that a single accuracy print cannot.

**Intervals, not point estimates.** Every rate carries a Wilson score
interval. A 5-point difference measured on 35 cases is not a difference, and
the interval is what makes that obvious instead of arguable.

**Paired tests for paired questions.** Model versus control is not two
independent samples — both classify the same cases from the same evidence.
Only the cases where they disagree carry information, which is McNemar's
test, and it is why 7/9 against 7/9 is uninformative rather than a tie.

**A ceiling, fitted honestly.** The Bayes-optimal ceiling is estimated on
one set of seeds and measured on another. Fitting and reporting on the same
data would produce a ceiling that flatters whatever the data happened to do.

Standard library only — no scipy — so the harness runs anywhere the rest of
the project does.
"""

from __future__ import annotations

import math
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .agent import CaseFile, HeuristicClient, classify_residue, residue_cases
from .correct import Route, build_queue, summarise
from .evaluate import load_labels
from .generate import NOISE_NOTES, generate
from .ingest import build_cases
from .models import CATALOGUE_INDEX, Cause
from .rules import classify

# Staff write about the whole shop. A note existing is not evidence, so the
# reader ceiling must not credit one that says nothing about the cause.
NOISE_STEMS = tuple(n.split("{")[0].strip().lower()[:16] for n in NOISE_NOTES)

TRAIN_SEEDS = range(1, 61)
TEST_SEEDS = range(61, 101)


# ----------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Rate:
    """A proportion with a Wilson score interval around it.

    Wilson rather than the normal approximation because these samples are
    small and the rates run close to 1, exactly where the normal interval
    misbehaves — it happily reports an upper bound above 100%.
    """

    correct: int
    total: int
    z: float = 1.96

    @property
    def point(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        n = self.total
        if n == 0:
            return (0.0, 0.0)
        p, z = self.point, self.z
        denom = 1 + z**2 / n
        centre = (p + z**2 / (2 * n)) / denom
        spread = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
        return (max(0.0, centre - spread), min(1.0, centre + spread))

    def __str__(self) -> str:
        low, high = self.interval
        return f"{self.point:.1%} [{low:.1%}–{high:.1%}] (n={self.total})"


def mcnemar(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value for paired binary outcomes.

    Only the discordant pairs carry information: cases both classifiers got
    right, or both got wrong, say nothing about which is better. Under the
    null the discordant pairs split like a fair coin, so this is an exact
    binomial test on that split.
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


# ----------------------------------------------------------------------
# Running the pipeline
# ----------------------------------------------------------------------

@dataclass
class CaseRecord:
    """One case, as every layer saw it. The unit all reporting is built on."""

    seed: int
    case_id: str
    truth: str
    discrepancy: int
    perishable: bool
    high_value: bool
    rules_resolved: bool
    rules_cause: str | None
    control_cause: str | None          # with notes
    control_no_notes_cause: str | None     # notes ablated away
    control_no_history_cause: str | None    # SKU history ablated away
    control_bare_cause: str | None          # profile only
    has_note: bool
    keyword_readable: bool
    informative_note: bool  # a note that actually says something about the cause


def run_seed(seed: int) -> tuple[list[CaseRecord], dict]:
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp)
        generate(raw, seed=seed)
        labels = load_labels(raw)
        result = build_cases(raw)
        findings = classify(result)
        casefile = CaseFile(result, findings)
        control = HeuristicClient(casefile)

        with_notes = classify_residue(result, findings)
        without_notes = classify_residue(result, findings, use_notes=False)
        without_history = classify_residue(result, findings, use_history=False)
        bare = classify_residue(result, findings, use_notes=False,
                                use_history=False)
        queue = build_queue(result, findings, with_notes)

        records = []
        for case in result.cases:
            finding = findings[case.case_id]
            sku = CATALOGUE_INDEX[case.sku_id]
            in_residue = not finding.resolved
            notes = casefile.get_staff_notes(case.case_id)["notes"] if in_residue else []
            records.append(CaseRecord(
                seed=seed,
                case_id=case.case_id,
                truth=labels[case.case_id],
                discrepancy=case.discrepancy,
                perishable=sku.perishable,
                high_value=sku.high_value,
                rules_resolved=finding.resolved,
                rules_cause=finding.cause.value if finding.resolved else None,
                control_cause=(with_notes[case.case_id].cause.value
                               if in_residue else None),
                control_no_notes_cause=(without_notes[case.case_id].cause.value
                                        if in_residue else None),
                control_no_history_cause=(without_history[case.case_id].cause.value
                                          if in_residue else None),
                control_bare_cause=(bare[case.case_id].cause.value
                                    if in_residue else None),
                has_note=bool(notes),
                keyword_readable=(in_residue
                                  and control._match_notes(case) is not None),
                informative_note=bool(notes) and not all(
                    any(stem and stem in n["text"].lower() for stem in NOISE_STEMS)
                    for n in notes
                ),
            ))
        return records, summarise(queue)


def run(seeds) -> tuple[list[CaseRecord], list[dict]]:
    records: list[CaseRecord] = []
    queues: list[dict] = []
    for seed in seeds:
        seed_records, queue_summary = run_seed(seed)
        records += seed_records
        queues.append(queue_summary)
    return records, queues


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------

def rules_precision(records: list[CaseRecord]) -> Rate:
    """Of the causes the rules layer committed to, how many were right.

    Clean cases are excluded: `none` is the overwhelming majority class, and
    including it would inflate precision with the easiest possible calls.
    """
    committed = [r for r in records
                 if r.rules_resolved and r.rules_cause != Cause.NONE.value]
    return Rate(sum(1 for r in committed if r.rules_cause == r.truth), len(committed))


def rules_recall(records: list[CaseRecord]) -> dict[str, Rate]:
    out = {}
    for cause in (c.value for c in Cause if c is not Cause.NONE):
        support = [r for r in records if r.truth == cause]
        if support:
            out[cause] = Rate(
                sum(1 for r in support if r.rules_cause == cause), len(support))
    return out


def residue_rates(records: list[CaseRecord]) -> dict[str, Rate]:
    residue = [r for r in records if not r.rules_resolved]
    n = len(residue)
    majority = Counter(r.truth for r in residue).most_common(1)[0][0]
    # Only a note that is both informative and beyond a keyword list is worth
    # anything to a reader. Anything else, the structural control already has.
    readable_by_reader = {
        (r.seed, r.case_id) for r in residue
        if r.informative_note and not r.keyword_readable
    }

    return {
        "majority": Rate(sum(1 for r in residue if r.truth == majority), n),
        "profile_only": Rate(
            sum(1 for r in residue if r.control_bare_cause == r.truth), n),
        "no_history": Rate(
            sum(1 for r in residue if r.control_no_history_cause == r.truth), n),
        "control_structure_only": Rate(
            sum(1 for r in residue if r.control_no_notes_cause == r.truth), n),
        "control_with_notes": Rate(
            sum(1 for r in residue if r.control_cause == r.truth), n),
        # A perfect reader gets every case whose note is informative; the
        # rest it can only do as well as the structural control does.
        "reader_ceiling": Rate(
            len(readable_by_reader)
            + sum(1 for r in residue
                  if (r.seed, r.case_id) not in readable_by_reader
                  and r.control_cause == r.truth),
            n),
    }


def end_to_end(records: list[CaseRecord]) -> Rate:
    return Rate(
        sum(1 for r in records
            if (r.rules_cause if r.rules_resolved else r.control_cause) == r.truth),
        len(records))


def bayes_ceiling(train: list[CaseRecord], test: list[CaseRecord]) -> dict[str, Rate]:
    """Best achievable accuracy from each feature set, fitted then measured.

    Fitting the lookup and scoring it on the same records would report how
    well the table memorised the data, not what the features are worth.
    """
    feature_sets = {
        "discrepancy": lambda r: (r.discrepancy,),
        "+ perishable": lambda r: (r.discrepancy, r.perishable),
        "+ perishable + high_value": lambda r: (r.discrepancy, r.perishable, r.high_value),
    }
    train_residue = [r for r in train if not r.rules_resolved]
    test_residue = [r for r in test if not r.rules_resolved]
    fallback = Counter(r.truth for r in train_residue).most_common(1)[0][0]

    out = {}
    for name, key in feature_sets.items():
        table: dict = defaultdict(Counter)
        for r in train_residue:
            table[key(r)][r.truth] += 1
        best = {k: c.most_common(1)[0][0] for k, c in table.items()}
        out[name] = Rate(
            sum(1 for r in test_residue if best.get(key(r), fallback) == r.truth),
            len(test_residue))
    return out


def notes_breakdown(records: list[CaseRecord]) -> dict[str, int]:
    residue = [r for r in records if not r.rules_resolved]
    noted = [r for r in residue if r.has_note]
    return {
        "residue": len(residue),
        "noted": len(noted),
        "keyword_readable": sum(1 for r in noted if r.keyword_readable),
        "informative_but_oblique": sum(
            1 for r in noted if r.informative_note and not r.keyword_readable),
        "noise_only": sum(1 for r in noted if not r.informative_note),
    }


def compare(records: list[CaseRecord], model: dict[str, str]) -> dict:
    """Paired comparison of a model against the control, on shared cases.

    Reports the discordant counts and a McNemar p-value, because that is
    what decides whether a difference in totals means anything.
    """
    paired = [r for r in records
              if r.case_id in model and r.control_cause is not None]
    model_only = sum(1 for r in paired
                     if model[r.case_id] == r.truth and r.control_cause != r.truth)
    control_only = sum(1 for r in paired
                       if r.control_cause == r.truth and model[r.case_id] != r.truth)
    return {
        "paired": len(paired),
        "model": Rate(sum(1 for r in paired if model[r.case_id] == r.truth), len(paired)),
        "control": Rate(sum(1 for r in paired if r.control_cause == r.truth), len(paired)),
        "model_only_correct": model_only,
        "control_only_correct": control_only,
        "p_value": mcnemar(model_only, control_only),
    }


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------

def _row(label: str, rate: Rate) -> str:
    low, high = rate.interval
    return (f"| {label} | {rate.point:.1%} | {low:.1%} – {high:.1%} | "
            f"{rate.correct:,} / {rate.total:,} |")


def render(train: list[CaseRecord], test: list[CaseRecord],
           queues: list[dict]) -> str:
    everything = train + test
    seeds = len({r.seed for r in everything})
    notes = notes_breakdown(everything)
    residue = residue_rates(everything)
    ceilings = bayes_ceiling(train, test)

    auto = sum(q["by_route"].get("auto", {}).get("count", 0) for q in queues)
    posted = sum(q["corrections"] for q in queues)
    value = sum(q["value_nzd"] for q in queues)

    lines = [
        "# Evaluation",
        "",
        f"Generated by `python3 -m src.recon.eval_report` over **{seeds} seeds** "
        f"({len(everything):,} cases). Every figure carries a 95% Wilson "
        "interval; a rate without one is an assertion.",
        "",
        "## Headline",
        "",
        "| Measure | Rate | 95% interval | Count |",
        "|---|---:|---:|---:|",
        _row("Rules precision (committed causes)", rules_precision(everything)),
        _row("End to end (rules + control)", end_to_end(everything)),
        _row("Residue — control with notes", residue["control_with_notes"]),
        "",
        "Rules precision is measured over committed causes only. Clean weeks are "
        "excluded: `none` is the majority class and counting it would inflate "
        "the figure with the easiest calls in the set.",
        "",
        "## Rules — recall by cause",
        "",
        "| Cause | Recall | 95% interval | Count |",
        "|---|---:|---:|---:|",
    ]
    for cause, rate in sorted(rules_recall(everything).items(),
                              key=lambda kv: -kv[1].point):
        lines.append(_row(f"`{cause}`", rate))

    lines += [
        "",
        "The three at zero are the judgement causes; the rules layer is not "
        "supposed to reach them. `short_delivery` is bounded by how often a "
        "goods-received note exists to prove it (70% by construction).",
        "",
        "## Residue — what each layer of evidence is worth",
        "",
        "| Classifier | Accuracy | 95% interval | Count |",
        "|---|---:|---:|---:|",
        _row("Majority class", residue["majority"]),
        _row("Control, structured features only", residue["control_structure_only"]),
        _row("Control + keyword-matched notes", residue["control_with_notes"]),
        _row("Ceiling if notes were read properly", residue["reader_ceiling"]),
        "",
        "### What each retrieval tool is worth",
        "",
        "The agent has three tools. Each was ablated through the control "
        "itself rather than a reimplementation, so this measures the tool and "
        "not a copy of it.",
        "",
        "| Evidence available | Accuracy | 95% interval | Count |",
        "|---|---:|---:|---:|",
        _row("Nothing (majority class)", residue["majority"]),
        _row("+ `get_sku_profile`", residue["profile_only"]),
        _row("+ `get_sku_history`", residue["control_structure_only"]),
        _row("+ `get_staff_notes`", residue["control_with_notes"]),
        "",
        f"Profile carries most of it "
        f"({residue['profile_only'].point - residue['majority'].point:+.1%}), "
        f"notes add "
        f"{residue['control_with_notes'].point - residue['control_structure_only'].point:+.1%}, "
        f"and history adds "
        f"{residue['control_structure_only'].point - residue['profile_only'].point:+.1%} "
        "— small, but it is the only evidence that distinguishes a recurring "
        "loss from a one-off, which is the entire shrinkage signal. All three "
        "earn their place; none is there on faith.",
        "",
        f"Of {notes['residue']:,} residue cases, {notes['noted']:,} carry a note. "
        f"A keyword list reads {notes['keyword_readable']:,} of them; "
        f"{notes['informative_but_oblique']:,} say something about the cause but "
        f"are phrased beyond any word list, and {notes['noise_only']:,} are pure "
        "noise that nobody could use.",
        "",
        "**The gap between the last two rows is the entire case for a language "
        "model here**, and it is bounded: it lives only in those oblique notes.",
        "",
        "## Ceiling from structured features alone",
        "",
        f"Fitted on {len({r.seed for r in train})} seeds, measured on "
        f"{len({r.seed for r in test})} held out. Fitting and scoring on the same "
        "data would report memorisation rather than what the features are worth.",
        "",
        "| Features | Best achievable | 95% interval | Count |",
        "|---|---:|---:|---:|",
    ]
    for name, rate in ceilings.items():
        lines.append(_row(name, rate))

    lines += [
        "",
        "## Corrections",
        "",
        f"Across {seeds} seeds the system drafted {posted:,} corrections worth "
        f"NZ${value:,.2f}, of which **{auto:,} ({auto / posted:.0%}) post "
        "automatically** — rule-certain, under the review threshold, and never "
        "seen by a person.",
        "",
        "## Reading this",
        "",
        "Overlapping intervals are not a difference. The control-with-notes and "
        "reader-ceiling rows are separated by a few points, which is why the "
        "model comparison uses a paired test (McNemar) on the cases where the "
        "two actually disagree, rather than comparing totals — see "
        "[FINDINGS.md](../FINDINGS.md).",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import os

    root = Path(__file__).resolve().parents[2]
    quick = os.environ.get("RECON_QUICK_EVAL")
    train_seeds = range(1, 16) if quick else TRAIN_SEEDS
    test_seeds = range(16, 26) if quick else TEST_SEEDS

    train, train_queues = run(train_seeds)
    test, test_queues = run(test_seeds)

    report = render(train, test, train_queues + test_queues)
    out = root / "docs" / "evaluation.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report)

    everything = train + test
    print(f"seeds        : {len({r.seed for r in everything})}")
    print(f"cases        : {len(everything):,}")
    print(f"rules prec.  : {rules_precision(everything)}")
    print(f"end to end   : {end_to_end(everything)}")
    for name, rate in residue_rates(everything).items():
        print(f"  {name:<26}{rate}")
    print(f"\nwritten to {out.relative_to(root)}")
