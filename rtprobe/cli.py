#!/usr/bin/env python3
"""rt-probe host CLI (stdlib only).

Subcommands:
  run          build the image, boot it in QEMU, measure, report.
  build-image  cross-compile the probes and build the QEMU image only.
  measure      parse an existing serial log and write the report.

`run --dry-run` prints the plan (probes, image dir, exact QEMU argv)
and exits without side effects.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtprobe import __version__
from rtprobe import config as config_mod
from rtprobe import measure as measure_mod
from rtprobe import qemu as qemu_mod
from rtprobe import report as report_mod


def _config_from_args(args):
    cfg = config_mod.Config()
    if getattr(args, "workdir", None):
        cfg.workdir = args.workdir
    if getattr(args, "output_dir", None):
        cfg.output_dir = args.output_dir
    if getattr(args, "timeout", None):
        cfg.qemu_timeout_s = args.timeout
    if getattr(args, "smp", None) is not None:
        cfg.qemu_smp = args.smp
    if getattr(args, "iterations", None):
        cfg.iterations = args.iterations
    if getattr(args, "warmup", None):
        cfg.warmup = args.warmup
    if getattr(args, "period_ms", None):
        cfg.period_ms = args.period_ms
    if getattr(args, "jitter_mem_mb", None) is not None:
        cfg.jitter_mem_mb = args.jitter_mem_mb
    if getattr(args, "rounds", None):
        cfg.rounds = args.rounds
    if getattr(args, "hold_ms", None):
        cfg.hold_ms = args.hold_ms
    if getattr(args, "repeat", None) is not None:
        cfg.repeat = args.repeat
    return cfg


def _report_and_finish(cfg, output_text):
    """Parse serial output, render + write the report, return exit code."""
    parsed = measure_mod.parse_lines(output_text)
    results = measure_mod.summarize_all(parsed)
    report_path, hist_path, charts_path = report_mod.write_report(
        results, parsed, cfg.output_dir)
    sys.stdout.write(report_mod.render_report(results, parsed))
    sys.stdout.write("Report: %s\nHistograms: %s\nCharts: %s\n"
                     % (report_path, hist_path, charts_path))
    log_path = os.path.join(cfg.output_dir, "serial.log")
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(output_text)
    sys.stdout.write("Serial log: %s\n" % log_path)
    complete = parsed.suite_done and not parsed.incomplete \
        and not parsed.missing
    return 0 if complete else 1


def _report_repeat_and_finish(cfg, run_outputs):
    """Aggregate N runs into one pooled report. Returns exit code.

    run_outputs: list of (timed_out, output_text), one per run.
    The image is built once by the caller; each output is one QEMU
    boot of the same image. Writes report.txt + histograms.txt +
    charts.html from the pooled samples, serial.log (all runs
    concatenated) plus one serial-run<i>.log per run. Exit 0 only
    when every run completed.
    """
    parsed_list = [measure_mod.parse_lines(text)
                   for _timed_out, text in run_outputs]
    pooled = measure_mod.merge_parsed(parsed_list)
    pooled_results = measure_mod.summarize_all(pooled)
    per_run_results = [measure_mod.summarize_all(p)
                       for p in parsed_list]
    aggregate = measure_mod.aggregate_runs(per_run_results)
    runs_complete = sum(1 for p in parsed_list
                        if p.suite_done and not p.incomplete
                        and not p.missing)
    report_path, hist_path, charts_path = report_mod.write_report(
        pooled_results, pooled, cfg.output_dir,
        aggregate=aggregate, per_run=per_run_results,
        repeat=cfg.repeat, runs_complete=runs_complete)
    sys.stdout.write(report_mod.render_report(
        pooled_results, pooled, aggregate=aggregate,
        per_run=per_run_results, repeat=cfg.repeat,
        runs_complete=runs_complete))
    sys.stdout.write("Report: %s\nHistograms: %s\nCharts: %s\n"
                     % (report_path, hist_path, charts_path))
    combined = "".join(
        "=== RT-PROBE RUN %d/%d ===\n%s"
        % (i + 1, cfg.repeat, text)
        for i, (_timed_out, text) in enumerate(run_outputs))
    log_path = os.path.join(cfg.output_dir, "serial.log")
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(combined)
    sys.stdout.write("Serial log: %s\n" % log_path)
    for i, (_timed_out, text) in enumerate(run_outputs):
        run_log = os.path.join(cfg.output_dir,
                               "serial-run%d.log" % (i + 1))
        with open(run_log, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if runs_complete == cfg.repeat else 1


def cmd_run(args):
    cfg = _config_from_args(args)
    if cfg.qemu_smp < 1:
        sys.stderr.write("--smp must be >= 1 (got %d)\n" % cfg.qemu_smp)
        return 2
    if cfg.jitter_mem_mb < 0:
        sys.stderr.write("--jitter-mem-mb must be >= 0 (got %d)\n"
                         % cfg.jitter_mem_mb)
        return 2
    if cfg.repeat < 1:
        sys.stderr.write("--repeat must be >= 1 (got %d)\n" % cfg.repeat)
        return 2
    cfg.dry_run = bool(getattr(args, "dry_run", False))
    argv = qemu_mod.build_qemu_argv(cfg, cfg.workdir)

    if cfg.dry_run:
        sys.stdout.write("RT-PROBE DRY RUN\n")
        sys.stdout.write("Probes: %s\n"
                         % ", ".join(config_mod.PROBE_NAMES))
        sys.stdout.write("Probe args: %s\n" % "; ".join(
            "%s %s" % (name, " ".join(argv))
            for name, argv in cfg.probe_args().items()))
        sys.stdout.write("Guest CPUs: %d\n" % cfg.qemu_smp)
        sys.stdout.write("Repeat: %d\n" % cfg.repeat)
        sys.stdout.write("SDP: %s\n" % cfg.sdp_dir)
        sys.stdout.write("Image dir: %s\n" % cfg.workdir)
        sys.stdout.write("QEMU timeout: %ds\n" % cfg.qemu_timeout_s)
        sys.stdout.write("QEMU argv:\n  %s\n" % " ".join(argv))
        sys.stdout.write("Output dir: %s\n" % cfg.output_dir)
        return 0

    sys.stdout.write("Building image in %s ...\n" % cfg.workdir)
    rc, out = qemu_mod.build_image(cfg)
    if rc != 0:
        sys.stdout.write(out)
        sys.stderr.write("build-image failed (exit %d)\n" % rc)
        return rc

    run_outputs = []
    for run_no in range(1, cfg.repeat + 1):
        if cfg.repeat > 1:
            sys.stdout.write("Booting QEMU, run %d/%d (timeout %ds) ...\n"
                             % (run_no, cfg.repeat, cfg.qemu_timeout_s))
        else:
            sys.stdout.write("Booting QEMU (timeout %ds) ...\n"
                             % cfg.qemu_timeout_s)
        try:
            timed_out, output = qemu_mod.run_qemu(
                argv, cfg.qemu_timeout_s,
                marker=config_mod.SUITE_DONE_MARKER)
        except OSError as exc:
            sys.stderr.write("failed to start QEMU: %s\n" % exc)
            return 1
        if timed_out:
            sys.stdout.write("QEMU timed out; using partial output.\n")
        if not qemu_mod.boot_ok(output):
            sys.stdout.write("WARNING: QNX did not reach "
                             "'Startup complete' in the captured log.\n")
        run_outputs.append((timed_out, output))

    if cfg.repeat > 1:
        return _report_repeat_and_finish(cfg, run_outputs)
    return _report_and_finish(cfg, run_outputs[0][1])


def cmd_build_image(args):
    cfg = _config_from_args(args)
    rc, out = qemu_mod.build_image(cfg)
    sys.stdout.write(out)
    if rc != 0:
        sys.stderr.write("build-image failed (exit %d)\n" % rc)
    else:
        paths = qemu_mod.image_paths(cfg.workdir)
        sys.stdout.write("Image: %s\n" % paths["disk_vmdk"])
        sys.stdout.write("Kernel: %s\n" % paths["ifs_bin"])
    return rc


def cmd_measure(args):
    cfg = _config_from_args(args)
    with open(args.log, "r", encoding="utf-8", errors="replace") as fh:
        output_text = fh.read()
    return _report_and_finish(cfg, output_text)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="rt-probe",
        description="QNX real-time latency workbench (host tool).")
    parser.add_argument("--version", action="version",
                        version="rt-probe %s" % __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="build, boot, measure, report.")
    run_p.add_argument("--workdir", default=None)
    run_p.add_argument("--output-dir", default=None)
    run_p.add_argument("--timeout", type=int, default=None,
                       help="QEMU timeout in seconds (default 180)")
    run_p.add_argument("--smp", type=int, default=None,
                       help="guest CPUs (default 2; use 1 to force a "
                            "single-CPU guest, e.g. for the "
                            "priority-inversion demo)")
    run_p.add_argument("--iterations", type=int, default=None)
    run_p.add_argument("--warmup", type=int, default=None)
    run_p.add_argument("--period-ms", type=int, default=None)
    run_p.add_argument("--jitter-mem-mb", type=int, default=None,
                       help="MiB per memory-streamer thread in the "
                            "jitter load phase (default 64; 0 = CPU "
                            "spinners only)")
    run_p.add_argument("--rounds", type=int, default=None)
    run_p.add_argument("--hold-ms", type=int, default=None)
    run_p.add_argument("--repeat", type=int, default=None,
                       help="run the suite N times and aggregate "
                            "across runs (default 1)")
    run_p.add_argument("--dry-run", action="store_true",
                       help="print the plan and exit.")
    run_p.set_defaults(func=cmd_run)

    bi_p = sub.add_parser("build-image",
                          help="build the QEMU image only.")
    bi_p.add_argument("--workdir", default=None)
    bi_p.set_defaults(func=cmd_build_image)

    m_p = sub.add_parser("measure",
                         help="parse a serial log and write a report.")
    m_p.add_argument("--log", required=True, help="serial log file")
    m_p.add_argument("--output-dir", default=None)
    m_p.set_defaults(func=cmd_measure)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
