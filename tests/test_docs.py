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

    def test_every_document_the_readme_links_to_exists(self):
        readme = (ROOT / "README.md").read_text()
        for target in re.findall(r"\]\((?!https?:)([^)#]+)\)", readme):
            self.assertTrue((ROOT / target).exists(), f"broken link: {target}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
