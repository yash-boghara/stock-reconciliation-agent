"""The agent layer, over the residue the rules decline to explain.

Everything here operates on cases where arithmetic has already failed. What
is left is a small negative number that could be spoilage, theft, or a bad
count, and telling those apart needs context the case itself does not carry:
what the item is, whether it spoils, whether it is worth stealing, and what
has happened to this SKU in previous weeks.

Two rules govern this module.

**The agent never sees a label.** Every tool reads the pipeline's own output
— the catalogue, the assembled cases, the rules layer's findings. `labels.csv`
is the evaluation set and touching it here would make every accuracy figure
downstream meaningless. There is a test that asserts this.

**The heuristic client is the control, not a mock.** It answers the same tool
calls with the same evidence and no model at all, which makes it both the
offline test double and the number the model has to beat. An agent that only
matches it is not earning its cost.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from .ingest import IngestResult
from .models import CATALOGUE_INDEX, Cause, ReconciliationCase
from .rules import Finding

MODEL = "claude-opus-5"
MAX_TOKENS = 8000

# The causes the rules layer cannot reach. The agent chooses among exactly
# these — offering it the structural causes would invite it to second-guess
# arithmetic that has already been checked.
JUDGEMENT_CAUSES = (
    Cause.UNLOGGED_WASTAGE,
    Cause.SHRINKAGE,
    Cause.MISCOUNT,
    Cause.SHORT_DELIVERY,
)

SYSTEM_PROMPT = """\
You are reconciling stock discrepancies for a New Zealand grocery retailer.

A deterministic rules layer has already run and explained every discrepancy
with a structural signature — unit mismatches, late invoices and their
carryover, till double-scans, and short deliveries provable against a
goods-received note. The cases reaching you are the ones it declined. Do not
re-litigate that arithmetic; it has been checked.

What is left is one of four causes:

- unlogged_wastage: stock damaged or expired and discarded without a wastage
  entry. Concentrated on short-dated lines, and scales with how much stock
  moved through that week.
- shrinkage: theft. Concentrated on small, valuable, easily-pocketed lines,
  and it recurs — a store with a tobacco problem has it most weeks, not once.
- miscount: the stocktake itself is wrong. Respects no pattern at all, which
  is what makes it the residual explanation rather than the first one. It is
  the only cause here that can produce a positive discrepancy.
- short_delivery: the supplier invoiced more than arrived, with no receiving
  note to prove it. Only reachable when a delivery was booked that week.

Use the tools before deciding. The SKU's profile tells you whether spoilage
or theft is even plausible for that line; its history tells you whether this
is a recurring pattern or a one-off. A single small negative on a dry-goods
line with a clean history is a miscount, and saying so plainly is a better
answer than inventing a story.

