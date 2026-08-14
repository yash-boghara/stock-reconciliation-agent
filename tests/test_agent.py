"""Tests for the agent layer and its control.

The load-bearing test here is the first one. Every accuracy figure in this
project depends on the agent never reading the file that holds the answers,
and that is exactly the kind of leak that is invisible once it exists — the
numbers simply get better and nobody asks why.

The rest pin the control's behaviour and exercise the model code path with a
stub, so the harness is covered on every CI run without an API key.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from src.recon.agent import (
    JUDGEMENT_CAUSES,
    _explain,
    CaseFile,
    Verdict,
    clean_rationale,
    contested_cases,
    estimate_cost,
    HeuristicClient,
    build_brief,
    classify_residue,
    classify_with_model,
    residue_cases,
)
from src.recon.evaluate import load_labels
from src.recon.generate import generate
from src.recon.ingest import build_cases
from src.recon.models import Cause
from src.recon.rules import classify

DATA = Path(__file__).resolve().parents[1] / "data" / "raw"

RECURRENCE_STEMS = (
    "facing looks light",
    "third week running",
    "front of shop",
    "same as last week",
)


def setUpModule():
    """Generate the dataset this module reads.

    `data/` is not committed — it regenerates from a fixed seed. Relying on
    another test module to have produced it first passes locally, where the
    directory is usually already there, and fails on a clean checkout.
    """
    generate(DATA)


def pipeline(raw: Path):
    result = build_cases(raw)
    findings = classify(result)
    return result, findings


class TestNoLabelLeakage(unittest.TestCase):
    """The agent may read the pipeline's output. It may not read the answers."""

    def test_labels_file_is_never_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            generate(raw)
            result, findings = pipeline(raw)

            # Make the answers unreadable, then run the whole layer. Anything
            # that reaches for labels.csv raises instead of silently helping.
            labels_path = raw / "labels.csv"
            labels_path.chmod(0o000)
            try:
                verdicts = classify_residue(result, findings)
            finally:
                labels_path.chmod(0o644)

            self.assertGreater(len(verdicts), 0)

    def test_tools_expose_only_pipeline_derived_facts(self):
        result, findings = pipeline(DATA)
        casefile = CaseFile(result, findings)
        profile = casefile.get_sku_profile("TOB-6001")
        self.assertEqual(
            set(profile),
            {"sku_id", "description", "supplier", "case_size",
             "unit_cost_nzd", "theft_prone", "short_dated"},
            "a tool grew a field — check it is not derived from labels",
        )
        history = casefile.get_sku_history("TOB-6001")
        for week in history["weeks"]:
            self.assertIn(week["rules_verdict"],
                          {"unexplained", *(c.value for c in Cause)})


class TestCaseFile(unittest.TestCase):
    def setUp(self):
        self.result, self.findings = pipeline(DATA)
        self.casefile = CaseFile(self.result, self.findings)

    def test_history_excludes_the_case_under_review(self):
        """Leaving the case in lets the agent count its own discrepancy as
        corroborating evidence for itself."""
        case = residue_cases(self.result, self.findings)[0]
        history = self.casefile.get_sku_history(case.sku_id, case.case_id)
        self.assertNotIn(case.case_id, [w["case_id"] for w in history["weeks"]])

    def test_unknown_sku_returns_an_error_not_a_guess(self):
        self.assertIn("error", self.casefile.get_sku_profile("ZZZ-9999"))

    def test_brief_states_the_arithmetic(self):
        case = residue_cases(self.result, self.findings)[0]
        brief = build_brief(case, self.casefile)
        self.assertIn(str(case.discrepancy), brief)
        self.assertIn(case.sku_id, brief)


class TestHeuristicControl(unittest.TestCase):
    """The control is the number the model has to beat, so it gets pinned."""

    @classmethod
    def setUpClass(cls):
        cls.result, cls.findings = pipeline(DATA)
        cls.verdicts = classify_residue(cls.result, cls.findings)
        cls.labels = load_labels(DATA)

    def test_covers_every_residue_case(self):
        expected = {c.case_id for c in residue_cases(self.result, self.findings)}
        self.assertEqual(set(self.verdicts), expected)

    def test_only_ever_names_a_judgement_cause(self):
        """Re-deciding a structural cause would mean second-guessing
        arithmetic the rules layer already proved."""
        allowed = set(JUDGEMENT_CAUSES)
        for verdict in self.verdicts.values():
            self.assertIn(verdict.cause, allowed)

    def test_beats_the_majority_baseline(self):
        correct = sum(1 for cid, v in self.verdicts.items()
                      if v.cause.value == self.labels[cid])
        majority = max(
            sum(1 for cid in self.verdicts if self.labels[cid] == cause)
            for cause in {self.labels[cid] for cid in self.verdicts}
        )
        self.assertGreater(correct, majority,
                           "the control no longer beats always-guess-the-mode")

    def test_control_accuracy_holds(self):
        correct = sum(1 for cid, v in self.verdicts.items()
                      if v.cause.value == self.labels[cid])
        self.assertEqual(correct, 30, "control moved; record the new figure")


