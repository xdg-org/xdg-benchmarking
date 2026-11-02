"""Comparison links must round-trip intent, including explicit empty choices."""

import unittest
from urllib.parse import parse_qs

from comparison_url import build_comparison_query, parse_comparison_query


class ComparisonQueryTests(unittest.TestCase):
    def test_comparison_round_trips_with_encoded_tags(self):
        runs = ["tag with spaces", "tag,+/&?#=", "タグ"]
        query = build_comparison_query(runs, "tokamak", ["double-down", "xdg"], "Inactive rate")
        settings, notices = parse_comparison_query(query)
        self.assertEqual(settings, {"runs": sorted(runs), "model": "tokamak",
                                    "executables": ["double-down", "xdg"], "metric": "Inactive rate"})
        self.assertEqual(notices, [])

    def test_no_query_uses_defaults_but_blank_run_is_intentionally_empty(self):
        self.assertIsNone(parse_comparison_query("")[0]["runs"])
        query = build_comparison_query([], "atr", [], "Active rate")
        restored = parse_comparison_query(query)[0]
        self.assertEqual(restored["runs"], [])
        self.assertEqual(restored["executables"], [])

    def test_duplicate_run_tags_are_deduplicated(self):
        settings, _ = parse_comparison_query("?run=one&run=one&run=two&exe=xdg&exe=xdg")
        self.assertEqual(settings["runs"], ["one", "two"])
        self.assertEqual(settings["executables"], ["xdg"])

    def test_unknown_metric_falls_back_with_a_notice(self):
        settings, notices = parse_comparison_query("?run=one&metric=bad")
        self.assertEqual(settings["runs"], ["one"])
        self.assertEqual(settings["metric"], "Active rate")
        self.assertIn("Unknown metric", notices[0])

    def test_conflicting_scalar_parameters_do_not_break_the_page(self):
        settings, notices = parse_comparison_query("?model=atr&model=msre&metric=active&metric=inactive")
        self.assertIsNone(settings["model"])
        self.assertIsNone(settings["metric"])
        self.assertEqual(len(notices), 2)

    def test_invalid_utf8_and_excessive_parameters_fail_to_empty_selection(self):
        for query in ("?run=%FF", "?" + "&".join(["run=a"] * 2049)):
            settings, notices = parse_comparison_query(query)
            self.assertEqual(settings["runs"], [])
            self.assertIn("could not be read", notices[0])

    def test_unrelated_query_parameters_are_preserved(self):
        query = build_comparison_query(["new"], "atr", ["xdg"], "Active rate",
                                       "?utm_source=shared&run=old&model=msre&metric=inactive")
        values = parse_qs(query[1:])
        self.assertEqual(values["utm_source"], ["shared"])
        self.assertEqual(values["run"], ["new"])
        self.assertEqual(values["metric"], ["active"])


if __name__ == "__main__":
    unittest.main()
