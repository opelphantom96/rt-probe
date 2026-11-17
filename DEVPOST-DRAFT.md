# Devpost submission draft — RT-Probe (QNX Global Hackathon 2026)

> DRAFT ONLY. Do NOT submit from this file — copy the fields into the
> Devpost form once the repo exists and the demo video is public on
> YouTube. Status of each blocker is in SUBMISSION.md.

## Project URL

- GitHub repo: https://github.com/opelphantom96/rt-probe
  (⚠️ repo does NOT exist yet — create the empty public repo first,
  then push; see SUBMISSION.md)
- Demo video: <YouTube URL — pending, user-side upload>
- Codelab: in-repo `CODELAB.md` ("Headless QNX 8.0 on QEMU without KVM")

## Title

RT-Probe — a QNX Real-Time Latency Workbench

## Tagline

Measure QNX message-passing, wake latency, jitter and priority
inversion — headless on QEMU, no hardware, one command.

## Category

Developer Tooling & Host Tools

Also entered for: Best Use of QNX-specific Technologies ($3,500),
Best Codelab ($3,500).

## Description

### Inspiration

Real-time behaviour is the reason people choose QNX — but measuring
it usually means a board, a JTAG probe, and a lab. We wanted the
opposite: one command on an ordinary Linux laptop that boots real
QNX 8.0 headless in QEMU and tells you, honestly, how its
real-time primitives behave.

### What it does

`./rt-probe run` cross-compiles four small C probes with `qcc`,
builds a bootable QNX image with `mkqnximage`, boots it headless
under QEMU (TCG, no KVM), runs the suite at startup, and writes a
report plus vector charts:

- **msg_roundtrip** — native QNX message-passing round-trip
  (`ChannelCreate` / `MsgSend` / `MsgReply`)
- **wake_latency** — time from `sem_post()` to a high-priority
  waiter running again
- **jitter_load** — periodic-thread jitter, idle vs under CPU +
  memory load (spinners + cache-line streamers)
- **prio_inversion** — the classic priority-inversion demo, same
  scenario with `PTHREAD_PRIO_NONE` vs `PTHREAD_PRIO_INHERIT`

Every run starts with a calibration probe (empty `ClockCycles()`
pair) so the report states its own measurement floor, and
`--repeat N` boots the suite N times and reports pooled statistics
plus cross-run spread — one run is not a statistic.

### How we built it

Host side: stdlib-only Python 3 (zero third-party packages) — CLI,
image build, QEMU driver, serial-log parser, report and SVG chart
renderer. Target side: four C probes plus a shell runner, staged
into the image through `mkqnximage` snippets
(`local/snippets/data_files.custom`, `post_start.custom`). The
image boots with `-kernel output/ifs.bin`; the suite runs from
`post_startup.sh` and prints machine-parseable `RT-PROBE` lines to
the serial console.

### Challenges we ran into

- The first priority-inversion demo showed no inversion at all:
  a sleep-based hold let the low thread release on a timer expiry
  even while preempted. The fix was a CPU-bound busy hold, verified
  CPU-0 pinning with diagnostics, and a coordinator running at
  `SCHED_FIFO 60` so it is never starved behind the spinning thread.
- TCG models no guest caches, so the memory-load streamers' effect
  is not resolvable above host noise — we kept the load (it is the
  right model for real hardware) and wrote the honest finding into
  the report instead of claiming an effect we cannot show.
- `mkqnximage` only picks up snippets from its `local/` tree, and
  `ifs_start.custom` runs before `/data` is mounted — both found
  empirically and documented in DESIGN.md.

### Accomplishments that we're proud of

- A complete, reproducible measurement pipeline: `./rt-probe run`
  → report + charts in ~1 minute.
- The priority-inheritance contrast reproduces on every run
  (INHERIT ≈ the 200 ms hold, run-mean spread 231 µs; NONE is
  2.9–3.0× the hold).
- A 14-step codelab that takes a reader from a bare Linux host to
  a booted QNX 8.0 guest running the suite — every command verified
  on this machine.
- 91 unit tests, all passing, no QEMU needed for the suite.

### What we learned

- Under emulation, absolute timings are indicative; the A/B
  deltas (idle vs load, inherit vs none) are the meaningful signal.
- Real-time demos fail silently when the harness, not the system
  under test, is the bottleneck — verify pinning, verify the
  coordinator cannot starve, verify the hold cannot self-release.
- A measurement tool must state its own floor and its own
  limitations on every run, or its numbers are decoration.

### What's next

- Run the same suite on real QNX hardware and compare the deltas
  with the TCG numbers.
- Add a network-latency probe (needs a guest network device) and
  a scheduling-latency probe under interrupt load.

## Built With

QNX SDP 8.0 · QNX 8.0.0 · QEMU 8.2.2 (TCG, no KVM) · Python 3
(stdlib only) · C (qcc) · mkqnximage

## Try it out / Build & run instructions

Prerequisites: Linux host, QNX SDP 8.0 installed (free QNX
Everywhere licence), QEMU 8.2.2, Python 3.10+. Full step-by-step:
`CODELAB.md` in the repo ("Headless QNX 8.0 on QEMU without KVM").

```bash
git clone https://github.com/opelphantom96/rt-probe.git
cd rt-probe
./rt-probe run            # build image, boot QEMU, measure, report
# -> out/report.txt, out/charts.html (+ out/charts/*.svg)
./rt-probe run --repeat 3 # pooled statistics across 3 boots
./run_tests.sh            # unit tests (no QEMU needed)
```

QNX version: SDP 8.0 / QNX 8.0.0 guest. Target: x86_64 QEMU
(`-smp 2 --cpu max -m 1024`, TCG). Toolchain: `qcc -V
gcc_ntox86_64 -O2`.

## Evidence of QNX use

The probes are written against native QNX APIs, not POSIX
generics: `ChannelCreate`/`MsgSend`/`MsgReply` message passing,
QNX semaphores, `SCHED_FIFO` fixed-priority scheduling,
`pthread_mutexattr_setprotocol` with `PTHREAD_PRIO_INHERIT` vs
`PTHREAD_PRIO_NONE`, `ClockCycles()` timing against
`SYSPAGE_ENTRY(qtime)->cycles_per_sec`, and `ThreadCtl`
`_NTO_TCTL_RUNMASK_GET_AND_SET` CPU pinning with per-thread
diagnostics. The suite runs on a real QNX 8.0.0 guest built with
`mkqnximage` and booted in QEMU; the serial log in every report
shows the QNX boot and the `RT-PROBE SUITE DONE` marker.

## Verified numbers (QEMU/TCG — indicative, not hardware-grade)

Pooled `--repeat 3`, 18 Nov 2026: msg round-trip mean 34.22 µs;
wake latency mean 19.13 µs; jitter idle mean 698.42 µs vs load
mean 4.70 ms; prio inversion NONE mean 290.76 ms vs INHERIT mean
100.07 ms (hold 200 ms). Calibration floor: timer overhead p50
20 ns, resolution 10 ns (N=3000). Full methodology and honest
limitations: `DESIGN.md` in the repo.

## Prize tracks

Grand $10,000 · Developer Tooling & Host Tools $4,000 · Best Use of
QNX-specific Technologies $3,500 · Best Codelab $3,500.
Deadline: 16 Dec 2026 02:00 WIB. Judging 15–29 Jan 2027.