class TestStaffNotes(unittest.TestCase):
    """Free-text notes are the evidence the numbers cannot carry."""

    def setUp(self):
        self.result, self.findings = pipeline(DATA)
        self.casefile = CaseFile(self.result, self.findings)
        self.control = HeuristicClient(self.casefile)

    def test_notes_reach_the_agent_verbatim(self):
        """Every other field is normalised hard; note text must not be. The
        signal lives in exactly how it was written."""
        texts = []
        for case in self.result.cases:
            texts += [n["text"] for n in
                      self.casefile.get_staff_notes(case.case_id)["notes"]]
        self.assertGreater(len(texts), 0)
        for text in texts:
            self.assertEqual(text, text.strip())
            self.assertNotEqual(text, text.upper())

    def test_a_case_with_no_note_returns_empty_not_an_error(self):
        quiet = [
            c for c in self.result.cases
            if not self.casefile.get_staff_notes(c.case_id)["notes"]
        ]
        self.assertGreater(len(quiet), 0)
        self.assertEqual(self.casefile.get_staff_notes(quiet[0].case_id),
                         {"notes": []})

    def test_keyword_matches_are_never_wrong(self):
        """The keyword list is the cheap baseline. It is allowed to miss;
        it is not allowed to misread, or it stops being a fair bar."""
        labels = load_labels(DATA)
        for case in residue_cases(self.result, self.findings):
            match = self.control._match_notes(case)
            if match is not None:
                self.assertEqual(match[0].value, labels[case.case_id],
                                 f"{case.case_id}: keyword matched the wrong cause")

    def test_notes_claiming_recurrence_are_corroborated_by_the_record(self):
        """A note reading "third week running" is a claim about history, and
        a careful reader will check it. If the record disagrees, the data
        punishes exactly the reasoning it should reward — the model found
        this by declining to trust an uncorroborated note, and was scored
        wrong for being right.
        """
        for seed in (1, 5, 11, 20260814):
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as tmp:
                raw = Path(tmp)
                generate(raw, seed=seed)
                result, findings = pipeline(raw)
                casefile = CaseFile(result, findings)
                for case in result.cases:
                    notes = casefile.get_staff_notes(case.case_id)["notes"]
                    text = " ".join(n["text"].lower() for n in notes)
                    # Only the phrases that assert a history of losses. A
                    # short delivery note reading "short on cereal again from
                    # this supplier" is a claim about the supplier, not about
                    # the stock record, and is nobody's business here.
                    if any(stem in text for stem in RECURRENCE_STEMS):
                        history = casefile.get_sku_history(case.sku_id, case.case_id)
                        self.assertGreaterEqual(
                            history["unexplained_negative_weeks"], 2,
                            f"{case.case_id}: note claims a pattern the record "
                            f"does not carry",
                        )

    def test_oblique_phrasings_defeat_the_keyword_list(self):
        """The model's entire headroom is here. If a keyword list could read
        these, there would be nothing for a reader to add."""
        oblique = [
            "had to pull 4 yoghurt — wouldn't keep till Monday",
            "third week running we're down on cigarettes",
            "chiller door left open overnight, milk not right after",
            "lost my place counting the rice",
            "rice count done late, might be out",
        ]
        for text in oblique:
            hit = any(phrase in text.lower()
                      for phrase, _ in HeuristicClient.KEYWORDS)
            self.assertFalse(hit, f"keyword list unexpectedly reads: {text!r}")


class TestContestedSubset(unittest.TestCase):
    """The only cases where a model and the control read different evidence.

    Everywhere else both see a case with no note, or a note the keyword list
    already reads correctly — so paying a model to re-derive the control's
    answer there measures nothing but spend.
    """

    def setUp(self):
        self.result, self.findings = pipeline(DATA)
        self.casefile = CaseFile(self.result, self.findings)
        self.control = HeuristicClient(self.casefile)

    def test_every_contested_case_has_a_note_the_keywords_cannot_read(self):
        contested = contested_cases(self.result, self.findings)
        self.assertGreater(len(contested), 0)
        for case in contested:
            self.assertTrue(self.casefile.get_staff_notes(case.case_id)["notes"])
            self.assertIsNone(self.control._match_notes(case))

    def test_contested_is_a_strict_subset_of_the_residue(self):
        residue = {c.case_id for c in residue_cases(self.result, self.findings)}
        contested = {c.case_id for c in contested_cases(self.result, self.findings)}
        self.assertLess(contested, residue)

    def test_running_a_subset_scores_only_that_subset(self):
        contested = contested_cases(self.result, self.findings)
        verdicts = classify_residue(self.result, self.findings, cases=contested)
        self.assertEqual(set(verdicts), {c.case_id for c in contested})


