"""Bit-true fixed-point models of the FPGA blocks (the reference the Verilog must match exactly).

All arithmetic is on Python/numpy int64 with the same rounding as the RTL:
    rshift_round(x, s) = (x + 2**(s-1)) >> s      (arithmetic shift, round half up), s = 0 -> x
    sat(x, n)          = clamp to the n-bit two's complement range
"""
import numpy as np


def rshift_round(x, s):
    if s <= 0:
        return x
    return (x + (1 << (s - 1))) >> s


def sat(x, n):
    lo, hi = -(1 << (n - 1)), (1 << (n - 1)) - 1
    return np.clip(x, lo, hi) if isinstance(x, np.ndarray) else max(lo, min(hi, x))


def to_fixed(z, frac_bits, n_bits):
    """complex float -> (I, Q) int64 arrays, rounded and saturated"""
    z = np.asarray(z)
    s = float(1 << frac_bits)
    i = sat(np.round(z.real * s).astype(np.int64), n_bits)
    q = sat(np.round(z.imag * s).astype(np.int64), n_bits)
    return i, q


# ------------------------------------------------------------------ canceller
CANC_TAP_BITS = 18          # complex taps, Q2.16
CANC_TAP_FRAC = 16
SAMPLE_BITS = 16            # ref and surveillance samples into the canceller


def canceller(ref_i, ref_q, s_i, s_q, taps_i, taps_q):
    """y[n] = sat16( s[n] - rshift_round(sum_k h[k] r[n-k], 16) ), r[n<0] = 0.
    taps: int arrays [ntaps] (one channel). Returns (y_i, y_q)."""
    ntaps = len(taps_i)
    n = len(ref_i)
    # complex integer convolution with four real convolutions
    rr = lambda a, b: np.convolve(a, b)[:n]
    acc_i = rr(ref_i, taps_i) - rr(ref_q, taps_q)
    acc_q = rr(ref_i, taps_q) + rr(ref_q, taps_i)
    y_i = sat(s_i - rshift_round(acc_i, CANC_TAP_FRAC), SAMPLE_BITS)
    y_q = sat(s_q - rshift_round(acc_q, CANC_TAP_FRAC), SAMPLE_BITS)
    assert ntaps <= 1024
    return y_i, y_q


def ls_taps(ref, surv, ntaps, diag_load=1e-6):
    """Least-squares (ECA) canceller taps from a snapshot, float. The host does this between CPIs."""
    from scipy.linalg import solve_toeplitz
    n = len(ref)
    r = np.array([np.vdot(ref[: n - k], ref[k:]) for k in range(ntaps)])  # r[k] = sum conj(x[n]) x[n+k]
    p = np.array([np.vdot(ref[: n - k], surv[k:]) for k in range(ntaps)])
    r = r.copy()
    r[0] *= 1 + diag_load
    return solve_toeplitz((r, np.conj(r)), p)


# ------------------------------------------------------------------ requantiser
def requant(x, shift, out_bits):
    return sat(rshift_round(np.asarray(x, np.int64), shift), out_bits)


# ------------------------------------------------------------------ stream packer
def pack_samples(ref_i, ref_q, sv_i, sv_q, ref_bits=12, sv_bits=8):
    """One sample = ref I, ref Q (ref_bits each) then surveillance ch0..3 I, Q (sv_bits each), LSB first,
    into a continuous bit stream cut into 64-bit little-endian words. 12+12+4*16 = 88 bits per sample;
    128 samples = 1408 bytes = 176 words = one UDP payload (TLAST on the last word)."""
    fields = []
    n = len(ref_i)
    words = []
    acc, nb = 0, 0
    mask = lambda b: (1 << b) - 1
    for k in range(n):
        for v, b in ((ref_i[k], ref_bits), (ref_q[k], ref_bits)):
            acc |= (int(v) & mask(b)) << nb
            nb += b
        for c in range(len(sv_i)):
            for v in (sv_i[c][k], sv_q[c][k]):
                acc |= (int(v) & mask(sv_bits)) << nb
                nb += sv_bits
        while nb >= 64:
            words.append(acc & mask(64))
            acc >>= 64
            nb -= 64
    if nb:
        words.append(acc & mask(64))
    return words


