"""End-to-end test of the micro-Doppler path: simulated UHF scene -> bit-true FPGA (canceller + md engine)
-> ARM classifier.

    python firmware/sim/test_e2e.py [seconds]

Scene (8 MS/s, DVB-T-like noise reference at -14 dBFS, 12-bit ADCs, 4-element ULA with d = 0.36 lambda):
  direct signal +44 dB above noise in every surveillance channel, 3 static clutter echoes,
  slot 0: far quadcopter (4 two-blade rotors ~100 rev/s, rotor echo -12 dB), echo -40 dB/sample, 300 samples, +20 deg
  slot 1: bird (6 Hz wing beat), 450 samples, -35 deg, -45 Hz
  slot 2: cued gate with no target (700 samples, 0 deg)
  slot 3: near quadcopter, echo -34 dB/sample (about half the distance), 220 samples, -10 deg, -80 Hz
The host's canceller taps come from a least-squares fit on a raw snapshot, quantised to Q2.16 as in the FPGA.
At UHF most rotor energy falls on the body line; a single rotor line is ~28 dB below the body, so the far quad
(body ~31 dB per 0.5 s segment) builds up z slowly (z_far 5.5 after 8 s) while the near one is quick.
Pass: slot 3 -> UAV, slot 1 -> bird, slot 2 -> no signal, slot 0 -> UAV / unknown / pending (never bird).
"""
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
sys.path.insert(0, os.path.join(HERE, "..", "ps"))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import fixedpoint as fx  # noqa: E402
from hw import SimRegs  # noqa: E402
from md_classifier import TargetMd  # noqa: E402
from pcl.micro_doppler import RotorSignature, WingBeatSignature, quadcopter_rotors  # noqa: E402

FS = 8e6
BLOG2 = 11
NCH = 4
D_LAMBDA = 0.36                    # 180 mm pitch at 600 MHz
LAM = 0.5
K = 0.9 * 4 * np.pi / LAM          # bistatic wave number
REF_RMS = 410.0                    # -14 dBFS on a 12-bit ADC
CHUNK = 1 << 19                    # 65.5 ms, a whole number of md blocks
RNG = np.random.default_rng(3)


def steer(az):
    return np.exp(1j * 2 * np.pi * D_LAMBDA * np.arange(NCH) * np.sin(np.radians(az)))


class Scene:
    def __init__(self):
        self.noise_rms = REF_RMS * 0.8 / 10 ** (44 / 20)            # direct (0.8 x ref) is +44 dB above noise
        self.direct = 0.8 * steer(70) * np.exp(1j * RNG.uniform(0, 2 * np.pi, NCH))
        self.clutter = [(d, a * steer(RNG.uniform(-80, 80))) for d, a in ((3, 0.05), (17, 0.02), (60, 0.01))]
        echo = self.noise_rms * 10 ** (-40 / 20) / REF_RMS            # body echo -40 dB below noise per sample
        self.targets = [
            {"tau": 300, "az": 20.0, "fd": 65.0, "amp": echo, "sig": RotorSignature(quadcopter_rotors(RNG), rel_power_db=-12.0)},
            {"tau": 450, "az": -35.0, "fd": -45.0, "amp": echo * 1.4,
             "sig": WingBeatSignature(beat_hz=6.0, excursion_m=0.12, am_depth=0.3, rel_power_db=-3.0)},
            {"tau": 220, "az": -10.0, "fd": -80.0, "amp": echo * 2.0, "sig": RotorSignature(quadcopter_rotors(RNG), rel_power_db=-12.0)},
        ]
        self.prev = np.zeros(1024, complex)
        self.n = 0

    def chunk(self, n):
        ref = (RNG.normal(size=n) + 1j * RNG.normal(size=n)) * REF_RMS / np.sqrt(2)
        r = np.concatenate([self.prev, ref])
        P = len(self.prev)
        t = (self.n + np.arange(n)) / FS
        s = np.outer(self.direct, ref)
        for d, a in self.clutter:
            s += np.outer(a, r[P - d: P - d + n])
        for tg in self.targets:
            # modulation on a 4 kHz grid, held (the micro-Doppler is far below the block rate)
            tc = t[::256]
            m = np.repeat(tg["sig"].modulation(tc, K, K), 256)[:n]
            e = tg["amp"] * m * np.exp(1j * 2 * np.pi * tg["fd"] * t) * r[P - tg["tau"]: P - tg["tau"] + n]
            s += np.outer(steer(tg["az"]), e)
        s += (RNG.normal(size=s.shape) + 1j * RNG.normal(size=s.shape)) * self.noise_rms / np.sqrt(2)
        self.prev = r[-P:]
        self.n += n
        q = lambda x: np.clip(np.round(x), -2048, 2047).astype(np.int64)
        return q(ref.real), q(ref.imag), q(s.real), q(s.imag)


