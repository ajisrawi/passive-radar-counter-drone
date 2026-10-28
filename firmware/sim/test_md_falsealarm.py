"""False-alarm rate of the on-board micro-Doppler classifier (firmware/ps/md_classifier.py) on targets with no
micro-Doppler: a pure body line (30 dB) in complex Gaussian noise, Monte Carlo over many tracks.

    python firmware/sim/test_md_falsealarm.py [trials]

Reports P(z_far > 6) and P(z_near > 6) at 8 and 20 looks; the decision threshold z = 6 is meant to keep each
under ~0.5 % (the host classifier's figure, pcl/classify.py).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ps"))
from md_classifier import TargetMd  # noqa: E402

FS = 3906.25


def trial(rng, n_looks):
    md = TargetMd(FS)
    n = md.nfft + (n_looks - 1) * md.hop
    t = np.arange(n) / FS
    fd = rng.uniform(-150, 150)
    if abs(fd) < 20:
        fd = 20 * np.sign(fd or 1)
    body = 10 ** (30 / 20) / np.sqrt(md.nfft * np.mean(np.hanning(md.nfft) ** 2)) * np.exp(1j * 2 * np.pi * fd * t)
    y = body + (rng.normal(size=n) + 1j * rng.normal(size=n)) / np.sqrt(2)
    md.feed(np.arange(n), y)
    r = md.report()
    return r["z_near"], r["z_far"], r["looks"]


def main(trials=400):
    rng = np.random.default_rng(11)
    out = {}
    for looks in (8, 20):
        z = np.array([trial(rng, looks)[:2] for _ in range(trials)])
        out[looks] = {"P(z_near>6)": float(np.mean(z[:, 0] > 6)), "P(z_far>6)": float(np.mean(z[:, 1] > 6)),
                      "z_far 99th pct": float(np.percentile(z[:, 1], 99))}
    ok = all(v["P(z_near>6)"] <= 0.01 and v["P(z_far>6)"] <= 0.01 for v in out.values())
    for k, v in out.items():
        print(f"  {k:2d} looks: {v}")
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(int(sys.argv[1]) if len(sys.argv) > 1 else 400) else 1)
