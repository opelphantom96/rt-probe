"""Terminal report rendering for RT-Probe results.

Pure functions over the summary dicts from rtprobe.measure; no I/O
except write_report().
"""

import os

from rtprobe import charts as charts_mod

HISTOGRAM_WIDTH = 40


def _fmt_ns(value):
    """Format a nanosecond value in the most readable unit."""
    if value >= 1_000_000:
        return "%.2f ms" % (value / 1_000_000.0)
    if value >= 1_000:
        return "%.2f us" % (value / 1_000.0)
    return "%.0f ns" % value


def histogram(samples, width=HISTOGRAM_WIDTH, bins=10):
    """ASCII histogram of samples. Returns a list of text lines."""
    if not samples:
        return ["(no samples)"]
    lo, hi = min(samples), max(samples)
    if lo == hi:
        return ["all %d samples at %s" % (len(samples), _fmt_ns(lo))]
    counts = [0] * bins
    span = hi - lo
    for value in samples:
        idx = min(int((value - lo) * bins / span), bins - 1)
        counts[idx] += 1
    peak = max(counts)
    lines = []
    for i, count in enumerate(counts):
        start = lo + span * i / bins
        end = lo + span * (i + 1) / bins
        bar = "#" * max(1, int(count * width / peak)) if count else ""
        lines.append("%10s-%10s |%-*s| %d" %
                     (_fmt_ns(start), _fmt_ns(end), width, bar, count))
    return lines


def _calibration_lines(results, parsed):
    """Measurement-floor section from the calibration probe's samples.

    Returns [] when the log has no calibration samples (e.g. an old
    log, or a hand-built image without the probe). The section states
    the floor the probe numbers sit on; it does not subtract anything.
    """
    overhead = results.get(("calibration", "timer_overhead_ns"))
    resolution = results.get(("calibration", "timer_resolution_ns"))
    if overhead is None and resolution is None:
        return []
    lines = []
    lines.append("Calibration (measurement floor)")
    lines.append("-------------------------------")
    if overhead is not None:
        lines.append("timer overhead (empty ClockCycles() pair, N=%d): "
                     "min %s  p50 %s  mean %s" % (
                         overhead["count"],
                         _fmt_ns(overhead["min"]),
                         _fmt_ns(overhead["p50"]),
                         _fmt_ns(overhead["mean"])))
    if resolution is not None:
        lines.append("timer resolution (smallest nonzero delta): %s"
                     % _fmt_ns(resolution["mean"]))
    cps = None
    if parsed is not None:
        for probe, text in parsed.diag:
            if probe == "calibration" and text.startswith("cycles_per_sec "):
                cps = text.split(None, 1)[1]
                break
    if cps is not None:
        lines.append("cycles_per_sec: %s" % cps)
    lines.append("The p50 overhead is the practical floor: samples near")
    lines.append("or below it are not resolvable. Probe numbers in this")
    lines.append("report are raw and NOT overhead-subtracted.")
    lines.append("")
    return lines


def _load_lines(parsed):
    """Load-configuration section for the jitter load phase (TODO #6).

    Reads the `RT-PROBE DIAG jitter_load ...` line the probe prints
    (mem_mb, stride, streamer/spinner counts) and states what the
    load phase actually ran. Returns [] when the log has no such line
    (e.g. an old log from before the memory load existed).
    """
    if parsed is None:
        return []
    lines = []
    for probe, text in parsed.diag:
        if probe == "jitter_load":
            lines.append("jitter_load: %s" % text)
    if not lines:
        return []
    return ["Load configuration (jitter load phase)",
            "--------------------------------------"] + lines + [""]


def _aggregate_lines(aggregate):
    """Cross-run aggregate section (TODO #4).

    aggregate: {(probe, metric): {...}} from measure.aggregate_runs.
    The pooled statistics live in the per-metric details below; this
    section adds the run-to-run view: how the per-run means moved.
    """
    lines = []
    lines.append("Cross-run aggregate")
    lines.append("-------------------")
    for (probe, metric), agg in sorted(aggregate.items()):
        lines.append("%s / %s" % (probe, metric))
        lines.append("  run means (%d runs): min %s  mean %s  max %s  "
                     "spread %s" % (
                         agg["runs"],
                         _fmt_ns(agg["min_run_mean"]),
                         _fmt_ns(agg["mean_of_means"]),
                         _fmt_ns(agg["max_run_mean"]),
                         _fmt_ns(agg["spread"])))
        lines.append("  mean of run p50s: %s"
                     % _fmt_ns(agg["mean_of_p50"]))
    lines.append("")
    return lines