State your confidence honestly. A reviewer acts on high confidence and
investigates low confidence, so a confident wrong answer costs more than an
uncertain right one.\
"""

TOOLS: list[dict] = [
    {
        "name": "get_sku_profile",
        "description": (
            "Look up what a SKU actually is: description, supplier, case size, "
            "unit cost, whether it is theft-prone, and whether it is "
            "short-dated. Call this first — whether spoilage or theft is "
            "plausible for a line depends entirely on what the line is."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "Canonical SKU, e.g. 'TOB-6001'.",
                },
            },
            "required": ["sku_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_staff_notes",
        "description": (
            "Free-text notes staff wrote against this SKU during the period. "
            "This is the only evidence that records what a person actually "
            "saw, and it frequently names the cause outright — or implies it. "
            "Read it before deciding: a note saying stock was binned past its "
            "date settles a case that the numbers alone cannot. Returns an "
            "empty list when nobody wrote anything, which is common and is "
            "not itself evidence of anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_id": {
                    "type": "string",
                    "description": "The case under review, e.g. 'CHL-4002-W03'.",
                },
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_sku_history",
        "description": (
            "Every other week for this SKU: the discrepancy observed and what "
            "the rules layer concluded, if anything. Use it to tell a "
            "recurring unexplained loss (theft or chronic spoilage) from a "
            "one-off (a bad count). Excludes the case under review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "Canonical SKU, e.g. 'TOB-6001'.",
                },
            },
            "required": ["sku_id"],
            "additionalProperties": False,
        },
    },
]

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "cause": {
            "type": "string",
            "enum": [c.value for c in JUDGEMENT_CAUSES],
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "rationale": {
            "type": "string",
            "description": "One or two sentences citing the evidence used.",
        },
    },
    "required": ["cause", "confidence", "rationale"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Verdict:
    case_id: str
    cause: Cause
    confidence: str
    rationale: str
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


# ----------------------------------------------------------------------
# Tool backend — reads pipeline output only, never labels
# ----------------------------------------------------------------------

@dataclass
class CaseFile:
    """The pipeline's own view of the world, which is all the agent may see."""

    result: IngestResult
    findings: dict[str, Finding]
    _by_sku: dict[str, list[ReconciliationCase]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for case in self.result.cases:
            self._by_sku.setdefault(case.sku_id, []).append(case)
        for cases in self._by_sku.values():
            cases.sort(key=lambda c: c.period_start)

    def get_sku_profile(self, sku_id: str) -> dict:
        sku = CATALOGUE_INDEX.get(sku_id)
        if sku is None:
            return {"error": f"unknown sku: {sku_id}"}
        return {
            "sku_id": sku.sku_id,
            "description": sku.description,
            "supplier": sku.supplier,
            "case_size": sku.case_size,
            "unit_cost_nzd": sku.unit_cost_nzd,
            "theft_prone": sku.high_value,
            "short_dated": sku.perishable,
        }

    def get_staff_notes(self, case_id: str) -> dict:
        evidence = self.result.evidence.get(case_id)
        notes = evidence.notes if evidence else []
        return {
            "notes": [
                {
                    "date": n["note_date"].isoformat(),
                    "author": n["author"],
                    "text": n["text"],
                }
                for n in notes
            ],
        }

    def get_sku_history(self, sku_id: str, exclude_case_id: str = "") -> dict:
        weeks = []
        for case in self._by_sku.get(sku_id, ()):
            if case.case_id == exclude_case_id:
                continue
            finding = self.findings.get(case.case_id)
            weeks.append({
                "case_id": case.case_id,
                "period_end": case.period_end.isoformat(),
                "discrepancy": case.discrepancy,
                "rules_verdict": (
                    finding.cause.value
                    if finding is not None and finding.resolved
                    else "unexplained"
                ),
            })
        unexplained = [
            w for w in weeks
            if w["rules_verdict"] == "unexplained" and w["discrepancy"] < 0
        ]
        return {
            "weeks": weeks,
            "unexplained_negative_weeks": len(unexplained),
            "total_weeks": len(weeks),
        }

    def dispatch(self, name: str, args: dict, case_id: str) -> dict:
        if name == "get_sku_profile":
            return self.get_sku_profile(args.get("sku_id", ""))
        if name == "get_staff_notes":
            return self.get_staff_notes(case_id)
        if name == "get_sku_history":
            return self.get_sku_history(args.get("sku_id", ""), case_id)
        return {"error": f"unknown tool: {name}"}


def build_brief(case: ReconciliationCase, casefile: CaseFile) -> str:
    """What the agent is told before it reaches for a tool."""
    evidence = casefile.result.evidence.get(case.case_id)
    booked = len(evidence.deliveries) if evidence else 0
    return (
        f"Case {case.case_id}\n"
        f"SKU: {case.sku_id}\n"
        f"Period: {case.period_start} to {case.period_end}\n"
        f"Opening count: {case.opening_count}\n"
        f"Delivered (booked this period): {case.delivered_units} "
        f"across {booked} docket(s)\n"
        f"Sold (recorded): {case.sold_units}\n"
        f"Expected close: {case.expected_closing}\n"
        f"Actual close: {case.closing_count}\n"
        f"Discrepancy: {case.discrepancy}\n"
        f"Staff notes on file for this SKU this period: {len(evidence.notes) if evidence else 0}\n\n"
        "Name the cause."
    )


# ----------------------------------------------------------------------
# Clients
# ----------------------------------------------------------------------

class Client(Protocol):
    """The slice of the Anthropic SDK this module uses."""

    def create(self, **kwargs: Any) -> Any: ...


class HeuristicClient:
    """No model. The control the agent has to beat, and the offline double.

    It consults exactly the evidence the tools expose, applying the same
    reasoning the system prompt describes. Keeping it in the same shape as
    the real client means the harness — brief, tools, scoring — is exercised
    on every CI run without an API key or a cent of spend.
    """

    def __init__(self, casefile: CaseFile, *, use_notes: bool = True) -> None:
        self.casefile = casefile
        # Switched off to ablate the notes and measure what free text is
        # worth on its own. Doing that by reimplementing the control in an
        # analysis script would measure the reimplementation instead.
        self.use_notes = use_notes

    def decide(self, case: ReconciliationCase) -> tuple[Cause, str, str]:
        profile = self.casefile.get_sku_profile(case.sku_id)
        history = self.casefile.get_sku_history(case.sku_id, case.case_id)

        matched = self._match_notes(case) if self.use_notes else None
        if matched is not None:
            cause, quote = matched
            return (cause, "high", f'Staff note: "{quote}"')

        if case.discrepancy > 0:
            return (Cause.MISCOUNT, "high",
                    "Positive discrepancy; only a miscount overstates a close "
                    "once the structural causes are excluded.")

        recurring = history["unexplained_negative_weeks"] >= 2
        if profile.get("theft_prone") and recurring:
            return (Cause.SHRINKAGE, "medium",
                    f"Theft-prone line with unexplained shortfalls in "
                    f"{history['unexplained_negative_weeks']} other weeks.")
        if profile.get("short_dated"):
            return (Cause.UNLOGGED_WASTAGE, "medium",
                    "Short-dated line; spoilage is the standing explanation "
                    "for a recurring small shortfall.")
        if abs(case.discrepancy) >= 7:
            return (Cause.UNLOGGED_WASTAGE, "low",
                    "Shortfall too large for a plausible counting slip.")
        return (Cause.MISCOUNT, "low",
                "Small shortfall on a line with no spoilage or theft profile "
                "and no recurring pattern.")


    # Keyword matching over the notes — the cheap way to read free text, and
    # therefore the bar a model has to clear rather than a straw man. It
    # catches the blunt phrasings and misses the oblique ones, which is
    # exactly the property worth measuring.
    KEYWORDS: tuple[tuple[str, Cause], ...] = (
        ("past date", Cause.UNLOGGED_WASTAGE),
        ("binned", Cause.UNLOGGED_WASTAGE),
        ("chucked", Cause.UNLOGGED_WASTAGE),
        ("dumped", Cause.UNLOGGED_WASTAGE),
        ("smelled off", Cause.UNLOGGED_WASTAGE),
        ("damaged", Cause.UNLOGGED_WASTAGE),
        ("helping themselves", Cause.SHRINKAGE),
        ("walking out", Cause.SHRINKAGE),
        ("nothing rung up", Cause.SHRINKAGE),
        ("looks light", Cause.SHRINKAGE),
        ("recount", Cause.MISCOUNT),
        ("counted the", Cause.MISCOUNT),
        ("disagreed", Cause.MISCOUNT),
        ("tally", Cause.MISCOUNT),
        ("short, no paperwork", Cause.SHORT_DELIVERY),
        ("less than the docket", Cause.SHORT_DELIVERY),
        ("driver was light", Cause.SHORT_DELIVERY),
    )

    def _match_notes(self, case: ReconciliationCase):
        for note in self.casefile.get_staff_notes(case.case_id)["notes"]:
            text = note["text"].lower()
            for phrase, cause in self.KEYWORDS:
                if phrase in text:
                    return cause, note["text"]
        return None


def classify_with_heuristic(
    case: ReconciliationCase, casefile: CaseFile, *, use_notes: bool = True
) -> Verdict:
    cause, confidence, rationale = HeuristicClient(
        casefile, use_notes=use_notes).decide(case)
    return Verdict(case.case_id, cause, confidence, rationale, tool_calls=2)


# ----------------------------------------------------------------------
# The model path
# ----------------------------------------------------------------------

def classify_with_model(
    case: ReconciliationCase,
    casefile: CaseFile,
    client: Any,
    *,
    effort: str = "medium",
    max_turns: int = 6,
) -> Verdict:
    """Run one residue case through Claude, with the two retrieval tools.

    A manual loop rather than the SDK tool runner: every tool call has to be
    counted and logged for the evaluation harness, tool results are served
    from local pipeline state rather than executed, and the same code path
    has to accept the heuristic control as a stand-in. The loop is small
    enough that owning it costs less than bending the runner around those.
    """
    messages: list[dict] = [{"role": "user", "content": build_brief(case, casefile)}]
    tool_calls = 0
    usage = {"input": 0, "output": 0, "cached": 0}

    for _ in range(max_turns):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                # Stable across every case in the run, and it renders after
                # the tool definitions, so this one breakpoint caches both.
                "cache_control": {"type": "ephemeral"},
            }],
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": VERDICT_SCHEMA},
            },
            tools=TOOLS,
            messages=messages,
        )

        u = getattr(response, "usage", None)
        if u is not None:
            usage["input"] += getattr(u, "input_tokens", 0) or 0
            usage["output"] += getattr(u, "output_tokens", 0) or 0
            usage["cached"] += getattr(u, "cache_read_input_tokens", 0) or 0

        if response.stop_reason == "refusal":
            raise RuntimeError(f"{case.case_id}: request declined by safety classifiers")

        if response.stop_reason != "tool_use":
            return _read_verdict(case, response, tool_calls, usage)

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            tool_calls += 1
            payload = casefile.dispatch(block.name, dict(block.input), case.case_id)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(payload, default=str),
            })
        messages.append({"role": "user", "content": results})

    raise RuntimeError(f"{case.case_id}: no verdict within {max_turns} turns")


