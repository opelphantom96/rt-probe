# RT-Probe target probes — cross-compile with qcc (QNX SDP 8.0).
#
# Requires the SDP environment: source ~/workspace/qnx/qnx800/qnxsdp-env.sh
# first (sets QNX_HOST / QNX_TARGET). The host CLI and build-image.sh do
# this for you; run `make` directly only after sourcing the env script.

QCC ?= qcc
TARGET ?= gcc_ntox86_64
CFLAGS ?= -O2 -Wall -Wextra
BIN_DIR = bin

PROBES = calibration msg_roundtrip wake_latency jitter_load prio_inversion
BINS = $(PROBES:%=$(BIN_DIR)/%)

all: $(BINS)

$(BIN_DIR):
	mkdir -p $(BIN_DIR)

$(BIN_DIR)/%: %.c probes.h | $(BIN_DIR)
	$(QCC) -V $(TARGET) $(CFLAGS) -o $@ $<

check-env:
ifndef QNX_TARGET
	$(error QNX_TARGET is not set — source ~/workspace/qnx/qnx800/qnxsdp-env.sh first)
endif

clean:
	rm -rf $(BIN_DIR)

.PHONY: all clean check-env
