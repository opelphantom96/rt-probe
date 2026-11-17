# RT-Probe — design notes

## Goal

One command (`./rt-probe run`) produces a complete, honest report of
QNX real-time behaviour on a headless QEMU target: message-passing
round-trip, semaphore wake latency, periodic-thread jitter under load,
and a priority-inversion demo with and without priority inheritance.
The report must be reproducible from a single host command and must
never overclaim what QEMU numbers mean.

## Pipeline

```
host CLI (rtprobe/cli.py, stdlib only)
  -> make probes/            qcc -V gcc_ntox86_64, -O2
  -> scripts/build-image.sh  stage binaries + snippets, mkqnximage
  -> QEMU -kernel ifs.bin    headless, TCG, -smp 2 --cpu max -m 1024
  -> post_start.custom       /data/rt-probe/run-probes.sh
  -> serial log              RT-PROBE lines parsed by rtprobe.measure
  -> out/report.txt + out/histograms.txt + out/charts.html
     (+ out/charts/*.svg) + out/serial.log
```

## Image integration (verified 17 Nov 2026)

`mkqnximage` searches the image dir's `local/` tree for snippet files
(`--extra-dirs` help: "only the standard mkqnximage directory and
local are used" by default):

- `local/snippets/data_files.custom` is included verbatim into
  `data.build`. Entries use mkfs build syntax:
  `[uid=0 gid=0 perms=755] <dest>=<source>`, source relative to the
  image dir. The data partition is mounted at `/data`
  (`mount -t qnx6 /dev/hd0t179 /data`), so `rt-probe/<bin>` lands at
  `/data/rt-probe/<bin>`. Verified: the generated `data.build`
  contains all five rt-probe entries.
- `local/snippets/post_start.custom` is included into
  `post_startup.sh` and runs at the END of system startup, with
  filesystems mounted and the serial console live. Verified: the
  generated `post_startup.sh` contains the runner invocation.
- `ifs_start.custom` runs BEFORE `/proc/boot/startup.sh`, i.e. before
  `/data` is mounted — it must NOT be used for the probes.
- `mkqnximage` refuses a non-empty directory without `--force`;
  `build-image.sh` always starts from a fresh directory.

## Probes

All probes print the same machine-parseable format (see
`probes/probes.h`) and flush every sample, so a killed QEMU session
still leaves partial results. Timing uses `ClockCycles()` converted
with `SYSPAGE_ENTRY(qtime)->cycles_per_sec`.

### msg_roundtrip (default 200 iters, 100 warmup)

Server thread owns a channel (`ChannelCreate`) and replies
immediately. Client measures `MsgSend` round-trip. Warmup iterations
are discarded. This is the purest QNX primitive in the suite and the
direct evidence for the "Best Use of QNX-specific Technologies"
bonus.

### wake_latency (default 200 iters, 100 warmup)

Waiter thread at SCHED_FIFO priority 100 blocks on `sem_wait()`.
Main records t0, posts, waiter records t1 on wake and hands it back
through a second semaphore. Sample = t1 - t0. The handshake happens
after t1 is recorded, so it does not contaminate the sample.

### jitter_load (default period 10 ms, 100 iters/phase, skip 10, mem 64 MiB)

Periodic thread (SCHED_FIFO 80) sleeps with `clock_nanosleep`
(`TIMER_ABSTIME`, `CLOCK_MONOTONIC`) and reports
`|actual - expected|` per period. Two phases: `jitter_idle_ns`, then
`jitter_load_ns` with two SCHED_FIFO-70 busy spinners saturating the
CPUs PLUS two SCHED_FIFO-70 memory streamers, each sweeping its own
`mem_mb` MiB buffer at a 64-byte stride (one cache line per access).
Spinners alone only contend for CPU time — a higher-priority periodic
thread preempts them and keeps its cache lines resident. The streamers
are what make the load realistic: they evict the periodic thread's
working set between periods and contend for memory bandwidth, so each
wake pays cache-refill costs the way it would on a loaded system.
Buffers are allocated once before the idle phase and fully written
(memset), so no page fault lands inside a measured phase; the size and
pattern are fixed and deterministic, and the total (2 x mem_mb MiB,
default 128 MiB in a 1 GiB guest) is bounded. `mem_mb=0` disables the
streamers (spinners only, the pre-TODO-#6 behaviour, for A/B
comparison); on allocation failure the probe degrades to spinners
only instead of failing. The probe prints one
`RT-PROBE DIAG jitter_load mem_mb=.. stride=64B streamers=.. spinners=2`
line, and the report states the load configuration alongside the
numbers. CLI: `--jitter-mem-mb N`. The first `skip` periods of each
phase are discarded.

### prio_inversion (default 5 rounds, hold 200 ms)

Low (prio 10) holds a mutex, med (prio 50) hogs the CPU, high
(prio 100) measures its wait for the mutex. Protocol A
(`PTHREAD_PRIO_NONE`) shows the inversion; protocol B
(`PTHREAD_PRIO_INHERIT`) shows the fix. Note the QNX values are
`PRIO_INHERIT=0`, `PRIO_NONE=1` — always use the symbolic names.
All three threads are pinned to CPU 0 with
`ThreadCtl(_NTO_TCTL_RUNMASK_GET_AND_SET)` and the pin is VERIFIED:
each thread prints `RT-PROBE DIAG pin <who> rc=a/b prev=0x.. cur=0x..
ok|FAIL` (see probes.h `rp_pin_cpu0_diag()`); a run with any FAIL
means the numbers are not a clean single-CPU comparison.

Two design points that the demo depends on (both found empirically):
- The hold is CPU-bound busy work, not a sleep. A sleep-based hold
  let low release on a timer expiry even while preempted and hid the
  inversion entirely (first live run: NONE 199.4 ms vs INHERIT 200.2 ms).
- The coordinator (main) runs at SCHED_FIFO 60 while posting the go
  signals. At default prio 10 it starves behind the spinning low
  thread on a single-CPU guest and posts after low already released,
  so high never blocks (~3 µs in both protocols).
Verified contrasts: smp 2 — NONE 301.3 ms vs INHERIT 199.2 ms;
smp 1 — NONE 502.7 ms vs INHERIT 200.3 ms (hold 200 ms); non-default
args (rounds 3, hold 100 ms) — NONE 302.3 ms vs INHERIT 95.6 ms.
INHERIT is consistently ≈ hold. NONE is hog-gated and varies
(300–500 ms) with host scheduling under TCG; do not overclaim the
exact NONE decomposition — the robust claim is NONE ≫ INHERIT.

## Methodology

- **Calibration.** Every run starts with the `calibration` probe:
  1000 empty `ClockCycles()` pairs. Its p50 is the practical floor
  of the measurement (live: 20 ns, resolution 10 ns); samples near or
  below it are not resolvable. The report states the floor and never
  subtracts it from the probe numbers.
- **Repeatability.** `--repeat N` boots the suite N times and reports
  pooled statistics plus the cross-run spread of the per-run means
  (live: INHERIT spread 231 µs over 3 runs; idle-jitter mean spread
  304 µs). One run is not a statistic; A/B deltas are the robust
  signal, not absolute means.
- **Warmup.** Every probe discards warmup iterations (msg/wake) or
  warmup periods (jitter) before sampling: cold caches, lazy page
  faults, and first-run thread creation must not pollute the numbers.
- **Percentiles, not just means.** The report shows count/min/p50/
  p90/p99/max/mean per metric. Real-time behaviour lives in the tail;
  a mean alone would hide it.
- **Load injection.** `jitter_load` measures the same periodic thread
  twice — idle, then with the CPUs saturated by lower-priority
  spinners AND the caches/memory bandwidth pressured by two streamer
  threads sweeping 2 x 64 MiB at a cache-line stride — so the reader
  sees the delta, not a single number. The load configuration is
  stated in the report (mem_mb, stride, streamer/spinner counts).
- **A/B protocol.** `prio_inversion` runs the same scenario twice
  with only the mutex protocol changed, so the comparison is the
  result, not a narrative.
- **Parsing discipline.** The CLI parses only `RT-PROBE` lines,
  counts (but does not keep) all other serial output, and flags
  probes that printed `BEGIN` without `END`, probes the runner
  reported `MISSING`, and a missing `SUITE DONE`. A run that ends
  early still writes its partial report and exits non-zero.

## Honest limitations (do not soften these in the submission)

1. **QEMU/TCG timings are indicative, not hardware-grade.** TCG
   translates guest code in software on a shared 1.5-vCPU host with
   no KVM, no PCID, and no ACPI. Absolute numbers will differ from
   real hardware, probably by a large factor; relative comparisons
   (idle vs load, inherit vs none) are the meaningful signal. The
   report says so on every run.
2. **SMP caveat for prio_inversion.** The guest has 2 CPUs by default
   (`--smp` sets the count; `--smp 1` boots a single-CPU guest).
   Pinning is now VERIFIED, not assumed: every thread prints an
   `RT-PROBE DIAG pin` line and 30/30 were `ok` on the smp-2 runs.
   The jitter load contrast also needs 2 CPUs — under `--smp 1` the
   load phase shows no degradation (spinners cannot starve the
   higher-priority periodic thread on one CPU), so jitter numbers from
   smp-1 runs are not comparable to smp-2 runs. Verified 18 Nov 2026:
   smp-1 with the memory load gives load p50 1.01 ms / p90 1.05 ms
   vs idle p50 1.09 ms / p90 1.46 ms — no degradation, slightly
   tighter than idle. The streamers do not change this: TCG models
   no guest caches, so there is no guest cache for them to evict;
   their only lever under TCG is host-side memory bandwidth, which
   is below the noise floor here.
3. **No guest networking.** The QEMU command attaches no network
   device, so `dhcpcd` fails and `sshd` faults at boot (a core dump
   in the serial log). Both are boot noise, not probe failures — the
   probes need no network.
4. **Per-probe arguments are plumbed (done 18 Nov 2026).** The host CLI
   writes one `args` file per build (`RTPROBE_ARGS_*` env →
   `local/rt-probe/args` in the image); `run-probes.sh` passes each
   line to its probe. CLI `--iterations` is suite-wide: msg/wake
   sample counts AND jitter samples per phase (default 200 → 190
   samples after the 10-period skip). The probes' own defaults
   (jitter 100/phase) apply only when a probe is run by hand.
5. **One run is not a statistic — use `--repeat N`.** The foundation
   reported one run; `--repeat N` (done 18 Nov 2026) boots the suite
   N times and aggregates pooled statistics plus cross-run spread.
   Under TCG, run-to-run means of the µs-scale metrics vary by tens
   of percent, so quote the A/B deltas, not single-run means.

## Full-build TODOs (in order)

1. **First live end-to-end run.** `./rt-probe run` on this VM and
   confirm the probes execute at boot and the report is complete.
   Fix whatever the autorun path gets wrong (first suspect: the
   `post_start.custom` hook or probe paths).
   ✅ DONE 18 Nov 2026 ~04:51 WIB (first live run, ~37 s wall, exit 0):
   all 4 probes ok, SUITE DONE, report in `out/report.txt`.
   Findings: (a) `boot_ok()` warns on every run — "Startup complete"
   never appears on the serial console of the mkqnximage qemu image
   (boot genuinely completes; post_start runs); fix `boot_ok()` in the
   full build to accept SUITE DONE / "Starting misc". (b)
   prio_inversion A/B contrast did NOT reproduce (NONE mean 199.4 ms
   vs INHERIT 200.2 ms) — SMP caveat confirmed: the med hog evidently
   ran on the second CPU (pinning is best-effort, no diagnostic);
   diagnose the ThreadCtl return or use `-smp 1` for this probe in
   the full build.
   ✅ RESOLVED 18 Nov 2026 ~05:00 WIB (this chunk): root cause was the
   sleep-based hold, not pinning — a nanosleep lets low release on a
   timer expiry even while preempted. Fix: CPU-bound busy hold while
   holding the mutex + `rp_pin_cpu0_diag()` (GET_AND_SET, prints
   rc + effective runmask per thread; 30/30 `ok`, prev=0x3 cur=0x1)
   + coordinator main at SCHED_FIFO 60 (without it, main starves
   behind the spinning low thread on a 1-CPU guest and the demo
   measures ~3 µs in both protocols). Verified: smp 2 NONE 301.3 ms
   vs INHERIT 199.2 ms; smp 1 NONE 502.7 ms vs INHERIT 200.3 ms.
   `boot_ok()` now also accepts SUITE DONE / "Starting misc" — no
   more warning on successful runs (verified in runs B/B2/C).
2. **Per-probe argument plumbing.** Give `run-probes.sh` a per-probe
   argument scheme (e.g. env vars or a small args file) and wire the
   CLI `--iterations/--warmup/--period-ms/--rounds/--hold-ms` flags
   through to the right probes.
   ✅ DONE 18 Nov 2026 ~05:05 WIB (this chunk): `Config.probe_args()`
   → `RTPROBE_ARGS_*` env → `local/rt-probe/args` staged into the
   image → `run-probes.sh` dispatches per probe (args file absent =
   probe defaults). New CLI flag `--smp N` (default 2; `--smp 1` is
   the single-CPU mode). Verified live with non-default args
   (`--iterations 50 --warmup 25 --period-ms 5 --rounds 3
   --hold-ms 100`): msg/wake count 50, jitter 40/phase, prio 3/round,
   contrast intact (NONE 302.3 ms vs INHERIT 95.6 ms). Tests 39 → 52,
   all passing (new: probe_args, build_image_env, boot_ok markers,
   smp argv, CLI dry-run args, run-probes.sh dispatch with stubs).
3. **Calibration.** Measure the timer overhead (empty
   `ClockCycles()` pair) and the `ClockCycles()` resolution; report
   them alongside the results so the numbers have a floor.
   ✅ DONE 18 Nov 2026 (this chunk): new `calibration` probe (runs
   FIRST in the suite) — 1000 empty `ClockCycles()` pairs per run,
   `timer_overhead_ns` samples + one `timer_resolution_ns` sample
   (smallest nonzero delta) + `RT-PROBE DIAG calibration
   cycles_per_sec`. The report renders a "Calibration (measurement
   floor)" section (p50 overhead is the practical floor; numbers are
   raw, NOT overhead-subtracted). Measured live, pooled over 3 runs
   (N=3000): overhead min 9 ns, p50 20 ns, mean 41 ns; resolution
   10 ns; cycles_per_sec 1,500,460,288. Overhead p50 ≈ 2 timer
   ticks — the floor is the timer, not the probe code.
