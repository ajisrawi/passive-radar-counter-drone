"""Receiver-to-host data-rate budget and the sample-precision study behind it.

    python -m pcl.data_rate

Board C streams IQ samples from the Zynq to the processing host over one Gigabit
Ethernet port (Zynq-7000 PS GEM + RTL8211F). This module

1. tabulates the stream rate for each option (channels, sample rate, bits per IQ
   sample) against what that link can carry, and
2. measures the target SNR lost when samples are re-quantised to fewer bits, by
   running simulated DVB-T data through the real chain (ECA -> CAF).

Fewer bits cost sensitivity because the surveillance channels are dominated by the
direct signal (~44 dB above thermal noise at a 15 km baseline). Quantisation noise
scales with the strongest signal present and is not correlated with the reference,
so ECA cannot remove it. Cancelling the direct signal and clutter in the FPGA first
(a fixed FIR whose taps the host computes) removes that limit.
"""
from dataclasses import dataclass

import numpy as np

from .link_budget import LinkBudget
from .processing import caf, eca
from .signal_model import FS_DVBT, Path, dvbt_like_ofdm, simulate_receiver

# ---------------------------------------------------------------- link capacity
GBE_LINE_BPS = 1e9
# Zynq-7000 GEM has no jumbo frames: 1472 B UDP payload per 1538 B on the wire
# (preamble 8 + Ethernet 14 + IP 20 + UDP 8 + FCS 4 + inter-frame gap 12).
GBE_PAYLOAD_BPS = GBE_LINE_BPS * 1472 / 1538
DESIGN_LIMIT = 0.75  # keep 25 % margin for the Linux/lwIP stack, control traffic and bursts
FS_8M = FS_DVBT * 7 / 8  # 8.000 MS/s: exact 7/8 polyphase resampler, still covers the 7.61 MHz DVB-T band


@dataclass
class Stream:
    name: str
    channels: list  # bits per IQ sample (I + Q) for each channel streamed
    fs: float

    @property
    def bps(self):
        return sum(self.channels) * self.fs


OPTIONS = [
    Stream("6 ch, 16-bit I/Q words (AD9361 native)", [32] * 6, FS_DVBT),
    Stream("6 ch, 12-bit packed", [24] * 6, FS_DVBT),
    Stream("5 ch, 12-bit packed", [24] * 5, FS_DVBT),
    Stream("5 ch, 12-bit, 8 MS/s", [24] * 5, FS_8M),
    Stream("5 ch, 10-bit, 8 MS/s", [20] * 5, FS_8M),
    Stream("5 ch, 8-bit, 8 MS/s (raw)", [16] * 5, FS_8M),
    Stream("ref 12-bit + 4 surv 8-bit after FPGA cancel, 8 MS/s", [24] + [16] * 4, FS_8M),
    Stream("ref 12-bit + 4 surv 6-bit after FPGA cancel, 8 MS/s", [24] + [12] * 4, FS_8M),
]


def budget_table():
    limit = DESIGN_LIMIT * GBE_PAYLOAD_BPS
    print(f"Gigabit Ethernet: {GBE_PAYLOAD_BPS/1e6:.0f} Mbit/s UDP payload (1500-byte MTU), "
          f"design limit {limit/1e6:.0f} Mbit/s ({DESIGN_LIMIT:.0%})")
    print(f"  {'stream':<55} {'Mbit/s':>7} {'of link':>8}  fits?")
    for o in OPTIONS:
        ok = "yes" if o.bps <= limit else ("tight" if o.bps <= GBE_PAYLOAD_BPS else "NO")
        print(f"  {o.name:<55} {o.bps/1e6:7.0f} {o.bps/GBE_PAYLOAD_BPS:8.0%}  {ok}")


# ---------------------------------------------------------------- quantisation study
AGC_LOADING = 5.0  # full scale = 5 x RMS per component (14 dB back-off). At 4 x (12 dB) the rare clipped
# OFDM peaks of the strong direct signal cost ~0.5 dB even at 16 bits; at 5 x the loss is gone.


def quantize(x, bits, loading=AGC_LOADING):
    """AGC + uniform quantiser: full scale = `loading` x the per-component RMS."""
    if bits is None:
        return x
    sigma = np.sqrt(np.mean(np.abs(x) ** 2) / 2)
    q = (2 ** (bits - 1)) / (loading * sigma)
    lim = 2 ** (bits - 1)
    re = np.clip(np.round(x.real * q), -lim, lim - 1)
    im = np.clip(np.round(x.imag * q), -lim, lim - 1)
    return ((re + 1j * im) / q).astype(np.complex64)


