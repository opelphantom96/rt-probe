/* jitter_load — periodic-thread jitter, idle vs under realistic load.
 *
 * A SCHED_FIFO thread wakes every `period_ms` (clock_nanosleep,
 * TIMER_ABSTIME, CLOCK_MONOTONIC) and records the deviation of its actual
 * wake time from the ideal schedule. Two phases:
 *   idle: no other load running.
 *   load: two busy-spin threads (SCHED_FIFO, lower priority) saturate
 *         the CPUs, PLUS two memory-streamer threads sweeping their own
 *         `mem_mb` MiB buffers at a 64-byte stride (one cache line per
 *         access). The spinners alone only contend for CPU time: a
 *         higher-priority periodic thread preempts them and keeps its
 *         own cache lines resident. The streamers are what make the
 *         load realistic — they evict the periodic thread's working
 *         set between periods and contend for memory bandwidth, so
 *         each wake pays cache-refill costs the way it would on a
 *         loaded system. The first `skip` periods of each phase are
 *         discarded (timer warmup).
 * Metric: jitter_ns = |actual - expected| per period.
 *
 * Usage: jitter_load [period_ms] [iterations_per_phase] [skip] [mem_mb]
 * Defaults: period_ms=10, iterations=100, skip=10, mem_mb=64
 * (mem_mb=0 disables the streamers: CPU spinners only, the pre-TODO-#6
 * behaviour, for A/B comparison). Buffers are allocated once before
 * the idle phase and fully written (memset) so no page fault lands
 * inside a measured phase; the size and pattern are fixed and
 * deterministic, and the total (2 x mem_mb MiB) is bounded.
 */
#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <sys/neutrino.h>
#include "probes.h"

#define PROBE_NAME "jitter_load"
#define PERIODIC_PRIO 80
#define LOAD_PRIO 70
#define STREAM_STRIDE 64        /* one cache line per access */

static volatile int g_stop;
static size_t g_stream_bytes;   /* bytes per streamer buffer */

/* One cache line (64 B) per access, sequential sweep, wrap around.
 * The volatile sink keeps the compiler from eliding the reads; the
 * returned value is the checksum, discarded by the caller. */
static void *streamer_thread(void *arg)
{
    uint8_t *buf = (uint8_t *)arg;
    uint8_t *p = buf;
    volatile uint64_t sink = 0;

    (void)rp_pin_cpu0();
    while (!g_stop) {
        sink += *(volatile uint64_t *)p;
        p += STREAM_STRIDE;
        if (p >= buf + g_stream_bytes)
            p = buf;
    }
    return (void *)(uintptr_t)sink;
}

static int64_t ts_to_ns(const struct timespec *ts)
{
    return (int64_t)ts->tv_sec * 1000000000LL + (int64_t)ts->tv_nsec;
}

static void ts_add_ns(struct timespec *ts, int64_t ns)
{
    ts->tv_sec += ns / 1000000000LL;
    ts->tv_nsec += ns % 1000000000LL;
    if (ts->tv_nsec >= 1000000000LL) {
        ts->tv_sec += 1;
        ts->tv_nsec -= 1000000000LL;
    }
}

static void *spinner_thread(void *arg)
{
    volatile unsigned long x = 0;

    (void)arg;
    (void)rp_pin_cpu0();
    while (!g_stop)
        x += 1;
    return (void *)x;
}

