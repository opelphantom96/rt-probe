# Headless QNX 8.0 on QEMU without KVM — from zero to a running program

This codelab takes you from a bare Linux machine to a booted QNX 8.0
guest running the RT-Probe real-time measurement suite — with **no KVM,
no hardware, and no network device in the guest**. Every command below
is one the author actually ran on the verification machine; where a
step could *not* be re-run from scratch, it says so plainly.

**What you will end up with:** a QEMU image that boots QNX 8.0.0
headless, runs five small probes at startup (message-passing
round-trip, semaphore wake latency, periodic-thread jitter under
load, priority inversion with and without priority inheritance, plus
a timer-calibration probe), and writes a report with percentiles and
SVG charts on your host.

**Time:** about 30–60 minutes once the toolchain is installed. The
long pole is the SDP download and install (Step 4), not the build or
the run — the image builds in ~10 s and a full run takes ~55 s.

**Verified on** (18 Nov 2026): Ubuntu 24.04 (noble), x86-64 host,
4 vCPUs, 7.9 GB RAM, QEMU 8.2.2 (Debian `1:8.2.2+ds-0ubuntu1.18`),
Python 3.12.3, GNU Make 4.3, QNX SDP 8.0 baseline
`com.qnx.qnx800` 8.0.0.00141T202311271501L, RT-Probe at
`~/workspace/qnx/rt-probe`. Your numbers will differ from the ones
quoted here — that is expected, see Step 12.

> **Scope note.** This codelab covers getting QNX running and the
> probe suite measured. It does not cover writing your own QNX
> programs (the Step 5 smoke test is as far as it goes) and it does
> not cover the Devpost submission — that is a later step of the
> project.

---

## Step 0 — Get the code

Check out the RT-Probe repo (the public link is added when the repo
is published; for now this directory) and work from its root for the
rest of the codelab:

```bash
cd ~/workspace/qnx/rt-probe
ls
# DESIGN.md  README.md  CODELAB.md  rt-probe  rtprobe/  probes/  scripts/  tests/
```

The layout:

```text
rt-probe/            entry point (sh wrapper -> python3 -m rtprobe.cli)
rtprobe/             host package: cli, config, measure, report, qemu,
                     charts (stdlib-only SVG charts)
probes/              target C sources (probes.h + 5 probes + Makefile)
  run-probes.sh      target-side runner (staged into the image)
scripts/
  build-image.sh     probe compile + mkqnximage integration
tests/               unit tests, one file per Python module
DESIGN.md            probe list, methodology, honest limitations
CODELAB.md           this file
```

Everything the host tool does is **stdlib-only Python** — no
third-party packages to install.

---

## Step 1 — Check your host (2 minutes)

There is no KVM on the verification machine, and there does not need
to be. Confirm the same on yours:

```bash
ls -l /dev/kvm
# ls: cannot access '/dev/kvm': No such file or directory   <- expected

qemu-system-x86_64 --version | head -1
# QEMU emulator version 8.2.2 (Debian 1:8.2.2+ds-0ubuntu1.18)

python3 --version   # Python 3.12.3 (3.10+ is fine)
make --version | head -1   # GNU Make 4.3

nproc               # 4 on the verification machine
free -m | head -2   # ~8 GB total; the guest takes 1 GB, keep the host lean
```

If `qemu-system-x86_64` is missing, go to Step 2 first.

**Disk space:** the SDP install takes on the order of 1–2 GB, the
built image is ~157 MB (raw disk) plus a ~10 MB kernel, and the
workspace holds the reports. A few GB free is plenty.

---

## Step 2 — Install QEMU

```bash
sudo apt-get update && sudo apt-get install -y qemu-system-x86
```

Then verify, and keep this check — it is the same command you use
any time QEMU seems to have vanished:

```bash
command -v qemu-system-x86_64
# /usr/bin/qemu-system-x86_64
qemu-system-x86_64 --version | head -1
```

