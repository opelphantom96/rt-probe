"""Tests for probes/run-probes.sh (per-probe argument dispatch).

Runs the real shell script against stub probe binaries in a temp dir
(via the RTPROBE_DIR override); no QNX, no QEMU needed. The host
/bin/sh here is dash; the QNX target sh is ksh-based — both are POSIX
sh, and the runner only uses POSIX constructs.
"""

import os
import stat
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "probes", "run-probes.sh")

PROBES = ("calibration", "msg_roundtrip", "wake_latency", "jitter_load",
          "prio_inversion")

STUB = """#!/bin/sh
echo "$0 $@" >> "$LOG"
"""


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.log = os.path.join(self.dir, "calls.log")
        for name in PROBES:
            path = os.path.join(self.dir, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(STUB)
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args_text=None):
        if args_text is not None:
            with open(os.path.join(self.dir, "args"), "w",
                      encoding="utf-8") as fh:
                fh.write(args_text)
        env = dict(os.environ)
        env["RTPROBE_DIR"] = self.dir
        env["LOG"] = self.log
        return subprocess.run(["sh", RUNNER], env=env,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)

    def _calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return [line.strip() for line in fh]

    def _calls_by_probe(self):
        by_name = {}
        for call in self._calls():
            parts = call.split()
            by_name[os.path.basename(parts[0])] = parts[1:]
        return by_name

    def test_per_probe_args_from_file(self):
        proc = self._run("msg_roundtrip 50 25\n"
                         "wake_latency 50 25\n"
                         "jitter_load 5 50\n"
                         "prio_inversion 3 100\n")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("RT-PROBE SUITE DONE", proc.stdout)
        by_name = self._calls_by_probe()
        self.assertEqual(len(by_name), 5)
        self.assertEqual(by_name["calibration"], [])
        self.assertEqual(by_name["msg_roundtrip"], ["50", "25"])
        self.assertEqual(by_name["wake_latency"], ["50", "25"])
        self.assertEqual(by_name["jitter_load"], ["5", "50"])
        self.assertEqual(by_name["prio_inversion"], ["3", "100"])

    def test_calibration_runs_first(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0)
        calls = self._calls()
        self.assertEqual(len(calls), 5)
        self.assertTrue(calls[0].endswith("/calibration"))

    def test_no_args_file_runs_defaults(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0)
        self.assertIn("RT-PROBE SUITE DONE", proc.stdout)
        by_name = self._calls_by_probe()
        self.assertEqual(len(by_name), 5)
        for args in by_name.values():
            self.assertEqual(args, [])

    def test_partial_args_file(self):
        # Only prio_inversion has an entry; the rest run with defaults.
        proc = self._run("prio_inversion 3 100\n")
        self.assertEqual(proc.returncode, 0)
        by_name = self._calls_by_probe()
        self.assertEqual(by_name["prio_inversion"], ["3", "100"])
        self.assertEqual(by_name["msg_roundtrip"], [])
        self.assertEqual(by_name["jitter_load"], [])

    def test_missing_probe_reported(self):
        os.remove(os.path.join(self.dir, "wake_latency"))
        proc = self._run("wake_latency 50 25\n")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("RT-PROBE MISSING wake_latency", proc.stdout)
        self.assertIn("RT-PROBE SUITE DONE", proc.stdout)
        self.assertEqual(len(self._calls()), 4)


if __name__ == "__main__":
    unittest.main()
