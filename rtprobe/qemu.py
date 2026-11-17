"""QEMU image build + run for rt-probe.

The QEMU command below is the exact one proven to boot QNX 8.0.0 to
"Startup complete" under TCG on this VM (see ~/workspace/qnx/README.md):
the kernel is loaded directly with -kernel output/ifs.bin. Booting from
the disk (SeaBIOS -> QNX boot loader) crawls under TCG and is NOT used.
"""

import os
import select
import subprocess
import time


def image_paths(image_dir):
    """Paths of the mkqnximage outputs for an image directory."""
    out = os.path.join(image_dir, "output")
    return {
        "ifs_bin": os.path.join(out, "ifs.bin"),
        "disk_vmdk": os.path.join(out, "disk-qemu.vmdk"),
        "disk_raw": os.path.join(out, "disk-qemu"),
        "pid_file": os.path.join(out, "qemu.pid"),
    }


def build_qemu_argv(cfg, image_dir):
    """Exact QEMU argv for one headless run (no network device)."""
    paths = image_paths(image_dir)
    return [
        "qemu-system-x86_64",
        "-smp", str(cfg.qemu_smp),
        "--cpu", "max",
        "-m", str(cfg.qemu_mem_mb),
        "-drive", "file=%s,if=ide,id=drv0" % paths["disk_vmdk"],
        "-pidfile", paths["pid_file"],
        "-nographic",
        "-kernel", paths["ifs_bin"],
        "-serial", "mon:stdio",
        "-object", "rng-random,filename=/dev/urandom,id=rng0",
        "-device", "virtio-rng-pci,rng=rng0",
    ]


def boot_ok(output):
    """True when the serial log shows QNX booted far enough to run the
    suite. Accepts any of:
      * "Startup complete" (the literal boot message), or
      * "RT-PROBE SUITE DONE" (the suite ran, so boot completed), or
      * "Starting misc" (the mkqnximage qemu image reaches this point
        in post-startup; the literal "Startup complete" string never
        appears on its serial console, so requiring it warns on every
        successful run).
    """
    return ("Startup complete" in output
            or "RT-PROBE SUITE DONE" in output
            or "Starting misc" in output)


def run_qemu(argv, timeout_s, marker=None, poll_interval=0.5):
    """Run QEMU, streaming stdout until the marker, exit, or timeout.

    Returns (timed_out, output). When the marker line appears the
    process is terminated early (the suite is done; no need to wait for
    the full timeout). On timeout the process is killed and whatever was
    captured so far is returned.

    The pipe is read unbuffered with os.read: a buffered text reader
    would swallow lines into its internal buffer where select() cannot
    see them, so a marker could sit undelivered until the timeout.
    """
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL,
                            text=False, bufsize=0)
    fd = proc.stdout.fileno()
    buf = bytearray()
    chunks = []
    start = time.monotonic()
    timed_out = False

    def _drain_lines(final=False):
        """Split complete lines out of buf into chunks. Returns True
        when the marker was seen in a complete line."""
        nonlocal buf
        while True:
            idx = buf.find(b"\n")
            if idx < 0:
                break
            line = bytes(buf[:idx + 1])
            del buf[:idx + 1]
            chunks.append(line.decode("utf-8", errors="replace"))
            if marker and marker in chunks[-1]:
                return True
        if final and buf:
            chunks.append(bytes(buf).decode("utf-8", errors="replace"))
            buf = bytearray()
        return False

    try:
        while True:
            if proc.poll() is not None:
                # Process exited: drain whatever is left in the pipe.
                while True:
                    rlist, _, _ = select.select([fd], [], [], 0.2)
                    if not rlist:
                        break
                    try:
                        data = os.read(fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    buf += data
                    if _drain_lines():
                        break
                _drain_lines(final=True)
                break
            rlist, _, _ = select.select([fd], [], [], poll_interval)
            if rlist:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    data = b""
                if not data:
                    _drain_lines(final=True)
                    break  # EOF
                buf += data
                if _drain_lines():
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    break
            if time.monotonic() - start > timeout_s:
                timed_out = True
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                # Best-effort drain of what is already in the pipe.
                while True:
                    rlist, _, _ = select.select([fd], [], [], 0.2)
                    if not rlist:
                        break
                    try:
                        data = os.read(fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    buf += data
                _drain_lines(final=True)
                break
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.stdout.close()
        except Exception:
            pass
    return timed_out, "".join(chunks)


def build_image_env(cfg):
    """Environment for scripts/build-image.sh.

    Carries QNX_ROOT plus one RTPROBE_ARGS_<PROBE> variable per probe,
    which the script turns into the target-side args file staged into
    the image (see scripts/build-image.sh).
    """
    env = dict(os.environ)
    env["QNX_ROOT"] = cfg.qnx_root
    for name, argv in cfg.probe_args().items():
        env["RTPROBE_ARGS_" + name.upper()] = " ".join(argv)
    return env


def build_image(cfg):
    """Run scripts/build-image.sh for cfg.workdir.

    Returns (returncode, combined output). The script sources the SDP
    environment itself; QNX_ROOT is passed through the environment.
    """
    proc = subprocess.run([cfg.build_image_script, cfg.workdir],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, env=build_image_env(cfg))
    return proc.returncode, proc.stdout
