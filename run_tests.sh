#!/bin/sh
# Run the rt-probe unit test suite (stdlib unittest, no QEMU needed).
# Usage: ./run_tests.sh [-v]
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DIR" || exit 1
exec python3 -m unittest discover -s tests "$@"
