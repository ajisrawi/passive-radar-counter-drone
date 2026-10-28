"""Access to the PL core (firmware/hdl/pcl_core.v) from Linux on the Zynq.

PclRegs maps the core's 4 KB AXI-Lite window through UIO (/dev/uioN, "generic-uio" node in the device tree, see
firmware/linux/pl-overlay.dtsi) and gives the register operations the daemon needs. The md ring is read by copying
the 2 KB window at 0x800 in one numpy copy, not record by record.
SimRegs has the same interface on top of the bit-true model, for tests on a PC.
"""
import mmap
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import fixedpoint as fx  # noqa: E402

ID, CTRL, CPI_LEN, SHIFTS, MD_CFG, STATUS = 0x000, 0x004, 0x008, 0x00C, 0x010, 0x014
SAMPLE_LO, SAMPLE_HI, PPS_LO, PPS_HI = 0x018, 0x01C, 0x020, 0x024
TAP_ADDR, TAP_I, TAP_Q = 0x040, 0x044, 0x048
MD_WR, MD_RD = 0x080, 0x084
MD_PRM, MD_RING = 0x100, 0x800
RING = 128
CORE_ID = 0x50434C01

RECORD = np.dtype([("hdr", "<u4"), ("i", "<i4"), ("q", "<i4"), ("blk", "<u4")])


