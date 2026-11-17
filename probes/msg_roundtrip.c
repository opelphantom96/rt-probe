/* msg_roundtrip — QNX native message-passing round-trip latency.
 *
 * A server thread owns a channel and replies immediately to every message.
 * The client (main thread) sends N messages and measures send->reply
 * round-trip time with ClockCycles(). Warmup iterations are discarded.
 *
 * Usage: msg_roundtrip [iterations] [warmup]
 * Defaults: iterations=200, warmup=100.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <semaphore.h>
#include <sys/neutrino.h>
#include "probes.h"

#define PROBE_NAME "msg_roundtrip"

static int g_chid = -1;
static sem_t g_ready;

static void *server_thread(void *arg)
{
    char msg[64];

    (void)arg;
    for (;;) {
        int rcvid = MsgReceive(g_chid, msg, sizeof(msg), NULL);
        if (rcvid == -1)
            break; /* channel destroyed -> exit */
        if (rcvid == 0)
            continue; /* pulse, ignore */
        MsgReply(rcvid, EOK, msg, sizeof(msg));
    }
    return NULL;
}

int main(int argc, char **argv)
{
    unsigned iters = 200, warmup = 100;
    pthread_t server;
    int coid;
    char msg[64], reply[64];
    unsigned i;

    if (argc > 1)
        iters = (unsigned)strtoul(argv[1], NULL, 10);
    if (argc > 2)
        warmup = (unsigned)strtoul(argv[2], NULL, 10);
    if (iters == 0)
        iters = 1;

    memset(msg, 0x5a, sizeof(msg));
    sem_init(&g_ready, 0, 0);

    g_chid = ChannelCreate(0);
    if (g_chid == -1) {
        perror("ChannelCreate");
        return 1;
    }
    if (pthread_create(&server, NULL, server_thread, NULL) != 0) {
        perror("pthread_create(server)");
        return 1;
    }

    coid = ConnectAttach(ND_LOCAL_NODE, getpid(), g_chid,
                         _NTO_SIDE_CHANNEL, 0);
    if (coid == -1) {
        perror("ConnectAttach");
        return 1;
    }

    rp_begin(PROBE_NAME);
    for (i = 0; i < warmup + iters; i++) {
        uint64_t t0 = rp_cycles();
        if (MsgSend(coid, msg, sizeof(msg), reply, sizeof(reply)) == -1) {
            perror("MsgSend");
            rp_end(PROBE_NAME, i, "error");
            return 1;
        }
        uint64_t t1 = rp_cycles();
        if (i >= warmup)
            rp_sample(PROBE_NAME, "roundtrip_ns", rp_to_ns(t1 - t0),
                      i - warmup);
    }
    rp_end(PROBE_NAME, iters, "ok");

    ConnectDetach(coid);
    ChannelDestroy(g_chid);
    pthread_join(server, NULL);
    sem_destroy(&g_ready);
    return 0;
}
