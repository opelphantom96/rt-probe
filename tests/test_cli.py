"""Tests for rtprobe.cli (arg parsing + dry-run + measure).

No QEMU is launched and no image is built: `run` is exercised only via
--dry-run, and `measure` via fixture logs.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtprobe import cli as cli_mod

LOG_COMPLETE = """Startup complete
RT-PROBE BEGIN msg_roundtrip
RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 1000 0
RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 2000 1
RT-PROBE END msg_roundtrip 2 ok
RT-PROBE SUITE DONE
"""

LOG_INCOMPLETE = """Startup complete
RT-PROBE BEGIN msg_roundtrip
RT-PROBE SAMPLE msg_roundtrip roundtrip_ns 1000 0
"""


class TestCli(unittest.TestCase):
    def test_help_exits_zero(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(io.StringIO()):
                cli_mod.main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_version_exits_zero(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(io.StringIO()):
                cli_mod.main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_bad_subcommand_exits_two(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(io.StringIO()), \
                 redirect_stderr(io.StringIO()):
                cli_mod.main(["nonsense"])
        self.assertEqual(cm.exception.code, 2)

    def test_run_dry_run_no_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = os.path.join(tmp, "img")
            outdir = os.path.join(tmp, "out")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_mod.main(["run", "--dry-run",
                                   "--workdir", workdir,
                                   "--output-dir", outdir])
            self.assertEqual(rc, 0)
            text = buf.getvalue()
            self.assertIn("DRY RUN", text)
            self.assertIn("QEMU argv", text)
            self.assertIn("-kernel", text)
            self.assertIn("ifs.bin", text)
            self.assertFalse(os.path.exists(workdir))
            self.assertFalse(os.path.exists(outdir))

    def test_run_dry_run_shows_smp_and_probe_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = os.path.join(tmp, "img")
            outdir = os.path.join(tmp, "out")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_mod.main(["run", "--dry-run",
                                   "--workdir", workdir,
                                   "--output-dir", outdir,
                                   "--smp", "1",
                                   "--iterations", "50",
                                   "--warmup", "25",
                                   "--period-ms", "5",
                                   "--rounds", "3",
                                   "--hold-ms", "100"])
            self.assertEqual(rc, 0)
            text = buf.getvalue()
            self.assertIn("Guest CPUs: 1", text)
            self.assertIn("-smp 1", text)
            self.assertIn("msg_roundtrip 50 25", text)
            self.assertIn("wake_latency 50 25", text)
            self.assertIn("jitter_load 5 50 10 64", text)
            self.assertIn("prio_inversion 3 100", text)
            self.assertFalse(os.path.exists(workdir))
            self.assertFalse(os.path.exists(outdir))

    def test_run_jitter_mem_mb_negative_returns_two(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_mod.main(["run", "--jitter-mem-mb", "-1"])
        self.assertEqual(rc, 2)

    def test_run_dry_run_shows_jitter_mem_mb_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = os.path.join(tmp, "img")
            outdir = os.path.join(tmp, "out")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_mod.main(["run", "--dry-run",
                                   "--workdir", workdir,
                                   "--output-dir", outdir,
                                   "--jitter-mem-mb", "0"])
            self.assertEqual(rc, 0)
            self.assertIn("jitter_load 10 200 10 0", buf.getvalue())
            self.assertFalse(os.path.exists(workdir))

    def test_run_smp_zero_returns_two(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_mod.main(["run", "--smp", "0"])
        self.assertEqual(rc, 2)

    def test_run_repeat_zero_returns_two(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_mod.main(["run", "--repeat", "0"])
        self.assertEqual(rc, 2)

    def test_run_dry_run_shows_repeat_and_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = os.path.join(tmp, "img")
            outdir = os.path.join(tmp, "out")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_mod.main(["run", "--dry-run",
                                   "--workdir", workdir,
                                   "--output-dir", outdir,
                                   "--repeat", "3"])
            self.assertEqual(rc, 0)
            text = buf.getvalue()
            self.assertIn("Repeat: 3", text)
            self.assertIn("calibration", text)
            self.assertFalse(os.path.exists(workdir))

    def test_measure_log_with_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "serial.log")
            outdir = os.path.join(tmp, "out")
            with open(log, "w", encoding="utf-8") as fh:
                fh.write("RT-PROBE DIAG calibration cycles_per_sec 100\n"
                         "RT-PROBE BEGIN calibration\n"
                         "RT-PROBE SAMPLE calibration timer_overhead_ns 5 0\n"
                         "RT-PROBE SAMPLE calibration timer_resolution_ns 5 0\n"
                         "RT-PROBE END calibration 2 ok\n"
                         "RT-PROBE SUITE DONE\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_mod.main(["measure", "--log", log,
                                   "--output-dir", outdir])
            self.assertEqual(rc, 0)
            self.assertIn("Calibration (measurement floor)", buf.getvalue())
            self.assertIn("timer resolution", buf.getvalue())

    def test_measure_complete_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "serial.log")
            outdir = os.path.join(tmp, "out")
            with open(log, "w", encoding="utf-8") as fh:
                fh.write(LOG_COMPLETE)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_mod.main(["measure", "--log", log,
                                   "--output-dir", outdir])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(
                os.path.join(outdir, "report.txt")))
            self.assertTrue(os.path.isfile(
                os.path.join(outdir, "serial.log")))
            self.assertIn("msg_roundtrip", buf.getvalue())

    def test_measure_incomplete_log_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "serial.log")
            outdir = os.path.join(tmp, "out")
            with open(log, "w", encoding="utf-8") as fh:
                fh.write(LOG_INCOMPLETE)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_mod.main(["measure", "--log", log,
                                   "--output-dir", outdir])
            self.assertEqual(rc, 1)
            self.assertIn("INCOMPLETE", buf.getvalue())

    def test_measure_missing_log_raises(self):
        with self.assertRaises(FileNotFoundError):
            with redirect_stdout(io.StringIO()):
                cli_mod.main(["measure", "--log", "/nonexistent/x.log"])


if __name__ == "__main__":
    unittest.main()
