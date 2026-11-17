# Demo video script + storyboard — RT-Probe (QNX Global Hackathon 2026)

Target: **under 3 minutes** (aim 2:30). Format: screen recording
(terminal + browser) with voiceover; every shot also carries
on-screen text, so a captioned silent cut works too. Record the
terminal/charts on the build VM; upload as **public** on YouTube.

## Shots

### 0. Title card — 0:00–0:08 (8 s)
- **Visual:** black screen, title fades in: "RT-Probe — a QNX
  real-time latency workbench". Subtitle: "One command. Real QNX 8.0.
  No hardware."
- **Narration:** "Real-time behaviour is why people choose QNX. But
  measuring it usually means a board and a lab. RT-Probe does it
  with one command, on a laptop."

### 1. The run — 0:08–0:50 (42 s)
- **Visual:** terminal, type `./rt-probe run`. Fast-forward the
  build/boot; pause on the serial log lines `RT-PROBE BEGIN …` /
  `RT-PROBE SUITE DONE`, then the report appearing.
- **On-screen text:** `./rt-probe run` → "cross-compile → build
  image → boot QNX 8.0 in QEMU → measure → report".
- **Narration:** "One command cross-compiles four probes, builds a
  bootable QNX image, boots it headless in QEMU, and runs the suite
  at startup. About a minute later, the report is ready."

### 2. The report — 0:50–1:20 (30 s)
- **Visual:** `out/report.txt` open; highlight the four probe
  sections and the calibration block (timer overhead p50 20 ns).
- **On-screen text:** "msg 34 µs · wake 19 µs · jitter idle 0.7 ms
  vs load 4.7 ms" + "every run states its own measurement floor".
- **Narration:** "Message round-trip, wake latency, jitter idle
  versus under load — and every run starts with a calibration probe,
  so the report states its own measurement floor."

### 3. The charts — 1:20–1:45 (25 s)
- **Visual:** `out/charts.html` in a browser; scroll through the
  four SVGs, linger on the prio_inversion chart (NONE vs INHERIT
  bars, 3.01× ratio).
- **On-screen text:** "priority inheritance: 301 ms → 100 ms".
- **Narration:** "Every run also renders vector charts. The star
  is priority inheritance: without it the high-priority thread
  waits three times the hold; with it, exactly the hold."

### 4. The honest part — 1:45–2:05 (20 s)
- **Visual:** DESIGN.md "Honest limitations" section on screen.
- **On-screen text:** "QEMU/TCG numbers are indicative — the A/B
  deltas are the signal".
- **Narration:** "These are QEMU numbers, not hardware numbers, and
  the report says so on every run. What travels to real hardware is
  the delta — and `--repeat N` measures the spread."

### 5. The codelab + close — 2:05–2:30 (25 s)
- **Visual:** CODELAB.md open; scroll the 14 steps; end card with
  repo URL + "MIT · QNX Global Hackathon 2026".
- **On-screen text:** "CODELAB.md — headless QNX 8.0 on QEMU
  without KVM, from zero" + repo URL.
- **Narration:** "And the codelab takes you from a bare Linux host
  to a booted QNX guest running this suite. RT-Probe — measure
  first, claim later."

## Recording checklist

- [ ] Terminal: clean font, large enough to read at 1080p; run
      `./rt-probe run` once for real and capture it (do not fake
      the output).
- [ ] Browser: `out/charts.html` from the same run as the report
      shown — numbers on screen must match the report.
- [ ] Keep every number on screen identical to the verified run
      quoted in README.md / DEVPOST-DRAFT.md.
- [ ] Export ≤ 3:00, upload **public** (not unlisted) to YouTube,
      title "RT-Probe — a QNX Real-Time Latency Workbench",
      description links the GitHub repo.
- [ ] Paste the YouTube URL into DEVPOST-DRAFT.md and SUBMISSION.md.
