"""Configuration and defaults for rt-probe.

Everything is a plain value with an environment override where it makes
sense. No third-party dependencies; stdlib only.
"""

import os
from dataclasses import dataclass, field

DEFAULT_QNX_ROOT = os.path.expanduser("~/workspace/qnx")
DEFAULT_WORKDIR = os.path.expanduser("~/workspace/qnx/rt-probe-image")
DEFAULT_QEMU_MEM_MB = 1024
DEFAULT_QEMU_SMP = 2
DEFAULT_QEMU_TIMEOUT_S = 180
DEFAULT_ITERATIONS = 200
DEFAULT_WARMUP = 100
DEFAULT_PERIOD_MS = 10
DEFAULT_JITTER_SKIP = 10
DEFAULT_JITTER_MEM_MB = 64
DEFAULT_ROUNDS = 5
DEFAULT_HOLD_MS = 200

PROBE_NAMES = ("calibration", "msg_roundtrip", "wake_latency",
               "jitter_load", "prio_inversion")

# The suite is finished when the target-side runner prints this line.
SUITE_DONE_MARKER = "RT-PROBE SUITE DONE"


@dataclass
class Config:
    """Resolved runtime configuration for one rt-probe invocation."""

    qnx_root: str = field(
        default_factory=lambda: os.environ.get("QNX_ROOT",
                                               DEFAULT_QNX_ROOT))
    workdir: str = DEFAULT_WORKDIR
    qemu_mem_mb: int = DEFAULT_QEMU_MEM_MB
    qemu_smp: int = DEFAULT_QEMU_SMP
    qemu_timeout_s: int = DEFAULT_QEMU_TIMEOUT_S
    iterations: int = DEFAULT_ITERATIONS
    warmup: int = DEFAULT_WARMUP
    period_ms: int = DEFAULT_PERIOD_MS
    # Memory pressure in the jitter load phase (TODO #6): MiB per
    # streamer thread (two streamers, so 2 x this in the guest).
    # 0 = CPU spinners only, the pre-TODO-#6 behaviour.
    jitter_mem_mb: int = DEFAULT_JITTER_MEM_MB
    rounds: int = DEFAULT_ROUNDS
    hold_ms: int = DEFAULT_HOLD_MS
    output_dir: str = os.path.expanduser("~/workspace/qnx/rt-probe/out")
    dry_run: bool = False
    # Repeatability (TODO #4): run the whole suite this many times and
    # aggregate across runs. 1 = single run, the historical behaviour.
    repeat: int = 1

    @property
    def sdp_dir(self) -> str:
        return os.path.join(self.qnx_root, "qnx800")

    @property
    def env_script(self) -> str:
        return os.path.join(self.sdp_dir, "qnxsdp-env.sh")

    @property
    def project_dir(self) -> str:
        """Directory containing rt-probe (the repo root)."""
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @property
    def probes_dir(self) -> str:
        return os.path.join(self.project_dir, "probes")

    @property
    def build_image_script(self) -> str:
        return os.path.join(self.project_dir, "scripts", "build-image.sh")

    def probe_args(self) -> dict:
        """Per-probe argv lists, keyed by probe name.

        Each probe takes different positional arguments (see probes/*.c):
          calibration:    [] (compiled-in default 1000 iterations;
                          the floor does not need CLI arguments)
          msg_roundtrip:  [iterations] [warmup]
          wake_latency:   [iterations] [warmup]
          jitter_load:    [period_ms] [iterations] [skip] [mem_mb]
                          (skip and mem_mb come from the compiled-in
                          defaults below; see jitter_mem_mb)
          prio_inversion: [rounds] [hold_ms]
        Values always come from this Config, so a run is explicit about
        what the probes received; the probes still default sensibly when
        invoked without arguments (e.g. by hand on the target).
        """
        return {
            "calibration": [],
            "msg_roundtrip": [str(self.iterations), str(self.warmup)],
            "wake_latency": [str(self.iterations), str(self.warmup)],
            "jitter_load": [str(self.period_ms), str(self.iterations),
                           str(DEFAULT_JITTER_SKIP),
                           str(self.jitter_mem_mb)],
            "prio_inversion": [str(self.rounds), str(self.hold_ms)],
        }