def _read_verdict(case, response, tool_calls: int, usage: dict) -> Verdict:
    text = next(
        (b.text for b in response.content if getattr(b, "type", None) == "text"),
        None,
    )
    if text is None:
        raise RuntimeError(f"{case.case_id}: response carried no verdict")
    parsed = json.loads(text)
    return Verdict(
        case_id=case.case_id,
        cause=Cause(parsed["cause"]),
        confidence=parsed["confidence"],
        rationale=parsed["rationale"],
        tool_calls=tool_calls,
        input_tokens=usage["input"],
        output_tokens=usage["output"],
        cached_tokens=usage["cached"],
    )


def _explain(exc: Exception, sdk: Any | None) -> str | None:
    """Turn the failures people actually hit into one actionable line.

    A stack trace ending in `_base_client.py` tells a reader nothing about
    what to do next, and this is a path the README invites them to run. Only
    the recognised cases are handled — anything else re-raises with its
    traceback intact, because a swallowed unknown error is worse than an
    ugly one.
    """
    if sdk is None:
        return None
    message = str(getattr(exc, "message", "") or exc)

    if isinstance(exc, sdk.AuthenticationError):
        return ("the API key was rejected. Check ANTHROPIC_API_KEY is set to a "
                "current key from console.anthropic.com/settings/keys.")
    if isinstance(exc, sdk.BadRequestError) and "credit balance" in message:
        return ("the API key is valid but the account has no credit. Add some "
                "under Plans & Billing in the Anthropic console, then re-run. "
                "This run needs roughly a dollar or two.")
    if isinstance(exc, sdk.RateLimitError):
        return "the account is rate limited right now. Wait and re-run."
    if isinstance(exc, sdk.APIConnectionError):
        return "the API was unreachable. Check the network and re-run."
    if isinstance(exc, sdk.APIStatusError):
        return f"the API returned {exc.status_code}: {message}"
    return None


