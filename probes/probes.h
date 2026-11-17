/* rt-probe common helpers: cycle timer + machine-parseable output format.
 *
 * Output contract (stdout, one line each):
 *   RT-PROBE BEGIN <name>
 *   RT-PROBE SAMPLE <name> <metric> <value_ns> <seq>
 *   RT-PROBE END <name> <count> <status>
 *
 * The host CLI parses only lines starting with "RT-PROBE"; everything else
 * on the serial console (boot messages, sshd faults, ...) is ignored.
 * Samples are flushed immediately so a killed QEMU session still leaves
 * partial results behind.
 */
#ifndef RTPROBE_H
#define RTPROBE_H

#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdint.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>

static inline uint64_t rp_cycles(void)
{
    return ClockCycles();
}

static inline uint64_t rp_to_ns(uint64_t cycles)
{
    double cps = (double)SYSPAGE_ENTRY(qtime)->cycles_per_sec;
    return (uint64_t)((double)cycles * 1.0e9 / cps);
}

static inline void rp_begin(const char *name)
{
    printf("RT-PROBE BEGIN %s\n", name);
    fflush(stdout);
}

static inline void rp_sample(const char *name, const char *metric,
                             uint64_t value_ns, unsigned seq)
{
    printf("RT-PROBE SAMPLE %s %s %llu %u\n", name, metric,
           (unsigned long long)value_ns, seq);
    fflush(stdout);
}

static inline void rp_end(const char *name, unsigned count, const char *status)
{
    printf("RT-PROBE END %s %u %s\n", name, count, status);
    fflush(stdout);
}

/* Best-effort: pin the calling thread to CPU 0. Returns 0 on success.
 * Failure is harmless (the probe still runs, the SMP caveat in DESIGN.md
 * applies). The runmask is passed as a pointer to an unsigned, per the
 * QNX ThreadCtl API. */
static inline int rp_pin_cpu0(void)
{
    unsigned mask = 0x01u;
    return ThreadCtl(_NTO_TCTL_RUNMASK, &mask);
}

/* Pin the calling thread to CPU 0 AND verify it stuck.
 * Uses _NTO_TCTL_RUNMASK_GET_AND_SET: the pointed-to value is the new
 * mask on entry and the previous mask on return, so calling it twice
 * with 0x01 reads back the effective mask. Prints one machine-readable
 * diagnostic line ("RT-PROBE DIAG pin <who> rc=a/b prev=0x.. cur=0x..
 * ok|FAIL") and returns 0 when the effective mask is CPU 0. The host
 * CLI ignores DIAG lines today (they land in the serial log); they exist
 * so a run can prove whether pinning held instead of guessing. */
static inline int rp_pin_cpu0_diag(const char *who)
{
    unsigned m = 0x01u;
    unsigned m2 = 0x01u;
    unsigned prev = 0;
    unsigned cur = 0;
    int rc1, rc2, ok;

    rc1 = ThreadCtl(_NTO_TCTL_RUNMASK_GET_AND_SET, &m);
    if (rc1 == 0)
        prev = m;
    rc2 = ThreadCtl(_NTO_TCTL_RUNMASK_GET_AND_SET, &m2);
    if (rc2 == 0)
        cur = m2;
    ok = (rc1 == 0 && rc2 == 0 && cur == 0x01u);
    printf("RT-PROBE DIAG pin %s rc=%d/%d prev=0x%x cur=0x%x %s\n",
           who, rc1, rc2, prev, cur, ok ? "ok" : "FAIL");
    fflush(stdout);
    return ok ? 0 : -1;
}

#endif /* RTPROBE_H */
