# Submission checklist — RT-Probe (QNX Global Hackathon 2026)

Deadline: **16 Dec 2026 02:00 WIB** · Devpost: https://qnx.devpost.com/
Category: **Developer Tooling & Host Tools** · Pool $50,000

## Done

- [x] Full build TODOs #1–#7 (live run, args, calibration, `--repeat N`,
      charts, load realism, codelab) — see DESIGN.md
- [x] 91/91 unit tests passing (`./run_tests.sh`)
- [x] MIT LICENSE in repo root
- [x] `.gitignore` (out/, probes/bin/, `__pycache__`, licence/keys,
      build artefacts) — no secrets in the tree (grep-checked)
- [x] README polished as repo front page (verified results, licence)
- [x] Devpost draft fields written — `DEVPOST-DRAFT.md`
- [x] Video script + storyboard written — `VIDEO-SCRIPT.md`
- [x] Local git repo initialised, committed, remote configured
      (`git@github.com:opelphantom96/rt-probe.git`)
- [x] Fresh-clone check from local repo (clone → tests → dry-run)

## Blocked — needs the user / parent agent

- [ ] **Create the empty public GitHub repo `opelphantom96/rt-probe`**
      — the VM has no GitHub API token (`gh` not authenticated, no
      `GH_TOKEN` in env), and repo creation cannot be done over SSH.
      Create it on github.com (New repository → public, no README —
      the tree already has one), then the push is one command:
      `GIT_SSH_COMMAND="ssh -F ~/workspace/qodo-hackathon/ssh-config" git push -u origin master`
      (SSH key already verified: `Hi opelphantom96!`).
- [ ] **Push + verify remote** — after the repo exists: push, then
      `git ls-remote` + a fresh `git clone` from GitHub to confirm
      the remote matches local.
- [ ] **Record + upload the demo video (<3 min, public YouTube)** —
      see `VIDEO-SCRIPT.md`. Needs the user's YouTube account.
- [ ] **Submit on Devpost** — paste the fields from
      `DEVPOST-DRAFT.md` into the form at qnx.devpost.com, attach the
      repo URL + video URL, pick the category, submit before
      16 Dec 2026 02:00 WIB.

## After submitting

- Judging 15–29 Jan 2027; winners ~4 Feb 2027.
- Keep the repo public and the video public until judging ends.