def main(seconds=4.0):
    t0 = time.time()
    scene = Scene()
    hw = SimRegs(nch=NCH)
    # out_shift: noise sums to ~5e4 per 2048-sample block here; 4 keeps it ~3e3, far from the 32-bit limit
    hw.configure(cpi_len=2_000_000, sv_shift=0, ref_shift=0, block_log2=BLOG2, out_shift=4)
    # host: least-squares taps from a raw snapshot, quantised as loaded into the FPGA
    ri, rq, si, sq = scene.chunk(CHUNK)
    ref = ri + 1j * rq
    for c in range(NCH):
        h = fx.ls_taps(ref[:65536].astype(complex), (si[c] + 1j * sq[c])[:65536].astype(complex), 128)
        hw.load_taps(c, *fx.to_fixed(h, fx.CANC_TAP_FRAC, fx.CANC_TAP_BITS))
    hw.commit_taps()
    # host tracker cues: slot 0 quad, 1 bird, 2 empty gate
    cues = [(300, 20.0), (450, -35.0), (700, 0.0), (220, -10.0)]
    for slot, (tau, az) in enumerate(cues):
        wi, wq = fx.steering_weights(az, NCH, D_LAMBDA)
        hw.set_target(slot, tau, wi, wq, True)
    hw.commit_targets()

    fs_slow = FS / (1 << BLOG2)
    cls = {slot: TargetMd(fs_slow) for slot in range(len(cues))}
    supp = []
    nchunks = int(seconds * FS // CHUNK)
    for k in range(nchunks):
        if k:
            ri, rq, si, sq = scene.chunk(CHUNK)
        yi, yq = hw.push(ri, rq, si, sq)
        supp.append(10 * np.log10(np.mean(np.abs(si + 1j * sq) ** 2) / np.mean(np.abs(yi + 1j * yq) ** 2)))
        rec, lost = hw.read_md()
        for slot in cls:
            m = rec["tgt"] == slot
            cls[slot].feed(rec["blk"][m], rec["y"][m])
    out = {slot: c.report() for slot, c in cls.items()}
    expect = {0: {"UAV", "unknown", "pending"}, 1: {"bird"}, 2: {"no signal"}, 3: {"UAV"}}
    ok = all(out[s]["class"] in expect[s] for s in expect)
    print(f"{nchunks * CHUNK / FS:.2f} s simulated in {time.time() - t0:.0f} s; slow-time rate {fs_slow:.0f} Hz; "
          f"direct-signal suppression in the FPGA canceller {np.mean(supp[1:]):.1f} dB")
    for s, r in out.items():
        print(f"  slot {s}: {r['class']:9s} looks {r['looks']:3d}  z_near {r['z_near']:7.1f}  z_far {r['z_far']:7.1f}  "
              f"body {r['body_doppler_hz']:7.1f} Hz at {r['body_snr_db']:5.1f} dB  strongest rotor line {r['rotor_line_hz']:6.1f} Hz")
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(float(sys.argv[1]) if len(sys.argv) > 1 else 4.0) else 1)
