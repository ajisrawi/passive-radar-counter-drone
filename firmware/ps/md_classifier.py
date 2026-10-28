"""Micro-Doppler drone / bird classifier on the FPGA's continuous slow-time samples (runs on the Zynq ARM).

The md engine delivers Y[m], the CAF value of a cued target's range cell and beam, at fs_slow = fs / 2^block_log2
(3906 Hz at 8 MS/s) with no gaps. Per target:
  1. segments of NFFT samples (default 2048 = 0.52 s), hop NFFT/2, Hann window. Its 2-bin main lobe keeps a rotor
     line in ~1.5 bins (Blackman-Harris spread it over 4 and cost 2.5x in z); its sidelobes 6 bins (12 Hz) out are
     ~-54 dB, so a body line up to ~50 dB SNR does not leak into the 12-30 Hz wing-beat band;
  2. power spectrum, noise floor = median of the usable bins / ln 2 (exponential noise), body line = strongest
     usable bin (|f| above the zero-Doppler guard, where the clutter residual sits);
  3. a segment whose body line is under MIN_BODY_SNR_DB is not a look (gate empty, track lost or wrong cue);
  4. the spectrum, normalised to the noise and centred on the body line, is averaged over all looks of the track;
  5. the same decision as the host (pcl/classify.py): strongest symmetric line in 12-30 Hz (wing beat) and in the
     rotor band, as z-scores; rotor z > 6 -> UAV, else wing-beat z > 6 -> bird, else unknown; >= 8 looks first.
The rotor band is 40-700 Hz at UHF; on the 4G/5G stacks blade lines move out with frequency, so its top is
min(rotor_top_hz, 0.45 fs_slow).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from pcl.classify import NEAR_BAND_HZ, FAR_BAND_HZ, ZERO_DOPPLER_GUARD_HZ, _line_z  # noqa: E402

MIN_BODY_SNR_DB = 12.0


def blackman_harris(n):
    k = np.arange(n) / n
    return 0.35875 - 0.48829 * np.cos(2 * np.pi * k) + 0.14128 * np.cos(4 * np.pi * k) - 0.01168 * np.cos(6 * np.pi * k)


class TargetMd:
    def __init__(self, fs_slow, nfft=2048, rotor_top_hz=FAR_BAND_HZ[1], z_thresh=6.0, min_looks=8):
        self.fs = fs_slow
        self.nfft = nfft
        self.hop = nfft // 2
        self.win = np.hanning(nfft).astype(np.float32)
        self.freq = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs_slow))
        self.usable = np.abs(self.freq) > ZERO_DOPPLER_GUARD_HZ
        self.offsets = (np.arange(nfft) - nfft // 2) * (fs_slow / nfft)
        self.far = (FAR_BAND_HZ[0], min(rotor_top_hz, 0.45 * fs_slow))
        self.z_thresh, self.min_looks = z_thresh, min_looks
        self.reset()

    def reset(self):
        self.buf = np.zeros(0, np.complex64)
        self.next_blk = None
        self.sum = np.zeros(self.nfft)
        self.cnt = np.zeros(self.nfft, np.int64)
        self.looks = 0
        self.last = {"body_doppler_hz": 0.0, "body_snr_db": 0.0}

    def feed(self, blk, y):
        """blk: block indices (int array, increasing), y: complex values. A gap restarts the segment buffer."""
        if len(blk) == 0:
            return
        if self.next_blk is not None and blk[0] != self.next_blk:
            self.buf = np.zeros(0, np.complex64)
        gaps = np.nonzero(np.diff(blk) != 1)[0]
        if len(gaps):                                     # keep only the run after the last gap
            k = gaps[-1] + 1
            blk, y = blk[k:], y[k:]
            self.buf = np.zeros(0, np.complex64)
        self.buf = np.concatenate([self.buf, y.astype(np.complex64)])
        self.next_blk = int(blk[-1]) + 1
        while len(self.buf) >= self.nfft:
            self._segment(self.buf[: self.nfft])
            self.buf = self.buf[self.hop:]

    def _segment(self, x):
        P = np.abs(np.fft.fftshift(np.fft.fft(x * self.win))) ** 2
        n0 = np.median(P[self.usable]) / np.log(2)
        if not n0 > 0:                        # all-zero samples: output shift too large, or the engine is idle
            self.last = {"body_doppler_hz": 0.0, "body_snr_db": -99.0}
            return
        di = int(np.argmax(np.where(self.usable, P, 0)))
        snr = P[di] / n0
        self.last = {"body_doppler_hz": float(self.freq[di]), "body_snr_db": float(10 * np.log10(snr))}
        if snr < 10 ** (MIN_BODY_SNR_DB / 10):
            return
        shift = self.nfft // 2 - di
        spec = np.roll(P / n0, shift)
        ok = np.roll(self.usable, shift)
        # bins next to the body line are its window main lobe: no information there
        ok[self.nfft // 2 - 2: self.nfft // 2 + 3] = False
        self.sum[ok] += spec[ok]
        self.cnt[ok] += 1
        self.looks += 1

    def report(self):
        mean = np.where(self.cnt > 0, self.sum / np.maximum(self.cnt, 1), 1.0)
        z_near = _line_z(mean, self.cnt, self.offsets, *NEAR_BAND_HZ)
        z_far = _line_z(mean, self.cnt, self.offsets, *self.far)
        # strongest rotor-band line offset (for the operator / logging)
        band = (np.abs(self.offsets) >= self.far[0]) & (np.abs(self.offsets) <= self.far[1]) & (self.cnt > 0)
        rotor_hz = float(abs(self.offsets[band][np.argmax(mean[band])])) if band.any() else 0.0
        if self.looks == 0 and self.last["body_snr_db"] < MIN_BODY_SNR_DB:
            cls = "no signal"
        elif self.looks < self.min_looks:
            cls = "pending"
        elif z_far > self.z_thresh:
            cls = "UAV"
        elif z_near > self.z_thresh:
            cls = "bird"
        else:
            cls = "unknown"
        return {"class": cls, "looks": self.looks, "z_near": float(z_near), "z_far": float(z_far),
                "rotor_line_hz": rotor_hz, **self.last}
