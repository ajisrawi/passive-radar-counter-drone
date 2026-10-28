"""Illuminator and receiver signal model.

The illuminator is a DVB-T-like OFDM signal (2K mode: 2048-point FFT, 1705 active
carriers, 1/4 guard interval, 64-QAM, fs = 64/7 MHz). Pilots are omitted; a real
DVB-T signal needs pilot/guard-interval ambiguity suppression (see docs/DESIGN.md).
"""
from dataclasses import dataclass

import numpy as np

FS_DVBT = 64e6 / 7


@dataclass
class Path:
    """One propagation path seen by the surveillance array."""

    label: str
    delay_samples: float  # bistatic delay in samples (may be fractional)
    doppler_hz: float
    snr_db: float  # per-element, per-sample power relative to noise
    angle_deg: float  # arrival angle relative to array broadside


def dvbt_like_ofdm(n_samples, rng, nfft=2048, n_carriers=1705, cp_len=512, qam=64):
    sym_len = nfft + cp_len
    n_sym = -(-n_samples // sym_len)
    bins = (np.arange(n_carriers) - n_carriers // 2) % nfft
    m = int(np.sqrt(qam))
    levels = 2 * np.arange(m) - (m - 1)
    X = np.zeros((n_sym, nfft), np.complex128)
    X[:, bins] = rng.choice(levels, (n_sym, n_carriers)) + 1j * rng.choice(levels, (n_sym, n_carriers))
    x = np.fft.ifft(X, axis=1)
    x = np.concatenate([x[:, -cp_len:], x], axis=1).ravel()[:n_samples]
    return (x / np.sqrt(np.mean(np.abs(x) ** 2))).astype(np.complex64)


def delay_doppler(x, delay_samples, doppler_hz, fs):
    """Apply a (fractional) delay and a Doppler shift."""
    n = len(x)
    f = np.fft.fftfreq(n)
    y = np.fft.ifft(np.fft.fft(x) * np.exp(-2j * np.pi * f * delay_samples))
    y[: int(np.ceil(delay_samples))] = 0  # drop circular wrap-around
    if doppler_hz:
        y *= np.exp(2j * np.pi * doppler_hz * np.arange(n) / fs)
    return y


def steering(angle_deg, n_elements):
    """Uniform linear array, half-wavelength spacing."""
    return np.exp(1j * np.pi * np.arange(n_elements) * np.sin(np.radians(angle_deg)))


def simulate_receiver(ref_clean, paths, n_elements, fs, ref_snr_db, rng):
    """Return (reference channel, surveillance channels [n_elements, N]).

    Noise power is 1 per sample in every channel.
    """
    n = len(ref_clean)

    def noise(shape):
        return ((rng.standard_normal(shape) + 1j * rng.standard_normal(shape)) / np.sqrt(2)).astype(np.complex64)

    ref = (ref_clean * np.sqrt(10 ** (ref_snr_db / 10)) + noise(n)).astype(np.complex64)
    surv = noise((n_elements, n))
    for p in paths:
        sig = delay_doppler(ref_clean, p.delay_samples, p.doppler_hz, fs) * np.sqrt(10 ** (p.snr_db / 10))
        surv += (steering(p.angle_deg, n_elements)[:, None] * sig[None, :]).astype(np.complex64)
    return ref, surv


class FastReceiver:
    """Multi-CPI receiver simulator.

    Static paths (direct signal + ground clutter) are a fixed linear filter of the
    illuminator, so they are applied as one precomputed frequency response per
    element. Moving targets are applied per CPI with their current delay, Doppler,
    RCS draw and micro-Doppler modulation. A new random OFDM signal and new noise
    are drawn every CPI.
    """

    def __init__(self, n_samples, static_paths, n_elements, fs, ref_snr_db, rng, mod_stride=32):
        from scipy import fft as sfft

        self.fft = sfft
        self.n, self.n_el, self.fs, self.rng = n_samples, n_elements, fs, rng
        self.ref_amp = np.sqrt(10 ** (ref_snr_db / 10))
        self.mod_stride = mod_stride
        self.f = sfft.fftfreq(n_samples).astype(np.float32)
        self.H = np.zeros((n_elements, n_samples), np.complex64)
        for p in static_paths:
            amp = np.sqrt(10 ** (p.snr_db / 10))
            resp = (amp * np.exp(-2j * np.pi * self.f * p.delay_samples)).astype(np.complex64)
            self.H += steering(p.angle_deg, n_elements)[:, None].astype(np.complex64) * resp[None, :]

    def _noise(self, shape):
        r = self.rng.standard_normal((2,) + tuple(np.atleast_1d(shape)), dtype=np.float32)
        return (r[0] + 1j * r[1]) * np.float32(np.sqrt(0.5))

    def cpi(self, t0, echoes):
        """Simulate one CPI starting at time t0.

        echoes: list of dicts with delay_samples, doppler_hz, snr_db, angle_deg and
        optionally modulation (callable t -> complex array).
        Returns (reference, surveillance [n_el, n]).
        """
        sfft, n = self.fft, self.n
        x = dvbt_like_ofdm(n, self.rng)
        X = sfft.fft(x, workers=-1)
        surv = sfft.ifft(X[None, :] * self.H, axis=1, workers=-1).astype(np.complex64)
        t_coarse = t0 + np.arange(0, n, self.mod_stride) / self.fs
        tn = np.arange(n, dtype=np.float64) / self.fs
        for e in echoes:
            sig = sfft.ifft(X * np.exp(-2j * np.pi * self.f * e["delay_samples"]), workers=-1)
            sig *= np.exp(2j * np.pi * e["doppler_hz"] * tn) * np.sqrt(10 ** (e["snr_db"] / 10))
            if e.get("modulation") is not None:
                sig *= np.repeat(e["modulation"](t_coarse), self.mod_stride)[:n]
            surv += (steering(e["angle_deg"], self.n_el)[:, None] * sig[None, :]).astype(np.complex64)
        surv += self._noise((self.n_el, n))
        ref = (x * self.ref_amp + self._noise(n)).astype(np.complex64)
        return ref, surv
