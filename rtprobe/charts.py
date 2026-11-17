"""SVG charts for RT-Probe results (stdlib only, no third-party deps).

Renders the pooled measurement samples as vector charts:

  - histogram per distribution metric (msg roundtrip, wake latency,
    jitter idle/load)
  - mean + min/max-whisker bars for the prio-inversion A/B pair

Why SVG and not matplotlib PNG (the DESIGN.md sketch): the host tool
is stdlib-only by repo rule, and matplotlib is not guaranteed on a
fresh machine — "gracefully skipped when absent" would mean the demo
artifact silently does not exist. SVG is always produced, is vector
(crisp at any size for the demo video/poster), opens in any browser,
and converts to PNG with any standard tool (rsvg-convert, Inkscape,
Chromium headless screenshot) when raster frames are needed.

Output (written by write_charts, called from report.write_report, so
a normal ./rt-probe run produces them alongside report.txt):

  out/charts.html            self-contained page, inline SVG, no
                             external resources, no network fetch
  out/charts/<name>.svg     one standalone file per chart, for reuse
                             in the video / submission

Charts are drawn only for metrics present in the parsed log; a
missing probe means its chart is omitted, never faked.
"""

import os
from xml.sax.saxutils import escape as _escape

from rtprobe import measure as measure_mod

# Panel geometry (px).
HIST_W = 680
HIST_H = 300
MARGIN = {"left": 70, "right": 16, "top": 38, "bottom": 40}
BINS = 12

BAR_FILL = "#2f6fb2"
NONE_FILL = "#c0392b"      # prio NONE: the bad protocol
INHERIT_FILL = "#1a7f37"   # prio INHERIT: the fix
MARKER_COLORS = {"p50": "#1a7f37", "p90": "#cf8a00", "p99": "#c0392b"}


def _fmt_ns(value):
    """Format a nanosecond value in the most readable unit.

    Mirrors report._fmt_ns (kept local: report imports this module,
    so importing the formatter from report would be circular).
    """
    if value >= 1_000_000:
        return "%.2f ms" % (value / 1_000_000.0)
    if value >= 1_000:
        return "%.2f us" % (value / 1_000.0)
    return "%.0f ns" % value


def histogram_bins(samples, bins=BINS):
    """Bin samples the same way report.histogram does (linear, lo..hi).

    Returns (lo, hi, counts) or None for an empty list. A single
    distinct value yields one bin holding all samples.
    """
    if not samples:
        return None
    lo, hi = min(samples), max(samples)
    if lo == hi:
        return (lo, hi, [len(samples)])
    counts = [0] * bins
    span = hi - lo
    for value in samples:
        idx = min(int((value - lo) * bins / span), bins - 1)
        counts[idx] += 1
    return (lo, hi, counts)


def _svg_open(width, height, title):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" '
            'height="%d" viewBox="0 0 %d %d" role="img" '
            'aria-label="%s">'
            % (width, height, width, height, _escape(title)))


def _stats_caption(stats):
    """One-line count/min/p50/p90/p99/max/mean caption for a metric."""
    return ("N=%d  min %s  p50 %s  p90 %s  p99 %s  max %s  mean %s"
            % (stats["count"],
               _fmt_ns(stats["min"]), _fmt_ns(stats["p50"]),
               _fmt_ns(stats["p90"]), _fmt_ns(stats["p99"]),
               _fmt_ns(stats["max"]), _fmt_ns(stats["mean"])))


