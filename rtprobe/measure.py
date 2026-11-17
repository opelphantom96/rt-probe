"""Parse RT-PROBE lines from a serial-console log and summarise them.

Line format (see probes/probes.h):
    RT-PROBE BEGIN <name>
    RT-PROBE SAMPLE <name> <metric> <value_ns> <seq>
    RT-PROBE END <name> <count> <status>

Everything else (boot messages, sshd faults, ...) is ignored.
"""

import re
from dataclasses import dataclass, field

BEGIN_RE = re.compile(r"^RT-PROBE BEGIN (\S+)\s*$")
SAMPLE_RE = re.compile(r"^RT-PROBE SAMPLE (\S+) (\S+) (\d+) (\d+)\s*$")
END_RE = re.compile(r"^RT-PROBE END (\S+) (\d+) (\S+)\s*$")
DIAG_RE = re.compile(r"^RT-PROBE DIAG (\S+) (.*\S)\s*$")
SUITE_DONE_RE = re.compile(r"^RT-PROBE SUITE DONE\s*$")
MISSING_RE = re.compile(r"^RT-PROBE MISSING (\S+)\s*$")


@dataclass
class ParsedLog:
    """Result of parsing one serial log."""

    # (probe, metric) -> list of sample values in nanoseconds, in order.
    samples: dict = field(default_factory=dict)
    # probe -> {"count": int, "status": str} from END lines.
    ends: dict = field(default_factory=dict)
    # probe names that printed BEGIN but no END.
    incomplete: list = field(default_factory=list)
    # probe names the runner reported missing from the image.
    missing: list = field(default_factory=list)
    # True when the runner printed RT-PROBE SUITE DONE.
    suite_done: bool = False
    # (probe, free text) diagnostic lines, e.g. calibration's
    # cycles_per_sec. Kept in order; the report may use them.
    diag: list = field(default_factory=list)
    # Non-RT-PROBE lines are counted, not kept (boot logs are big).
    other_lines: int = 0


def parse_lines(text: str) -> ParsedLog:
    """Parse RT-PROBE output out of a serial log."""
    parsed = ParsedLog()
    begun = set()

    for line in text.splitlines():
        line = line.strip()
        m = SAMPLE_RE.match(line)
        if m:
            name, metric, value, _seq = m.groups()
            parsed.samples.setdefault((name, metric), []).append(int(value))
            continue
        m = BEGIN_RE.match(line)
        if m:
            begun.add(m.group(1))
            continue
        m = END_RE.match(line)
        if m:
            name, count, status = m.groups()
            parsed.ends[name] = {"count": int(count), "status": status}
            begun.discard(name)
            continue
        m = MISSING_RE.match(line)
        if m:
            parsed.missing.append(m.group(1))
            continue
        m = DIAG_RE.match(line)
        if m:
            parsed.diag.append((m.group(1), m.group(2)))
            continue
        if SUITE_DONE_RE.match(line):
            parsed.suite_done = True
            continue
        parsed.other_lines += 1

    parsed.incomplete = sorted(begun)
    return parsed


def percentile(sorted_samples, pct):
    """Percentile of an already-sorted sample list (linear interpolation).

    pct is 0..100. Raises ValueError on an empty list.
    """
    if not sorted_samples:
        raise ValueError("percentile of empty sample list")
    if len(sorted_samples) == 1:
        return float(sorted_samples[0])
    rank = (pct / 100.0) * (len(sorted_samples) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_samples) - 1)
    frac = rank - lo
    return sorted_samples[lo] * (1.0 - frac) + sorted_samples[hi] * frac


def summarize(samples):
    """Summary statistics for a list of nanosecond samples.

    Returns a dict with count/min/p50/p90/p99/max/mean (floats except
    count). Raises ValueError on an empty list.
    """
    if not samples:
        raise ValueError("summarize of empty sample list")
    ordered = sorted(samples)
    total = sum(ordered)
    return {
        "count": len(ordered),
        "min": float(ordered[0]),
        "p50": percentile(ordered, 50),
        "p90": percentile(ordered, 90),
        "p99": percentile(ordered, 99),
        "max": float(ordered[-1]),
        "mean": total / len(ordered),
    }


def summarize_all(parsed: ParsedLog) -> dict:
    """Summaries for every (probe, metric) in a parsed log."""
    return {key: summarize(values)
            for key, values in sorted(parsed.samples.items())}


def merge_parsed(parsed_list) -> ParsedLog:
    """Pool the samples of several runs into one ParsedLog.

    Samples concatenate in run order; suite_done is True only when
    every run finished; incomplete/missing are the sorted union across
    runs; diag lines concatenate; other_lines sum. Used for the pooled
    statistics of a --repeat run.
    """
    merged = ParsedLog()
    if not parsed_list:
        return merged
    for parsed in parsed_list:
        for key, values in parsed.samples.items():
            merged.samples.setdefault(key, []).extend(values)
        for name, end in parsed.ends.items():
            merged.ends.setdefault(name, end)
        merged.incomplete = sorted(set(merged.incomplete)
                                   | set(parsed.incomplete))
        merged.missing = sorted(set(merged.missing)
                                | set(parsed.missing))
        merged.diag.extend(parsed.diag)
        merged.other_lines += parsed.other_lines
    merged.suite_done = all(p.suite_done for p in parsed_list)
    return merged


def aggregate_runs(per_run_summaries) -> dict:
    """Cross-run statistics for each (probe, metric).

    per_run_summaries: list of results dicts, one per run, as returned
    by summarize_all. Returns {(probe, metric): {...}} with:
      runs          number of runs that produced this metric
      mean_of_means mean of the per-run means
      min_run_mean  smallest per-run mean
      max_run_mean  largest per-run mean
      spread        max_run_mean - min_run_mean (run-to-run spread of
                    the mean, in ns)
      mean_of_p50   mean of the per-run p50s
    A metric missing from a run is skipped for that run (a run that
    ends early still contributes what it measured).
    """
    by_key = {}
    for summary in per_run_summaries:
        for key, stats in summary.items():
            by_key.setdefault(key, []).append(stats)
    out = {}
    for key in sorted(by_key):
        stats_list = by_key[key]
        means = [s["mean"] for s in stats_list]
        p50s = [s["p50"] for s in stats_list]
        out[key] = {
            "runs": len(stats_list),
            "mean_of_means": sum(means) / len(means),
            "min_run_mean": min(means),
            "max_run_mean": max(means),
            "spread": max(means) - min(means),
            "mean_of_p50": sum(p50s) / len(p50s),
        }
    return out
