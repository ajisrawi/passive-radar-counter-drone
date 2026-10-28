/*
 * pcl_streamd: FPGA sample stream -> UDP (Board C: Zynq-7020 PS Gigabit Ethernet).
 *
 * The PL packer emits 1408-byte packets (128 samples, TLAST) on AXI-Stream into a Xilinx AXI DMA (S2MM,
 * scatter-gather). This program owns the DMA from user space:
 *   - DMA registers through UIO (/dev/uioN, "generic-uio" node "pcl-dma"),
 *   - descriptors and packet buffers in one u-dma-buf (/dev/udmabuf0, physically contiguous),
 *   - a ring of NBD descriptors, one packet each, in tail-pointer mode: the engine fills BDs until it reaches
 *     TAILDESC; this loop sends completed packets with sendmmsg() (batches of up to 64), clears their status and
 *     moves TAILDESC behind them.
 * Each UDP datagram = 16-byte header {"PCLS", seq u32, first_sample u64} + 1408-byte payload.
 * first_sample counts from the sample counter latched when streaming was enabled; a ring overrun (engine idle at
 * the tail) is reported on stderr and in the seq gap the host sees.
 *
 * NOT COMPILED IN THE DEVELOPMENT ENVIRONMENT (no C compiler there): build and test on the board,
 *   make && sudo ./pcl_streamd --host 192.168.1.2 --port 50001
 *
 * AXI DMA register / descriptor layout: Xilinx PG021 (AXI DMA v7.1), S2MM channel, 32-bit addresses.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>

#define PKT_BYTES   1408u
#define BUF_STRIDE  1536u            /* per-packet buffer, 64-byte aligned */
#define NBD         4096u            /* 4096 x 1408 B = 5.8 MB = 65 ms of stream at 704 Mbit/s */
#define BATCH       64

/* S2MM registers */
#define S2MM_DMACR      0x30
#define S2MM_DMASR      0x34
#define S2MM_CURDESC    0x38
#define S2MM_TAILDESC   0x40
#define DMACR_RS        (1u << 0)
#define DMACR_RESET     (1u << 2)
#define DMASR_HALTED    (1u << 0)
#define DMASR_IDLE      (1u << 1)
#define DMASR_ERRMASK   0x00007770u

/* SG descriptor (64-byte aligned) */
struct bd {
    volatile uint32_t next, next_msb, buf, buf_msb, rsvd0, rsvd1, control, status;
    volatile uint32_t app[5];
    uint32_t pad[3];
};
#define BD_CMPLT        (1u << 31)
#define BD_LEN_MASK     0x03FFFFFFu

static volatile int stop;
static void on_sig(int s) { (void)s; stop = 1; }

static uint32_t read_u32_file(const char *path, int base)
{
    char b[64] = {0};
    int fd = open(path, O_RDONLY);
    if (fd < 0 || read(fd, b, sizeof b - 1) <= 0) { perror(path); exit(1); }
    close(fd);
    return (uint32_t)strtoul(b, NULL, base);
}