4. **Repeatability.** `--repeat N` in the CLI: run the suite N times,
   aggregate per-metric statistics across runs.
   ✅ DONE 18 Nov 2026 (this chunk): `--repeat N` (default 1) —
   image built once, suite booted N times, one pooled report:
   pooled count/min/p50/p90/p99/max/mean per metric + a "Cross-run
   aggregate" section (per-run means min/mean/max, spread, mean of
   run p50s) + one "Per-run detail" line per run; serial.log is the
   runs concatenated, plus one serial-run<i>.log per run. Verified
   live: `--repeat 3` on the short config (~96 s wall, 3/3 complete).
   Findings: prio contrast intact in every run (NONE 268–302 ms vs
   INHERIT 99.9–100.2 ms); INHERIT run-mean spread 231 µs (very
   stable). Idle jitter is the least repeatable metric under TCG
   (run means 500–804 µs, spread 304 µs, ~43% of mean); µs-scale
   run means vary by tens of percent run to run — the robust signals
   are the A/B deltas (NONE vs INHERIT, load vs idle), not the
   absolute means.
5. **Charts.** PNG charts for the demo video (optional matplotlib,
   gracefully skipped when absent; ASCII histograms stay the default
   so the CLI keeps zero dependencies).
   ✅ DONE 18 Nov 2026 (this chunk): **stdlib-only inline SVG, not
   matplotlib** — matplotlib is installed on this VM (3.6.3) but is
   not stdlib, so "gracefully skipped when absent" would mean the
   demo artifact silently missing on a fresh machine. New module
   `rtprobe/charts.py` renders `out/charts.html` (self-contained,
   inline SVG, no scripts, no external resources) + standalone
   `out/charts/*.svg` (msg_roundtrip, wake_latency,
   jitter_idle_vs_load, prio_inversion), wired into
   `report.write_report` so every `./rt-probe run` and `measure`
   produces them. Histograms carry p50/p90/p99 markers + full stats
   captions; jitter idle/load are stacked panels with their own
   x-scales (the load tail reaches ~30x the idle max) plus a
   load/idle ratio line; prio is mean bars with min/max whiskers +
   per-round dots and the NONE/INHERIT ratio. Missing probes omit
   their chart, never faked. For raster video frames convert with
   any standard tool (rsvg-convert, Inkscape, Chromium headless
   screenshot). Verified live: `--repeat 2` short config (~65 s
   wall, 2/2 complete) — NONE 301.70 ms vs INHERIT 100.18 ms
   (3.01x), msg p50 24.36 us, wake p50 11.34 us, jitter idle p50
   699.15 us vs load p50 930.16 us / p90 19.64 ms. Tests 67 → 82,
   all passing (new tests/test_charts.py, 15 tests).
