"""Passive radar signal processing chain.

    reference + surveillance channels
        -> ECA clutter / direct-signal cancellation (per channel)
        -> batched cross-ambiguity function (range-Doppler map, per channel)
        -> digital beamforming in the range-Doppler domain
        -> 2D CA-CFAR detection + peak picking
        -> direction finding per detection
"""
import numpy as np
from scipy import fft as sfft
from scipy.linalg import solve_toeplitz
from scipy.ndimage import maximum_filter, uniform_filter

from .signal_model import steering

C = 299_792_458.0


def eca(ref, surv, n_taps, n_batches=1, diag_load=1e-6):
    """Extensive Cancellation Algorithm (zero-Doppler, optionally batched = ECA-B).

    Removes the least-squares projection of `surv` onto delayed copies of `ref`
    (lags 0..n_taps-1). This cancels the direct signal and stationary clutter.
    The normal equations are Toeplitz, so they are built with FFTs and solved
    with Levinson recursion: O(N log N) instead of forming an N x K matrix.
    More batches track slowly moving clutter but widen the zero-Doppler notch
    to about n_batches / CPI Hz.
    """
    n = len(ref)
    out = np.empty_like(surv)
    edges = np.linspace(0, n, n_batches + 1).astype(int)
    for a, b in zip(edges[:-1], edges[1:]):
        r, s = ref[a:b].astype(np.complex128), surv[a:b].astype(np.complex128)
        nfft = sfft.next_fast_len(len(r) + n_taps)
        fr = sfft.fft(r, nfft, workers=-1)
        c = sfft.ifft(np.conj(fr) * fr, workers=-1)[:n_taps]  # autocorrelation lags 0..K-1
        p = sfft.ifft(np.conj(fr) * sfft.fft(s, nfft, workers=-1), workers=-1)[:n_taps]  # cross-correlation
        c[0] *= 1 + diag_load
        w = solve_toeplitz((c, np.conj(c)), p)
        out[a:b] = s - sfft.ifft(fr * sfft.fft(w, nfft), workers=-1)[: len(r)]
    return out


def caf(ref, surv, fs, n_range, n_segments, window=True):
    """Batched cross-ambiguity function.

    The CPI is cut into `n_segments` segments of length L. For each segment the
    range correlation is computed with FFTs (surveillance segments overlap by
    n_range samples so long delays are not truncated), then an FFT across
    segments gives Doppler. Valid while |Doppler| << fs / L.

    Returns caf [n_doppler, n_range], doppler axis (Hz), bistatic range axis (m).
    """
    L = len(ref) // n_segments
    nfft = 1 << int(np.ceil(np.log2(L + n_range)))
    ref_seg = ref[: L * n_segments].reshape(n_segments, L)
    surv_pad = np.concatenate([surv, np.zeros(n_range, surv.dtype)])
    surv_seg = np.stack([surv_pad[m * L : m * L + L + n_range] for m in range(n_segments)])
    corr = sfft.ifft(np.conj(sfft.fft(ref_seg, nfft, axis=1, workers=-1)) * sfft.fft(surv_seg, nfft, axis=1, workers=-1),
                     axis=1, workers=-1)
    corr = corr[:, :n_range]
    win = np.hanning(n_segments)[:, None] if window else 1.0
    out = np.fft.fftshift(sfft.fft(corr * win, axis=0, workers=-1), axes=0)
    doppler = np.fft.fftshift(np.fft.fftfreq(n_segments, d=L / fs))
    rng_axis = np.arange(n_range) * C / fs
    return out, doppler, rng_axis


def beam_max_map(caf_channels, angles_deg):
    """Max over a fan of beams of |a(theta)^H x|^2 for every range-Doppler cell."""
    n_el = caf_channels.shape[0]
    best = np.zeros(caf_channels.shape[1:])
    for th in angles_deg:
        a = steering(th, n_el) / n_el
        best = np.maximum(best, np.abs(np.tensordot(np.conj(a), caf_channels, axes=1)) ** 2)
    return best


def ca_cfar(power, guard=(3, 3), train=(8, 8), pfa=1e-7):
    """2D cell-averaging CFAR. Returns (detection mask, threshold)."""
    outer = (2 * (guard[0] + train[0]) + 1, 2 * (guard[1] + train[1]) + 1)
    inner = (2 * guard[0] + 1, 2 * guard[1] + 1)
    sum_outer = uniform_filter(power, outer, mode=("wrap", "nearest")) * np.prod(outer)
    sum_inner = uniform_filter(power, inner, mode=("wrap", "nearest")) * np.prod(inner)
    n_train = np.prod(outer) - np.prod(inner)
    alpha = n_train * (pfa ** (-1.0 / n_train) - 1.0)
    threshold = alpha * (sum_outer - sum_inner) / n_train
    return power > threshold, threshold


def detect(power, doppler, min_doppler_hz=3.0, merge=True, merge_range_cells=2, merge_doppler_hz=50.0,
           merge_weaker_db=10.0, **cfar_kw):
    """CFAR + local-maximum peak picking, ignoring the zero-Doppler clutter ridge.

    With merge=True, a peak in (almost) the same range cell as a stronger peak is
    dropped when it is within merge_doppler_hz of it, or is merge_weaker_db weaker.
    This removes micro-Doppler sidebands (wing-beat lines, rotor flashes) that would
    otherwise start false tracks. Trade-off: two real targets in the same range cell
    and within 50 Hz are reported as one.
    """
    mask, thr = ca_cfar(power, **cfar_kw)
    peaks = mask & (power == maximum_filter(power, size=(5, 5)))
    peaks &= (np.abs(doppler) >= min_doppler_hz)[:, None]
    di, ri = np.nonzero(peaks)
    order = np.argsort(-power[di, ri])
    dets = [(int(di[k]), int(ri[k]), float(10 * np.log10(power[di[k], ri[k]] / thr[di[k], ri[k]]))) for k in order]
    if not merge:
        return dets
    kept = []
    for d in dets:
        dup = False
        for k in kept:
            if abs(d[1] - k[1]) <= merge_range_cells:
                close = abs(doppler[d[0]] - doppler[k[0]]) <= merge_doppler_hz
                weaker = 10 * np.log10(power[k[0], k[1]] / power[d[0], d[1]]) >= merge_weaker_db
                if close or weaker:
                    dup = True
                    break
        if not dup:
            kept.append(d)
    return kept


def refine_peak(power, di, ri):
    """Parabolic interpolation in Doppler and range; returns fractional (di, ri)."""

    def interp(a, b, c):
        den = a - 2 * b + c
        return 0.0 if den == 0 else 0.5 * (a - c) / den

    p = 10 * np.log10(power)
    nd, nr = p.shape
    dd = interp(p[(di - 1) % nd, ri], p[di, ri], p[(di + 1) % nd, ri])
    dr = interp(p[di, ri - 1], p[di, ri], p[di, ri + 1]) if 0 < ri < nr - 1 else 0.0
    return di + dd, ri + dr


def doa_bartlett(snapshot, angles_deg=np.arange(-90, 90.01, 0.05)):
    """Single-snapshot DOA (maximum likelihood for one source) from per-element CAF values."""
    n_el = len(snapshot)
    a = np.stack([steering(t, n_el) for t in angles_deg])
    spec = np.abs(np.conj(a) @ snapshot) ** 2
    return float(angles_deg[np.argmax(spec)]), spec
