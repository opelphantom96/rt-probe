"""Tests for rtprobe.measure (log parsing + statistics + repeat
aggregation)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtprobe import measure as measure_mod

SAMPLE_LOG = """SeaBIOS (version 1.16.3-debian-1.16.3-2)
Booting from ROM..
Startup complete
QNX noname 8.0.0 2026/10/30-09:10:05EDT x86pc x86_64
RT-PROBE BEGIN msg_roundtrip
RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 1234 0
RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 2345 1
RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 3456 2
RT-PROBE END msg_roundtrip 3 ok
RT-PROBE BEGIN wake_latency
RT-PROBE SAMPLE wake_latency wake_ns 999 0
RT-PROBE SUITE DONE
"""


class TestParseLines(unittest.TestCase):
    def test_samples_and_ends(self):
        parsed = measure_mod.parse_lines(SAMPLE_LOG)
        self.assertEqual(
            parsed.samples[("msg_roundtrip", "roundtrip_ns")],
            [1234, 2345, 3456])
        self.assertEqual(parsed.samples[("wake_latency", "wake_ns")],
                         [999])
        self.assertEqual(parsed.ends["msg_roundtrip"],
                         {"count": 3, "status": "ok"})
        self.assertTrue(parsed.suite_done)
        self.assertEqual(parsed.missing, [])

    def test_incomplete_probe_detected(self):
        parsed = measure_mod.parse_lines(SAMPLE_LOG)
        self.assertEqual(parsed.incomplete, ["wake_latency"])

    def test_boot_noise_counted_not_kept(self):
        parsed = measure_mod.parse_lines(SAMPLE_LOG)
        self.assertGreater(parsed.other_lines, 0)
        self.assertEqual(len(parsed.samples), 2)

    def test_no_suite_done(self):
        parsed = measure_mod.parse_lines("RT-PROBE BEGIN x\n")
        self.assertFalse(parsed.suite_done)
        self.assertEqual(parsed.incomplete, ["x"])

    def test_missing_probe(self):
        parsed = measure_mod.parse_lines("RT-PROBE MISSING jitter_load\n"
                                         "RT-PROBE SUITE DONE\n")
        self.assertEqual(parsed.missing, ["jitter_load"])
        self.assertTrue(parsed.suite_done)

    def test_malformed_lines_ignored(self):
        parsed = measure_mod.parse_lines(
            "RT-PROBE SAMPLE only-two-fields\n"
            "RT-PROBE SAMPLE a b not-a-number 0\n"
            "RT-PROBE SAMPLE a b 10 0\n")
        self.assertEqual(parsed.samples, {("a", "b"): [10]})

    def test_diag_lines_kept(self):
        parsed = measure_mod.parse_lines(
            "RT-PROBE DIAG calibration cycles_per_sec 2445000000\n"
            "RT-PROBE DIAG pin low rc=0/0 prev=0x3 cur=0x1 ok\n"
            "RT-PROBE SUITE DONE\n")
        self.assertEqual(parsed.diag, [
            ("calibration", "cycles_per_sec 2445000000"),
            ("pin", "low rc=0/0 prev=0x3 cur=0x1 ok"),
        ])
        self.assertTrue(parsed.suite_done)

    def test_diag_line_counts_as_diag_not_other(self):
        parsed = measure_mod.parse_lines(
            "RT-PROBE DIAG calibration cycles_per_sec 100\n")
        self.assertEqual(parsed.other_lines, 0)


class TestMergeAndAggregate(unittest.TestCase):
    def _parsed(self, text):
        return measure_mod.parse_lines(text)

    def test_merge_pools_samples(self):
        p1 = self._parsed(
            "RT-PROBE SAMPLE a m 10 0\nRT-PROBE SAMPLE a m 20 1\n"
            "RT-PROBE SUITE DONE\n")
        p2 = self._parsed(
            "RT-PROBE SAMPLE a m 30 0\nRT-PROBE SUITE DONE\n")
        merged = measure_mod.merge_parsed([p1, p2])
        self.assertEqual(merged.samples[("a", "m")], [10, 20, 30])
        self.assertTrue(merged.suite_done)

    def test_merge_incomplete_union(self):
        p1 = self._parsed("RT-PROBE BEGIN a\nRT-PROBE SUITE DONE\n")
        p2 = self._parsed("RT-PROBE BEGIN b\n")
        merged = measure_mod.merge_parsed([p1, p2])
        self.assertFalse(merged.suite_done)
        self.assertEqual(merged.incomplete, ["a", "b"])

    def test_merge_empty(self):
        merged = measure_mod.merge_parsed([])
        self.assertEqual(merged.samples, {})
        self.assertFalse(merged.suite_done)

    def test_aggregate_run_means_and_spread(self):
        r1 = {("a", "m"): measure_mod.summarize([100, 200])}
        r2 = {("a", "m"): measure_mod.summarize([300, 400])}
        agg = measure_mod.aggregate_runs([r1, r2])
        entry = agg[("a", "m")]
        self.assertEqual(entry["runs"], 2)
        self.assertAlmostEqual(entry["mean_of_means"], 250.0)
        self.assertAlmostEqual(entry["min_run_mean"], 150.0)
        self.assertAlmostEqual(entry["max_run_mean"], 350.0)
        self.assertAlmostEqual(entry["spread"], 200.0)
        self.assertAlmostEqual(entry["mean_of_p50"], 250.0)

    def test_aggregate_skips_missing_metric(self):
        r1 = {("a", "m"): measure_mod.summarize([100, 200]),
              ("a", "n"): measure_mod.summarize([5, 6])}
        r2 = {("a", "m"): measure_mod.summarize([300, 400])}
        agg = measure_mod.aggregate_runs([r1, r2])
        self.assertEqual(agg[("a", "n")]["runs"], 1)
        self.assertEqual(agg[("a", "m")]["runs"], 2)


class TestStatistics(unittest.TestCase):
    def test_percentile(self):
        samples = [10, 20, 30, 40]
        self.assertAlmostEqual(measure_mod.percentile(samples, 50), 25.0)
        self.assertAlmostEqual(measure_mod.percentile(samples, 0), 10.0)
        self.assertAlmostEqual(measure_mod.percentile(samples, 100), 40.0)
        self.assertAlmostEqual(measure_mod.percentile(samples, 90), 37.0)

    def test_percentile_single(self):
        self.assertEqual(measure_mod.percentile([7], 99), 7.0)

    def test_percentile_empty_raises(self):
        with self.assertRaises(ValueError):
            measure_mod.percentile([], 50)

    def test_summarize(self):
        s = measure_mod.summarize([100, 200, 300, 400])
        self.assertEqual(s["count"], 4)
        self.assertEqual(s["min"], 100.0)
        self.assertEqual(s["max"], 400.0)
        self.assertEqual(s["mean"], 250.0)
        self.assertAlmostEqual(s["p50"], 250.0)

    def test_summarize_empty_raises(self):
        with self.assertRaises(ValueError):
            measure_mod.summarize([])

    def test_summarize_all(self):
        parsed = measure_mod.parse_lines(SAMPLE_LOG)
        out = measure_mod.summarize_all(parsed)
        self.assertIn(("msg_roundtrip", "roundtrip_ns"), out)
        self.assertEqual(out[("msg_roundtrip", "roundtrip_ns")]["count"], 3)


if __name__ == "__main__":
    unittest.main()