def residue_cases(result: IngestResult, findings: dict[str, Finding]) -> list:
    return [c for c in result.cases if not findings[c.case_id].resolved]


def contested_cases(result: IngestResult, findings: dict[str, Finding]) -> list:
    """Residue cases carrying a note no keyword list can read.

    This is the only population where a model and the control can disagree
    on evidence rather than luck. Everywhere else they see identical facts:
    a case with no note, or one whose note the keyword matcher already
    reads correctly. Measuring here costs a quarter of a full run and
    carries all of the signal.
    """
    casefile = CaseFile(result, findings)
    control = HeuristicClient(casefile)
    return [
        case for case in residue_cases(result, findings)
        if casefile.get_staff_notes(case.case_id)["notes"]
        and control._match_notes(case) is None
    ]


def classify_residue(
    result: IngestResult,
    findings: dict[str, Finding],
    *,
    client: Any | None = None,
    effort: str = "medium",
    cases: list | None = None,
    use_notes: bool = True,
) -> dict[str, Verdict]:
    """Verdicts for every residue case. No client means the heuristic control."""
    casefile = CaseFile(result, findings)
    verdicts: dict[str, Verdict] = {}
    for case in (residue_cases(result, findings) if cases is None else cases):
        verdicts[case.case_id] = (
            classify_with_heuristic(case, casefile, use_notes=use_notes)
            if client is None
            else classify_with_model(case, casefile, client, effort=effort)
        )
    return verdicts