int main(int argc, char **argv)
{
    const char *host = "192.168.1.2", *uio_dma = "/dev/uio1", *udmabuf = "udmabuf0";
    int port = 50001;
    uint64_t sample0 = 0;
    static struct option opts[] = {
        {"host", 1, 0, 'h'}, {"port", 1, 0, 'p'}, {"dma", 1, 0, 'd'}, {"udmabuf", 1, 0, 'u'},
        {"sample0", 1, 0, 's'}, {0, 0, 0, 0}};
    for (int c; (c = getopt_long(argc, argv, "", opts, NULL)) != -1;) {
        if (c == 'h') host = optarg;
        else if (c == 'p') port = atoi(optarg);
        else if (c == 'd') uio_dma = optarg;
        else if (c == 'u') udmabuf = optarg;
        else if (c == 's') sample0 = strtoull(optarg, NULL, 0);
    }
    signal(SIGINT, on_sig);
    signal(SIGTERM, on_sig);

    /* DMA registers */
    int fd_dma = open(uio_dma, O_RDWR | O_SYNC);
    if (fd_dma < 0) { perror(uio_dma); return 1; }
    volatile uint32_t *dma = mmap(NULL, 0x10000, PROT_READ | PROT_WRITE, MAP_SHARED, fd_dma, 0);
    if (dma == MAP_FAILED) { perror("mmap dma"); return 1; }
#define R(o) dma[(o) >> 2]

    /* u-dma-buf: descriptors first, then packet buffers */
    char path[128];
    snprintf(path, sizeof path, "/sys/class/u-dma-buf/%s/phys_addr", udmabuf);
    uint32_t phys = read_u32_file(path, 16);
    snprintf(path, sizeof path, "/sys/class/u-dma-buf/%s/size", udmabuf);
    uint32_t size = read_u32_file(path, 10);
    size_t need = NBD * sizeof(struct bd) + (size_t)NBD * BUF_STRIDE;
    if (size < need) { fprintf(stderr, "%s too small: %u < %zu\n", udmabuf, size, need); return 1; }
    snprintf(path, sizeof path, "/dev/%s", udmabuf);
    int fd_buf = open(path, O_RDWR | O_SYNC);          /* O_SYNC: uncached mapping, no cache maintenance */
    if (fd_buf < 0) { perror(path); return 1; }
    uint8_t *mem = mmap(NULL, need, PROT_READ | PROT_WRITE, MAP_SHARED, fd_buf, 0);
    if (mem == MAP_FAILED) { perror("mmap buf"); return 1; }
    struct bd *bd = (struct bd *)mem;
    uint32_t bd_phys = phys, buf_phys = phys + NBD * sizeof(struct bd);
    uint8_t *buf = mem + NBD * sizeof(struct bd);

    /* reset, build the ring, start */
    R(S2MM_DMACR) = DMACR_RESET;
    for (int i = 0; i < 1000 && (R(S2MM_DMACR) & DMACR_RESET); i++) usleep(10);
    for (uint32_t i = 0; i < NBD; i++) {
        memset((void *)&bd[i], 0, sizeof bd[i]);
        bd[i].next = bd_phys + ((i + 1) % NBD) * sizeof(struct bd);
        bd[i].buf = buf_phys + i * BUF_STRIDE;
        bd[i].control = PKT_BYTES;
    }
    R(S2MM_CURDESC) = bd_phys;
    R(S2MM_DMACR) = DMACR_RS;
    R(S2MM_TAILDESC) = bd_phys + (NBD - 1) * sizeof(struct bd);

    /* UDP */
    int s = socket(AF_INET, SOCK_DGRAM, 0);
    int sndbuf = 8 << 20;
    setsockopt(s, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof sndbuf);
    struct sockaddr_in dst = {.sin_family = AF_INET, .sin_port = htons(port)};
    inet_pton(AF_INET, host, &dst.sin_addr);

    struct hdr { char magic[4]; uint32_t seq; uint64_t first_sample; } __attribute__((packed));
    static struct hdr hdrs[BATCH];
    static struct iovec iov[BATCH][2];
    static struct mmsghdr msgs[BATCH];
    uint32_t head = 0, seq = 0;
    uint64_t sent = 0, overruns = 0;
    time_t t_log = time(NULL);

    while (!stop) {
        int n = 0;
        while (n < BATCH && (bd[(head + n) % NBD].status & BD_CMPLT)) {
            uint32_t k = (head + n) % NBD;
            uint32_t len = bd[k].status & BD_LEN_MASK;
            memcpy(hdrs[n].magic, "PCLS", 4);
            hdrs[n].seq = seq;
            hdrs[n].first_sample = sample0 + (uint64_t)seq * 128u;
            iov[n][0] = (struct iovec){&hdrs[n], sizeof hdrs[n]};
            iov[n][1] = (struct iovec){buf + (size_t)k * BUF_STRIDE, len};
            msgs[n].msg_hdr = (struct msghdr){.msg_name = &dst, .msg_namelen = sizeof dst, .msg_iov = iov[n], .msg_iovlen = 2};
            seq++;
            n++;
        }
        if (n == 0) {
            uint32_t sr = R(S2MM_DMASR);
            if (sr & DMASR_ERRMASK) { fprintf(stderr, "DMA error, DMASR=%08x\n", sr); return 2; }
            if (sr & DMASR_IDLE) overruns++;          /* engine reached the tail: we fell behind */
            usleep(200);
            continue;
        }
        int done = 0;
        while (done < n) {
            int r = sendmmsg(s, msgs + done, n - done, 0);
            if (r < 0) { if (errno == EINTR) continue; perror("sendmmsg"); break; }
            done += r;
        }
        /* recycle: clear status, move the tail to the last recycled BD */
        for (int i = 0; i < n; i++) bd[(head + i) % NBD].status = 0;
        uint32_t last = (head + n - 1) % NBD;
        head = (head + n) % NBD;
        R(S2MM_TAILDESC) = bd_phys + last * sizeof(struct bd);
        sent += n;
        if (time(NULL) != t_log) {
            static uint64_t sent_prev;
            t_log = time(NULL);
            fprintf(stderr, "packets %llu (%.0f Mbit/s payload), overruns %llu\n", (unsigned long long)sent,
                    (double)(sent - sent_prev) * PKT_BYTES * 8.0 / 1e6, (unsigned long long)overruns);
            sent_prev = sent;
        }
    }
    R(S2MM_DMACR) = 0;
    return 0;
}