static int run_phase(const char *metric, unsigned iters, unsigned skip,
                     long period_ns)
{
    struct timespec next, now;
    unsigned i;

    clock_gettime(CLOCK_MONOTONIC, &next);
    for (i = 0; i < iters; i++) {
        ts_add_ns(&next, period_ns);
        if (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL) != 0)
            return -1;
        clock_gettime(CLOCK_MONOTONIC, &now);
        if (i >= skip) {
            int64_t dev = ts_to_ns(&now) - ts_to_ns(&next);
            if (dev < 0)
                dev = -dev;
            rp_sample(PROBE_NAME, metric, (uint64_t)dev, i - skip);
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    long period_ms = 10, period_ns;
    long mem_mb = 64;
    unsigned iters = 100, skip = 10;
    pthread_t load1, load2, stream1, stream2;
    uint8_t *buf1 = NULL, *buf2 = NULL;
    unsigned n_streamers = 0;
    pthread_attr_t attr;
    struct sched_param sp;

    if (argc > 1)
        period_ms = strtol(argv[1], NULL, 10);
    if (argc > 2)
        iters = (unsigned)strtoul(argv[2], NULL, 10);
    if (argc > 3)
        skip = (unsigned)strtoul(argv[3], NULL, 10);
    if (argc > 4)
        mem_mb = strtol(argv[4], NULL, 10);
    if (period_ms <= 0)
        period_ms = 10;
    if (iters == 0)
        iters = 1;
    if (skip >= iters)
        skip = 0;
    if (mem_mb < 0)
        mem_mb = 0;
    period_ns = period_ms * 1000000L;

    (void)rp_pin_cpu0();

    /* Memory load: one private buffer per streamer, allocated and
     * pre-touched before any measurement so page faults never land
     * inside a phase. On allocation failure the probe degrades to
     * spinners only (noted in the DIAG line) instead of failing:
     * the jitter samples must still be produced. */
    if (mem_mb > 0) {
        g_stream_bytes = (size_t)mem_mb * 1024u * 1024u;
        buf1 = malloc(g_stream_bytes);
        buf2 = buf1 ? malloc(g_stream_bytes) : NULL;
        if (buf1 && buf2) {
            n_streamers = 2;
            /* memset faults every page in now, so no page fault
             * lands inside a measured phase. */
            memset(buf1, 0, g_stream_bytes);
            memset(buf2, 0, g_stream_bytes);
        } else {
            free(buf1);
            free(buf2);
            buf1 = buf2 = NULL;
        }
    }
    printf("RT-PROBE DIAG jitter_load mem_mb=%ld stride=%dB "
           "streamers=%u spinners=2%s\n",
           mem_mb, STREAM_STRIDE, n_streamers,
           (mem_mb > 0 && n_streamers == 0) ? " mem_alloc_failed" : "");
    fflush(stdout);

    /* The periodic work runs inline in main (SCHED_FIFO 80) so the
     * measurement thread itself is the highest-priority thread. */
    pthread_attr_init(&attr);
    pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
    pthread_attr_setschedpolicy(&attr, SCHED_FIFO);
    sp.sched_priority = PERIODIC_PRIO;
    pthread_attr_setschedparam(&attr, &sp);
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    pthread_attr_destroy(&attr);

    rp_begin(PROBE_NAME);

    if (run_phase("jitter_idle_ns", iters, skip, period_ns) != 0) {
        rp_end(PROBE_NAME, 0, "error");
        return 1;
    }

    /* Load phase: two spinners (CPU saturation) plus two streamers
     * (cache/memory pressure), all lower priority than us. */
    g_stop = 0;
    pthread_attr_init(&attr);
    pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
    pthread_attr_setschedpolicy(&attr, SCHED_FIFO);
    sp.sched_priority = LOAD_PRIO;
    pthread_attr_setschedparam(&attr, &sp);
    pthread_create(&load1, &attr, spinner_thread, NULL);
    pthread_create(&load2, &attr, spinner_thread, NULL);
    if (n_streamers == 2) {
        pthread_create(&stream1, &attr, streamer_thread, buf1);
        pthread_create(&stream2, &attr, streamer_thread, buf2);
    }
    pthread_attr_destroy(&attr);

    if (run_phase("jitter_load_ns", iters, skip, period_ns) != 0) {
        g_stop = 1;
        pthread_join(load1, NULL);
        pthread_join(load2, NULL);
        if (n_streamers == 2) {
            pthread_join(stream1, NULL);
            pthread_join(stream2, NULL);
        }
        free(buf1);
        free(buf2);
        rp_end(PROBE_NAME, 0, "error");
        return 1;
    }
    g_stop = 1;
    pthread_join(load1, NULL);
    pthread_join(load2, NULL);
    if (n_streamers == 2) {
        pthread_join(stream1, NULL);
        pthread_join(stream2, NULL);
    }
    free(buf1);
    free(buf2);

    rp_end(PROBE_NAME, 2 * (iters - skip), "ok");
    return 0;
}
