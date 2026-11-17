"""Tests for rtprobe.charts (stdlib-only SVG charts)."""

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtprobe import charts as charts_mod
from rtprobe import measure as measure_mod
from rtprobe import report as report_mod


def _synthetic_log():
    """A small but complete suite log: all four probes + calibration."""
    lines = [
        "RT-PROBE BEGIN calibration",
        "RT-PROBE SAMPLE calibration timer_overhead_ns 20 0",
        "RT-PROBE SAMPLE calibration timer_overhead_ns 30 1",
        "RT-PROBE SAMPLE calibration timer_resolution_ns 10 0",
        "RT-PROBE END calibration 3 ok",
        "RT-PROBE BEGIN msg_roundtrip",
        "RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 21000 0",
        "RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 26000 1",
        "RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 31000 2",
        "RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 45000 3",
        "RT-PROBE END msg_roundtrip 4 ok",
        "RT-PROBE BEGIN wake_latency",
        "RT-PROBE SAMPLE wake_latency wake_ns 9000 0",
        "RT-PROBE SAMPLE wake_latency wake_ns 14000 1",
        "RT-PROBE SAMPLE wake_latency wake_ns 30000 2",
        "RT-PROBE END wake_latency 3 ok",
        "RT-PROBE BEGIN jitter_load",
        "RT-PROBE SAMPLE jitter_load jitter_idle_ns 400000 0",
        "RT-PROBE SAMPLE jitter_load jitter_idle_ns 700000 1",
        "RT-PROBE SAMPLE jitter_load jitter_idle_ns 900000 2",
        "RT-PROBE SAMPLE jitter_load jitter_load_ns 800000 0",
        "RT-PROBE SAMPLE jitter_load jitter_load_ns 5000000 1",
        "RT-PROBE SAMPLE jitter_load jitter_load_ns 20000000 2",
        "RT-PROBE END jitter_load 6 ok",
        "RT-PROBE BEGIN prio_inversion",
        "RT-PROBE SAMPLE prio_inversion inversion_wait_none_ns "
        "290000000 0",
        "RT-PROBE SAMPLE prio_inversion inversion_wait_none_ns "
        "302000000 1",
        "RT-PROBE SAMPLE prio_inversion inversion_wait_inherit_ns "
        "100000000 0",
        "RT-PROBE SAMPLE prio_inversion inversion_wait_inherit_ns "
        "100200000 1",
        "RT-PROBE END prio_inversion 4 ok",
        "RT-PROBE SUITE DONE",
    ]
    return "\n".join(lines) + "\n"


def _parsed_and_results(text=None):
    parsed = measure_mod.parse_lines(text if text is not None
                                     else _synthetic_log())
    return parsed, measure_mod.summarize_all(parsed)


class TestFmtNs(unittest.TestCase):
    def test_matches_report_formatter(self):
        # charts._fmt_ns mirrors report._fmt_ns; drift would show
        # different units on the chart axes vs the report text.
        for value in (0, 9, 999, 1000, 1500, 999999, 1000000,
                      2500000, 100000000, 302000000):
            self.assertEqual(charts_mod._fmt_ns(value),
                             report_mod._fmt_ns(value))


