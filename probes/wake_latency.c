/* wake_latency — semaphore wake latency.
 *
 * A waiter thread (SCHED_FIFO, priority 100) blocks on sem_wait().
 * The main thread records t0, posts the semaphore, and the waiter records
 * t1 immediately after sem_wait() returns, handing it back through a second
 * semaphore. Sample = t1 - t0, i.e. the time from "wake requested" to
 * "woken thread running again". Warmup iterations are discarded.
 *
 * Usage: wake_latency [iterations] [warmup]
 * Defaults: iterations=200, warmup=100.
 */
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <sys/neutrino.h>
#include "probes.h"

#define PROBE_NAME "wake_latency"
#define WAITER_PRIO 100

static sem_t g_go, g_done;
static volatile uint64_t g_wake_cycles;

static void *waiter_thread(void *arg)
{
    unsigned iters = *(unsigned *)arg;

    (void)rp_pin_cpu0();
    for (unsigned i = 0; i < iters; i++) {
        sem_wait(&g_go);
        g_wake_cycles = rp_cycles();
        sem_post(&g_done);
    }
    return NULL;
}

int main(int argc, char **argv)
{
    unsigned iters = 200, warmup = 100, total;
    pthread_t waiter;
    pthread_attr_t attr;
    struct sched_param sp;

    if (argc > 1)
        iters = (unsigned)strtoul(argv[1], NULL, 10);
    if (argc > 2)
        warmup = (unsigned)strtoul(argv[2], NULL, 10);
    if (iters == 0)
        iters = 1;
    total = warmup + iters;

    sem_init(&g_go, 0, 0);
    sem_init(&g_done, 0, 0);

    pthread_attr_init(&attr);
    pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
    pthread_attr_setschedpolicy(&attr, SCHED_FIFO);
    sp.sched_priority = WAITER_PRIO;
    pthread_attr_setschedparam(&attr, &sp);
    if (pthread_create(&waiter, &attr, waiter_thread, &total) != 0) {
        perror("pthread_create(waiter)");
        return 1;
    }
    pthread_attr_destroy(&attr);

    rp_begin(PROBE_NAME);
    for (unsigned i = 0; i < total; i++) {
        uint64_t t0 = rp_cycles();
        sem_post(&g_go);
        sem_wait(&g_done);
        if (i >= warmup)
            rp_sample(PROBE_NAME, "wake_ns", rp_to_ns(g_wake_cycles - t0),
                      i - warmup);
    }
    rp_end(PROBE_NAME, iters, "ok");

    pthread_join(waiter, NULL);
    sem_destroy(&g_go);
    sem_destroy(&g_done);
    return 0;
}
