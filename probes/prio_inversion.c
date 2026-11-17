/* prio_inversion — classic priority-inversion demo, with and without
 * QNX priority inheritance.
 *
 * Three SCHED_FIFO threads, pinned to CPU 0 when possible:
 *   low  (prio 10): locks the mutex, holds it HOLD_MS, unlocks.
 *   med  (prio 50): CPU hog, started while low holds the lock.
 *   high (prio 100): tries to lock the mutex; measures the wait.
 *
 * The hold is CPU-bound busy work, not a sleep: a sleep-based hold
 * would let low release on a timer expiry even while preempted, hiding
 * the inversion entirely. Busy work only completes when the thread
 * actually gets CPU time, so under PRIO_NONE the medium hog delays the
 * release (high waits ~ hog + hold) while under PRIO_INHERIT low
 * inherits high's priority, preempts med, and releases after ~hold.
 * Each thread prints an RT-PROBE DIAG pin line (ThreadCtl return codes
 * + effective runmask) so a run proves whether pinning held.
 *
 * Protocol A (PTHREAD_PRIO_NONE): med preempts low, so high waits until
 *   low is rescheduled — long wait (inversion).
 * Protocol B (PTHREAD_PRIO_INHERIT): low inherits high's priority while
 *   high waits, preempts med, releases quickly — short wait.
 * Each protocol runs ROUNDS rounds; one sample per round.
 *
 * SMP caveat (see DESIGN.md): on the 2-CPU guest the hog may run on the
 * second CPU and the inversion may not reproduce. All three threads are
 * pinned to CPU 0 (diagnosed, not assumed); if pinning fails the probe
 * still reports what it measured, and the DIAG lines say so. The CLI
 * also offers --smp 1, which removes the second CPU entirely.
 *
 * Usage: prio_inversion [rounds] [hold_ms]
 * Defaults: rounds=5, hold_ms=200.
 */
#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <time.h>
#include <sys/neutrino.h>
#include "probes.h"

#define PROBE_NAME "prio_inversion"
#define PRIO_LOW 10
#define PRIO_MED 50
#define PRIO_HIGH 100

static pthread_mutex_t g_mtx;
static sem_t g_low_locked, g_med_go, g_high_go;
static volatile uint64_t g_high_wait_ns;
static long g_hold_ms;

/* Busy-wait for `ms` milliseconds of CPU time. Deliberate: a
 * sleep-based hold would let the low thread release on a timer expiry
 * even while preempted, hiding the inversion. Busy work only completes
 * when the thread actually gets CPU time. */
static void busy_hold_ms(long ms)
{
    uint64_t cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec;
    uint64_t budget = (uint64_t)ms * (cps / 1000u);
    uint64_t start = rp_cycles();
    volatile unsigned long x = 0;

    while (rp_cycles() - start < budget)
        x += 1;
    (void)x;
}

static void *low_thread(void *arg)
{
    (void)arg;
    (void)rp_pin_cpu0_diag("low");
    pthread_mutex_lock(&g_mtx);
    sem_post(&g_low_locked);
    /* Hold the lock for HOLD_MS of CPU time (busy work, not sleep). */
    busy_hold_ms(g_hold_ms);
    pthread_mutex_unlock(&g_mtx);
    return NULL;
}

static void *med_thread(void *arg)
{
    struct timespec end, now;
    volatile unsigned long x = 0;

    (void)arg;
    (void)rp_pin_cpu0_diag("med");
    sem_wait(&g_med_go);
    /* Hog the CPU for HOLD_MS + 100 ms. */
    clock_gettime(CLOCK_MONOTONIC, &end);
    end.tv_sec += (g_hold_ms + 100) / 1000;
    end.tv_nsec += ((g_hold_ms + 100) % 1000) * 1000000L;
    if (end.tv_nsec >= 1000000000L) {
        end.tv_sec += 1;
        end.tv_nsec -= 1000000000L;
    }
    for (;;) {
        x += 1;
        clock_gettime(CLOCK_MONOTONIC, &now);
        if (now.tv_sec > end.tv_sec ||
            (now.tv_sec == end.tv_sec && now.tv_nsec >= end.tv_nsec))
            break;
    }
    return (void *)x;
}