if __name__ == "__main__":
    from pathlib import Path

    from .evaluate import load_labels
    from .ingest import build_cases
    from .rules import classify

    root = Path(__file__).resolve().parents[2]
    raw = root / "data" / "raw"
    if not (raw / "stock_counts.csv").exists():
        # data/ is not committed and regenerates from a fixed seed, so a
        # clean checkout should just work rather than fail on a missing file.
        from .generate import generate

        generate(raw)
    result = build_cases(raw)
    findings = classify(result)
    labels = load_labels(raw)

    client = None
    sdk = None
    if os.environ.get("RECON_USE_MODEL"):
        import anthropic as sdk  # imported lazily so the offline path needs no SDK

        client = sdk.Anthropic()

    # Only the cases whose notes defeat a keyword list can separate the two.
    # Everywhere else they read identical evidence, so paying a model to
    # re-derive the control's answer measures nothing.
    subset = (contested_cases(result, findings)
              if os.environ.get("RECON_ONLY_CONTESTED") else None)

    try:
        verdicts = classify_residue(result, findings, client=client, cases=subset)
    except Exception as exc:  # noqa: BLE001 — re-raised below unless recognised
        hint = _explain(exc, sdk)
        if hint is None:
            raise
        print(f"\nThe model path could not run: {hint}\n")
        print("The heuristic control needs no key and no credit — it is the")
        print("number the model has to beat anyway:\n")
        print("    python3 -m src.recon.agent\n")
        raise SystemExit(1)

    control = classify_residue(result, findings, cases=subset)
    label = "claude" if client else "heuristic control"

    correct = sum(1 for cid, v in verdicts.items() if v.cause.value == labels[cid])
    ctrl_correct = sum(1 for cid, v in control.items() if v.cause.value == labels[cid])

    scope = "contested cases only" if subset is not None else "full residue"
    print(f"scope         : {scope}")
    print(f"cases         : {len(verdicts)}")
    print(f"classifier    : {label}")
    print(f"correct       : {correct}/{len(verdicts)} ({correct / len(verdicts):.1%})")
    if client is not None:
        print(f"control       : {ctrl_correct}/{len(control)} "
              f"({ctrl_correct / len(control):.1%})")

        # Equal totals are not a tie. Both classifiers saw the same cases, so
        # only the ones they disagree on carry information — which is a paired
        # question, and comparing totals answers a different one.
        from .eval_report import Rate, mcnemar

        model_only = sum(1 for cid, v in verdicts.items()
                         if v.cause.value == labels[cid]
                         and control[cid].cause.value != labels[cid])
        control_only = sum(1 for cid, v in verdicts.items()
                           if control[cid].cause.value == labels[cid]
                           and v.cause.value != labels[cid])
        p = mcnemar(model_only, control_only)
        low, high = Rate(correct, len(verdicts)).interval
        print(f"model 95% CI  : {low:.1%} – {high:.1%}")
        print(f"disagreements : model-only {model_only}, control-only "
              f"{control_only}  (McNemar p={p:.3f})")
        if model_only + control_only == 0:
            print("                identical on every case — nothing to test")
        elif p > 0.05:
            print("                not significant at this sample size")
        tokens = sum(v.input_tokens for v in verdicts.values())
        cached = sum(v.cached_tokens for v in verdicts.values())
        out = sum(v.output_tokens for v in verdicts.values())
        print(f"tokens        : {tokens:,} in ({cached:,} cached), {out:,} out")

    # Every case, every time. A run that prints five rows makes the next
    # question cost another run.
    print()
    print(f"{'case':<17}{'truth':<18}{'model':<18}{'control':<18}")
    print("-" * 71)
    for cid in sorted(verdicts):
        v, c = verdicts[cid], control[cid]
        flag = "" if v.cause.value == labels[cid] else "  <- miss"
        if v.cause is not c.cause:
            flag += "  [differs from control]"
        print(f"{cid:<17}{labels[cid]:<18}{v.cause.value:<18}{c.cause.value:<18}{flag}")

    out_path = root / "data" / "agent_verdicts.json"
    out_path.write_text(json.dumps({
        "scope": scope,
        "classifier": label,
        "correct": correct,
        "total": len(verdicts),
        "control_correct": ctrl_correct,
        "cases": {
            cid: {
                "truth": labels[cid],
                "model": v.cause.value,
                "control": control[cid].cause.value,
                "confidence": v.confidence,
                "rationale": v.rationale,
                "tool_calls": v.tool_calls,
                "input_tokens": v.input_tokens,
                "cached_tokens": v.cached_tokens,
                "output_tokens": v.output_tokens,
            }
            for cid, v in sorted(verdicts.items())
        },
    }, indent=2))
    print(f"\nfull record written to {out_path.relative_to(root)}")