def _histogram_group(samples, stats, title, width, height):
    """One histogram panel as an SVG <g> at the origin.

    Bars + p50/p90/p99 dashed markers + legend. The caller positions
    the group with a transform. Returns the group string.
    """
    plot_w = width - MARGIN["left"] - MARGIN["right"]
    plot_h = height - MARGIN["top"] - MARGIN["bottom"]
    parts = ['<g>']
    parts.append('<text x="%d" y="18" font-size="14" font-weight="bold" '
                 'font-family="sans-serif">%s</text>'
                 % (MARGIN["left"], _escape(title)))
    binned = histogram_bins(samples)
    if binned is None:
        parts.append('<text x="%d" y="%d" font-size="12" '
                     'font-family="sans-serif">(no samples)</text>'
                     % (MARGIN["left"], MARGIN["top"] + 20))
        parts.append('</g>')
        return "".join(parts)
    lo, hi, counts = binned
    peak = max(counts)
    x0, y0 = MARGIN["left"], MARGIN["top"]
    # Gridlines + count labels.
    for frac, label in ((0.0, "0"), (0.5, str(peak // 2)),
                        (1.0, str(peak))):
        gy = y0 + plot_h - frac * plot_h
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" '
                     'stroke="#ddd" stroke-width="1"/>'
                     % (x0, gy, x0 + plot_w, gy))
        parts.append('<text x="%d" y="%.1f" font-size="10" '
                     'text-anchor="end" font-family="sans-serif">%s</text>'
                     % (x0 - 6, gy + 3, label))
    # Bars.
    n_bins = len(counts)
    bar_w = plot_w / n_bins
    for i, count in enumerate(counts):
        if not count:
            continue
        bar_h = count / peak * plot_h
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                     'fill="%s"/>'
                     % (x0 + i * bar_w + 1, y0 + plot_h - bar_h,
                        bar_w - 2, bar_h, BAR_FILL))
    # Percentile markers (only meaningful when lo < hi).
    if lo < hi:
        for key in ("p50", "p90", "p99"):
            value = stats[key]
            mx = x0 + (value - lo) / (hi - lo) * plot_w
            mx = min(max(mx, x0), x0 + plot_w)
            parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" '
                         'stroke="%s" stroke-width="1.5" '
                         'stroke-dasharray="5,3"/>'
                         % (mx, y0, mx, y0 + plot_h,
                            MARKER_COLORS[key]))
    # X-axis ticks: lo / mid / hi.
    for frac, value in ((0.0, lo), (0.5, (lo + hi) / 2.0), (1.0, hi)):
        tx = x0 + frac * plot_w
        parts.append('<text x="%.1f" y="%d" font-size="10" '
                     'text-anchor="middle" font-family="sans-serif">%s'
                     '</text>'
                     % (tx, y0 + plot_h + 16, _fmt_ns(value)))
    # Legend for the markers.
    lx = x0 + plot_w - 150
    for j, key in enumerate(("p50", "p90", "p99")):
        ly = y0 + 12 + j * 14
        parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" '
                     'stroke-width="2" stroke-dasharray="5,3"/>'
                     % (lx, ly, lx + 18, ly, MARKER_COLORS[key]))
        parts.append('<text x="%d" y="%d" font-size="10" '
                     'font-family="sans-serif">%s %s</text>'
                     % (lx + 22, ly + 3, key, _fmt_ns(stats[key])))
    # Caption: full stats line under the axis.
    parts.append('<text x="%d" y="%d" font-size="11" '
                 'font-family="sans-serif">%s</text>'
                 % (x0, y0 + plot_h + 32, _escape(_stats_caption(stats))))
    parts.append('</g>')
    return "".join(parts)


def svg_histogram(samples, stats, title):
    """Standalone histogram SVG for one metric."""
    body = _histogram_group(samples, stats, title, HIST_W, HIST_H)
    return _svg_open(HIST_W, HIST_H, title) + body + "</svg>"


def svg_jitter_pair(idle_samples, idle_stats, load_samples, load_stats):
    """Two stacked histogram panels: jitter idle vs under load.

    Each panel has its own x-scale (the load tail reaches ~30x the
    idle max, so a shared scale would crush the idle panel into one
    bin). A delta line under the panels states the p50/p90 ratios.
    """
    panel_h = HIST_H
    panel_gap = 48
    total_h = panel_h * 2 + panel_gap + 22
    parts = [_svg_open(HIST_W, total_h, "jitter idle vs load")]
    parts.append('<g transform="translate(0,0)">'
                 + _histogram_group(idle_samples, idle_stats,
                                    "jitter — idle", HIST_W, panel_h)
                 + '</g>')
    parts.append('<g transform="translate(0,%d)">'
                 % (panel_h + panel_gap)
                 + _histogram_group(load_samples, load_stats,
                                    "jitter — under CPU + memory load",
                                    HIST_W, panel_h)
                 + '</g>')
    ratio_p50 = (load_stats["p50"] / idle_stats["p50"]
                 if idle_stats["p50"] else float("nan"))
    ratio_p90 = (load_stats["p90"] / idle_stats["p90"]
                 if idle_stats["p90"] else float("nan"))
    parts.append('<text x="%d" y="%d" font-size="12" font-weight="bold" '
                 'font-family="sans-serif">load / idle: p50 %.1f\u00d7, '
                 'p90 %.1f\u00d7 (panels have different x-scales)</text>'
                 % (MARGIN["left"], total_h - 6, ratio_p50, ratio_p90))
    parts.append("</svg>")
    return "".join(parts)