**A gotcha from the author's machine:** a VM restart once wiped the
apt install of QEMU entirely (`qemu-system-x86_64: command not
found` the next morning), and `apt-get update` over the egress proxy
took ~10 minutes before the reinstall would even start. On a normal
machine this does not happen — but the symptom and the fix are the
same everywhere: if the binary is missing, reinstall it with the
command above. `apt-get install -s qemu-system-x86` (simulate, no
changes) is a safe way to check the package name resolves before
you install.

You need only the `qemu-system-x86` package: the full-system x86-64
emulator. No `qemu-kvm`, no libvirt, no bridging — the guest gets no
network device at all (Step 9 explains why that is fine).

---

## Step 3 — myQNX account and the QNX Everywhere licence

QNX SDP 8.0 is a commercial product, but the **QNX Everywhere**
program gives you a free non-commercial licence for exactly this
kind of work. You need:

1. A **myQNX account** — create one at <https://www.qnx.com>
   (sign up, confirm the email).
2. The **QNX Everywhere** program — join it from the QNX developers
   pages (<https://qnx.software/en/developers/get-started/qnx-everywhere>).
   It entitles you to the SDP 8.0 baseline and a licence key.

The licence is activated through the QNX Software Center (Step 4)
and the key file lands at:

```text
~/.qnx/license/licenses
```

Two rules that are not negotiable:

- **Never move, copy, or print the licence file.** Check that it
  exists with `ls -l ~/.qnx/license/licenses` only. Never `cat` it,
  never paste it anywhere, never commit it.
- **Builds use the `$HOME` copy.** On the author's machine the
  Software Center first wrote the key to `/root/.qnx/license/`,
  which was then wiped by a VM restart; the `~/.qnx/license/`
  copy is the one that survives and the one the tools read
  (`QNX_CONFIGURATION=$HOME/.qnx`, set by `qnxsdp-env.sh` in
  Step 4). If a tool fails with `license check failed`, the first
  thing to check is that `~/.qnx/license/licenses` exists.

> **Verification status — read this.** The account creation and the
> SDP install in Steps 3–4 were **not re-run from scratch** for this
> codelab: they need your myQNX login and a ~100 MB download, and
> re-installing a working toolchain to prove a step that already ran
> would be waste, not verification. They are transcribed from the
> install script that ran on 17 Nov 2026
> (`~/workspace/qnx/install-sdp8.sh`, run 20:46–20:55 WIB with the
> user's login supplied transiently — the password was never stored)
> and from the QNX docs linked at the end. Everything from Step 5
> on was re-run command by command for this codelab on 18 Nov 2026.

---

## Step 4 — Install SDP 8.0 (unattended)

The prepared script `~/workspace/qnx/install-sdp8.sh` does the whole
install. It reads the myQNX login **only from the environment**
(`MYQNX_USER` / `MYQNX_PASSWORD`), never prints it, and never writes
it to a file. Run it as:

```bash
MYQNX_USER=you@example.com MYQNX_PASSWORD='<your-myqnx-password>' \
  bash ~/workspace/qnx/install-sdp8.sh
```

What it does, in order:

1. **Logs in to myQNX** (`POST https://www.qnx.com/account/login.html`)
   and saves the auth cookie to `~/.qnx/myqnxcookies.auth`. It aborts
   if the cookie is not produced.
2. **Downloads the QNX Software Center installer** (2.0.4,
   `qnx-setup-2.0.4-202501021438-linux.run`, 99.85 MB) using that
   cookie, and prints its sha256. The recorded checksum on the
   author's install was:
   `5695a0ec8a1fd91840753b2cba86a9325f6052d4f69c757166cc61b09bcbe507`
   — compare the value you get with the checksum posted on the QNX
   download page (visible after myQNX login) and **do not proceed
   on a mismatch**. (Without the cookie, the download URL serves a
   myQNX login form, not the binary — that is how you know the
   login step failed.)
3. **Installs the Software Center** into `~/workspace/qnx/qnxinstall/`
   (accepting the EULA on the command line).
4. **Activates the licence** (`qnxsoftwarecenter_clt -syncLicenseKeys
   -activateAll -listLicenseKeys`).
5. **Installs the SDP 8.0 baseline** (`-cleanInstall -destination
   ~/workspace/qnx/qnx800 -installBaseline com.qnx.qnx800`).
6. **Verifies** the install by sourcing the environment script and
   locating `mkqnximage` and `qcc`.

When it finishes, verify the toolchain yourself:

```bash
ls ~/workspace/qnx/qnx800/qnxsdp-env.sh
source ~/workspace/qnx/qnx800/qnxsdp-env.sh
# QNX_HOST=/home/hatch/workspace/qnx/qnx800/host/linux/x86_64
# QNX_TARGET=/home/hatch/workspace/qnx/qnx800/target/qnx
# MAKEFLAGS=-I/home/hatch/workspace/qnx/qnx800/target/qnx/usr/include

which mkqnximage qcc
# /home/hatch/workspace/qnx/qnx800/host/common/bin/mkqnximage
# /home/hatch/workspace/qnx/qnx800/host/linux/x86_64/usr/bin/qcc
```

Notes on that environment script — you will source it in every new
shell that builds anything:

- It sets `QNX_HOST`, `QNX_TARGET`, `QNX_CONFIGURATION=$HOME/.qnx`
  and prepends the SDP `usr/bin` directories to `PATH`.
- It **unsets `PYTHONPATH`** and sets `PYTHONDONTWRITEBYTECODE=1`.
  That is why the RT-Probe wrapper sets its own `PYTHONPATH`
  explicitly (see `rt-probe`) — if your own tooling misbehaves after
  sourcing, check those two first.

Sources: [Unattended installation on Linux/macOS](https://www.qnx.com/developers/docs/qsc/com.qnx.doc.qsc.inst_larg_org/topic/create_headless_installation_linux_macos.html),
[QSC command line](https://www.qnx.com/developers/docs/qsc/com.qnx.doc.qsc.user_guide/topic/commandline_qsc.html),
[QSC download page](https://www.qnx.com/download/group.html?programid=29178).

---

## Step 5 — Prove the cross-compiler works (2 minutes)

Before building the whole suite, compile one tiny program and look
at what comes out:

```bash
source ~/workspace/qnx/qnx800/qnxsdp-env.sh

cat > /tmp/hello-qnx.c <<'EOF'
#include <stdio.h>
int main(void){printf("hello qnx\n");return 0;}
EOF

qcc -V gcc_ntox86_64 -o /tmp/hello-qnx /tmp/hello-qnx.c
file /tmp/hello-qnx
```

Expected output (verified 18 Nov 2026):

```text
/tmp/hello-qnx: ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV),
dynamically linked, interpreter /usr/lib/ldqnx-64.so.2, ...
```

That interpreter is the giveaway: this is a QNX binary, not a Linux
one. Trying to run it on the host fails exactly as it should:

```bash
/tmp/hello-qnx
# bash: /tmp/hello-qnx: cannot execute: required file not found
```

"Required file not found" means the *loader* (`ldqnx-64.so.2`) is
missing on the host — the binary is fine, it just cannot run here.
It runs on the QNX guest. If `file` instead reports a Linux
interpreter (`/lib64/ld-linux-x86-64.so.2`), your `qcc` invocation
is wrong — check the `-V gcc_ntox86_64` flag.

---

## Step 6 — Build a bare QNX image with mkqnximage (5 minutes)

`mkqnximage` builds a bootable QNX image directory from the SDP.
Try it bare first, so you see the tool before RT-Probe wraps it:

```bash
source ~/workspace/qnx/qnx800/qnxsdp-env.sh
mkdir -p /tmp/qnx-bare-image && cd /tmp/qnx-bare-image
mkqnximage --type=qemu --arch=x86_64
ls -l output/
```

Expected (verified during setup, 17 Nov 2026): `output/disk-qemu`
(raw, ~157 MB), `output/disk-qemu.vmdk`, and `output/ifs.bin`
(~10.4 MB — the kernel image, the thing QEMU will actually boot).

Two things to know:

- `mkqnximage` **refuses a non-empty directory** without `--force`.
  Always start from a fresh directory. (`scripts/build-image.sh`
  wipes and recreates its workdir for exactly this reason.)
- A QEMU smoke test during setup confirmed QEMU executes x86-64
  guest code with no KVM: SeaBIOS 1.16.3 booted under `-accel tcg`
  and iPXE started, failing on boot devices as expected with no disk
  attached.

You will not boot this bare image in this codelab — the RT-Probe
image in Step 8 is the same thing with the probes staged in, and
that is the one worth booting.

---

## Step 7 — Look at the plan before you run it

From the repo root, ask the CLI what it is about to do:

```bash
cd ~/workspace/qnx/rt-probe
./rt-probe run --dry-run
```

Expected output (verified 18 Nov 2026):

```text
RT-PROBE DRY RUN
Probes: calibration, msg_roundtrip, wake_latency, jitter_load, prio_inversion
Probe args: calibration ; msg_roundtrip 200 100; wake_latency 200 100; jitter_load 10 200 10 64; prio_inversion 5 200
Guest CPUs: 2
Repeat: 1
SDP: /home/hatch/workspace/qnx/qnx800
Image dir: /home/hatch/workspace/qnx/rt-probe-image
QEMU timeout: 180s
QEMU argv:
  qemu-system-x86_64 -smp 2 --cpu max -m 1024 -drive file=/home/hatch/workspace/qnx/rt-probe-image/output/disk-qemu.vmdk,if=ide,id=drv0 -pidfile /home/hatch/workspace/qnx/rt-probe-image/output/qemu.pid -nographic -kernel /home/hatch/workspace/qnx/rt-probe-image/output/ifs.bin -serial mon:stdio -object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-pci,rng=rng0
Output dir: /home/hatch/workspace/qnx/rt-probe/out
```

Read that QEMU line carefully — it is the whole boot, and Step 9
walks through it flag by flag. The dry run has no side effects.

---

## Step 8 — Build the RT-Probe image

```bash
cd ~/workspace/qnx/rt-probe
./rt-probe build-image
```

What happens (see `scripts/build-image.sh` for the full script):

1. `qcc` cross-compiles the five probes (`calibration`,
   `msg_roundtrip`, `wake_latency`, `jitter_load`,
   `prio_inversion`) plus the target-side runner
   (`probes/run-probes.sh`).
2. The binaries are staged into a **fresh** image directory
   (`~/workspace/qnx/rt-probe-image`, wiped first).
3. Two `mkqnximage` snippets are written:
   `local/snippets/data_files.custom` puts the binaries on the data
   partition (mounted at `/data` at runtime, so
   `rt-probe/msg_roundtrip` lands at
   `/data/rt-probe/msg_roundtrip`), and
   `local/snippets/post_start.custom` runs
   `/data/rt-probe/run-probes.sh` at the **end** of system startup.
   That hook placement matters: an earlier hook (`ifs_start.custom`)
   runs *before* `/data` is mounted and must not be used for the
   probes.
4. `mkqnximage --type=qemu --arch=x86_64` builds the image.

Expected tail (verified 18 Nov 2026, ~10 s):

```text
Generating output/build/data.build
Generating output/build/qemu_options
Building disk
Generating system partition . . .
Generating data partition . . .
Generating ifs . . .
Building boot partition . . .
Building disk . . .
== 6. Verify outputs ==
IMAGE OK
kernel: /home/hatch/workspace/qnx/rt-probe-image/output/ifs.bin
disk:   /home/hatch/workspace/qnx/rt-probe-image/output/disk-qemu.vmdk
Image: /home/hatch/workspace/qnx/rt-probe-image/output/disk-qemu.vmdk
Kernel: /home/hatch/workspace/qnx/rt-probe-image/output/ifs.bin
```

And the outputs:

```bash
ls -l ~/workspace/qnx/rt-probe-image/output/
# disk-qemu       157229568 bytes (raw disk)
# disk-qemu.vmdk        169 bytes (descriptor pointing at the raw disk)
# ifs.bin          10931708 bytes (~10.4 MB kernel image)
```

---

## Step 9 — Boot it by hand (optional, but instructive)

This is the same QEMU line the dry run printed, run directly.
**Do not boot from the disk** — the SeaBIOS → QNX bootloader path
crawls under TCG (2 dots in 280 s during setup). Load the kernel
directly with `-kernel`:

```bash
cd ~/workspace/qnx/rt-probe-image
timeout 150 qemu-system-x86_64 \
  -smp 2 --cpu max -m 1024 \
  -drive file=output/disk-qemu.vmdk,if=ide,id=drv0 \
  -pidfile output/qemu.pid \
  -nographic \
  -kernel output/ifs.bin \
  -serial mon:stdio \
  -object rng-random,filename=/dev/urandom,id=rng0 \
  -device virtio-rng-pci,rng=rng0 \
  > /tmp/rtprobe-manual-boot.log 2>&1
```

Flag by flag:

| Flag | Why |
|---|---|
| `-smp 2 --cpu max` | 2 guest CPUs, best CPU model QEMU offers. `--smp 1` is a valid variant (single-CPU guest) — see Step 12. |
| `-m 1024` | 1 GB guest RAM. The jitter load phase reserves 2 × 64 MB inside it. |
| `-drive file=…vmdk,if=ide,id=drv0` | The data partition lives on this disk; the probes run from it. |
| `-nographic -serial mon:stdio` | Headless: the serial console (and the QEMU monitor) share your terminal. No display, no window. |
| `-kernel output/ifs.bin` | Boot the kernel image directly — the fast path. |
| `-object rng-random … -device virtio-rng-pci` | A virtio RNG so the guest has entropy; without it some startup services stall. |
| (no `-net`, no `-nic`) | Deliberate: the guest gets **no network device**. |

What you should see in `/tmp/rtprobe-manual-boot.log` (verified
18 Nov 2026):

```text
---> Starting misc
...
RT-PROBE SUITE DONE
```

The `timeout 150` kills QEMU after 150 s, so the command exits
with code 124 — that is expected. QEMU does not exit on its own
after the suite finishes; the CLI (Step 10) terminates it as soon
as it sees the marker. If you run QEMU without `timeout`, stop it
with **Ctrl-A X** (the `-nographic` escape sequence) once you see
`RT-PROBE SUITE DONE`.

**Boot noise you can ignore** — all of this appears in the log and
none of it is a probe failure:

```text
ACPI table not found (0x4746434d)
System behaves poorly without PCID support.
Memory fault (core dumped)          <- sshd, which has no network to serve
```

The networking failures (`dhcpcd`, `sshd`) are expected: no
interface was attached, and the probes need no network. One more:
the literal string `Startup complete` **never appears** on this
image's serial console even on a fully successful boot — the CLI
treats `RT-PROBE SUITE DONE` (or `Starting misc`) as the boot-ok
signal instead (see `rtprobe/qemu.py: boot_ok()`).

---

## Step 10 — Run the suite the easy way

```bash
cd ~/workspace/qnx/rt-probe
./rt-probe run
```

This builds the image (Step 8), boots it in QEMU (Step 9),
captures the serial log, parses the `RT-PROBE` lines, and writes
the report. Verified 18 Nov 2026: **~55 s wall, exit 0**.

The report is printed to your terminal and written to
`out/report.txt`. The tail of the run looks like this:

```text
Report: /home/hatch/workspace/qnx/rt-probe/out/report.txt
Histograms: /home/hatch/workspace/qnx/rt-probe/out/histograms.txt
Charts: /home/hatch/workspace/qnx/rt-probe/out/charts.html
Serial log: /home/hatch/workspace/qnx/rt-probe/out/serial.log
```

Everything the run produced:

| File | What |
|---|---|
| `out/report.txt` | The report: calibration floor, load config, per-metric count/min/p50/p90/p99/max/mean |
| `out/histograms.txt` | ASCII histograms of the same samples |
| `out/charts.html` | Self-contained page with inline SVG charts (no scripts, no external resources — open it in any browser) |
| `out/charts/*.svg` | The four charts standalone, for the demo video |
| `out/serial.log` | The full serial console capture |

**Faster iteration.** The defaults (200 iterations, 100 warmup)
are for the real report. While you are iterating, use the short
config — same suite, fewer samples, ~40 s:

```bash
./rt-probe run --iterations 50 --warmup 25 --period-ms 5 --rounds 3 --hold-ms 100
```

And you can re-parse any captured log without booting again:

```bash
./rt-probe measure --log out/serial.log --output-dir /tmp/rtprobe-measure-check
# Report: /tmp/rtprobe-measure-check/report.txt  (byte-identical to out/report.txt)
```

That last point is worth knowing: `measure` on the same log
reproduces the same report exactly, so the report is a pure
function of the serial log.

---

## Step 11 — Read the report

Here is the report from the verification run (18 Nov 2026, default
config). Yours will have different numbers — read the *shape*,
not the digits:

```text
RT-PROBE REPORT
===============

Suite: complete
Finished probes: calibration, jitter_load, msg_roundtrip, prio_inversion, wake_latency

Calibration (measurement floor)
-------------------------------
timer overhead (empty ClockCycles() pair, N=1000): min 10 ns  p50 20 ns  mean 52 ns
timer resolution (smallest nonzero delta): 10 ns
cycles_per_sec: 1497841035
The p50 overhead is the practical floor: samples near
or below it are not resolvable. Probe numbers in this
report are raw and NOT overhead-subtracted.

Load configuration (jitter load phase)
--------------------------------------
jitter_load: mem_mb=64 stride=64B streamers=2 spinners=2

jitter_load / jitter_idle_ns
----------------------------
count 190  min 1.06 ms  p50 1.23 ms  p90 1.44 ms  p99 2.51 ms  max 2.83 ms  mean 1.28 ms

jitter_load / jitter_load_ns
----------------------------
count 190  min 217.20 us  p50 3.29 ms  p90 26.99 ms  p99 75.19 ms  max 93.23 ms  mean 9.62 ms

msg_roundtrip / roundtrip_ns
----------------------------
count 200  min 20.82 us  p50 27.15 us  p90 81.19 us  p99 1.39 ms  max 1.61 ms  mean 76.22 us

prio_inversion / inversion_wait_inherit_ns
------------------------------------------
count 5  min 189.04 ms  p50 200.25 ms  p90 200.44 ms  p99 200.55 ms  max 200.56 ms  mean 198.07 ms

prio_inversion / inversion_wait_none_ns
---------------------------------------
count 5  min 301.89 ms  p50 504.68 ms  p90 530.29 ms  p99 544.93 ms  max 546.56 ms  mean 434.29 ms

wake_latency / wake_ns
----------------------
count 200  min 9.55 us  p50 14.04 us  p90 32.63 us  p99 57.24 us  max 252.83 us  mean 19.74 us

All timings are indicative QEMU/TCG measurements,
not hardware-grade numbers (see DESIGN.md).
```

How to read it:

- **Calibration first.** Every run starts with 1000 empty
  `ClockCycles()` pairs. The p50 overhead here is 20 ns and the
  timer resolution is 10 ns — that is the floor of the measurement.
  The probe numbers are raw, never overhead-subtracted, and the
  report says so.
- **The load configuration is stated on every report**
  (`mem_mb=64 stride=64B streamers=2 spinners=2`), so a reader can
  see what "under load" meant. Change it with
  `--jitter-mem-mb N` (0 = CPU spinners only).
- **Percentiles, not just means.** Real-time behaviour lives in
  the tail: the jitter load phase has p50 3.29 ms but p99 75.19 ms
  and max 93.23 ms. A mean alone (9.62 ms) would hide that shape.
- **The A/B comparisons are the result.** Priority inheritance
  waits ≈ the 200 ms hold (mean 198.07 ms); without it the high
  thread waits far longer (mean 434.29 ms). Idle vs load jitter
  (p50 1.23 ms vs 3.29 ms) is the same kind of comparison.
- **Charts.** Open `out/charts.html` in a browser: histograms
  with p50/p90/p99 markers for msg/wake, stacked idle/load panels
  for jitter (each with its own x-scale — the load tail reaches
  ~30× the idle max), and mean bars with min/max whiskers plus
  per-round dots for the priority inversion.

---

## Step 12 — Repeatability: one run is not a statistic

Run the suite three times and aggregate:

```bash
./rt-probe run --repeat 3 --iterations 50 --warmup 25 --period-ms 5 --rounds 3 --hold-ms 100
```

The image is built once and booted three times; the report pools
all samples and adds a "Cross-run aggregate" section (per-run
means, spread, mean of run p50s) plus one "Per-run detail" line
per run. `out/serial.log` concatenates the runs, and there is one
`out/serial-run<i>.log` per run. (Note: `out/` keeps per-run logs
from earlier `--repeat` runs; a shorter repeat does not clean the
stale ones.)

Why this matters — verified, not assumed. Under TCG, run-to-run
means of the µs-scale metrics vary by tens of percent, and idle
jitter is the least repeatable metric in the suite:

- Idle-jitter p50 was **531 µs** in one short-config run and
  **1.23 ms** in the default-config verification run in this
  codelab; an earlier A/B pair on identical config gave p50
  **164 µs vs 622 µs** — a 4–5× spread with no load at all.
- The priority-inversion contrast, by contrast, reproduces in
  every run (NONE 268–505 ms vs INHERIT ≈ 100–200 ms, i.e. ≈ the
  hold). INHERIT run-mean spread was 231 µs over 3 runs — very
  stable.

So: **quote the A/B deltas, not single-run means.** The robust
claims are "NONE ≫ INHERIT" and "load tail ≫ idle tail", not
"msg round-trip is 27.15 µs".

Two more comparability notes:

- **`--smp 1` numbers are not comparable to `--smp 2` numbers.**
  Under a single-CPU guest the jitter load phase shows no
  degradation (spinners cannot starve the higher-priority
  periodic thread on one CPU): verified load p50 1.01 ms vs idle
  p50 1.09 ms. Use `--smp 1` for the priority-inversion demo if
  you want the single-CPU textbook case (NONE 502.7 ms vs
  INHERIT 200.3 ms at hold 200 ms), but do not compare its jitter
  numbers with smp-2 runs.
- **The memory streamers do not move the numbers under TCG.**
  An A/B control (`--jitter-mem-mb 0`, spinners only) gives the
  same load-phase distribution as the default 64 MiB streamers
  (load p90 ~21–22 ms either way). TCG models no guest caches, so
  there is no guest cache for the streamers to evict; the
  load-phase tail is dominated by host scheduling. The memory
  load is still the right model for real hardware — cache
  eviction and bandwidth contention are real mechanisms CPU
  spinners never exercise — but this codelab does not claim an
  effect TCG cannot show.

---

## Step 13 — What the numbers mean, and what they don't

The honest limitations, stated the same way in `DESIGN.md` — do
not soften these when you present the results:

1. **QEMU/TCG timings are indicative, not hardware-grade.** TCG
   translates guest code in software on a shared host with no KVM,
   no PCID, and no ACPI. Absolute numbers will differ from real
   hardware, probably by a large factor; relative comparisons
   (idle vs load, inherit vs none) are the meaningful signal.
2. **No guest networking.** The QEMU command attaches no network
   device, so `dhcpcd` fails and `sshd` faults at boot. Both are
   boot noise, not probe failures — the probes need no network.
3. **One run is not a statistic** — use `--repeat N` (Step 12).
4. **The load-phase tail is host scheduling.** Under TCG the
   jitter load tail is dominated by missed slots on the host, and
   the memory streamers' cache-eviction mechanism is not
   resolvable above that noise at these sample counts.

If you present RT-Probe results anywhere, present the A/B deltas
with the TCG caveat attached. That is the whole point of the tool:
an honest report, not a fast-looking one.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `qemu-system-x86_64: command not found` | QEMU not installed (or wiped by a VM restart — Step 2). Reinstall with `sudo apt-get install -y qemu-system-x86`. |
| `license check failed` from `mkqnximage`/`qcc` | The licence file is missing. Check `ls -l ~/.qnx/license/licenses` exists (Step 3). Never copy it from another machine's `/root` — re-activate with the Software Center instead. |
| `mkqnximage` refuses the directory | It refuses a non-empty directory without `--force`. Start from a fresh directory; `build-image.sh` wipes its workdir for you. |
| Boot crawls (dots, minutes, nothing) | You booted from the disk instead of `-kernel output/ifs.bin`. Always use the `-kernel` path (Step 9). |
| QEMU exits immediately / no serial output | Check the QEMU command line against the dry run (Step 7) — usually a wrong `-drive` path or a missing `output/ifs.bin` (run Step 8 first). |
| Suite never reaches `RT-PROBE SUITE DONE` | Check the tail of the serial log: a probe that printed `BEGIN` without `END` is flagged in the report, and a missing probe is reported `MISSING` by the runner. Also check the QEMU timeout (default 180 s) is enough on a loaded host. |
| `WARNING: QNX did not reach 'Startup complete'` | Harmless on this image — the literal string never appears on its serial console. The CLI accepts `SUITE DONE` / `Starting misc` as boot-ok; if the suite completed, ignore the warning. |
| Host runs out of memory during a run | The guest takes 1 GB and TCG is heavy. Close other work; the verification host had ~1.5 GB available and still ran fine. |
| `./rt-probe` fails with a Python error after sourcing `qnxsdp-env.sh` | The env script unsets `PYTHONPATH`. The `rt-probe` wrapper sets its own — run it as `./rt-probe`, not as `python3 -m rtprobe.cli` from a sourced shell without the wrapper. |

---

## Verification note — what was checked, and what was not

Re-verified step by step for this codelab, **18 Nov 2026** on the
machine in Step 0:

- Step 1 checks: `/dev/kvm` absent; QEMU 8.2.2; Python 3.12.3;
  Make 4.3; toolchain env script and licence file present.
- Step 2: `apt-get install -s qemu-system-x86` (simulate) resolves
  to the installed 8.2.2; `sudo -n true` confirms passwordless sudo
  on this machine (yours may prompt once — that is fine).
- Step 5: `qcc -V gcc_ntox86_64` produces a QNX ELF
  (`/usr/lib/ldqnx-64.so.2`); host execution fails with
  "cannot execute: required file not found", as documented.
- Step 7: `./rt-probe run --dry-run` output reproduced verbatim.
- Step 8: `./rt-probe build-image` — ~10 s, `IMAGE OK`, outputs
  as listed.
- Step 9: raw QEMU command boots the image; `RT-PROBE SUITE DONE`
  appears once in the log; `timeout 150` exits 124 as documented.
- Step 10: `./rt-probe run` (default config) — ~55 s, exit 0,
  report + histograms + charts + serial log all written.
- Step 10: `./rt-probe measure --log out/serial.log` reproduces
  the report byte-identically (`diff` clean).
- Step 11: report numbers quoted above are from that run.
- Tests: `./run_tests.sh` — 86/86 pass (plus the new codelab
  consistency tests in `tests/test_codelab.py`).

**Not re-verified from scratch** (see Step 3): myQNX account
creation and the SDP 8.0 download/install — transcribed from the
17 Nov 2026 install and the QNX docs; the installer sha256 is
recorded in Step 4 for you to compare. The bare-QEMU SeaBIOS
smoke test in Step 6 is from setup on 17 Nov 2026, not re-run
here.

---

## Where to go next

- `README.md` — the short version: quickstart, probe table, layout.
- `DESIGN.md` — methodology, the honest limitations, and the
  full-build TODO list (this codelab is TODO #7; the repo and
  submission are TODO #8).
- `./rt-probe run --help` — every flag, including `--smp`,
  `--repeat`, and `--jitter-mem-mb`.
- `./run_tests.sh` — the unit tests (no QEMU needed).
