"""Tests for rtprobe.report (rendering + file output)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtprobe import measure as measure_mod
from rtprobe import report as report_mod


class TestRender(unittest.TestCase):
    def test_report_contains_sections(self):
        results = {("msg_roundtrip", "roundtrip_ns"):
                   measure_mod.summarize([1000, 2000, 3000, 4000])}
        text = report_mod.render_report(results)
        self.assertIn("msg_roundtrip / roundtrip_ns", text)
        self.assertIn("count 4", text)
        self.assertIn("p50", text)
        self.assertIn("QEMU/TCG", text)  # honesty note

    def test_report_no_samples(self):
        text = report_mod.render_report({})
        self.assertIn("No samples collected.", text)

    def test_report_with_parsed_completeness(self):
        parsed = measure_mod.parse_lines(
            "RT-PROBE BEGIN a\nRT-PROBE END a 1 ok\n"
            "RT-PROBE SUITE DONE\n")
        text = report_mod.render_report({}, parsed)
        self.assertIn("Suite: complete", text)

    def test_report_incomplete_flagged(self):
        parsed = measure_mod.parse_lines("RT-PROBE BEGIN a\n")
        text = report_mod.render_report({}, parsed)
        self.assertIn("INCOMPLETE", text)
        self.assertIn("Incomplete probes: a", text)

    def test_calibration_section_present(self):
        parsed = measure_mod.parse_lines(
            "RT-PROBE DIAG calibration cycles_per_sec 2445000000\n"
            "RT-PROBE BEGIN calibration\n"
            "RT-PROBE SAMPLE calibration timer_overhead_ns 400 0\n"
            "RT-PROBE SAMPLE calibration timer_overhead_ns 500 1\n"
            "RT-PROBE SAMPLE calibration timer_resolution_ns 400 0\n"
            "RT-PROBE END calibration 3 ok\n"
            "RT-PROBE SUITE DONE\n")
        results = measure_mod.summarize_all(parsed)
        text = report_mod.render_report(results, parsed)
        self.assertIn("Calibration (measurement floor)", text)
        self.assertIn("timer overhead", text)
        self.assertIn("timer resolution", text)
        self.assertIn("cycles_per_sec: 2445000000", text)
        self.assertIn("NOT overhead-subtracted", text)
        # Calibration metrics live only in the floor section, not in
        # the per-metric listing.
        self.assertNotIn("calibration / timer_overhead_ns", text)
        self.assertNotIn("calibration / timer_resolution_ns", text)

    def test_calibration_section_absent_without_samples(self):
        results = {("msg_roundtrip", "roundtrip_ns"):
                   measure_mod.summarize([1000, 2000])}
        text = report_mod.render_report(results)
        self.assertNotIn("Calibration (measurement floor)", text)

    def test_load_section_present(self):
        parsed = measure_mod.parse_lines(
            "RT-PROBE DIAG jitter_load mem_mb=64 stride=64B "
            "streamers=2 spinners=2\n"
            "RT-PROBE BEGIN jitter_load\n"
            "RT-PROBE SAMPLE jitter_load jitter_idle_ns 400 0\n"
            "RT-PROBE SAMPLE jitter_load jitter_load_ns 800 0\n"
            "RT-PROBE END jitter_load 2 ok\n"
            "RT-PROBE SUITE DONE\n")
        results = measure_mod.summarize_all(parsed)
        text = report_mod.render_report(results, parsed)
        self.assertIn("Load configuration (jitter load phase)", text)
        self.assertIn("jitter_load: mem_mb=64 stride=64B "
                      "streamers=2 spinners=2", text)

    def test_load_section_absent_without_diag(self):
        parsed = measure_mod.parse_lines(
            "RT-PROBE BEGIN jitter_load\n"
            "RT-PROBE SAMPLE jitter_load jitter_idle_ns 400 0\n"
            "RT-PROBE END jitter_load 1 ok\n"
            "RT-PROBE SUITE DONE\n")
        results = measure_mod.summarize_all(parsed)
        text = report_mod.render_report(results, parsed)
        self.assertNotIn("Load configuration", text)

    def test_repeat_sections(self):
        r1 = {("a", "m"): measure_mod.summarize([100, 200])}
        r2 = {("a", "m"): measure_mod.summarize([300, 400])}
        agg = measure_mod.aggregate_runs([r1, r2])
        pooled = measure_mod.summarize([100, 200, 300, 400])
        text = report_mod.render_report(
            {("a", "m"): pooled}, aggregate=agg, per_run=[r1, r2],
            repeat=2, runs_complete=2)
        self.assertIn("Repeatability: 2 runs — 2 complete", text)
        self.assertIn("Cross-run aggregate", text)
        self.assertIn("run means (2 runs)", text)
        self.assertIn("spread", text)
        self.assertIn("Per-run detail", text)
        self.assertIn("run 1:", text)
        self.assertIn("run 2:", text)

    def test_repeat_partial_completion(self):
        r1 = {("a", "m"): measure_mod.summarize([100, 200])}
        agg = measure_mod.aggregate_runs([r1])
        text = report_mod.render_report(
            {("a", "m"): measure_mod.summarize([100, 200])},
            aggregate=agg, per_run=[r1], repeat=2, runs_complete=1)
        self.assertIn("Repeatability: 2 runs — 1 complete", text)


class TestHistogram(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(report_mod.histogram([]), ["(no samples)"])

    def test_all_equal(self):
        lines = report_mod.histogram([500, 500, 500])
        self.assertEqual(len(lines), 1)
        self.assertIn("3 samples", lines[0])

    def test_spread_scales(self):
        lines = report_mod.histogram([0, 100, 200, 300, 1000])
        self.assertEqual(len(lines), 10)
        # The bin holding the max value has a bar; empty bins have none.
        self.assertIn("#", lines[-1])
        self.assertIn("| 1", lines[-1])


class TestWriteReport(unittest.TestCase):
    def test_files_written(self):
        parsed = measure_mod.parse_lines(
            "RT-PROBE BEGIN a\n"
            "RT-PROBE SAMPLE a m 10 0\n"
            "RT-PROBE SAMPLE a m 20 1\n"
            "RT-PROBE END a 2 ok\n"
            "RT-PROBE SUITE DONE\n")
        results = measure_mod.summarize_all(parsed)
        with tempfile.TemporaryDirectory() as tmp:
            report_path, hist_path, charts_path = report_mod.write_report(
                results, parsed, tmp)
            self.assertTrue(os.path.isfile(report_path))
            self.assertTrue(os.path.isfile(hist_path))
            self.assertTrue(os.path.isfile(charts_path))
            # The synthetic log has no charted metric, so no SVGs —
            # the page is still written (see test_charts for SVGs).
            self.assertTrue(os.path.isdir(os.path.join(tmp, "charts")))
            with open(report_path, encoding="utf-8") as fh:
                self.assertIn("a / m", fh.read())


if __name__ == "__main__":
    unittest.main()