def svg_prio_bars(none_samples, none_stats, inherit_samples,
                  inherit_stats):
    """Mean bars with min/max whiskers + per-round dots: NONE vs INHERIT.

    The mean is the bar; the whisker is the full observed range; each
    dot is one measured round, so the reader sees both the average
    and the spread (NONE varies with host scheduling under TCG).
    """
    width, height = HIST_W, HIST_H
    plot_w = width - MARGIN["left"] - MARGIN["right"]
    # The ratio line sits under the title, so the plot starts lower
    # than the usual top margin (otherwise the line would collide
    # with the per-bar mean labels at the bottom).
    ratio = (none_stats["mean"] / inherit_stats["mean"]
             if inherit_stats["mean"] else float("nan"))
    parts = [_svg_open(width, height, "priority inversion: NONE vs INHERIT")]
    parts.append('<text x="%d" y="18" font-size="14" font-weight="bold" '
                 'font-family="sans-serif">priority inversion \u2014 '
                 'high thread wait for the mutex</text>' % MARGIN["left"])
    parts.append('<text x="%d" y="34" font-size="12" font-weight="bold" '
                 'font-family="sans-serif">NONE mean is %.2f\u00d7 the '
                 'INHERIT mean \u2014 INHERIT waits ~the hold time; '
                 'NONE is hog-gated.</text>'
                 % (MARGIN["left"], ratio))
    y0 = 56
    plot_h = height - y0 - MARGIN["bottom"]
    x0 = MARGIN["left"]
    top = max(none_stats["max"], inherit_stats["max"]) * 1.08
    for frac, label in ((0.0, "0"), (0.5, _fmt_ns(top / 2)),
                        (1.0, _fmt_ns(top))):
        gy = y0 + plot_h - frac * plot_h
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" '
                     'stroke="#ddd" stroke-width="1"/>'
                     % (x0, gy, x0 + plot_w, gy))
        parts.append('<text x="%d" y="%.1f" font-size="10" '
                     'text-anchor="end" font-family="sans-serif">%s</text>'
                     % (x0 - 6, gy + 3, label))

    def y_of(value):
        return y0 + plot_h - (value / top) * plot_h

    series = (("NONE (no inheritance)", none_samples, none_stats,
               NONE_FILL),
              ("INHERIT", inherit_samples, inherit_stats, INHERIT_FILL))
    slot_w = plot_w / 2
    bar_w = 110
    for i, (label, samples, stats, color) in enumerate(series):
        cx = x0 + slot_w * (i + 0.5)
        mean_y = y_of(stats["mean"])
        parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%.1f" '
                     'fill="%s"/>'
                     % (cx - bar_w / 2, mean_y, bar_w,
                        y0 + plot_h - mean_y, color))
        # Whisker: min..max with caps.
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                     'stroke="#333" stroke-width="1.5"/>'
                     % (cx, y_of(stats["min"]), cx, y_of(stats["max"])))
        for wy in (y_of(stats["min"]), y_of(stats["max"])):
            parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                         'stroke="#333" stroke-width="1.5"/>'
                         % (cx - 14, wy, cx + 14, wy))
        # Per-round dots, spread horizontally inside the bar.
        n = len(samples)
        for j, value in enumerate(sorted(samples)):
            dx = (cx - bar_w / 2 + 10
                  + (j + 0.5) * (bar_w - 20) / max(n, 1))
            parts.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="#fff" '
                         'stroke="#333" stroke-width="1"/>'
                         % (dx, y_of(value)))
        parts.append('<text x="%.1f" y="%d" font-size="11" '
                     'text-anchor="middle" font-family="sans-serif">%s'
                     '</text>' % (cx, y0 + plot_h + 16, label))
        parts.append('<text x="%.1f" y="%d" font-size="11" '
                     'text-anchor="middle" font-family="sans-serif">mean '
                     '%s (N=%d, range %s\u2013%s)</text>'
                     % (cx, y0 + plot_h + 32, _fmt_ns(stats["mean"]),
                        stats["count"], _fmt_ns(stats["min"]),
                        _fmt_ns(stats["max"])))
    parts.append("</svg>")
    return "".join(parts)