def _per_run_lines(per_run):
    """One compact line per run: each metric's mean in that run.

    per_run: list of per-run results dicts (from summarize_all).
    Calibration metrics are left out here — they live in the
    calibration section.
    """
    lines = []
    lines.append("Per-run detail")
    lines.append("--------------")
    for i, summary in enumerate(per_run, 1):
        parts = ["%s/%s mean %s" % (probe, metric, _fmt_ns(stats["mean"]))
                 for (probe, metric), stats in sorted(summary.items())
                 if probe != "calibration"]
        lines.append("run %d: %s" % (i, "; ".join(parts)))
    lines.append("")
    return lines


def render_report(results, parsed=None, aggregate=None, per_run=None,
                  repeat=1, runs_complete=None):
    """Render the full text report for summarized results.

    results: {(probe, metric): summary-dict} from measure.summarize_all.
    parsed: optional ParsedLog, used for the completeness section.
    aggregate: optional cross-run dict from measure.aggregate_runs
        (TODO #4); per_run: optional list of per-run results dicts.
    repeat: number of runs the report covers (1 = single run).
    runs_complete: how many of the runs finished (None = unknown).
    Calibration metrics are rendered in their own floor section, not
    in the per-metric listing.
    """
    lines = []
    lines.append("RT-PROBE REPORT")
    lines.append("===============")
    lines.append("")

    if repeat > 1:
        if runs_complete is None:
            lines.append("Repeatability: %d runs" % repeat)
        else:
            lines.append("Repeatability: %d runs — %d complete"
                         % (repeat, runs_complete))
        lines.append("")

    if parsed is not None:
        done = sorted(parsed.ends)
        lines.append("Suite: %s" % ("complete" if parsed.suite_done
                                    else "INCOMPLETE (no SUITE DONE)"))
        if parsed.missing:
            lines.append("Missing probes: %s" % ", ".join(parsed.missing))
        if parsed.incomplete:
            lines.append("Incomplete probes: %s"
                         % ", ".join(parsed.incomplete))
        if done:
            lines.append("Finished probes: %s" % ", ".join(done))
        lines.append("")

    lines.extend(_calibration_lines(results, parsed))
    lines.extend(_load_lines(parsed))
    if aggregate:
        lines.extend(_aggregate_lines(aggregate))
    if per_run:
        lines.extend(_per_run_lines(per_run))

    if not results:
        lines.append("No samples collected.")
        lines.append("")
        lines.append("All timings are indicative QEMU/TCG measurements,")
        lines.append("not hardware-grade numbers (see DESIGN.md).")
        return "\n".join(lines) + "\n"

    for (probe, metric), summary in sorted(results.items()):
        if probe == "calibration":
            continue  # rendered in the calibration section above
        lines.append("%s / %s" % (probe, metric))
        lines.append("-" * (len(probe) + len(metric) + 3))
        lines.append("count %d  min %s  p50 %s  p90 %s  p99 %s  max %s  "
                     "mean %s" % (
                         summary["count"],
                         _fmt_ns(summary["min"]),
                         _fmt_ns(summary["p50"]),
                         _fmt_ns(summary["p90"]),
                         _fmt_ns(summary["p99"]),
                         _fmt_ns(summary["max"]),
                         _fmt_ns(summary["mean"])))
        lines.append("")

    lines.append("All timings are indicative QEMU/TCG measurements,")
    lines.append("not hardware-grade numbers (see DESIGN.md).")
    return "\n".join(lines) + "\n"


def render_histograms(parsed):
    """Render one ASCII histogram per (probe, metric)."""
    lines = []
    for key in sorted(parsed.samples):
        lines.append("%s / %s" % (key[0], key[1]))
        lines.append("-" * (len(key[0]) + len(key[1]) + 3))
        lines.extend(histogram(parsed.samples[key]))
        lines.append("")
    return "\n".join(lines) + "\n"


def write_report(results, parsed, output_dir, aggregate=None, per_run=None,
                 repeat=1, runs_complete=None):
    """Write report.txt (+ histograms + charts) into output_dir.

    Returns (report_path, hist_path, charts_html_path). results/parsed
    are the POOLED values for a --repeat run (or the single run's
    values otherwise); aggregate/per_run carry the cross-run view.
    Histograms are always drawn from the pooled samples, calibration
    included; charts (charts.html + charts/*.svg) are drawn for every
    metric the pooled log supports.
    """
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "report.txt")
    hist_path = os.path.join(output_dir, "histograms.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(render_report(results, parsed, aggregate=aggregate,
                               per_run=per_run, repeat=repeat,
                               runs_complete=runs_complete))
    with open(hist_path, "w", encoding="utf-8") as fh:
        fh.write(render_histograms(parsed))
    charts_path, _svg_paths = charts_mod.write_charts(
        results, parsed, output_dir, repeat=repeat)
    return report_path, hist_path, charts_path
