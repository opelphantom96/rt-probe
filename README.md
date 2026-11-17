# RT-Probe — a QNX real-time latency workbench

A stdlib-only Python host tool that cross-compiles a small QNX probe
suite, boots it headless in QEMU x86_64 via `mkqnximage`, and turns the
probes' serial-console output into a terminal report.

Entry for the **QNX Global Hackathon 2026**, category **Developer
Tooling & Host Tools** (plus the $3,500 "Best Use of QNX-specific
Technologies" bonus: the probes measure native QNX message passing,
priorities, and the priority-inheritance protocol). Deadline:
**16 Dec 2026 02:00 WIB**.

## What it measures

| Probe | What |
|---|---|
| `msg_roundtrip` | Native message-passing round-trip (ChannelCreate/MsgSend/MsgReply) |
| `wake_latency` | Time from `sem_post()` to a high-priority waiter running again |
| `jitter_load` | Periodic-thread jitter, idle vs under CPU load |
| `prio_inversion` | Priority-inversion wait, without vs with priority inheritance |

All timings are **indicative QEMU/TCG measurements, not hardware-grade
numbers** — see DESIGN.md for the honest caveats.

## Verified results (QEMU/TCG, `--repeat 3` pooled, 18 Nov 2026)

Pooled across 3 boots of the suite (image built once). Absolute
numbers are TCG-indicative; the A/B deltas are the robust signal.

| Metric | Pooled mean |
|---|---|
| msg round-trip | 34.22 µs |
| wake latency | 19.13 µs |
| jitter, idle | 698.42 µs |
| jitter, under CPU + memory load | 4.70 ms |
| prio inversion, `PTHREAD_PRIO_NONE` | 290.76 ms |
| prio inversion, `PTHREAD_PRIO_INHERIT` | 100.07 ms |

Calibration floor (empty `ClockCycles()` pair, N=3000): overhead
p50 20 ns, resolution 10 ns — the floor is the timer, not the probe
code. Priority inheritance is the star: the wait is ≈ the 200 ms
hold in every run (run-mean spread 231 µs), while without it the wait
is 2.9–3.0× the hold and host-scheduling-gated. Idle jitter is the
least repeatable metric under TCG (run-mean spread ~43%) — quote the
deltas, not single-run means.

## Requirements

- QNX SDP 8.0 at `~/workspace/qnx/qnx800/` (already installed)
- QEMU 8.2.2 (`qemu-system-x86_64`, TCG only — no `/dev/kvm` here)
- Python 3.10+ (stdlib only, no third-party packages)
- The license key file lives at `~/.qnx/license/licenses`
  (`/home/hatch/.qnx/license/licenses`). Never move, copy, or print
  it — check it exists with `ls -l` only. (An earlier copy under
  `/root/.qnx/license/` was wiped by a VM restart; the `$HOME` copy
  is the one builds use.)

New here? Start with **[CODELAB.md](CODELAB.md)** — "Headless QNX
8.0 on QEMU without KVM", from zero to a running program, every
command verified on this machine.

## Quickstart

```bash
# Print the plan without doing anything
./rt-probe run --dry-run

# Full run: build image, boot QEMU, measure, write the report
./rt-probe run
# -> report in ~/workspace/qnx/rt-probe/out/report.txt
# -> charts in ~/workspace/qnx/rt-probe/out/charts.html
#    (+ standalone SVGs in out/charts/ for the demo video)

# Build the QEMU image only
./rt-probe build-image [--workdir DIR]

# Parse an existing serial log and write the report
./rt-probe measure --log serial.log [--output-dir DIR]

# Unit tests (no QEMU needed)
./run_tests.sh
```

## How it works

```
./rt-probe run
  -> qcc cross-compiles probes/            (QNX x86_64 binaries)
  -> scripts/build-image.sh stages them into a fresh mkqnximage dir
     (local/snippets/*.custom) and builds the QEMU image
  -> QEMU boots it headless with -kernel output/ifs.bin
     (the disk-bootloader path crawls under TCG and is NOT used)
  -> post_start.custom runs /data/rt-probe/run-probes.sh at the end
     of system startup; probes print RT-PROBE lines to the serial console
  -> the CLI captures the serial log, parses the lines, and writes
     out/report.txt + out/histograms.txt + out/charts.html
     (+ out/charts/*.svg) + out/serial.log
```

## Probe output format

```
RT-PROBE BEGIN <name>
RT-PROBE SAMPLE <name> <metric> <value_ns> <seq>
RT-PROBE END <name> <count> <status>
RT-PROBE SUITE DONE
```

The CLI ignores every other serial line (boot messages, sshd faults,
etc.) and flags probes that never printed `END`.

## Layout

```
rt-probe/            entry point (sh wrapper -> python3 -m rtprobe.cli)
rtprobe/             host package: cli, config, measure, report, qemu,
                     charts (stdlib-only SVG charts)
probes/              target C sources (probes.h + 4 probes + Makefile)
  run-probes.sh      target-side runner (staged into the image)
scripts/
  build-image.sh     probe compile + mkqnximage integration
tests/               unit tests, one file per Python module
DESIGN.md            probe list, methodology, honest limitations
CODELAB.md           step-by-step: headless QNX 8.0 on QEMU without KVM
```

## Status

Full build TODOs 1–7 are done (see DESIGN.md): first live run,
per-probe args, calibration, `--repeat N`, SVG charts, memory-load
realism, and the codelab. All 91 unit tests pass (`./run_tests.sh`).
Remaining: TODO #8, repo + Devpost submission — see
[SUBMISSION.md](SUBMISSION.md).

## License

MIT — see [LICENSE](LICENSE).