def fir_weights(ref, surv, n_taps):
    """Least-squares canceller taps (what the host computes from a short snapshot and loads into the FPGA)."""
    from scipy import fft as sfft
    from scipy.linalg import solve_toeplitz

    r, s = ref.astype(np.complex128), surv.astype(np.complex128)
    nfft = sfft.next_fast_len(len(r) + n_taps)
    fr = sfft.fft(r, nfft)
    c = sfft.ifft(np.conj(fr) * fr)[:n_taps]
    p = sfft.ifft(np.conj(fr) * sfft.fft(s, nfft))[:n_taps]
    c[0] *= 1 + 1e-6
    return solve_toeplitz((c, np.conj(c)), p)


def apply_fir(ref, surv, w):
    """surv - (ref * w): the fixed FIR canceller the FPGA runs on every surveillance channel."""
    return (surv - np.convolve(ref, w)[: len(ref)]).astype(np.complex64)


def target_snr_db(ref, surv, fs, tgt_delay, tgt_dopp, n_range=256, n_seg=128, eca_taps=160):
    clean = eca(ref, surv, eca_taps)
    m, dopp, _ = caf(ref, clean, fs, n_range, n_seg)
    p = np.abs(m) ** 2
    di = int(np.argmin(np.abs(dopp - tgt_dopp)))
    ri = int(round(tgt_delay))
    peak = p[di - 1:di + 2, ri - 1:ri + 2].max()
    mask = np.ones_like(p, bool)
    mask[di - 4:di + 5, ri - 4:ri + 5] = False
    mask[np.abs(dopp) < 10.0, :] = False  # zero-Doppler notch
    return 10 * np.log10(peak / np.mean(p[mask]))


FPGA_TAPS = 128  # canceller length: 128 samples = 4.2 km of bistatic range at 9.14 MS/s


def precision_study(dsi_list=(43.8, 53.3), n=1 << 19, seeds=(7, 8, 9)):
    """Target SNR loss vs. full precision for each re-quantisation scheme, averaged over `seeds`."""
    lb = LinkBudget()
    fs = FS_DVBT
    tgt_delay, tgt_dopp = 180.0, 150.3
    tgt_caf_snr = 35.0  # strong enough that noise on the peak itself does not blur the comparison
    tgt_snr = tgt_caf_snr - 10 * np.log10(n)
    print(f"\nPrecision study: {n:,}-sample CPI, ECA 160 taps on the host, FPGA canceller {FPGA_TAPS} taps,"
          f" mean of {len(seeds)} runs. Target SNR change vs. floating point (negative = loss):")
    schemes = [("12-bit all channels", 12, 12, None), ("10-bit all channels", 10, 10, None),
               ("8-bit all channels", 8, 8, None),
               ("FPGA cancel (12-bit in), surv -> 8-bit, ref 12-bit", 12, 8, FPGA_TAPS),
               ("FPGA cancel (12-bit in), surv -> 6-bit, ref 12-bit", 12, 6, FPGA_TAPS)]
    results = {}
    for dsi in dsi_list:
        loss = {name: [] for name, *_ in schemes}
        resid = []
        for seed in seeds:
            rng = np.random.default_rng(seed)
            base_paths = [Path("direct", 0.0, 0.0, dsi, 0.0)]
            for k in range(8):  # static ground clutter, as in run_demo.py
                base_paths.append(Path(f"clutter{k}", float(rng.integers(3, 120)), 0.0,
                                       float(rng.uniform(10, 35)), 0.0))
            tgt = Path("drone", tgt_delay, tgt_dopp, tgt_snr, 0.0)
            ref_snr = min(lb.ref_snr_db(15e3), 50.0)  # multipath-limited reference, as in run_demo
            # training snapshot (same static channel, independent signal) for the FPGA canceller taps
            r_tr, s_tr = simulate_receiver(dvbt_like_ofdm(1 << 16, rng), base_paths, 1, fs, ref_snr, rng)
            ref, surv = simulate_receiver(dvbt_like_ofdm(n, rng), base_paths + [tgt], 1, fs, ref_snr, rng)
            surv = surv[0]
            base = target_snr_db(ref, surv, fs, tgt_delay, tgt_dopp)
            for name, b_in, b_out, taps in schemes:
                rq, sq = quantize(ref, b_in), quantize(surv, b_in)
                if taps:
                    w = fir_weights(quantize(r_tr, b_in), quantize(s_tr[0], b_in), taps)
                    residual = apply_fir(rq, sq, w)
                    resid.append(10 * np.log10(np.mean(np.abs(residual) ** 2)))
                    sq = quantize(residual, b_out)
                loss[name].append(target_snr_db(rq, sq, fs, tgt_delay, tgt_dopp) - base)
        print(f"  direct signal {dsi:.1f} dB above noise "
              f"(after the FPGA canceller the surveillance residual is {np.mean(resid):.1f} dB above noise):")
        for name, *_ in schemes:
            v = np.array(loss[name])
            results[(dsi, name)] = v.mean()
            print(f"    {name:<52} {v.mean():+5.1f} dB  (runs {' '.join(f'{x:+.1f}' for x in v)})")
    return results


if __name__ == "__main__":
    budget_table()
    precision_study()