class PclRegs:
    def __init__(self, uio="/dev/uio0", size=0x1000):
        self.fd = os.open(uio, os.O_RDWR | os.O_SYNC)
        self.mm = mmap.mmap(self.fd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        self.w32 = np.frombuffer(self.mm, np.uint32)
        if self.rd(ID) != CORE_ID:
            raise RuntimeError(f"{uio}: not a pcl_core (ID {self.rd(ID):#x})")
        self.ctrl = 0

    def rd(self, a):
        return int(self.w32[a >> 2])

    def wr(self, a, v):
        self.w32[a >> 2] = v & 0xFFFFFFFF

    # ------------------------------------------------------------------ configuration
    def configure(self, cpi_len, sv_shift, ref_shift, block_log2, out_shift):
        self.wr(CPI_LEN, cpi_len)
        self.wr(SHIFTS, (ref_shift << 4) | sv_shift)
        self.wr(MD_CFG, (out_shift << 8) | block_log2)

    def stream(self, on):
        self.ctrl = int(bool(on))
        self.wr(CTRL, self.ctrl)

    def load_taps(self, ch, ti, tq):
        for k, (a, b) in enumerate(zip(ti, tq)):
            self.wr(TAP_ADDR, (ch << 16) | k)
            self.wr(TAP_I, int(a))
            self.wr(TAP_Q, int(b))

    def commit_taps(self):
        self.wr(CTRL, self.ctrl | 0x2)

    def set_target(self, slot, tau, wi, wq, enable):
        base = MD_PRM + 32 * slot
        self.wr(base, (int(enable) << 31) | int(tau))
        for c in range(len(wi)):
            self.wr(base + 4 * (c + 1), ((int(wi[c]) & 0xFFFF) << 16) | (int(wq[c]) & 0xFFFF))

    def commit_targets(self):
        self.wr(CTRL, self.ctrl | 0x4)

    # ------------------------------------------------------------------ readout
    def status(self):
        s = self.rd(STATUS)
        lo = self.rd(SAMPLE_LO)
        return {"sample": (self.rd(SAMPLE_HI) << 32) | lo, "pps_sample": (self.rd(PPS_HI) << 32) | self.rd(PPS_LO),
                "canceller_overrun": bool(s & 1), "md_overrun": bool(s & 2), "stream_overflow": bool(s & 4),
                "md_ring_overflow": bool(s & 8), "tap_bank": (s >> 4) & 1}

    def read_md(self):
        """new md records since the last call: structured array (tgt, blk, i, q); lost = records overwritten"""
        wr, rd = self.rd(MD_WR), self.rd(MD_RD)
        n = (wr - rd) & 0xFFFFFFFF
        lost = max(0, n - RING)
        if lost:
            rd = (wr - RING) & 0xFFFFFFFF
            n = RING
        ring = np.frombuffer(self.mm, RECORD, RING, MD_RING).copy()   # one bulk copy of the window
        idx = (rd + np.arange(n)) % RING
        rec = ring[idx]
        self.wr(MD_RD, wr)
        return records(rec), lost

    def close(self):
        self.mm.close()
        os.close(self.fd)


def records(rec):
    return {"tgt": (rec["hdr"] >> 24).astype(np.int64), "blk": rec["blk"].astype(np.int64),
            "y": rec["i"].astype(np.float64) + 1j * rec["q"].astype(np.float64)}


class SimRegs:
    """Same interface, driven by the bit-true model. push() feeds canceller-input samples (int I/Q arrays)."""

    def __init__(self, nch=4, ntaps=128, ntgt=8):
        self.nch, self.ntaps, self.ntgt = nch, ntaps, ntgt
        self.taps_i = np.zeros((nch, ntaps), np.int64)
        self.taps_q = np.zeros((nch, ntaps), np.int64)
        self.shadow_taps = (self.taps_i.copy(), self.taps_q.copy())
        self.tg = [{"tau": 0, "w_i": np.zeros(nch, np.int64), "w_q": np.zeros(nch, np.int64), "en": False} for _ in range(ntgt)]
        self.shadow_tg = [dict(t) for t in self.tg]
        self.block_log2, self.out_shift = 11, 16
        self.n = 0
        self.hist = None
        self.out = []

    def configure(self, cpi_len, sv_shift, ref_shift, block_log2, out_shift):
        self.block_log2, self.out_shift = block_log2, out_shift

    def stream(self, on):
        pass

    def load_taps(self, ch, ti, tq):
        self.shadow_taps[0][ch] = ti
        self.shadow_taps[1][ch] = tq

    def commit_taps(self):          # simplification: applies at the next push (callers push whole CPIs)
        self.taps_i, self.taps_q = self.shadow_taps[0].copy(), self.shadow_taps[1].copy()

    def set_target(self, slot, tau, wi, wq, enable):
        self.shadow_tg[slot] = {"tau": int(tau), "w_i": np.asarray(wi), "w_q": np.asarray(wq), "en": bool(enable)}

    def commit_targets(self):       # applies at the next push (callers push whole blocks)
        self.tg = [dict(t) for t in self.shadow_tg]

    def push(self, ref_i, ref_q, s_i, s_q):
        """process one chunk (length a multiple of the block) through canceller + md engine, with history"""
        B = 1 << self.block_log2
        H = B * (-(-max(self.ntaps, 4096) // B))           # history prefix: whole blocks covering taps and delays
        if self.hist is None:
            z = lambda *s: np.zeros(s, np.int64)
            self.hist = (z(H), z(H), z(self.nch, H), z(self.nch, H))
        ri = np.concatenate([self.hist[0], ref_i]); rq = np.concatenate([self.hist[1], ref_q])
        si = np.concatenate([self.hist[2], s_i], axis=1); sq = np.concatenate([self.hist[3], s_q], axis=1)
        yi = np.zeros_like(si); yq = np.zeros_like(sq)
        for c in range(self.nch):
            yi[c], yq[c] = canceller_fast(ri, rq, si[c], sq[c], self.taps_i[c], self.taps_q[c])
        res = fx.md_engine(ri, rq, yi, yq, self.tg, self.block_log2, self.out_shift, n0=self.n - H)
        skip = H // B
        for t, (Yi, Yq, first) in res.items():
            if not self.tg[t]["en"]:
                continue
            for m in range(skip, len(Yi)):
                self.out.append((t, first + m, Yi[m], Yq[m]))
        self.hist = (ri[-H:], rq[-H:], si[:, -H:], sq[:, -H:])
        self.n += len(ref_i)
        return yi[:, H:], yq[:, H:]

    def read_md(self):
        o, self.out = self.out, []
        if not o:
            return {"tgt": np.zeros(0, int), "blk": np.zeros(0, int), "y": np.zeros(0, complex)}, 0
        a = np.array(o, dtype=object)
        return {"tgt": a[:, 0].astype(int), "blk": a[:, 1].astype(int),
                "y": a[:, 2].astype(float) + 1j * a[:, 3].astype(float)}, 0

    def status(self):
        return {"sample": self.n, "pps_sample": 0, "canceller_overrun": False, "md_overrun": False,
                "stream_overflow": False, "md_ring_overflow": False, "tap_bank": 0}


def canceller_fast(ref_i, ref_q, s_i, s_q, taps_i, taps_q):
    """fx.canceller with FFT convolutions: the products are integers < 2^53, so rounding the float result back
    to integers is exact; identical output, ~100x faster on long records."""
    from scipy.signal import fftconvolve
    n = len(ref_i)
    cv = lambda a, b: np.rint(fftconvolve(a.astype(float), b.astype(float))[:n]).astype(np.int64)
    acc_i = cv(ref_i, taps_i) - cv(ref_q, taps_q)
    acc_q = cv(ref_i, taps_q) + cv(ref_q, taps_i)
    return (fx.sat(s_i - fx.rshift_round(acc_i, fx.CANC_TAP_FRAC), fx.SAMPLE_BITS),
            fx.sat(s_q - fx.rshift_round(acc_q, fx.CANC_TAP_FRAC), fx.SAMPLE_BITS))
