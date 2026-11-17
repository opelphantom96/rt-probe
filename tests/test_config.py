"""Tests for rtprobe.config (no QEMU, no filesystem side effects)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtprobe import config as config_mod


class TestDefaults(unittest.TestCase):
    def test_defaults(self):
        cfg = config_mod.Config()
        self.assertEqual(cfg.qemu_mem_mb, 1024)
        self.assertEqual(cfg.qemu_smp, 2)
        self.assertEqual(cfg.qemu_timeout_s, 180)
        self.assertEqual(cfg.iterations, 200)
        self.assertEqual(cfg.warmup, 100)
        self.assertEqual(cfg.period_ms, 10)
        self.assertEqual(cfg.jitter_mem_mb, 64)
        self.assertEqual(cfg.rounds, 5)
        self.assertEqual(cfg.hold_ms, 200)
        self.assertEqual(cfg.repeat, 1)
        self.assertFalse(cfg.dry_run)

    def test_probe_names(self):
        self.assertEqual(config_mod.PROBE_NAMES,
                         ("calibration", "msg_roundtrip", "wake_latency",
                          "jitter_load", "prio_inversion"))

    def test_suite_done_marker(self):
        self.assertEqual(config_mod.SUITE_DONE_MARKER,
                         "RT-PROBE SUITE DONE")


class TestPaths(unittest.TestCase):
    def test_paths_join_qnx_root(self):
        cfg = config_mod.Config(qnx_root="/x/qnx")
        self.assertEqual(cfg.sdp_dir, "/x/qnx/qnx800")
        self.assertEqual(cfg.env_script, "/x/qnx/qnx800/qnxsdp-env.sh")
        self.assertTrue(cfg.build_image_script.endswith(
            "scripts/build-image.sh"))

    def test_qnx_root_env_override(self):
        old = os.environ.get("QNX_ROOT")
        try:
            os.environ["QNX_ROOT"] = "/env/qnx"
            cfg = config_mod.Config()
            self.assertEqual(cfg.qnx_root, "/env/qnx")
        finally:
            if old is None:
                os.environ.pop("QNX_ROOT", None)
            else:
                os.environ["QNX_ROOT"] = old

    def test_probe_args_defaults(self):
        cfg = config_mod.Config()
        self.assertEqual(cfg.probe_args(), {
            "calibration": [],
            "msg_roundtrip": ["200", "100"],
            "wake_latency": ["200", "100"],
            "jitter_load": ["10", "200", "10", "64"],
            "prio_inversion": ["5", "200"],
        })

    def test_probe_args_custom_values(self):
        cfg = config_mod.Config(iterations=50, warmup=25, period_ms=5,
                                rounds=3, hold_ms=100, jitter_mem_mb=32)
        args = cfg.probe_args()
        self.assertEqual(args["msg_roundtrip"], ["50", "25"])
        self.assertEqual(args["wake_latency"], ["50", "25"])
        self.assertEqual(args["jitter_load"], ["5", "50", "10", "32"])
        self.assertEqual(args["prio_inversion"], ["3", "100"])


if __name__ == "__main__":
    unittest.main()