def unpack_samples(words, n, nch=4, ref_bits=12, sv_bits=8):
    """inverse of pack_samples (host side); returns ref (complex int) [n], surv [nch, n]"""
    big = 0
    for w in reversed(words):
        big = (big << 64) | int(w)
    per = 2 * ref_bits + 2 * nch * sv_bits

    def sx(v, b):
        return v - (1 << b) if v >> (b - 1) else v
    ref = np.zeros(n, np.complex64)
    surv = np.zeros((nch, n), np.complex64)
    for k in range(n):
        s = big >> (k * per)
        ri = sx(s & ((1 << ref_bits) - 1), ref_bits)
        rq = sx((s >> ref_bits) & ((1 << ref_bits) - 1), ref_bits)
        ref[k] = ri + 1j * rq
        o = 2 * ref_bits
        for c in range(nch):
            si = sx((s >> o) & ((1 << sv_bits) - 1), sv_bits)
            sq = sx((s >> (o + sv_bits)) & ((1 << sv_bits) - 1), sv_bits)
            surv[c, k] = si + 1j * sq
            o += 2 * sv_bits
    return ref, surv


# ------------------------------------------------------------------ micro-Doppler engine
MD_W_BITS = 16              # beam weights, Q1.15
MD_W_FRAC = 15
MD_ACC_BITS = 56
MD_OUT_BITS = 32


def md_engine(ref_i, ref_q, s_i, s_q, targets, block_log2, out_shift, n0=0):
    """Range-gated, beamformed slow-time samples for each target.

    For target t with delay tau (samples) and weights w[c] (int I/Q, Q1.15):
        b[n]   = rshift_round( sum_c s_c[n] * conj(w_c), 15 )          (complex, ~20 bits)
        z[n]   = b[n] * conj(r[n - tau])                                (r[<0] = 0)
        Y[m]   = sat32( rshift_round( sum_{n in block m} z[n], out_shift ) )
    Blocks are 2**block_log2 samples long, aligned to the global sample counter (n0 = counter of sample 0).
    s_i/s_q: [nch, n]. targets: list of dicts {tau, w_i[nch], w_q[nch]}.
    Returns {t: (Y_i, Y_q, first_block_index)} for complete blocks only.
    """
    n = len(ref_i)
    B = 1 << block_log2
    out = {}
    for t, tg in enumerate(targets):
        wi = np.asarray(tg["w_i"], np.int64)[:, None]
        wq = np.asarray(tg["w_q"], np.int64)[:, None]
        # s * conj(w) = (si wi + sq wq) + j (sq wi - si wq)
        bi = rshift_round(np.sum(s_i * wi + s_q * wq, axis=0), MD_W_FRAC)
        bq = rshift_round(np.sum(s_q * wi - s_i * wq, axis=0), MD_W_FRAC)
        tau = int(tg["tau"])
        ri = np.zeros(n, np.int64)
        rq = np.zeros(n, np.int64)
        ri[tau:] = ref_i[: n - tau]
        rq[tau:] = ref_q[: n - tau]
        # b * conj(r) = (bi ri + bq rq) + j (bq ri - bi rq)
        zi = bi * ri + bq * rq
        zq = bq * ri - bi * rq
        first = -(-n0 // B)               # first block that starts at or after n0
        start = first * B - n0
        nblk = (n - start) // B
        if nblk <= 0:
            out[t] = (np.zeros(0, np.int64), np.zeros(0, np.int64), first)
            continue
        seg = slice(start, start + nblk * B)
        Yi = zi[seg].reshape(nblk, B).sum(axis=1)
        Yq = zq[seg].reshape(nblk, B).sum(axis=1)
        out[t] = (sat(rshift_round(Yi, out_shift), MD_OUT_BITS), sat(rshift_round(Yq, out_shift), MD_OUT_BITS), first)
    return out


def steering_weights(angle_deg, nch=4, d_over_lambda=0.5):
    """Q1.15 beam weights (1/nch amplitude each) toward angle (degrees from boresight), ULA."""
    k = np.arange(nch)
    a = np.exp(1j * 2 * np.pi * d_over_lambda * k * np.sin(np.radians(angle_deg))) / nch
    return to_fixed(a, MD_W_FRAC, MD_W_BITS)