class TestRobustness(unittest.TestCase):
    """What happens when the API or the model misbehaves.

    These are not hypotheticals: the contamination case below is text a real
    run actually returned.
    """

    def setUp(self):
        self.result, self.findings = pipeline(DATA)
        self.casefile = CaseFile(self.result, self.findings)
        self.case = residue_cases(self.result, self.findings)[0]

    def test_stray_markup_is_stripped_and_reported(self):
        """Observed in a real run. Truncate at the marker — everything after
        it is the model losing the thread — and flag it, because silently
        repairing bad output means nobody learns it is happening."""
        dirty = ("Paper towels are bulky dry goods and the -2 is tiny."
                 "</parameter>|<br>|<br>Note: I output the JSON above.<br>{")
        cleaned, was_dirty = clean_rationale(dirty)
        self.assertTrue(was_dirty)
        self.assertEqual(cleaned,
                         "Paper towels are bulky dry goods and the -2 is tiny.")

    def test_clean_text_is_left_alone(self):
        text = "Short-dated line with a note recording spoilage."
        cleaned, was_dirty = clean_rationale(text)
        self.assertFalse(was_dirty)
        self.assertEqual(cleaned, text)

    def test_contamination_survives_into_the_verdict_as_a_flag(self):
        client = StubClient([text_response({
            "cause": "miscount", "confidence": "low",
            "rationale": "Tiny gap, clean history.</parameter><br>stray",
        })])
        verdict = classify_with_model(self.case, self.casefile, client)
        self.assertTrue(verdict.rationale_was_cleaned)
        self.assertNotIn("<br>", verdict.rationale)
        self.assertIs(verdict.cause, Cause.MISCOUNT,
                      "the enum-constrained field must be unaffected")

    def test_malformed_json_fails_loudly(self):
        """A verdict that cannot be parsed must not become a default."""
        broken = StubResponse(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="{not json")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1,
                                  cache_read_input_tokens=0))
        with self.assertRaises(RuntimeError):
            classify_with_model(self.case, self.casefile, StubClient([broken]))

    def test_a_transient_failure_is_retried(self):
        class RateLimitError(Exception):
            pass

        good = text_response({"cause": "miscount", "confidence": "low",
                              "rationale": "ok"})

        class Flaky(StubMessages):
            def create(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    raise RateLimitError("slow down")
                return good

        client = SimpleNamespace(messages=Flaky([]))
        verdict = classify_with_model(self.case, self.casefile, client)
        self.assertIs(verdict.cause, Cause.MISCOUNT)
        self.assertEqual(verdict.attempts, 2)

    def test_a_permanent_failure_is_not_retried(self):
        """Retrying a rejected key or an empty balance spends time and, on a
        paid path, money — it will fail identically every time."""
        class BadRequestError(Exception):
            pass

        class Always(StubMessages):
            def create(self, **kwargs):
                self.calls.append(kwargs)
                raise BadRequestError("credit balance is too low")

        client = SimpleNamespace(messages=Always([]))
        with self.assertRaises(BadRequestError):
            classify_with_model(self.case, self.casefile, client)
        self.assertEqual(len(client.messages.calls), 1)

    def test_every_request_carries_a_timeout(self):
        client = StubClient([text_response(
            {"cause": "miscount", "confidence": "low", "rationale": "ok"})])
        classify_with_model(self.case, self.casefile, client)
        self.assertIn("timeout", client.messages.calls[0])


class TestCostModel(unittest.TestCase):
    def test_cost_reflects_the_published_rates(self):
        verdict = Verdict("c", Cause.MISCOUNT, "low", "x",
                          input_tokens=1_000_000, output_tokens=0,
                          cached_tokens=0)
        self.assertAlmostEqual(verdict.cost_usd, 5.00, places=4)

    def test_cached_reads_are_billed_at_a_tenth(self):
        cached = Verdict("c", Cause.MISCOUNT, "low", "x",
                         cached_tokens=1_000_000)
        self.assertAlmostEqual(cached.cost_usd, 0.50, places=4)

    def test_summary_reports_what_the_cache_saved(self):
        verdicts = {
            "a": Verdict("a", Cause.MISCOUNT, "low", "x",
                         input_tokens=1_000, cached_tokens=9_000,
                         output_tokens=300),
        }
        summary = estimate_cost(verdicts)
        self.assertGreater(summary["usd"], 0)
        self.assertAlmostEqual(summary["cache_read_share"], 0.9, places=3)
        self.assertGreater(summary["usd_saved_by_cache"], 0)


class TestFailureMessages(unittest.TestCase):
    """A path the README tells people to run must fail in words, not in a
    stack trace ending inside the SDK's base client.

    The SDK is not installed in CI, so the exception classes are stubbed —
    `_explain` only needs the namespace to isinstance against.
    """

    def setUp(self):
        class APIStatusError(Exception):
            def __init__(self, message, status_code=400):
                super().__init__(message)
                self.message = message
                self.status_code = status_code

        class BadRequestError(APIStatusError): pass
        class AuthenticationError(APIStatusError): pass
        class RateLimitError(APIStatusError): pass
        class APIConnectionError(Exception): pass

        self.sdk = SimpleNamespace(
            APIStatusError=APIStatusError,
            BadRequestError=BadRequestError,
            AuthenticationError=AuthenticationError,
            RateLimitError=RateLimitError,
            APIConnectionError=APIConnectionError,
        )

    def test_no_credit_is_named_as_a_billing_problem(self):
        exc = self.sdk.BadRequestError(
            "Your credit balance is too low to access the Anthropic API.")
        hint = _explain(exc, self.sdk)
        self.assertIn("no credit", hint)
        self.assertIn("Plans & Billing", hint)

    def test_a_rejected_key_is_not_reported_as_billing(self):
        hint = _explain(self.sdk.AuthenticationError("invalid x-api-key"), self.sdk)
        self.assertIn("key was rejected", hint)
        self.assertNotIn("credit", hint)

    def test_unrecognised_errors_are_left_to_re_raise(self):
        """Swallowing an unknown failure is worse than an ugly traceback."""
        self.assertIsNone(_explain(ValueError("something new"), self.sdk))

    def test_offline_runs_never_consult_the_sdk(self):
        self.assertIsNone(_explain(ValueError("x"), None))


class StubResponse(SimpleNamespace):
    pass


class StubMessages:
    """Replays a scripted sequence of API responses."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0)


class StubClient:
    def __init__(self, script):
        self.messages = StubMessages(script)


def text_response(payload: dict) -> StubResponse:
    return StubResponse(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                              cache_read_input_tokens=80),
    )


def tool_response(name: str, args: dict) -> StubResponse:
    return StubResponse(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id="toolu_1", name=name, input=args)],
        usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                              cache_read_input_tokens=0),
    )


class TestModelPath(unittest.TestCase):
    """Exercises the real loop with a stub — no API key, no spend."""

    def setUp(self):
        self.result, self.findings = pipeline(DATA)
        self.casefile = CaseFile(self.result, self.findings)
        self.case = residue_cases(self.result, self.findings)[0]

    def test_tool_call_is_served_and_the_verdict_parsed(self):
        client = StubClient([
            tool_response("get_sku_profile", {"sku_id": self.case.sku_id}),
            text_response({"cause": "shrinkage", "confidence": "medium",
                           "rationale": "Theft-prone line, recurring shortfall."}),
        ])
        verdict = classify_with_model(self.case, self.casefile, client)
        self.assertIs(verdict.cause, Cause.SHRINKAGE)
        self.assertEqual(verdict.tool_calls, 1)
        self.assertEqual(verdict.input_tokens, 200)
        self.assertEqual(verdict.cached_tokens, 80)

        # The tool result must be fed back as a tool_result block.
        second = client.messages.calls[1]["messages"]
        self.assertEqual(second[-1]["content"][0]["type"], "tool_result")
        payload = json.loads(second[-1]["content"][0]["content"])
        self.assertEqual(payload["sku_id"], self.case.sku_id)

    def test_system_prompt_is_cached_and_schema_is_enforced(self):
        client = StubClient([
            text_response({"cause": "miscount", "confidence": "low", "rationale": "x"}),
        ])
        classify_with_model(self.case, self.casefile, client)
        call = client.messages.calls[0]
        self.assertEqual(call["system"][0]["cache_control"], {"type": "ephemeral"})
        schema = call["output_config"]["format"]["schema"]
        self.assertEqual(set(schema["properties"]["cause"]["enum"]),
                         {c.value for c in JUDGEMENT_CAUSES})

    def test_refusal_is_raised_not_parsed_as_a_verdict(self):
        client = StubClient([
            StubResponse(stop_reason="refusal", content=[],
                         usage=SimpleNamespace(input_tokens=10, output_tokens=0,
                                               cache_read_input_tokens=0)),
        ])
        with self.assertRaises(RuntimeError):
            classify_with_model(self.case, self.casefile, client)

    def test_a_loop_that_never_decides_raises(self):
        client = StubClient([
            tool_response("get_sku_profile", {"sku_id": self.case.sku_id})
            for _ in range(6)
        ])
        with self.assertRaises(RuntimeError):
            classify_with_model(self.case, self.casefile, client, max_turns=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
