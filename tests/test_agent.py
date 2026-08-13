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
