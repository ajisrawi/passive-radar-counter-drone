"""Drone vs bird classification from micro-Doppler.

For every detection, the per-element CAF is beamformed toward the detected
direction and the Doppler spectrum of the target's range cell is stored,
centred on the body line (in units of the noise floor).

Over a track these spectra are averaged. Two bands are tested:

    near band  12-30 Hz from the body : wing-beat sidebands (birds)
    far band   40-700 Hz from the body: rotor / propeller blade lines (UAVs)

At UHF, blades (~0.1 m) are short compared with the wavelength (0.5 m), so rotor
energy concentrates in a few harmonic lines at multiples of the blade rate
instead of a broad smear. The test therefore looks for the strongest symmetric
line (rotors give equal lines at +f and -f): averaging over K looks makes the
noise per bin shrink as 1/sqrt(K) while stable lines stay put.
"""
import numpy as np

from .signal_model import steering

NEAR_BAND_HZ = (12.0, 30.0)
FAR_BAND_HZ = (40.0, 700.0)
ZERO_DOPPLER_GUARD_HZ = 8.0


def micro_doppler_features(cafs, doppler, di, ri, angle_rel_deg, exclude_cells=5):
    n_el = cafs.shape[0]
    a = steering(angle_rel_deg, n_el) / n_el
    beam = np.abs(np.tensordot(np.conj(a), cafs, axes=1)) ** 2  # [n_doppler, n_range]

    # Noise per bin: median of exponential = N0 ln 2, from cells away from the target
    cols = np.ones(beam.shape[1], bool)
    cols[max(ri - exclude_cells, 0): ri + exclude_cells + 1] = False
    rows = np.abs(doppler) > ZERO_DOPPLER_GUARD_HZ
    n0 = np.median(beam[np.ix_(rows, cols)]) / np.log(2)

    spec = beam[:, ri] / n0
    off = doppler - doppler[di]
    usable = np.abs(doppler) > ZERO_DOPPLER_GUARD_HZ

    def band(lo, hi):
        m = usable & (np.abs(off) >= lo) & (np.abs(off) <= hi)
        return float(np.sum(spec[m] - 1.0)), int(m.sum())

    near_x, near_n = band(*NEAR_BAND_HZ)
    far_x, far_n = band(*FAR_BAND_HZ)
    centred = np.roll(spec, len(spec) // 2 - di)
    centred_usable = np.roll(usable, len(spec) // 2 - di)
    centred[~centred_usable] = np.nan  # zero-Doppler clutter notch carries no information
    return {
        "body_snr_db": float(10 * np.log10(spec[di])),
        "near_excess": near_x, "near_n": near_n,
        "far_excess": far_x, "far_n": far_n,
        "spectrum": centred,  # body at index len//2, noise floor = 1
        "bin_hz": float(doppler[1] - doppler[0]),
    }


def _line_z(mean_spec, counts, offsets, lo, hi):
    """Strongest symmetric line in a band, as a z-score against averaged noise."""
    c = len(mean_spec) // 2
    best = 0.0
    for k in np.nonzero((offsets >= lo) & (offsets <= hi))[0]:
        j = 2 * c - k  # mirror bin (-f)
        if not (0 <= j < len(mean_spec)) or counts[k] == 0 or counts[j] == 0:
            continue
        excess = (mean_spec[k] - 1) + (mean_spec[j] - 1)
        sigma = np.sqrt(1 / counts[k] + 1 / counts[j])  # exponential noise: std = mean / sqrt(K)
        best = max(best, excess / sigma)
    return float(best)


def track_scores(features_list):
    """(z_near, z_far): strongest symmetric line in each band of the track-averaged spectrum."""
    S = np.array([f["spectrum"] for f in features_list])
    counts = np.sum(~np.isnan(S), axis=0)
    mean_spec = np.where(counts > 0, np.nansum(S, axis=0) / np.maximum(counts, 1), 1.0)
    offsets = (np.arange(S.shape[1]) - S.shape[1] // 2) * features_list[0]["bin_hz"]
    return (_line_z(mean_spec, counts, offsets, *NEAR_BAND_HZ),
            _line_z(mean_spec, counts, offsets, *FAR_BAND_HZ))


def classify_track(features_list, speed_mps=None, z_thresh=6.0, min_looks=8):
    """Noise-only Monte Carlo: P(z > 6) = 0.5% at 4 looks, < 0.25% at >= 10 looks."""
    """Return (class, z_near, z_far)."""
    z_near, z_far = track_scores(features_list)
    if len(features_list) < min_looks:
        return "pending", z_near, z_far
    if z_far > z_thresh:
        return "UAV", z_near, z_far
    if z_near > z_thresh:
        return "bird", z_near, z_far
    return "unknown", z_near, z_far
