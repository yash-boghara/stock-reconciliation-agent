"""Measure the rules layer against planted ground truth.

The number this exists to produce is how far deterministic checks get on
their own. Until that is known, any claim about what the agent adds is
unfounded — an agent that recovers cases the rules already had is not
earning its cost.

Two figures matter and they are not the same:

    precision  when a rule names a cause, how often it is right
    recall     of the cases with that cause, how many the rules caught

Low recall means work left on the table. Low precision means wrong causes
being acted on, which is worse: a bad correction reaches a human as a
confident recommendation.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .ingest import build_cases
from .models import Cause
from .rules import Finding, classify

RESIDUE = "unresolved"


@dataclass
class Score:
    cause: str
    support: int      # cases truly of this cause
    predicted: int    # cases the rules called this cause
    correct: int

    @property
    def precision(self) -> float:
        return self.correct / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.correct / self.support if self.support else 0.0


def load_labels(raw_dir: Path) -> dict[str, str]:
    with (raw_dir / "labels.csv").open(encoding="utf-8") as fh:
        return {r["case_id"]: r["cause"] for r in csv.DictReader(fh)}


def score(labels: dict[str, str], findings: dict[str, Finding]) -> dict[str, Score]:
    """Per-cause precision and recall, residue counted as its own class.

    Residue is scored rather than dropped. A rules layer that declines
    everything would otherwise look flawless, and declining is exactly the
    behaviour that hands work to the expensive layer.
    """
    causes = sorted({*labels.values(), RESIDUE})
    scores = {c: Score(c, 0, 0, 0) for c in causes}

    for case_id, truth in labels.items():
        finding = findings.get(case_id)
        if finding is None:
            continue
        predicted = finding.cause.value if finding.resolved else RESIDUE

        scores[truth].support += 1
        scores.setdefault(predicted, Score(predicted, 0, 0, 0)).predicted += 1
        if predicted == truth:
            scores[truth].correct += 1

    return scores


def confusion(labels: dict[str, str], findings: dict[str, Finding]) -> dict[tuple, int]:
    matrix: dict[tuple, int] = {}
    for case_id, truth in labels.items():
        finding = findings.get(case_id)
        if finding is None:
            continue
        predicted = finding.cause.value if finding.resolved else RESIDUE
        matrix[(truth, predicted)] = matrix.get((truth, predicted), 0) + 1
    return matrix


def report(raw_dir: Path) -> dict[str, float]:
    labels = load_labels(raw_dir)
    result = build_cases(raw_dir)
    findings = classify(result)
    scores = score(labels, findings)

    total = len(labels)
    correct = sum(s.correct for s in scores.values())
    residue = sum(1 for f in findings.values() if not f.resolved)

    # Precision over cases where a rule actually committed to a cause.
    committed = [
        (labels[cid], f) for cid, f in findings.items()
        if f.resolved and f.cause is not Cause.NONE and cid in labels
    ]
    committed_right = sum(1 for truth, f in committed if f.cause.value == truth)

    print(f"cases                 : {total}")
    print(f"overall accuracy      : {correct}/{total} ({correct / total:.1%})")
    print(f"rules committed       : {len(committed)}")
    if committed:
        print(f"  of which correct    : {committed_right} "
              f"({committed_right / len(committed):.1%} precision)")
    print(f"left as residue       : {residue} ({residue / total:.1%})")
    print()

    print(f"{'cause':<20}{'support':>8}{'pred':>7}{'correct':>9}"
          f"{'prec':>8}{'recall':>8}")
    print("-" * 60)
    for name in sorted(scores):
        s = scores[name]
        if not (s.support or s.predicted):
            continue
        print(f"{name:<20}{s.support:>8}{s.predicted:>7}{s.correct:>9}"
              f"{s.precision:>8.0%}{s.recall:>8.0%}")

    print()
    print("residue composition (what the agent layer would inherit):")
    matrix = confusion(labels, findings)
    residue_rows = sorted(
        ((truth, n) for (truth, pred), n in matrix.items() if pred == RESIDUE),
        key=lambda kv: -kv[1],
    )
    for truth, n in residue_rows:
        print(f"  {truth:<20}{n:>4}")

    mistakes = [
        (truth, pred, n) for (truth, pred), n in matrix.items()
        if truth != pred and pred != RESIDUE
    ]
    if mistakes:
        print()
        print("misclassifications (a rule named the wrong cause):")
        for truth, pred, n in sorted(mistakes, key=lambda t: -t[2]):
            print(f"  {truth} -> {pred}: {n}")

    return {
        "accuracy": correct / total,
        "residue_rate": residue / total,
        "precision": committed_right / len(committed) if committed else 0.0,
    }


if __name__ == "__main__":
    report(Path(__file__).resolve().parents[2] / "data" / "raw")
