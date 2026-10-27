import unittest

try:
    from benchmarks.metrics import error_rate, normalize, field_scores, release_status
except ImportError:
    error_rate = normalize = field_scores = release_status = None


class MetricsTests(unittest.TestCase):
    def test_unicode_scripts_and_marks_are_preserved(self):
        self.assertIsNotNone(normalize, "Unicode scoring is not implemented")
        self.assertEqual(normalize("தமிழ், తెలుగు! हिंदी?"), "தமிழ் తెలుగు हिंदी")

    def test_one_substitution_out_of_three_words(self):
        self.assertIsNotNone(error_rate, "ASR scoring is not implemented")
        self.assertEqual(error_rate("meet arun tomorrow", "meet hari tomorrow"), (1, 3))

    def test_insertions_are_not_clamped_to_one(self):
        self.assertIsNotNone(error_rate)
        self.assertEqual(error_rate("one", "one two three"), (2, 1))

    def test_empty_reference_hallucination_is_counted(self):
        self.assertIsNotNone(error_rate)
        self.assertEqual(error_rate("", "invented words"), (2, 0))

    def test_cjk_character_metric(self):
        self.assertIsNotNone(error_rate)
        self.assertEqual(error_rate("明天开会", "明天开车", chars=True), (1, 4))

    def test_field_metrics_penalize_hallucination_and_missing_fields(self):
        self.assertIsNotNone(field_scores, "Extraction scoring is not implemented")
        self.assertEqual(field_scores({"person": "Arun", "time": "15:00"},
                                      {"person": "Arun", "place": "Chennai"}),
                         {"tp": 1, "fp": 1, "fn": 1, "precision": .5, "recall": .5, "f1": .5})

    def test_wrong_value_counts_false_positive_and_false_negative(self):
        self.assertIsNotNone(field_scores)
        self.assertEqual(field_scores({"time": "15:00"}, {"time": "16:00"})["f1"], 0)

    def test_missing_measurement_never_passes(self):
        self.assertIsNotNone(release_status, "Fail-closed gates are not implemented")
        self.assertEqual(release_status(None, 100, 100, 0), "PENDING")

    def test_decimal_budget_and_failure_enforcement(self):
        self.assertIsNotNone(release_status)
        self.assertEqual(release_status(500000001, 100, 100, 0), "FAIL")
        self.assertEqual(release_status(100, 100, 100, 1), "FAIL")
        self.assertEqual(release_status(100, 100, 0, 0), "PENDING")
        self.assertEqual(release_status(100, 100, 100, 0), "PASS")


if __name__ == "__main__":
    unittest.main()