6. **Load realism.** Add a memory/cache-pressure phase to
   `jitter_load` (streaming reads over a buffer larger than cache).
   ✅ DONE 18 Nov 2026 (this chunk): the load phase is now two
   SCHED_FIFO-70 CPU spinners PLUS two SCHED_FIFO-70 memory
   streamers, each sweeping its own 64 MiB buffer at a 64-byte
   stride (one cache line per access), buffers allocated and
   memset before any measurement; total 2 x mem_mb MiB, bounded
   and deterministic. New CLI flag `--jitter-mem-mb N` (default 64;
   0 = spinners only, the old behaviour, for A/B comparison);
   the probe prints `RT-PROBE DIAG jitter_load mem_mb=.. stride=64B
   streamers=.. spinners=2` and the report states the load
   configuration in its own section; the jitter chart panel is now
   "under CPU + memory load". Verified live (short config,
   `--iterations 50 --warmup 25 --period-ms 5 --rounds 3
   --hold-ms 100`, ~39 s wall, exit 0, suite complete, prio
   contrast intact NONE 301.5 ms vs INHERIT 100.3 ms):
   idle p50 531 µs / mean 675 µs, load p50 794 µs / p90 22.38 ms /
   mean 5.99 ms / max 32.69 ms. Honest finding — an A/B control
   (`--jitter-mem-mb 0`, same config) gives load p50 140 µs /
   p90 21.03 ms / mean 4.31 ms / max 29.54 ms, and the old
   spinners-only baseline was p90 19.64 ms / mean 4.89 ms: the
   load-phase distribution is the same with and without the
   streamers. Under TCG the tail is dominated by host scheduling
   (missed slots), and TCG models no guest caches, so the
   streamers' cache-eviction mechanism is not resolvable above
   the host noise at N=40 — the idle phase alone varies 4–5x
   run to run (p50 164 µs vs 622 µs, identical config, no load).
   The memory load is still the right model for real hardware
   (cache eviction + bandwidth contention are real mechanisms
   spinners never exercise), and its config is now stated on
   every report — but the numbers do not claim an effect TCG
   cannot show. Tests 82 → 86, all passing (new: config
   jitter_mem_mb/probe_args, CLI --jitter-mem-mb, qemu env,
   report load-section present/absent, chart label).
   Side note: this VM's QEMU had vanished (VM restart wiped the
   apt install) — reinstalled `qemu-system-x86` 8.2.2 via apt
   before verifying (apt-get update over the egress proxy took
   ~10 min; the install itself then completed).