static void *high_thread(void *arg)
{
    (void)arg;
    (void)rp_pin_cpu0_diag("high");
    sem_wait(&g_high_go);
    {
        uint64_t t0 = rp_cycles();
        pthread_mutex_lock(&g_mtx);
        uint64_t t1 = rp_cycles();
        g_high_wait_ns = rp_to_ns(t1 - t0);
        pthread_mutex_unlock(&g_mtx);
    }
    return NULL;
}

static int make_thread(pthread_t *tid, void *(*fn)(void *), void *arg,
                       int prio)
{
    pthread_attr_t attr;
    struct sched_param sp;
    int rc;

    pthread_attr_init(&attr);
    pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
    pthread_attr_setschedpolicy(&attr, SCHED_FIFO);
    sp.sched_priority = prio;
    pthread_attr_setschedparam(&attr, &sp);
    rc = pthread_create(tid, &attr, fn, arg);
    pthread_attr_destroy(&attr);
    return rc;
}

static int run_protocol(int protocol, const char *metric, unsigned rounds)
{
    unsigned r;

    for (r = 0; r < rounds; r++) {
        pthread_mutexattr_t mattr;
        pthread_t low, med, high;

        pthread_mutexattr_init(&mattr);
        pthread_mutexattr_setprotocol(&mattr, protocol);
        pthread_mutex_init(&g_mtx, &mattr);
        pthread_mutexattr_destroy(&mattr);

        sem_init(&g_low_locked, 0, 0);
        sem_init(&g_med_go, 0, 0);
        sem_init(&g_high_go, 0, 0);
        g_high_wait_ns = 0;

        if (make_thread(&low, low_thread, NULL, PRIO_LOW) != 0 ||
            make_thread(&med, med_thread, NULL, PRIO_MED) != 0 ||
            make_thread(&high, high_thread, NULL, PRIO_HIGH) != 0) {
            perror("pthread_create");
            return -1;
        }

        sem_wait(&g_low_locked); /* low holds the mutex now */
        sem_post(&g_med_go);
        sem_post(&g_high_go);

        pthread_join(high, NULL);
        pthread_join(low, NULL);
        pthread_join(med, NULL);

        rp_sample(PROBE_NAME, metric, g_high_wait_ns, r);

        sem_destroy(&g_low_locked);
        sem_destroy(&g_med_go);
        sem_destroy(&g_high_go);
        pthread_mutex_destroy(&g_mtx);
    }
    return 0;
}

int main(int argc, char **argv)
{
    unsigned rounds = 5;
    int rc = 0;
    int orig_policy;
    struct sched_param orig_sp;

    g_hold_ms = 200;
    if (argc > 1)
        rounds = (unsigned)strtoul(argv[1], NULL, 10);
    if (argc > 2)
        g_hold_ms = strtol(argv[2], NULL, 10);
    if (rounds == 0)
        rounds = 1;
    if (g_hold_ms <= 0)
        g_hold_ms = 200;

    /* The coordinator (main) must be able to preempt the spinning low
     * thread to post the go signals promptly. On a single-CPU guest
     * main (default prio 10) starves behind low (prio 10, spinning,
     * never blocking) and posts after low already released, so high
     * never blocks and the demo measures ~0 in both protocols. Run the
     * coordination at FIFO 60 (above low 10 and med 50, below high
     * 100) and restore the original scheduling afterwards. */
    orig_policy = sched_getscheduler(0);
    sched_getparam(0, &orig_sp);
    {
        struct sched_param sp;
        sp.sched_priority = 60;
        pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    }

    rp_begin(PROBE_NAME);
    if (run_protocol(PTHREAD_PRIO_NONE, "inversion_wait_none_ns", rounds) != 0) {
        rp_end(PROBE_NAME, 0, "error");
        rc = 1;
        goto out;
    }
    if (run_protocol(PTHREAD_PRIO_INHERIT, "inversion_wait_inherit_ns", rounds) != 0) {
        rp_end(PROBE_NAME, rounds, "error");
        rc = 1;
        goto out;
    }
    rp_end(PROBE_NAME, 2 * rounds, "ok");
out:
    pthread_setschedparam(pthread_self(), orig_policy, &orig_sp);
    return rc;
}
