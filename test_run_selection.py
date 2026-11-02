"""Selection must stay stable while discovery results change."""

import unittest

import pandas as pd

from run_selection import build_run_records, find_runs, select_runs


class RunSelectionTests(unittest.TestCase):
    def setUp(self):
        self.records = build_run_records(pd.DataFrame([
            {"Run_ID": run_id, "Run_Date": date, "Run_Date_Parsed": pd.Timestamp(date),
             "Model": model, "Executable": "xdg", "Config_File": config,
             "Particles_Per_Thread": particles, "Config_Max_Threads": 80,
             "Machine": "x86_64", "OS": "Linux", "Python_Version": "3.12"}
            for run_id, date, config, particles in [
                ("old", "2025-11-20", "scaling_config_ex.i", 50),
                ("new", "2025-11-22", "scaling_config_xdg.i", 5000),
            ]
            for model in ["atr", "msre"]
        ]))

    def select(self, action, selected, checked=None, previous=None, matches=None, **kwargs):
        return select_runs(action, selected, checked, previous or [],
                           self.records if matches is None else matches, self.records, **kwargs)

    def test_one_row_per_run_newest_first(self):
        self.assertEqual([row['id'] for row in self.records], ["new", "old"])
        self.assertEqual(self.records[0]['Models'], "atr, msre")

    def test_search_matches_words_across_metadata_case_insensitively(self):
        matches = find_runs(self.records, "LINUX 5000 XDG")
        self.assertEqual([row['id'] for row in matches], ["new"])
        self.assertEqual(find_runs(self.records, "does-not-exist"), [])

    def test_dates_are_inclusive_and_combine_with_properties(self):
        self.assertEqual(len(find_runs(self.records, start_date="2025-11-22", end_date="2025-11-22")), 1)
        self.assertEqual(find_runs(self.records, start_date="2025-11-22", properties=[[], [50]]), [])
        self.assertEqual(len(find_runs(self.records, properties=[[], []])), 2)

    def test_search_and_dates_never_remove_a_selection(self):
        self.assertEqual(self.select("run-search", ["new"], matches=[self.records[1]]), ["new"])
        self.assertEqual(self.select("run-date-range", ["new"], matches=[]), ["new"])

    def test_checking_and_unchecking_preserves_hidden_selection(self):
        older = [self.records[1]]
        selected = self.select("run-table", ["new"], ["old"], older, older)
        self.assertEqual(selected, ["new", "old"])
        self.assertEqual(self.select("run-table", selected, [], older, older), ["new"])

    def test_bulk_selection_adds_matching_runs_and_clear_stays_empty(self):
        self.assertEqual(self.select("select-matching", ["new"], matches=[self.records[1]]), ["new", "old"])
        self.assertEqual(self.select("clear-selection", ["new", "old"]), [])
        self.assertEqual(self.select("run-search", []), [])
        self.assertEqual(self.select("data-version", []), [])

    def test_individual_removal_and_refresh_remove_only_affected_ids(self):
        self.assertEqual(self.select("remove-run", ["new", "old"], remove_id="new"), ["old"])
        self.assertEqual(self.select("data-version", ["new", "deleted"]), ["new"])
        self.assertEqual(self.select("data-version", ["old"]), ["old"])

    def test_linked_missing_runs_remain_until_the_user_removes_them(self):
        self.assertEqual(self.select("data-version", ["new", "missing"], retain_missing=True), ["new", "missing"])
        self.assertEqual(self.select("run-search", ["missing"], matches=[], retain_missing=True), ["missing"])
        self.assertEqual(self.select("remove-run", ["new", "missing"], remove_id="missing", retain_missing=True), ["new"])


if __name__ == "__main__":
    unittest.main()
