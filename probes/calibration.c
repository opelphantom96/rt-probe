/* calibration — the timer floor for the suite.
 *
 * Measures the cost of the measurement itself: an empty ClockCycles()
 * pair, back to back, N times. The distribution's p50 is the practical
 * floor — probe samples near or below it are not resolvable, because
 * the timer call itself costs that much. Also reports the timer
 * resolution: the smallest nonzero delta seen (one timer tick, in ns),
 * and cycles_per_sec as a DIAG line.
 *
 * The numbers are raw and honest: under TCG the pair cost is inflated
 * by translation, so the floor on this target is higher than on real
 * hardware. The report shows the floor next to the probe numbers and
 * does NOT subtract it from them.
 *
 * Usage: calibration [iterations]
 * Defaults: iterations=1000.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>
#include "probes.h"

#define PROBE_NAME "calibration"

int main(int argc, char **argv)
{
    unsigned iters = 1000;
    uint64_t min_nonzero = 0;
    unsigned i;

    if (argc > 1)
        iters = (unsigned)strtoul(argv[1], NULL, 10);
    if (iters == 0)
        iters = 1;

    printf("RT-PROBE DIAG calibration cycles_per_sec %llu\n",
           (unsigned long long)SYSPAGE_ENTRY(qtime)->cycles_per_sec);
    fflush(stdout);

    rp_begin(PROBE_NAME);
    for (i = 0; i < iters; i++) {
        uint64_t t0 = rp_cycles();
        uint64_t t1 = rp_cycles();
        uint64_t delta_ns = rp_to_ns(t1 - t0);
        if (delta_ns != 0
            && (min_nonzero == 0 || delta_ns < min_nonzero))
            min_nonzero = delta_ns;
        rp_sample(PROBE_NAME, "timer_overhead_ns", delta_ns, i);
    }
    /* One sample holding the measured resolution (single value, so its
     * summary is the value itself). */
    rp_sample(PROBE_NAME, "timer_resolution_ns", min_nonzero, 0);
    rp_end(PROBE_NAME, iters + 1, "ok");
    return 0;
}
