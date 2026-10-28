"""Antenna design for the multiband passive radar (TV + 4G + 5G).

    python hardware/antenna/antenna_design.py

Per band group (the four Board A2 builds) one site needs:
  * a surveillance panel: 4 slant-45 printed dipoles over a flanged reflector, a uniform linear array at
    lambda/2 of the band top (Board A2 CH1..CH4);
  * a reference antenna: a printed log-periodic dipole array (LPDA) aimed at the transmitter (CH0), and a
    second one for stack B when its transmitter is on another mast (CH5, the spare channel).

Everything here is closed-form (design equations + array factor). Impedance and front-to-back must be
confirmed on a VNA / with a far-field test, using the trim allowances listed in the output.

Outputs (next to this file): design.json, DIMENSIONS.md, patterns_<band>.png, panel_<band>.png, lpda_<name>.png
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
C0 = 299_792_458.0

# Board A2 builds: pass band (MHz) and the array spacing already fixed in DESIGN.md (lambda/2 at band top)
BANDS = {
    "uhf": {"f": (470e6, 821e6), "services": "DVB-T 470-694, LTE B28/B20, 5G n28", "d_mm": 180.0},
    "mid": {"f": (1805e6, 2170e6), "services": "LTE B3, B1", "d_mm": 69.0},
    "high": {"f": (2496e6, 2690e6), "services": "LTE B7, 5G n41", "d_mm": 56.0},
    "n78": {"f": (3300e6, 3800e6), "services": "5G n78", "d_mm": 39.0},
}
N_ELEM = 4
SLANT_DEG = 45.0

# element substrate: JLCPCB FR-4, 1.6 mm, 1 oz
ER, H_SUB, T_CU = 4.4, 1.6e-3, 35e-6
TAN_D = 0.02


# ---------------------------------------------------------------- transmission lines (Hammerstad-Jensen)
def microstrip_z0(w, h=H_SUB, er=ER):
    u = w / h
    ee = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / u)
    if u <= 1:
        z = 60 / math.sqrt(ee) * math.log(8 / u + u / 4)
    else:
        z = 120 * math.pi / (math.sqrt(ee) * (u + 1.393 + 0.667 * math.log(u + 1.444)))
    return z, ee


def microstrip_width(z0, h=H_SUB, er=ER):
    lo, hi = 0.05e-3, 20e-3
    for _ in range(80):
        mid = (lo + hi) / 2
        if microstrip_z0(mid, h, er)[0] > z0:
            lo = mid
        else:
            hi = mid
    w = (lo + hi) / 2
    return w, microstrip_z0(w, h, er)[1]


# ---------------------------------------------------------------- slant dipole over a reflector
def printed_dipole_eeff(w_arm, lam):
    """Effective permittivity seen by a strip dipole printed on one face of a thin substrate.
    Empirical fill factor for a strip on a thin board in air (fringing mostly in air)."""
    q = 0.5 * (1 - math.exp(-6 * H_SUB / max(w_arm, H_SUB)))  # ~0.14 for wide arms on 1.6 mm
    return 1 + (ER - 1) * q * 0.5


def element(band):
    f1, f2 = BANDS[band]["f"]
    fc = math.sqrt(f1 * f2)
    lc = C0 / fc
    frac_bw = (f2 - f1) / fc
    wideband = frac_bw > 0.35
    # wide arms for bandwidth: ~0.08 lambda for the 54 % UHF band, ~0.05 lambda for the narrower bands
    w_arm = lc * (0.085 if wideband else 0.05)
    ee = printed_dipole_eeff(w_arm, lc)
    # resonant length of a fat dipole: 0.47 lambda shortened by width (Balanis end effect) and substrate.
    # UHF (54 % band): a bowtie (arms flare from w_arm at the gap to 2 x w_arm at the tips) resonating at
    # 0.9 fc, so the bottom of the TV band is not far below resonance; a bowtie stays matched well above it.
    f_res = 0.9 * fc if wideband else fc
    l_res = C0 / f_res
    shorten = 1 - 0.6 * (w_arm / l_res)
    L = 0.47 * l_res * shorten / math.sqrt(ee)
    gap = max(1.0e-3, 0.01 * lc)
    h = lc / 4  # dipole above reflector
    # reflector: width >= 0.8 lambda_low across, flanges 0.15 lambda_c for >= 20 dB front-to-back
    l_low = C0 / f1
    refl_w = max(0.8 * lc, 0.65 * l_low)
    flange = 0.15 * lc
    w50, ee50 = microstrip_width(50.0)
    lg = lc / math.sqrt(ee50)
    return {
        "fc_MHz": round(fc / 1e6, 1), "lambda_c_mm": round(lc * 1e3, 1), "fractional_bw_pct": round(frac_bw * 100, 1),
        "arm_shape": "bowtie: width w at the feed gap flaring to 2w at the tips" if wideband else "straight strip",
        "resonance_MHz": round(f_res / 1e6, 1),
        "expected_match": ("VSWR < 2 over ~520-821 MHz, < 3 at 470 MHz (about 1.2 dB mismatch loss at the band bottom)"
                           if wideband else "VSWR < 2 across the band (fractional bandwidth well inside a fat printed dipole's ~25 %)"),
        "dipole_length_mm": round(L * 1e3, 1), "arm_width_mm": round(w_arm * 1e3, 1), "feed_gap_mm": round(gap * 1e3, 1),
        "height_above_reflector_mm": round(h * 1e3, 1),
        "balun": {
            "type": "microstrip-to-parallel-strip taper (double-sided printed dipole): F.Cu 50 ohm strip widens, "
                    "B.Cu ground narrows, both to the parallel-strip width, over the stem height (~lambda/4)",
            "stem_length_mm": round(h * 1e3, 1),
            "microstrip_50ohm_width_mm_formula": round(w50 * 1e3, 2),
            "microstrip_50ohm_width_mm_field_solved": "see pcb/pcb_report.json (2.81 mm)",
            "parallel_strip_width_mm": 4.0,
            "stem_ground_width_mm": 12.0,
            "lambda_g_mm": round(lg * 1e3, 1),
        },
        "board_mm": [round((L + 2 * 2e-3) * 1e3, 1), round((h + w_arm + 3e-3) * 1e3, 1)],
        "trim": "arms are drawn 3 % long: trim both ends equally for resonance at fc; trim the open stub for match",
        "reflector_width_mm": round(refl_w * 1e3, 1),
        "flange_height_mm": round(flange * 1e3, 1),
        "_si": {"L": L, "h": h, "fc": fc, "f1": f1, "f2": f2},
    }


def dipole_pattern(theta_axis, L, k):
    """Far field of a thin centre-fed dipole (sinusoidal current); theta_axis from the dipole axis."""
    s = np.sin(theta_axis)
    s = np.where(np.abs(s) < 1e-6, 1e-6, s)
    return (np.cos(k * L / 2 * np.cos(theta_axis)) - np.cos(k * L / 2)) / s


def element_field(az, el, L, h, f):
    """Co-polar field of the slant dipole at height h over an infinite reflector (image theory).
    Coordinates: x = array axis (horizontal), y = up, z = boresight. az/el in radians."""
    k = 2 * math.pi * f / C0
    ux = np.cos(el) * np.sin(az)
    uy = np.sin(el)
    uz = np.cos(el) * np.cos(az)
    a = np.array([math.cos(math.radians(SLANT_DEG)), math.sin(math.radians(SLANT_DEG)), 0.0])
    cpsi = np.clip(ux * a[0] + uy * a[1], -1, 1)
    F = dipole_pattern(np.arccos(cpsi), L, k)
    G = 2 * np.sin(k * h * np.clip(uz, 0, None))  # image factor, zero in the back half-space
    return np.abs(F * G)


def directivity_dbi(L, h, f, n=181):
    az = np.linspace(-math.pi / 2, math.pi / 2, n)
    el = np.linspace(-math.pi / 2, math.pi / 2, n)
    A, E = np.meshgrid(az, el)
    P = element_field(A, E, L, h, f) ** 2
    dA = (az[1] - az[0]) * (el[1] - el[0])
    prad = np.sum(P * np.cos(E)) * dA
    return 10 * math.log10(4 * math.pi * P.max() / prad)


def hpbw_deg(ang_deg, p_db):
    i0 = int(np.argmax(p_db))
    m = p_db[i0] - 3
    lo = i0
    while lo > 0 and p_db[lo] > m:
        lo -= 1
    hi = i0
    while hi < len(p_db) - 1 and p_db[hi] > m:
        hi += 1
    return float(ang_deg[hi] - ang_deg[lo])


def array_analysis(band, el):
    d = BANDS[band]["d_mm"] * 1e-3
    L, h = el["_si"]["L"], el["_si"]["h"]
    az = np.radians(np.linspace(-90, 90, 3601))
    out = {}
    for tag, f in (("f_low", el["_si"]["f1"]), ("f_c", el["_si"]["fc"]), ("f_high", el["_si"]["f2"])):
        k = 2 * math.pi * f / C0
        ep = element_field(az, np.zeros_like(az), L, h, f)
        ep_db = 20 * np.log10(ep / ep.max() + 1e-12)
        res = {"freq_MHz": round(f / 1e6, 1), "d_over_lambda": round(d * f / C0, 3),
               "element_gain_dBi": round(directivity_dbi(L, h, f) - 0.8, 1),  # 0.8 dB: FR-4, balun, finite reflector
               "element_hpbw_az_deg": round(hpbw_deg(np.degrees(az), ep_db), 1),
               "element_gain_at_60deg_dB": round(float(np.interp(math.radians(60), az, ep_db)), 1)}
        for steer in (0, 30, 50):
            s = math.radians(steer)
            n = np.arange(N_ELEM) - (N_ELEM - 1) / 2
            af = np.abs(np.exp(1j * k * d * np.outer(np.sin(az) - math.sin(s), n)).sum(axis=1)) / N_ELEM
            tot = 20 * np.log10(af * ep / ep.max() + 1e-12)
            # strongest lobe that is not the main beam = grating / side lobe level
            # main beam = between its first nulls: |sin(az) - sin(steer)| < lambda / (N d)
            main = np.abs(np.sin(az) - math.sin(s)) < C0 / f / (N_ELEM * d)
            res[f"steer_{steer}"] = {
                "beam_hpbw_deg": round(hpbw_deg(np.degrees(az), 20 * np.log10(af + 1e-12)), 1),
                # full pattern (element x array), relative to its own peak
                "sidelobe_dB": round(float(tot[~main].max() - tot[main].max()), 1),
                "scan_loss_dB": round(float(-np.interp(s, az, ep_db)), 1),
            }
        # grating lobe free scan limit: d/lambda < 1/(1+sin(theta))
        dl = d * f / C0
        res["grating_free_scan_deg"] = 90.0 if dl <= 0.5 else round(math.degrees(math.asin(1 / dl - 1)), 1)
        out[tag] = res
    return out


# ---------------------------------------------------------------- LPDA reference antennas (Carrel)
def lpda(name, fmin, fmax, tau=0.88, sigma=0.16, z_line=100.0):
    alpha = math.atan((1 - tau) / (4 * sigma))
    B = fmax / fmin
    Bar = 1.1 + 7.7 * (1 - tau) ** 2 / math.tan(alpha)
    Bs = B * Bar
    N = int(math.ceil(1 + math.log(Bs) / math.log(1 / tau)))
    lmax = C0 / fmin
    # printed on FR-4 with the two half-elements on opposite faces: mild shortening; metal rods: none
    shorten = 1 / math.sqrt(1.12) if fmax > 1e9 else 0.97
    L = [lmax / 2 * shorten * tau ** i for i in range(N)]
    R = [L[i] / (2 * math.tan(alpha)) for i in range(N)]  # distance from the virtual apex
    spacing = [R[i] - R[i + 1] for i in range(N - 1)]
    boom = R[0] - R[-1]
    wf, _ = microstrip_width(50.0)
    return {
        "name": name, "f_MHz": [fmin / 1e6, fmax / 1e6], "tau": tau, "sigma": sigma,
        "alpha_deg": round(math.degrees(alpha), 2), "elements": N,
        "element_lengths_mm": [round(x * 1e3, 1) for x in L],
        "spacings_mm": [round(x * 1e3, 1) for x in spacing],
        "boom_length_mm": round(boom * 1e3, 1),
        "gain_dBi_approx": 7.5,
        "front_to_back_dB_approx": 18,
        "build": ("aluminium: two 12 mm square booms 8 mm apart, 4 mm rod half-elements alternating between booms; "
                  "RG-316/RG-402 coax run inside one boom (infinite balun), shield to that boom, centre to the other at the "
                  "short end; booms shorted at the long end. Element lengths are for rods (no substrate shortening)."
                  if fmax < 1e9 else
                  "printed twin-boom on FR-4 1.6 mm: half-elements on alternating faces; fed at the short end by a "
                  f"50 ohm microstrip ({wf*1e3:.2f} mm) running inside the top boom (infinite balun), shorted at the long end"),
        "boom_width_mm": round(max(3 * wf, 0.01 * lmax) * 1e3, 1),
        "board_mm": [round((boom + 0.02) * 1e3, 1), round((L[0] + 0.02) * 1e3, 1)],
        "mount": "slant 45 deg, aimed at the transmitter; elevation tilt toward the transmitter mast",
    }


# ---------------------------------------------------------------- plots
def plot_patterns(band, el):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = BANDS[band]["d_mm"] * 1e-3
    L, h = el["_si"]["L"], el["_si"]["h"]
    az = np.radians(np.linspace(-90, 90, 721))
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    for f, sty in ((el["_si"]["f1"], ":"), (el["_si"]["fc"], "-"), (el["_si"]["f2"], "--")):
        k = 2 * math.pi * f / C0
        ep = element_field(az, np.zeros_like(az), L, h, f)
        ep_db = 20 * np.log10(ep / ep.max() + 1e-12)
        ax[0].plot(np.degrees(az), ep_db, sty, label=f"{f/1e6:.0f} MHz")
        n = np.arange(N_ELEM) - (N_ELEM - 1) / 2
        for steer, col in ((0, "C0"), (45, "C3")):
            s = math.radians(steer)
            af = np.abs(np.exp(1j * k * d * np.outer(np.sin(az) - math.sin(s), n)).sum(axis=1)) / N_ELEM
            ax[1].plot(np.degrees(az), 20 * np.log10(af * ep / ep.max() + 1e-12), sty, color=col,
                       label=f"{f/1e6:.0f} MHz, steer {steer}°")
    for a, t in zip(ax, ("Element (slant ±45° dipole over reflector), azimuth", f"4-element array, d = {d*1e3:.0f} mm")):
        a.set_ylim(-30, 1)
        a.set_xlim(-90, 90)
        a.set_xlabel("azimuth from boresight (°)")
        a.set_ylabel("relative gain (dB)")
        a.set_title(t, fontsize=10)
        a.grid(alpha=0.3)
        a.legend(fontsize=7)
    fig.suptitle(f"Surveillance panel '{band}' ({BANDS[band]['services']}) - front half-space, infinite-reflector model")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, f"patterns_{band}.png"), dpi=110)
    plt.close(fig)


def plot_panel(band, el):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = BANDS[band]["d_mm"]
    L = el["dipole_length_mm"]
    w = el["arm_width_mm"]
    rw = el["reflector_width_mm"]
    span = (N_ELEM - 1) * d
    rl = span + max(rw * 0.75, d)  # reflector length: half a reflector width past the end elements
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.add_patch(plt.Rectangle((-rl / 2, -rw / 2), rl, rw, fc="#d9d9d9", ec="k"))
    ax.add_patch(plt.Rectangle((-rl / 2, -rw / 2), rl, rw, fc="none", ec="k", lw=3, ls="--"))
    c, s = math.cos(math.radians(SLANT_DEG)), math.sin(math.radians(SLANT_DEG))
    for i in range(N_ELEM):
        x0 = -span / 2 + i * d
        for sign in (-1, 1):
            # one arm, as a rotated rectangle from the centre gap outwards
            x1, y1 = x0 + sign * c * el["feed_gap_mm"] / 2, sign * s * el["feed_gap_mm"] / 2
            arm = (L - el["feed_gap_mm"]) / 2
            wt = 2 * w if el["arm_shape"].startswith("bowtie") else w
            pts = np.array([[0, -w / 2], [arm, -wt / 2], [arm, wt / 2], [0, w / 2]])
            rot = np.array([[c, -s], [s, c]]) * sign
            P = pts @ rot.T + [x1, y1]
            ax.add_patch(plt.Polygon(P, fc="#c87533", ec="k"))
        ax.text(x0, -rw / 2 - 0.06 * rw, f"CH{i+1}", ha="center", va="top", fontsize=9)
    ax.annotate("", xy=(-span / 2, rw / 2 + 0.08 * rw), xytext=(-span / 2 + d, rw / 2 + 0.08 * rw),
                arrowprops=dict(arrowstyle="<->"))
    ax.text(-span / 2 + d / 2, rw / 2 + 0.1 * rw, f"d = {d:.0f}", ha="center", va="bottom", fontsize=9)
    ax.set_aspect("equal")
    ax.set_xlim(-rl / 2 - 0.1 * rl, rl / 2 + 0.1 * rl)
    ax.set_ylim(-rw / 2 - 0.25 * rw, rw / 2 + 0.25 * rw)
    ax.set_title(f"Panel '{band}', front view (mm): reflector {rl:.0f} × {rw:.0f}, flanges {el['flange_height_mm']:.0f} high "
                 f"(dashed), dipoles {L:.0f} long at +45°, {el['height_above_reflector_mm']:.0f} above reflector", fontsize=8)
    ax.set_xlabel("array axis (horizontal)")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, f"panel_{band}.png"), dpi=110)
    plt.close(fig)
    return round(rl, 0)


def plot_lpda(lp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4))
    x = 0.0
    xs = [0.0]
    for sp in lp["spacings_mm"]:
        x += sp
        xs.append(x)
    bw = lp["boom_width_mm"]
    ax.add_patch(plt.Rectangle((-5, -bw / 2), x + 10, bw, fc="#c87533", ec="k", alpha=0.6))
    for i, (xi, Li) in enumerate(zip(xs, lp["element_lengths_mm"])):
        sgn = 1 if i % 2 == 0 else -1
        ax.plot([xi, xi], [0, sgn * Li / 2], color="#c87533", lw=3)
        ax.plot([xi, xi], [0, -sgn * Li / 2], color="#7a4a20", lw=3, ls="--")
    ax.set_aspect("equal")
    ax.set_title(f"LPDA {lp['name']}: {lp['f_MHz'][0]:.0f}-{lp['f_MHz'][1]:.0f} MHz, {lp['elements']} dipoles, "
                 f"boom {lp['boom_length_mm']:.0f} mm (solid = top face, dashed = bottom face; feed at the short end)", fontsize=8)
    ax.set_xlabel("mm")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, f"lpda_{lp['name']}.png"), dpi=110)
    plt.close(fig)


def main():
    design = {"slant_deg": SLANT_DEG, "elements_per_panel": N_ELEM, "substrate": "FR-4 1.6 mm, er 4.4", "bands": {}}
    for band in BANDS:
        el = element(band)
        arr = array_analysis(band, el)
        plot_patterns(band, el)
        rl = plot_panel(band, el)
        el = {k: v for k, v in el.items() if not k.startswith("_")}
        design["bands"][band] = {"services": BANDS[band]["services"], "spacing_mm": BANDS[band]["d_mm"],
                                 "reflector_length_mm": rl, "element": el, "array": arr}
    design["lpda"] = [lpda("U", 450e6, 870e6), lpda("H", 1700e6, 4000e6)]
    for lp in design["lpda"]:
        plot_lpda(lp)
    json.dump(design, open(os.path.join(HERE, "design.json"), "w"), indent=1)
    print(json.dumps(design, indent=1))


if __name__ == "__main__":
    main()
