"""Tests for normalisation and dataset integrity.

The last test is the important one. It asserts that every planted label
agrees with the discrepancy the pipeline actually observes. If a future
change to the generator or the ingest layer breaks that agreement, the
evaluation set is quietly lying about what correct looks like — and every
accuracy number measured against it becomes meaningless.
"""

from __future__ import annotations

import csv
import unittest
from datetime import date
from pathlib import Path

from src.recon.generate import generate
from src.recon.ingest import (
    build_cases,
    normalise_date,
    normalise_qty,
    normalise_sku,
    normalise_uom,
)

DATA = Path(__file__).resolve().parents[1] / "data" / "raw"


class TestNormalisation(unittest.TestCase):
    def test_sku_spellings_fold_to_one_canonical_form(self):
        for raw in ("BEV-0142", "bev0142", "  BEV 0142 ", "bev-0142", "0BEV-0142"):
            self.assertEqual(normalise_sku(raw), "BEV-0142", msg=raw)

    def test_unknown_sku_is_rejected_not_guessed(self):
        for raw in ("ZZZ-9999", "BEV-14", "", "not a sku"):
            with self.assertRaises(ValueError, msg=raw):
                normalise_sku(raw)

    def test_date_formats(self):
        for raw in ("2026-06-03", "03/06/2026", "03-Jun-2026"):
            self.assertEqual(normalise_date(raw), date(2026, 6, 3), msg=raw)

    def test_nz_day_first_convention_is_honoured(self):
        # 06/07/2026 is 6 July, not 7 June. Getting this backwards shifts
        # rows between periods and invents discrepancies.
        self.assertEqual(normalise_date("06/07/2026"), date(2026, 7, 6))

    def test_quantities(self):
        self.assertEqual(normalise_qty("12"), 12)
        self.assertEqual(normalise_qty("12.0"), 12)
        self.assertEqual(normalise_qty(" 12 "), 12)

    def test_fractional_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            normalise_qty("12.4")

    def test_blank_uom_means_eaches(self):
        self.assertEqual(normalise_uom(""), "EACH")
        self.assertEqual(normalise_uom(None), "EACH")
        self.assertEqual(normalise_uom("case"), "CASE")


class TestDatasetIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generate(DATA)
        cls.result = build_cases(DATA)
        with (DATA / "labels.csv").open(encoding="utf-8") as fh:
            cls.labels = {r["case_id"]: r for r in csv.DictReader(fh)}

    def test_generation_is_deterministic(self):
        first = (DATA / "labels.csv").read_text(encoding="utf-8")
        generate(DATA)
        self.assertEqual(first, (DATA / "labels.csv").read_text(encoding="utf-8"))

    def test_every_case_has_a_label(self):
        for case in self.result.cases:
            self.assertIn(case.case_id, self.labels)

    def test_no_rows_rejected_from_clean_generated_data(self):
        self.assertEqual(self.result.rejections, [])

    def test_export_duplicates_are_dropped(self):
        self.assertGreater(self.result.duplicates_dropped, 0)

    def test_labels_agree_with_observed_discrepancies(self):
        for case in self.result.cases:
            labelled_clean = self.labels[case.case_id]["cause"] == "none"
            observed_clean = case.discrepancy == 0
            self.assertEqual(
                labelled_clean,
                observed_clean,
                f"{case.case_id}: label={self.labels[case.case_id]['cause']} "
                f"but discrepancy={case.discrepancy}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