7. **Codelab.** "Headless QNX 8.0 on QEMU without KVM, from zero to
   a running program" ($3,500 Best Codelab ticket, ~1–2 days once the
   build works).
   ✅ DONE 18 Nov 2026 (this chunk): `CODELAB.md` in the repo root —
   14 steps from a bare Linux host to a booted QNX 8.0 guest running
   the suite (host checks, QEMU install incl. the wiped-by-restart
   gotcha, myQNX + QNX Everywhere licence, unattended SDP 8.0
   install, qcc smoke test, bare mkqnximage build, dry-run, image
   build, manual QEMU boot flag-by-flag, `./rt-probe run`, reading
   the report + charts, `--repeat N`, honest limitations,
   troubleshooting). Linked from README.md. Verified step by step
   for this codelab: prereq checks; `apt-get install -s
   qemu-system-x86` (package resolves, 8.2.2); qcc hello-world →
   QNX ELF (`/usr/lib/ldqnx-64.so.2`), host run fails as documented;
   dry-run output verbatim; `build-image` ~10 s, IMAGE OK;
   raw QEMU boot → `RT-PROBE SUITE DONE` once, `timeout 150` exit
   124 as documented; `./rt-probe run` default config ~55 s, exit 0;
   `measure` on the same log reproduces the report byte-identically;
   report numbers quoted are from that run. **Not re-verified from
   scratch** (stated in the codelab): myQNX signup + SDP
   download/install — transcribed from the 17 Nov install script +
   QNX docs, installer sha256 recorded for comparison; the
   bare-QEMU SeaBIOS smoke test is from setup, 17 Nov. New
   `tests/test_codelab.py` (5 tests): required headings present,
   every `./rt-probe` command in the codelab parses against the real
   CLI parser, the manual QEMU argv matches `build_qemu_argv`
   modulo paths, licence rule + not-reverified note present.
   Tests 86 → 91, all passing.
   Side fixes in this chunk: README.md licence line corrected
   (only `~/.qnx/license/licenses` exists now; the `/root` copy was
   wiped by a VM restart) and the stale Status section updated.
8. **Repo + submission.** Create the public GitHub repo, push, and
   prepare the Devpost submission (repo + <3 min demo video).
