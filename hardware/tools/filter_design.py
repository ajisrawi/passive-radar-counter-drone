"""Board A band filter: 0.1 dB Chebyshev low-pass (5th order) + high-pass (3rd order), 50 ohm.

Pass band: DVB-T UHF 470-694 MHz. Stop bands: FM/DAB/VHF below, LTE800/GSM900 and up above.
Prints ideal and E-series values and the response with 0402 parasitics (Q ~ 40 L, ~ 300 C).
"""
import numpy as np

R0 = 50.0
G_LP5 = [1.1468, 1.3712, 1.9750, 1.3712, 1.1468]
G_HP3 = [1.0316, 1.1474, 1.0316]
E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]
L_AVAIL_NH = [1.5, 2.2, 3.3, 3.9, 4.7, 5.6, 6.8, 7.5, 8.2, 10, 12, 15, 18, 22, 27, 33, 39, 47]  # LQW15AN family


def nearest(v, series):
    dec = 10 ** np.floor(np.log10(v))
    cands = [s * dec for s in series] + [s * dec * 10 for s in series]
    return min(cands, key=lambda c: abs(np.log(c / v)))


def design(f_lp, f_hp):
    w_lp, w_hp = 2 * np.pi * f_lp, 2 * np.pi * f_hp
    lp = [("C_sh", G_LP5[0] / (w_lp * R0)), ("L_se", G_LP5[1] * R0 / w_lp), ("C_sh", G_LP5[2] / (w_lp * R0)),
          ("L_se", G_LP5[3] * R0 / w_lp), ("C_sh", G_LP5[4] / (w_lp * R0))]
    hp = [("C_se", 1 / (w_hp * R0 * G_HP3[0])), ("L_sh", R0 / (w_hp * G_HP3[1])), ("C_se", 1 / (w_hp * R0 * G_HP3[2]))]
    return hp + lp


def snap(elems):
    out = []
    for kind, v in elems:
        if kind.startswith("L"):
            out.append((kind, nearest(v * 1e9, L_AVAIL_NH) * 1e-9))
        else:
            out.append((kind, nearest(v * 1e12, E24) * 1e-12))
    return out


def s21_db(elems, f, q_l=40, q_c=300):
    w = 2 * np.pi * f
    A = np.ones_like(f, complex); B = np.zeros_like(f, complex); C_ = np.zeros_like(f, complex); D = np.ones_like(f, complex)
    for kind, v in elems:
        if kind[0] == "L":
            z = 1j * w * v + w * v / q_l
        else:
            z = 1 / (1j * w * v) + 1 / (w * v * q_c)
        if kind.endswith("se"):
            m = (np.ones_like(f), z, np.zeros_like(f), np.ones_like(f))
        else:
            m = (np.ones_like(f), np.zeros_like(f), 1 / z, np.ones_like(f))
        A, B, C_, D = A * m[0] + B * m[2], A * m[1] + B * m[3], C_ * m[0] + D * m[2], C_ * m[1] + D * m[3]
    s21 = 2 / (A + B / R0 + C_ * R0 + D)
    return 20 * np.log10(np.abs(s21))


if __name__ == "__main__":
    ideal = design(780e6, 420e6)
    real = snap(ideal)
    print("Element          ideal        chosen")
    for (k, v), (_, r) in zip(ideal, real):
        u, s = ("nH", 1e9) if k[0] == "L" else ("pF", 1e12)
        print(f"  {k:<6} {v*s:9.2f} {u}  {r*s:7.2f} {u}")
    pts = {"FM 100 MHz": 100e6, "DAB 220 MHz": 220e6, "470 MHz": 470e6, "550 MHz": 550e6, "694 MHz": 694e6,
           "LTE800 806 MHz": 806e6, "GSM900 940 MHz": 940e6, "1800 MHz": 1.8e9}
    f = np.array(list(pts.values()))
    s = s21_db(real, f)
    print("\nInsertion loss with 0402 parasitics (Q_L=40, Q_C=300):")
    for (name, _), v in zip(pts.items(), s):
        print(f"  {name:<16} {v:7.1f} dB")