class TestHistogramBins(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(charts_mod.histogram_bins([]))

    def test_all_equal(self):
        lo, hi, counts = charts_mod.histogram_bins([500, 500, 500])
        self.assertEqual((lo, hi), (500, 500))
        self.assertEqual(counts, [3])

    def test_counts_match_report_histogram(self):
        # Same binning as the ASCII histogram: every sample lands in
        # exactly one bin, and the per-bin counts agree.
        samples = [0, 100, 200, 300, 1000]
        lo, hi, counts = charts_mod.histogram_bins(samples, bins=10)
        self.assertEqual(sum(counts), len(samples))
        self.assertEqual(counts[-1], 1)  # max lands in the last bin
        lines = report_mod.histogram(samples, bins=10)
        ascii_counts = [int(line.rsplit("|", 1)[1].strip())
                        for line in lines]
        self.assertEqual(counts, ascii_counts)


class TestSvgHistogram(unittest.TestCase):
    def test_valid_xml_with_markers(self):
        _parsed, results = _parsed_and_results()
        samples = [21000, 26000, 31000, 45000]
        svg = charts_mod.svg_histogram(
            samples, results[("msg_roundtrip", "roundtrip_ns")],
            "msg round-trip")
        root = ET.fromstring(svg)
        self.assertEqual(root.tag,
                         "{http://www.w3.org/2000/svg}svg")
        self.assertIn("msg round-trip", svg)
        self.assertIn("p50", svg)
        self.assertIn("p90", svg)
        self.assertIn("p99", svg)
        self.assertIn("N=4", svg)
        self.assertIn("<rect", svg)

    def test_empty_samples(self):
        stats = measure_mod.summarize([1000, 2000])
        svg = charts_mod.svg_histogram([], stats, "empty")
        ET.fromstring(svg)  # still well-formed
        self.assertIn("(no samples)", svg)

    def test_all_equal_samples(self):
        stats = measure_mod.summarize([5000, 5000])
        svg = charts_mod.svg_histogram([5000, 5000], stats, "flat")
        ET.fromstring(svg)
        self.assertIn("<rect", svg)


class TestPrioBars(unittest.TestCase):
    def test_valid_xml_ratio_and_dots(self):
        _parsed, results = _parsed_and_results()
        svg = charts_mod.svg_prio_bars(
            [290000000, 302000000],
            results[("prio_inversion", "inversion_wait_none_ns")],
            [100000000, 100200000],
            results[("prio_inversion", "inversion_wait_inherit_ns")])
        ET.fromstring(svg)
        self.assertIn("NONE", svg)
        self.assertIn("INHERIT", svg)
        # 2 rounds x 2 protocols = 4 dots.
        self.assertEqual(svg.count("<circle"), 4)
        # Mean ratio ~2.96x.
        self.assertIn("2.96", svg)


class TestJitterPair(unittest.TestCase):
    def test_valid_xml_delta_line(self):
        _parsed, results = _parsed_and_results()
        svg = charts_mod.svg_jitter_pair(
            [400000, 700000, 900000],
            results[("jitter_load", "jitter_idle_ns")],
            [800000, 5000000, 20000000],
            results[("jitter_load", "jitter_load_ns")])
        ET.fromstring(svg)
        self.assertIn("idle", svg)
        self.assertIn("under CPU + memory load", svg)
        self.assertIn("load / idle", svg)


class TestBuildCharts(unittest.TestCase):
    def test_full_set(self):
        parsed, results = _parsed_and_results()
        charts = charts_mod.build_charts(results, parsed)
        self.assertEqual(sorted(charts),
                         ["jitter_idle_vs_load.svg",
                          "msg_roundtrip.svg", "prio_inversion.svg",
                          "wake_latency.svg"])
        for _title, svg in charts.values():
            ET.fromstring(svg)

    def test_partial_log_omits_missing_charts(self):
        text = ("RT-PROBE BEGIN msg_roundtrip\n"
                "RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 21000 0\n"
                "RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 26000 1\n"
                "RT-PROBE END msg_roundtrip 2 ok\n"
                "RT-PROBE SUITE DONE\n")
        parsed, results = _parsed_and_results(text)
        charts = charts_mod.build_charts(results, parsed)
        self.assertEqual(sorted(charts), ["msg_roundtrip.svg"])

    def test_jitter_single_phase_falls_back(self):
        text = ("RT-PROBE BEGIN jitter_load\n"
                "RT-PROBE SAMPLE jitter_load jitter_idle_ns 400000 0\n"
                "RT-PROBE SAMPLE jitter_load jitter_idle_ns 700000 1\n"
                "RT-PROBE END jitter_load 2 ok\n"
                "RT-PROBE SUITE DONE\n")
        parsed, results = _parsed_and_results(text)
        charts = charts_mod.build_charts(results, parsed)
        self.assertEqual(sorted(charts), ["jitter.svg"])

    def test_empty_log(self):
        parsed, results = _parsed_and_results("")
        self.assertEqual(charts_mod.build_charts(results, parsed), {})


class TestWriteCharts(unittest.TestCase):
    def test_files_written_and_page_self_contained(self):
        parsed, results = _parsed_and_results()
        with tempfile.TemporaryDirectory() as tmp:
            html_path, svg_paths = charts_mod.write_charts(
                results, parsed, tmp, repeat=2)
            self.assertTrue(os.path.isfile(html_path))
            self.assertEqual(len(svg_paths), 4)
            for path in svg_paths:
                self.assertTrue(os.path.isfile(path))
                ET.parse(path)
            with open(html_path, encoding="utf-8") as fh:
                html = fh.read()
            self.assertIn("RT-Probe charts", html)
            self.assertIn("2 runs pooled", html)
            self.assertIn("Measurement floor", html)
            self.assertIn("QEMU/TCG", html)
            self.assertIn("<svg", html)
            # Self-contained: no scripts and no external references
            # (the SVG xmlns URI is a namespace name, not a fetch).
            self.assertNotIn("<script", html)
            self.assertNotIn("src=", html)
            self.assertNotIn("href=", html)
            self.assertNotIn("@import", html)
            self.assertNotIn("url(", html)

    def test_empty_log_still_writes_page(self):
        parsed, results = _parsed_and_results("")
        with tempfile.TemporaryDirectory() as tmp:
            html_path, svg_paths = charts_mod.write_charts(
                results, parsed, tmp)
            self.assertTrue(os.path.isfile(html_path))
            self.assertEqual(svg_paths, [])
            with open(html_path, encoding="utf-8") as fh:
                self.assertIn("No charts", fh.read())


if __name__ == "__main__":
    unittest.main()