def build_charts(results, parsed):
    """Build every chart the log's data supports.

    Returns an ordered dict: filename -> (title, svg string).
    A missing probe omits its chart; nothing is drawn from absent
    data. results: {(probe, metric): summary} from
    measure.summarize_all; parsed: ParsedLog with the raw samples.
    """
    charts = {}
    samples = parsed.samples
    msg = samples.get(("msg_roundtrip", "roundtrip_ns"))
    if msg:
        charts["msg_roundtrip.svg"] = (
            "Message-passing round-trip",
            svg_histogram(msg, results[("msg_roundtrip", "roundtrip_ns")],
                          "msg round-trip"))
    wake = samples.get(("wake_latency", "wake_ns"))
    if wake:
        charts["wake_latency.svg"] = (
            "Semaphore wake latency",
            svg_histogram(wake, results[("wake_latency", "wake_ns")],
                          "wake latency"))
    idle = samples.get(("jitter_load", "jitter_idle_ns"))
    load = samples.get(("jitter_load", "jitter_load_ns"))
    if idle and load:
        charts["jitter_idle_vs_load.svg"] = (
            "Periodic-thread jitter: idle vs under load",
            svg_jitter_pair(idle, results[("jitter_load",
                                           "jitter_idle_ns")],
                            load, results[("jitter_load",
                                          "jitter_load_ns")]))
    elif idle or load:
        key = ("jitter_load", "jitter_idle_ns") if idle else \
            ("jitter_load", "jitter_load_ns")
        which = idle if idle else load
        charts["jitter.svg"] = (
            "Periodic-thread jitter",
            svg_histogram(which, results[key],
                          "jitter \u2014 %s" % key[1]))
    none = samples.get(("prio_inversion", "inversion_wait_none_ns"))
    inherit = samples.get(("prio_inversion",
                           "inversion_wait_inherit_ns"))
    if none and inherit:
        charts["prio_inversion.svg"] = (
            "Priority inversion: NONE vs INHERIT",
            svg_prio_bars(none, results[("prio_inversion",
                                         "inversion_wait_none_ns")],
                          inherit, results[("prio_inversion",
                                            "inversion_wait_inherit_ns")]))
    return charts


def render_charts_page(charts, results, parsed=None, repeat=1):
    """Self-contained HTML page inlining every chart.

    No external resources, no scripts, no network fetch: the page
    opens from disk. Carries the same honesty note as report.txt and
    the calibration floor when the log has one.
    """
    lines = []
    lines.append("<!DOCTYPE html>")
    lines.append('<html lang="en"><head><meta charset="utf-8">')
    lines.append("<title>RT-Probe charts</title>")
    lines.append("<style>body{font-family:sans-serif;max-width:760px;"
                 "margin:2em auto;padding:0 1em;color:#222}"
                 "h1{font-size:1.4em}h2{font-size:1.15em;margin-top:2em}"
                 "figure{margin:1em 0}figcaption{font-size:.9em;color:#555}"
                 ".note{background:#f6f6f6;border-left:4px solid #c0392b;"
                 "padding:.6em .9em;font-size:.92em}</style>")
    lines.append("</head><body>")
    lines.append("<h1>RT-Probe charts</h1>")
    if repeat > 1:
        lines.append("<p>Repeatability: %d runs pooled.</p>" % repeat)
    overhead = results.get(("calibration", "timer_overhead_ns"))
    if overhead is not None:
        lines.append("<p>Measurement floor: timer overhead p50 %s "
                     "(N=%d); probe numbers are raw, NOT "
                     "overhead-subtracted.</p>"
                     % (_fmt_ns(overhead["p50"]), overhead["count"]))
    lines.append('<p class="note">All timings are indicative QEMU/TCG '
                 "measurements, not hardware-grade numbers. Absolute "
                 "values will differ from real hardware; the meaningful "
                 "signals are the relative comparisons (idle vs load, "
                 "INHERIT vs NONE). See DESIGN.md.</p>")
    if not charts:
        lines.append("<p>No charts: the log contained no samples for "
                     "any charted metric.</p>")
    for _filename, (title, svg) in charts.items():
        lines.append("<h2>%s</h2>" % _escape(title))
        lines.append("<figure>%s</figure>" % svg)
    lines.append("</body></html>")
    return "\n".join(lines) + "\n"


def write_charts(results, parsed, output_dir, repeat=1):
    """Write charts.html + charts/*.svg into output_dir.

    Returns (html_path, [svg paths]). Safe to call with partial or
    empty data: the page is still written, with whatever charts the
    log supports (possibly none).
    """
    charts_dir = os.path.join(output_dir, "charts")
    os.makedirs(charts_dir, exist_ok=True)
    charts = build_charts(results, parsed)
    svg_paths = []
    for filename, (_title, svg) in charts.items():
        path = os.path.join(charts_dir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        svg_paths.append(path)
    html_path = os.path.join(output_dir, "charts.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render_charts_page(charts, results, parsed,
                                    repeat=repeat))
    return html_path, svg_paths
