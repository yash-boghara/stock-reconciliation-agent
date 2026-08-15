"""Tests that the prose cannot drift away from the code.

Documentation rots faster than anything else in a project, and the way it
rots is silent: a number stays in a README long after the code stopped
producing it, and every reader takes it on trust. This suite treats a
published figure as an assertion the build has to defend.

`docs/evaluation.md` is machine-generated and CI fails if it drifts from the
harness. These tests extend that guarantee to the hand-written documents,
which quote it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "docs" / "evaluation.md"
PROSE = ("README.md", "FINDINGS.md", "docs/agent-design.md")

# Figures that were true once and are not any more. Each was published in an
# earlier revision, so each is exactly the kind of number that survives a
# rewrite by being plausible.
SUPERSEDED = (
    "83.4%",     # residue control, before the 100-seed measurement
    "88.8%",     # reader ceiling, likewise
    "75.0%",     # structure-only control, on the pre-fix dataset
    "1585",      # rules commitments, when the sweep was 40 seeds
    "1,585",
    "95.0%",     # end-to-end, before the harness
    "$0.0023",   # cost per case, off by 6x in the first draft
)


def headline_figures() -> dict[str, str]:
    """Percentages the generated report publishes in its tables."""
    rows = re.findall(r"^\| ([^|]+?) \| (\d+\.\d%) \|",
                      EVALUATION.read_text(), re.MULTILINE)
    return {label.strip().strip("`"): value for label, value in rows}


class TestGeneratedReport(unittest.TestCase):
    def test_the_report_is_committed(self):
        """A reader should not have to run anything to see the evidence."""
        self.assertTrue(EVALUATION.exists(),
                        "run `python3 -m src.recon.eval_report`")

    def test_it_publishes_the_headline_measures(self):
        labels = headline_figures()
        for expected in ("Rules precision (committed causes)",
                         "End to end (rules + control)"):
            self.assertIn(expected, labels)

    def test_every_rate_carries_an_interval(self):
        """A rate without one is an assertion, which is the thing this
        project is trying not to publish."""
        text = EVALUATION.read_text()
        for line in text.splitlines():
            if re.match(r"^\| .+ \| \d+\.\d% \|", line):
                self.assertRegex(
                    line, r"\d+\.\d% – \d+\.\d%",
                    f"row publishes a rate with no interval:\n{line}")


class TestWalkthroughIsStillTrue(unittest.TestCase):
    """The walkthrough traces two named cases in detail.

    It is the document a stranger reads first, and it quotes specific
    arithmetic — so it is also the document most able to be quietly wrong
    after a generator change. These assert the trace against real output.
    """

    @classmethod
    def setUpClass(cls):
        from src.recon.agent import classify_residue
        from src.recon.correct import build_queue
        from src.recon.generate import generate
        from src.recon.ingest import build_cases
        from src.recon.rules import classify

        raw = ROOT / "data" / "raw"
        generate(raw)
        cls.result = build_cases(raw)
        findings = classify(cls.result)
        cls.queue = {c.case_id: c for c in build_queue(
            cls.result, findings, classify_residue(cls.result, findings))}
        cls.text = (ROOT / "docs" / "walkthrough.md").read_text()

    def case(self, case_id):
        return next(c for c in self.result.cases if c.case_id == case_id)

    def test_the_auto_posted_example_still_reconciles(self):
        """87 + 4 - 88 = 3 against a counted 71, so +68 — and 68 is exactly
        4 cases of 18 booked as 4 units."""
        case = self.case("SNK-1001-W03")
        self.assertEqual(
            (case.opening_count, case.delivered_units,
             case.sold_units, case.closing_count),
            (87, 4, 88, 71))
        self.assertEqual(case.discrepancy, 68)

        correction = self.queue["SNK-1001-W03"]
        self.assertEqual(correction.route.value, "auto")
        self.assertAlmostEqual(correction.value_nzd, 122.40, places=2)
        self.assertEqual(correction.owner, "goods-in")

        # And the document has to say so. Asserting only that the code still
        # produces these values leaves the prose free to claim anything.
        for quoted in (f"= +{case.discrepancy}",
                       f"NZ${correction.value_nzd:,.2f}",
                       f"{case.opening_count} + {case.delivered_units} - "
                       f"{case.sold_units}"):
            self.assertIn(quoted, self.text,
                          f"walkthrough no longer states {quoted!r}")

    def test_the_contrast_example_still_needs_a_human(self):
        """The whole point of the contrast: $2.10 is reviewed while $122.40
        posts itself, because of provenance rather than value."""
        correction = self.queue["BEV-0142-W03"]
        self.assertEqual(correction.route.value, "review")
        self.assertAlmostEqual(correction.value_nzd, 2.10, places=2)
        self.assertNotEqual(correction.confidence, "rule")
        self.assertIn(f"NZ${correction.value_nzd:,.2f}", self.text)

    def test_the_funnel_numbers_are_current(self):
        flagged = [c for c in self.result.cases if c.discrepancy != 0]
        auto = [c for c in self.queue.values() if c.route.value == "auto"]
        self.assertEqual(len(self.result.cases), 150)
        self.assertEqual(len(flagged), 75)
        self.assertEqual(len(auto), 30)
        for figure in ("150 cases", "75 balanced", "75 discrepancies",
                       "30 auto", "45 review"):
            self.assertIn(figure, self.text, f"walkthrough lost: {figure}")

    def test_quoted_raw_rows_are_really_in_the_data(self):
        """The messy rows are quoted verbatim to show what arrives. If the
        generator stops producing them the illustration is fiction."""
        for filename, fragment in (
            ("deliveries.csv", "D9209205"),
            ("stock_counts.csv", "SNK-1001-W03"),
        ):
            raw = (ROOT / "data" / "raw" / filename).read_text()
            row = next(line for line in raw.splitlines() if fragment in line)
            self.assertIn(row, self.text,
                          f"walkthrough quotes a {filename} row that no longer exists")


class TestProseMatchesTheCode(unittest.TestCase):
    def test_no_document_quotes_a_superseded_figure(self):
        offences = []
        for name in PROSE:
            text = (ROOT / name).read_text()
            for figure in SUPERSEDED:
                if figure in text:
                    offences.append(f"{name} still quotes {figure}")
        self.assertEqual(offences, [], "\n".join(offences))

    def test_the_readme_quotes_the_generated_headline_figures(self):
        """If the harness moves a number, the README has to move with it."""
        readme = (ROOT / "README.md").read_text()
        figures = headline_figures()
        for label in ("End to end (rules + control)",
                      "Residue — control with notes"):
            value = figures[label]
            # assertTrue rather than assertIn: assertIn prints the whole
            # container on failure, and the container here is the README.
            self.assertTrue(
                value in readme,
                f"README does not quote the measured {label} ({value}) — "
                "re-run `python3 -m src.recon.eval_report` and update it")

    def test_the_readme_states_the_real_test_count(self):
        """It has drifted twice. A number a human has to remember to update
        is a number that will be wrong."""
        import re
        import unittest as ut

        readme = (ROOT / "README.md").read_text()
        claimed = {int(n) for n in re.findall(r"(\d+) tests", readme)}
        self.assertTrue(claimed, "README no longer states a test count")

        # Count by discovery, not by running the suite — running it from
        # inside itself recurses until something gives up.
        suite = ut.TestLoader().discover(str(ROOT / "tests"),
                                         top_level_dir=str(ROOT))
        actual = suite.countTestCases()
        self.assertEqual(
            claimed, {actual},
            f"README claims {sorted(claimed)} tests; discovery finds {actual}")

    def test_every_document_the_readme_links_to_exists(self):
        readme = (ROOT / "README.md").read_text()
        for target in re.findall(r"\]\((?!https?:)([^)#]+)\)", readme):
            self.assertTrue((ROOT / target).exists(), f"broken link: {target}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
