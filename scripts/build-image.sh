#!/usr/bin/env bash
# build-image.sh — RT-Probe image integration.
#
# Cross-compiles the probe suite with qcc, stages the binaries into a
# fresh mkqnximage directory, and builds the QEMU image.
#
# Integration mechanism (verified against mkqnximage 8.0):
#  * mkqnximage searches the image dir's `local/` tree for snippet files.
#  * `local/snippets/data_files.custom` is included verbatim into
#    data.build; entries use mkfs build syntax
#    "[uid=0 gid=0 perms=755] <dest>=<source>", source relative to the
#    image dir. The data partition is mounted at /data, so
#    `rt-probe/msg_roundtrip` lands at /data/rt-probe/msg_roundtrip.
#  * `local/snippets/post_start.custom` is included into post_startup.sh
#    and runs at the END of system startup (filesystems mounted, serial
#    console live) — the right hook. (ifs_start.custom runs BEFORE
#    startup.sh, i.e. before /data is mounted, so it must NOT be used.)
#
# Usage: scripts/build-image.sh [workdir]
#   workdir defaults to $QNX_ROOT/rt-probe-image (QNX_ROOT defaults to
#   ~/workspace/qnx). The workdir is wiped and recreated; mkqnximage
#   refuses a non-empty directory without --force.
#
# No secrets are used or printed by this script. It sources the SDP
# environment script only.

set -euo pipefail

QNX_ROOT="${QNX_ROOT:-$HOME/workspace/qnx}"
RT_PROBE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="${1:-$QNX_ROOT/rt-probe-image}"

source "$QNX_ROOT/qnx800/qnxsdp-env.sh"

echo "== 1. Cross-compile probes =="
make -C "$RT_PROBE_DIR/probes"

echo "== 2. Fresh image dir: $WORKDIR =="
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR/local/rt-probe" "$WORKDIR/local/snippets"

echo "== 3. Stage probe binaries =="
cp "$RT_PROBE_DIR/probes/bin/calibration" \
   "$RT_PROBE_DIR/probes/bin/msg_roundtrip" \
   "$RT_PROBE_DIR/probes/bin/wake_latency" \
   "$RT_PROBE_DIR/probes/bin/jitter_load" \
   "$RT_PROBE_DIR/probes/bin/prio_inversion" \
   "$RT_PROBE_DIR/probes/run-probes.sh" \
   "$WORKDIR/local/rt-probe/"
chmod 755 "$WORKDIR/local/rt-probe/"*

echo "== 3b. Probe arguments (from RTPROBE_ARGS_* env) =="
# One line per probe in the args file staged into the image; the
# target-side runner passes each line to its probe (see
# probes/run-probes.sh). Only lines with a value are written.
{
    for p in calibration msg_roundtrip wake_latency jitter_load prio_inversion; do
        var="RTPROBE_ARGS_$(printf '%s' "$p" | tr 'a-z' 'A-Z')"
        val="${!var:-}"
        if [ -n "$val" ]; then
            printf '%s %s\n' "$p" "$val"
        fi
    done
} > "$WORKDIR/local/rt-probe/args"
cat "$WORKDIR/local/rt-probe/args"

echo "== 4. mkqnximage snippets (data partition + startup hook) =="
cat > "$WORKDIR/local/snippets/data_files.custom" <<'EOF'
# rt-probe: probe binaries + runner, added to the data partition
# (mounted at /data at runtime).
[uid=0 gid=0 perms=755] rt-probe/calibration=local/rt-probe/calibration
[uid=0 gid=0 perms=755] rt-probe/msg_roundtrip=local/rt-probe/msg_roundtrip
[uid=0 gid=0 perms=755] rt-probe/wake_latency=local/rt-probe/wake_latency
[uid=0 gid=0 perms=755] rt-probe/jitter_load=local/rt-probe/jitter_load
[uid=0 gid=0 perms=755] rt-probe/prio_inversion=local/rt-probe/prio_inversion
[uid=0 gid=0 perms=755] rt-probe/run-probes.sh=local/rt-probe/run-probes.sh
[uid=0 gid=0 perms=644] rt-probe/args=local/rt-probe/args
EOF
cat > "$WORKDIR/local/snippets/post_start.custom" <<'EOF'
# rt-probe: run the probe suite at the end of system startup.
# Output goes to the serial console, where the host CLI captures it.
/data/rt-probe/run-probes.sh
EOF

echo "== 5. Build image =="
cd "$WORKDIR"
mkqnximage --type=qemu --arch=x86_64

echo "== 6. Verify outputs =="
test -f "$WORKDIR/output/ifs.bin"
test -f "$WORKDIR/output/disk-qemu.vmdk"
echo "IMAGE OK"
echo "kernel: $WORKDIR/output/ifs.bin"
echo "disk:   $WORKDIR/output/disk-qemu.vmdk"
