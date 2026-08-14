"""Tests for the evaluation harness.

The harness is what makes every claim in this project checkable, so its own
arithmetic has to be checkable first. A confidence interval that is quietly
wrong is worse than none: it converts a guess into a guess wearing a number.

The statistics are tested against values worked out by hand, not against the
implementation's own output.
"""

from __future__ import annotations

import unittest

from src.recon.eval_report import (
    Rate,
    bayes_ceiling,
    end_to_end,
    mcnemar,
    notes_breakdown,
    residue_rates,
    rules_precision,
    run,
    run_seed,
)


class TestWilsonInterval(unittest.TestCase):
    def test_interval_brackets_the_estimate(self):
        rate = Rate(30, 35)
        low, high = rate.interval
        self.assertLess(low, rate.point)
        self.assertGreater(high, rate.point)

    def test_perfect_score_does_not_exceed_one(self):
        """The reason for Wilson over the normal approximation: at p=1 the
        normal interval runs above 100%, which is not a probability."""
        low, high = Rate(3891, 3891).interval
        self.assertLessEqual(high, 1.0)
        self.assertLess(low, 1.0)
        self.assertGreater(low, 0.99, "4k clean commitments should bound tightly")

    def test_a_small_sample_is_visibly_uninformative(self):
        """7/9 is the contested-case result. The interval is what shows it
        cannot resolve a five-point effect."""
        low, high = Rate(7, 9).interval
        self.assertLess(low, 0.55)
        self.assertGreater(high, 0.90)
        self.assertGreater(high - low, 0.35)

    def test_more_evidence_narrows_the_interval(self):
        narrow = Rate(840, 1000).interval
        wide = Rate(84, 100).interval
        self.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])

    def test_no_observations_is_safe(self):
        self.assertEqual(Rate(0, 0).point, 0.0)
        self.assertEqual(Rate(0, 0).interval, (0.0, 0.0))

    def test_known_value(self):
        """Hand-computed: Wilson 95% for 1/10 is about 0.018 to 0.404."""
        low, high = Rate(1, 10).interval
        self.assertAlmostEqual(low, 0.0179, places=3)
        self.assertAlmostEqual(high, 0.4042, places=3)


class TestMcNemar(unittest.TestCase):
    """Model versus control is a paired question, so it needs a paired test."""

    def test_no_disagreement_is_no_evidence(self):
        """The contested run: 7/9 against 7/9, agreeing on every case. Equal
        totals are not a tie — there is simply nothing to test."""
        self.assertEqual(mcnemar(0, 0), 1.0)

    def test_an_even_split_is_no_evidence(self):
        self.assertEqual(mcnemar(5, 5), 1.0)

    def test_a_lopsided_split_is_evidence(self):
        self.assertLess(mcnemar(12, 1), 0.01)

    def test_symmetric_in_its_arguments(self):
        self.assertEqual(mcnemar(9, 2), mcnemar(2, 9))

    def test_small_lopsided_samples_stay_unconvincing(self):
        """Two wins and no losses feels decisive and is not: p = 0.5."""
        self.assertAlmostEqual(mcnemar(2, 0), 0.5, places=6)

    def test_known_value(self):
        """Hand-computed: 7 discordant pairs, the smaller side being 1, so
        the one-sided tail is (C(7,0) + C(7,1)) / 2**7 = 8/128."""
        self.assertAlmostEqual(mcnemar(6, 1), 2 * 8 / 128, places=6)


class TestHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records, cls.queues = run(range(1, 6))

    def test_a_seed_is_reproducible(self):
        first, _ = run_seed(3)
        second, _ = run_seed(3)
        self.assertEqual([r.truth for r in first], [r.truth for r in second])
        self.assertEqual([r.control_cause for r in first],
                         [r.control_cause for r in second])

    def test_every_case_is_recorded_once_per_seed(self):
        keys = [(r.seed, r.case_id) for r in self.records]
        self.assertEqual(len(keys), len(set(keys)))

    def test_rules_precision_ignores_clean_weeks(self):
        """Counting `none` would pad the figure with the easiest calls in
        the set, and it is the majority class."""
        committed = [r for r in self.records
                     if r.rules_resolved and r.rules_cause != "none"]
        self.assertEqual(rules_precision(self.records).total, len(committed))

    def test_reading_notes_cannot_hurt(self):
        """A ceiling below the classifier it bounds would mean the ceiling
        is computed wrong."""
        rates = residue_rates(self.records)
        self.assertGreaterEqual(rates["reader_ceiling"].point,
                                rates["control_with_notes"].point)
        self.assertGreaterEqual(rates["control_with_notes"].point,
                                rates["control_structure_only"].point)

    def test_notes_breakdown_adds_up(self):
        counts = notes_breakdown(self.records)
        self.assertEqual(
            counts["keyword_readable"]
            + counts["informative_but_oblique"]
            + counts["noise_only"],
            counts["noted"])
        self.assertLessEqual(counts["noted"], counts["residue"])

    def test_end_to_end_covers_every_case(self):
        self.assertEqual(end_to_end(self.records).total, len(self.records))

    def test_the_ceiling_is_measured_on_unseen_seeds(self):
        """Fitting and scoring the same records reports memorisation. If the
        split ever stops being honest, the ceiling silently inflates."""
        train, _ = run(range(1, 4))
        test, _ = run(range(4, 6))
        self.assertFalse({r.seed for r in train} & {r.seed for r in test})

        fitted = bayes_ceiling(train, test)
        memorised = bayes_ceiling(train, train)
        for features, rate in fitted.items():
            self.assertLessEqual(rate.point, memorised[features].point + 1e-9,
                                 f"{features}: held-out beat memorised")


if __name__ == "__main__":
    unittest.main(verbosity=2)
