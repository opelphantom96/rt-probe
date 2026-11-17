"""Tests for rtprobe.qemu (argv construction + streaming run).

No real QEMU is launched: run_qemu is exercised with small Python
one-liners standing in for the QEMU process.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtprobe import config as config_mod
from rtprobe import qemu as qemu_mod


class TestBuildArgv(unittest.TestCase):
    def test_proven_boot_command(self):
        cfg = config_mod.Config(workdir="/tmp/img")
        argv = qemu_mod.build_qemu_argv(cfg, "/tmp/img")
        self.assertEqual(argv[0], "qemu-system-x86_64")
        # Kernel is loaded directly; the disk bootloader path is NOT used.
        self.assertIn("-kernel", argv)
        self.assertIn("/tmp/img/output/ifs.bin", argv)
        self.assertIn("-drive", argv)
        drive = argv[argv.index("-drive") + 1]
        self.assertIn("disk-qemu.vmdk", drive)
        self.assertIn("if=ide", drive)
        self.assertEqual(argv[argv.index("-smp") + 1], "2")
        self.assertEqual(argv[argv.index("--cpu") + 1], "max")
        self.assertEqual(argv[argv.index("-m") + 1], "1024")
        self.assertIn("-serial", argv)
        self.assertIn("mon:stdio", argv)
        self.assertIn("-nographic", argv)
        # No SeaBIOS disk boot: no -machine / -boot arguments.
        self.assertNotIn("-machine", argv)
        self.assertNotIn("-boot", argv)

    def test_image_paths(self):
        paths = qemu_mod.image_paths("/tmp/img")
        self.assertEqual(paths["ifs_bin"], "/tmp/img/output/ifs.bin")
        self.assertEqual(paths["disk_vmdk"],
                         "/tmp/img/output/disk-qemu.vmdk")


    def test_smp_one_in_argv(self):
        cfg = config_mod.Config(workdir="/tmp/img", qemu_smp=1)
        argv = qemu_mod.build_qemu_argv(cfg, "/tmp/img")
        self.assertEqual(argv[argv.index("-smp") + 1], "1")


class TestBuildImageEnv(unittest.TestCase):
    def test_probe_args_in_env(self):
        cfg = config_mod.Config(iterations=50, warmup=25, period_ms=5,
                                rounds=3, hold_ms=100)
        env = qemu_mod.build_image_env(cfg)
        self.assertEqual(env["RTPROBE_ARGS_MSG_ROUNDTRIP"], "50 25")
        self.assertEqual(env["RTPROBE_ARGS_WAKE_LATENCY"], "50 25")
        self.assertEqual(env["RTPROBE_ARGS_JITTER_LOAD"], "5 50 10 64")
        self.assertEqual(env["RTPROBE_ARGS_PRIO_INVERSION"], "3 100")
        self.assertIn("QNX_ROOT", env)

    def test_default_args_in_env(self):
        cfg = config_mod.Config()
        env = qemu_mod.build_image_env(cfg)
        self.assertEqual(env["RTPROBE_ARGS_MSG_ROUNDTRIP"], "200 100")
        self.assertEqual(env["RTPROBE_ARGS_PRIO_INVERSION"], "5 200")


class TestBootOk(unittest.TestCase):
    def test_detects_startup_complete(self):
        self.assertTrue(qemu_mod.boot_ok("foo\nStartup complete\nbar"))
        self.assertFalse(qemu_mod.boot_ok("foo\nbar"))

    def test_suite_done_counts_as_boot(self):
        # The suite ran, so boot completed — even without the literal
        # "Startup complete" string.
        self.assertTrue(qemu_mod.boot_ok("boot\nRT-PROBE SUITE DONE\n"))

    def test_starting_misc_counts_as_boot(self):
        # The mkqnximage qemu image never prints "Startup complete" to
        # serial; "Starting misc" is its post-startup marker.
        self.assertTrue(qemu_mod.boot_ok("---> Starting misc\n"))

    def test_empty_log_is_not_boot_ok(self):
        self.assertFalse(qemu_mod.boot_ok(""))


class TestRunQemu(unittest.TestCase):
    def _py(self, code):
        return [sys.executable, "-u", "-c", code]

    def test_marker_exits_early(self):
        code = ("import sys, time; print('boot'); "
                "print('RT-PROBE SUITE DONE'); sys.stdout.flush(); "
                "time.sleep(30)")
        start = time.monotonic()
        timed_out, output = qemu_mod.run_qemu(
            self._py(code), timeout_s=20,
            marker="RT-PROBE SUITE DONE")
        elapsed = time.monotonic() - start
        self.assertFalse(timed_out)
        self.assertIn("RT-PROBE SUITE DONE", output)
        self.assertLess(elapsed, 10)

    def test_timeout_kills_and_returns_partial(self):
        code = ("import sys, time; print('boot'); sys.stdout.flush(); "
                "time.sleep(30)")
        start = time.monotonic()
        timed_out, output = qemu_mod.run_qemu(
            self._py(code), timeout_s=2, marker="RT-PROBE SUITE DONE")
        elapsed = time.monotonic() - start
        self.assertTrue(timed_out)
        self.assertIn("boot", output)
        self.assertLess(elapsed, 10)

    def test_process_exit_ends_run(self):
        code = "print('quick exit')"
        timed_out, output = qemu_mod.run_qemu(
            self._py(code), timeout_s=10)
        self.assertFalse(timed_out)
        self.assertIn("quick exit", output)


if __name__ == "__main__":
    unittest.main()
