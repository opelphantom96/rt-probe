"""Tests for CODELAB.md consistency with the code it documents.

The codelab is a promise that its commands work. These tests keep the
promise honest without booting QEMU:
  * every `./rt-probe ...` command in a fenced bash block must parse
    against the real CLI argument parser;
  * the manual QEMU command in the codelab must match the argv the CLI
    builds (modulo the file paths, which are relative in the codelab
    and absolute in the CLI);
  * the required sections must be present.
No QEMU is launched and no image is built.
"""

import os
import re
import shlex
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtprobe import cli as cli_mod
from rtprobe import config as config_mod
from rtprobe import qemu as qemu_mod

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODELAB = os.path.join(REPO_DIR, "CODELAB.md")

REQUIRED_HEADINGS = (
    "## Step 0 — Get the code",
    "## Step 1 — Check your host",
    "## Step 2 — Install QEMU",
    "## Step 3 — myQNX account and the QNX Everywhere licence",
    "## Step 4 — Install SDP 8.0 (unattended)",
    "## Step 5 — Prove the cross-compiler works",
    "## Step 6 — Build a bare QNX image with mkqnximage",
    "## Step 7 — Look at the plan before you run it",
    "## Step 8 — Build the RT-Probe image",
    "## Step 9 — Boot it by hand",
    "## Step 10 — Run the suite the easy way",
    "## Step 11 — Read the report",
    "## Step 12 — Repeatability: one run is not a statistic",
    "## Step 13 — What the numbers mean, and what they don't",
    "## Troubleshooting",
    "## Verification note — what was checked, and what was not",
)


def _fenced_bash_blocks(text):
    """Yield the bodies of ```bash fenced blocks."""
    return re.findall(r"```bash\n(.*?)```", text, re.DOTALL)


def _rtprobe_commands(text):
    """(line, argv) for every ./rt-probe invocation in bash blocks."""
    commands = []
    for block in _fenced_bash_blocks(text):
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("./rt-probe"):
                commands.append((stripped, shlex.split(stripped)))
    return commands


def _manual_qemu_argv(text):
    """The qemu-system-x86_64 command from the Step 9 block, joined."""
    for block in _fenced_bash_blocks(text):
        if "qemu-system-x86_64" in block and "-kernel" in block:
            joined = block.replace("\\\n", " ")
            for line in joined.splitlines():
                stripped = line.strip()
                if stripped.startswith("timeout "):
                    tokens = shlex.split(stripped)
                    # drop `timeout N` and anything after a redirect
                    tokens = tokens[2:]
                    if ">" in tokens:
                        tokens = tokens[:tokens.index(">")]
                    return tokens
    return None


def _normalize_qemu_argv(argv):
    """Replace filesystem paths with PATH so relative (codelab) and
    absolute (CLI) argv compare equal."""
    out = []
    for tok in argv:
        if "=" in tok:
            key, _val = tok.split("=", 1)
            out.append(key + "=PATH" if "/" in _val else tok)
        elif "/" in tok:
            out.append("PATH")
        else:
            out.append(tok)
    return out


class TestCodelab(unittest.TestCase):
    def setUp(self):
        with open(CODELAB, encoding="utf-8") as fh:
            self.text = fh.read()

    def test_required_sections_present(self):
        for heading in REQUIRED_HEADINGS:
            with self.subTest(heading=heading):
                self.assertIn(heading, self.text)

    def test_rtprobe_commands_parse(self):
        commands = _rtprobe_commands(self.text)
        self.assertGreater(len(commands), 0,
                           "no ./rt-probe commands found in CODELAB.md")
        parser = cli_mod.build_parser()
        for line, argv in commands:
            with self.subTest(command=line):
                try:
                    parser.parse_args(argv[1:])
                except SystemExit as exc:
                    self.fail("./rt-probe command does not parse "
                              "against the real CLI (%s): %s"
                              % (exc.code, line))

    def test_manual_qemu_argv_matches_cli(self):
        argv = _manual_qemu_argv(self.text)
        self.assertIsNotNone(argv, "no manual QEMU command in CODELAB.md")
        expected = _normalize_qemu_argv(
            qemu_mod.build_qemu_argv(config_mod.Config(), ""))
        self.assertEqual(_normalize_qemu_argv(argv), expected)

    def test_codelab_names_the_licence_rule(self):
        self.assertIn("~/.qnx/license/licenses", self.text)
        self.assertIn("Never move, copy, or print the licence file",
                      self.text)

    def test_codelab_states_what_was_not_reverified(self):
        self.assertIn("Not re-verified from scratch", self.text)


if __name__ == "__main__":
    unittest.main()
