#!/bin/sh
# run-probes.sh — target-side runner, staged into the QNX image at
# /data/rt-probe/ by scripts/build-image.sh and invoked from
# post_start.custom at the end of system startup.
#
# Runs every probe binary in order; each probe prints RT-PROBE lines to
# the serial console, where the host CLI captures and parses them.
# Per-probe arguments come from the `args` file staged next to this
# script (one line per probe: "<name> <arg>..."), written by
# scripts/build-image.sh from the host CLI flags. When the file is
# absent (e.g. a hand-built image), every probe runs with its
# compiled-in defaults. Positional arguments to this script are ignored.
#
# RTPROBE_DIR overrides the probe directory (used by the host-side unit
# tests with stub binaries; unset on the target, where it is /data/rt-probe).

DIR=${RTPROBE_DIR:-/data/rt-probe}

# probe_args <name> — print that probe's args from $DIR/args, if any.
probe_args() {
    [ -f "$DIR/args" ] || return 0
    while read -r name rest; do
        if [ "$name" = "$1" ]; then
            printf '%s' "$rest"
            return 0
        fi
    done < "$DIR/args"
}

for p in calibration msg_roundtrip wake_latency jitter_load prio_inversion; do
    if [ -x "$DIR/$p" ]; then
        # Word-split the args on purpose: probe_args prints them
        # space-separated, or nothing when the args file is absent.
        # shellcheck disable=SC2086
        "$DIR/$p" $(probe_args "$p")
    else
        echo "RT-PROBE MISSING $p"
    fi
done
echo "RT-PROBE SUITE DONE"
