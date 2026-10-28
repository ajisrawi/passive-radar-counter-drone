"""Radomes for the surveillance panels and the LPDA-H reference: sizes from design.json, RF transmission through
the wall (exact multilayer slab, TE/TM, oblique incidence, slant polarization), and wind deflection of the front.

    python hardware/antenna/radome_design.py   -> radome.json, radome_transmission.png

Concept (like a base-station panel antenna):
  * aluminium back tray; the reflector is its front plate; elements stand on it; the SMAs and pigtails live in
    the tray behind the reflector; N-type bulkheads, drain and vent on the tray's bottom face;
  * a cover (radome) with a flat front face, gasketed flange screwed to the tray lip;
  * one radome per panel, so each band group stays a separate module (a site may not fit all four).
Formulas: transmission line (ABCD) model of plane-wave incidence on dielectric layers; Roark rectangular plate,
all edges fixed (the cover's side walls hold the front face's edges).
"""
import json
import math
import os

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "design.json")))
C0 = 299.792458  # mm * GHz

# typical datasheet values: confirm with the chosen supplier before release
MATERIALS = {
    "ASA": {"er": 3.0, "tand": 0.012, "E_GPa": 2.3, "sigma_MPa": 45, "rho": 1070, "note": "UV-stable, thermoformable sheet"},
    "PC": {"er": 2.9, "tand": 0.009, "E_GPa": 2.35, "sigma_MPa": 60, "rho": 1200, "note": "needs a UV-coated grade"},
    "GRP": {"er": 4.4, "tand": 0.016, "E_GPa": 17.0, "sigma_MPa": 200, "rho": 1850, "note": "glass/polyester, moulded or pultruded"},
}
WATER = {0.6: complex(80, -3), 2.0: complex(77, -10), 3.5: complex(74, -17)}   # er of water vs GHz (20 C)
ICE = complex(3.15, -0.003)

BANDS = {"uhf": (470, 821), "mid": (1805, 2170), "high": (2496, 2690), "n78": (3300, 3800)}
WIND_MS = 44.0          # 160 km/h design wind
CD = 1.3                # flat box, wind on the face

# cover choice per panel: material, wall t (mm)
CHOICE = {"uhf": ("GRP", 3.0), "mid": ("ASA", 2.5), "high": ("ASA", 2.5), "n78": ("ASA", 2.5)}


def water_er(f_ghz):
    ks = sorted(WATER)
    return complex(np.interp(f_ghz, ks, [WATER[k].real for k in ks]), np.interp(f_ghz, ks, [WATER[k].imag for k in ks]))


def slab(layers, f_ghz, theta_deg, pol):
    """complex transmission of stacked layers [(er, t_mm)] in air, relative to the same thickness of air"""
    k0 = 2 * math.pi * f_ghz / C0
    s = math.sin(math.radians(theta_deg))
    kz0 = k0 * math.cos(math.radians(theta_deg))
    z0 = 1 / kz0 if pol == "TE" else kz0          # wave impedance up to a common constant
    M = np.eye(2, dtype=complex)
    ttot = 0.0
    for er, t in layers:
        kz = k0 * np.sqrt(er - s * s + 0j)
        if kz.imag > 0:
            kz = -kz
        z = 1 / kz if pol == "TE" else kz / er
        d = kz * t
        M = M @ np.array([[np.cos(d), 1j * z * np.sin(d)], [1j * np.sin(d) / z, np.cos(d)]])
        ttot += t
    A, B, Cc, Dd = M.ravel()
    T = 2 / (A + B / z0 + Cc * z0 + Dd)
    return T * np.exp(1j * kz0 * ttot)


def slant(layers, f, th):
    """+45 deg slant wave, scanned in azimuth (plane of incidence horizontal): half TE, half TM"""
    te, tm = slab(layers, f, th, "TE"), slab(layers, f, th, "TM")
    co, x = (te + tm) / 2, (te - tm) / 2
    return {"loss_dB": -20 * math.log10(abs(co)), "xpd_dB": 20 * math.log10(abs(co) / max(abs(x), 1e-12)),
            "ipd_deg": -math.degrees(np.angle(co)), "te_dB": -20 * math.log10(abs(te)), "tm_dB": -20 * math.log10(abs(tm))}


def plate(q, a, b, t, E):
    """Roark Table 11.4 case 8 (all edges fixed), uniform pressure: max deflection and edge stress"""
    r = [(1.0, 0.0138, 0.3078), (1.2, 0.0188, 0.3834), (1.4, 0.0226, 0.4356), (1.6, 0.0251, 0.4680),
         (1.8, 0.0267, 0.4872), (2.0, 0.0277, 0.4974), (100, 0.0284, 0.5000)]
    ab = max(a, b) / min(a, b)
    b = min(a, b)
    al = np.interp(ab, [x[0] for x in r], [x[1] for x in r])
    be = np.interp(ab, [x[0] for x in r], [x[2] for x in r])
    return al * q * b ** 4 / (E * t ** 3), be * q * b * b / (t * t)


def design():
    q = 0.5 * 1.225 * WIND_MS ** 2
    out = {"wind_ms": WIND_MS, "wind_pressure_Pa": round(q), "materials": MATERIALS, "panels": {}}
    for band, b in D["bands"].items():
        el = b["element"]
        lam_c = el["lambda_c_mm"]
        lam_hi = C0 / (BANDS[band][1] / 1000)
        h_el = {"uhf": 164.7, "mid": 44.7, "high": 34.8, "n78": 26.3}[band]   # element top edge above reflector (ANTENNA.md)
        gap = max(12.0, round(0.06 * lam_c))          # element top -> inner front face
        side = 15.0 if band != "uhf" else 20.0        # reflector edge -> inner side wall
        mname, t = CHOICE[band]
        m = MATERIALS[mname]
        L, W = b["reflector_length_mm"], el["reflector_width_mm"]
        inner = (L + 2 * side, W + 2 * side, h_el + gap)             # x along the array, z vertical, y depth
        tray_d = 45.0 if band == "uhf" else 30.0
        outer = (inner[0] + 2 * t, inner[1] + 2 * t, inner[2] + t + tray_d + 3)  # + 3 mm flange/gasket
        w, sg = plate(q, inner[0] / 1000, inner[1] / 1000, t / 1000, m["E_GPa"] * 1e9)
        area_front = outer[0] * outer[1] / 1e6
        cover_area = (inner[0] * inner[1] + 2 * (inner[0] + inner[1]) * inner[2]) / 1e6
        tray_area = (outer[0] * outer[1] + 2 * (outer[0] + outer[1]) * tray_d) / 1e6
        mass = cover_area * t / 1000 * m["rho"] + tray_area * 0.002 * 2700 + L * W / 1e6 * 0.002 * 2700 + (3.0 if band == "uhf" else 1.0)
        rf = {}
        f_lo, f_hi = BANDS[band][0] / 1000, BANDS[band][1] / 1000
        for f in (f_lo, f_hi):
            for th in (0, 30, 50):
                dry = slant([(m["er"] * (1 - 1j * m["tand"]), t)], f, th)
                wet = slant([(water_er(f), 0.2), (m["er"] * (1 - 1j * m["tand"]), t)], f, th)
                ice = slant([(ICE, 10.0), (m["er"] * (1 - 1j * m["tand"]), t)], f, th)
                rf[f"{f * 1000:.0f}MHz_{th}deg"] = {"dry_loss_dB": round(dry["loss_dB"], 3), "dry_xpd_dB": round(dry["xpd_dB"], 1),
                                                     "wet_0.2mm_loss_dB": round(wet["loss_dB"], 2), "ice_10mm_loss_dB": round(ice["loss_dB"], 2),
                                                     "ipd_deg": round(dry["ipd_deg"], 1)}
        # phase error between elements from a +-0.2 mm thickness tolerance at band top, broadside
        p1 = slab([(m["er"] * (1 - 1j * m["tand"]), t - 0.2)], f_hi, 0, "TE")
        p2 = slab([(m["er"] * (1 - 1j * m["tand"]), t + 0.2)], f_hi, 0, "TE")
        out["panels"][band] = {
            "material": mname, "wall_mm": t, "thin_wall_ratio": round(t * math.sqrt(m["er"]) / lam_hi, 3),
            "element_height_mm": h_el, "front_gap_mm": gap, "side_clearance_mm": side,
            "cover_inner_mm": [round(x, 1) for x in inner], "tray_depth_mm": tray_d,
            "outer_LxHxD_mm": [round(outer[0]), round(outer[1]), round(outer[2])],
            "corner_radius_mm": 25 if band == "uhf" else 10, "flange_mm": 20 if band == "uhf" else 12,
            "screws": f"M5 A4 at <= 100 mm pitch, {2 * math.ceil((outer[0] + outer[1]) / 100)} total",
            "bulkheads": "4 x N-type female (S1-S4), bottom face; drain hole + pressure vent",
            "front_deflection_mm": round(w * 1000, 2), "front_stress_MPa": round(sg / 1e6, 1),
            "stress_safety_factor": round(m["sigma_MPa"] / (sg / 1e6), 1),
            "wind_load_N": round(CD * q * area_front), "mass_kg": round(mass, 1),
            "phase_spread_deg_for_pm0.2mm": round(abs(math.degrees(np.angle(p2 / p1))), 2),
            "rf": rf,
        }
    # LPDA-H paddle radome (PCB 180.1 x 89.3 mm, boom along x, short end forward)
    m = MATERIALS["ASA"]
    t = 2.0
    inner = (180.1 + 2 * 10, 89.3 + 2 * 8, 1.6 + 2 * 10)
    rf = {}
    for f in (1.7, 4.0):
        for th in (0, 50):
            r = slant([(m["er"] * (1 - 1j * m["tand"]), t)], f, th)
            rf[f"{f * 1000:.0f}MHz_{th}deg"] = {"dry_loss_dB": round(r["loss_dB"], 3), "dry_xpd_dB": round(r["xpd_dB"], 1)}
    out["lpda_h"] = {"material": "ASA", "wall_mm": t, "inner_mm": [round(x, 1) for x in inner],
                     "outer_mm": [round(inner[0] + 2 * t + 40), round(inner[1] + 2 * t), round(inner[2] + 2 * t)],
                     "build": "two-shell clamshell, PCB held in a slot in both shells; 40 mm solid rear stub clamps to a "
                              "25 mm GRP mast arm; cable out of the rear through an M12 gland on the boom centre line",
                     "rf": rf}
    out["lpda_u"] = {"build": "no radome: bare aluminium (anodised, stainless hardware), as for commercial UHF LPDAs. "
                              "Seal the feed end of the boom coax with adhesive-lined heat-shrink and a drain hole at the low point."}
    out["combined"] = combined(q)
    return out


def combined(q):
    """all four surveillance panels in one radome: UHF panel on top, the three 4G/5G panels in a row below,
    one tray, one GRP cover with a stepped wall (3 mm over UHF, 2 mm over the 4G/5G window) and an internal
    GRP rib between the two zones that halves the free span of the front face"""
    B = D["bands"]
    u = B["uhf"]
    Lu, Wu = u["reflector_length_mm"], u["element"]["reflector_width_mm"]
    side, gap_v, gap_h, t_u, t_s = 20.0, 60.0, 40.0, 3.0, 2.0
    small = ["mid", "high", "n78"]
    row = sum(B[b]["reflector_length_mm"] for b in small) + gap_h * (len(small) - 1)
    ws = max(B[b]["element"]["reflector_width_mm"] for b in small)
    ix = max(Lu, row) + 2 * side
    iz = side + Wu + gap_v + ws + side
    iy = 164.7 + max(12.0, round(0.06 * u["element"]["lambda_c_mm"]))
    zU = iz / 2 - side - Wu / 2
    zS = zU - Wu / 2 - gap_v - ws / 2
    zr = zU - Wu / 2 - gap_v / 2                                      # rib, in the gap between the zones
    xs, x = {}, -row / 2
    for b in small:
        L = B[b]["reflector_length_mm"]
        xs[b] = round(x + L / 2, 1)
        x += L + gap_h
    fl, td = 20.0, 45.0
    ox, oz = ix + 2 * t_u, iz + 2 * t_u
    grp = MATERIALS["GRP"]
    span_u, span_s = iz / 2 - zr, zr + iz / 2
    w_u, s_u = plate(q, ix / 1000, span_u / 1000, t_u / 1000, grp["E_GPa"] * 1e9)
    w_s, s_s = plate(q, ix / 1000, span_s / 1000, t_s / 1000, grp["E_GPa"] * 1e9)
    rf = {}
    for b in ["uhf"] + small:
        t = t_u if b == "uhf" else t_s
        lay = [(grp["er"] * (1 - 1j * grp["tand"]), t)]
        f = BANDS[b][1] / 1000
        r0, r50 = slant(lay, f, 0), slant(lay, f, 50)
        wet = slant([(water_er(f), 0.2)] + lay, f, 0)
        rf[b] = {"wall_mm": t, "f_MHz": BANDS[b][1], "dry_loss_dB_0_50": [round(r0["loss_dB"], 2), round(r50["loss_dB"], 2)],
                 "wet_loss_dB_0": round(wet["loss_dB"], 2), "xpd_50_dB": round(r50["xpd_dB"], 1)}
    area_front = (ox + 2 * fl) * (oz + 2 * fl) / 1e6
    cover_area = (ix * iz + 2 * (ix + iz) * iy) / 1e6
    tray_area = ((ox + 2 * fl) * (oz + 2 * fl) + 2 * (ox + oz + 4 * fl) * td) / 1e6
    refl = sum(B[b]["reflector_length_mm"] * B[b]["element"]["reflector_width_mm"] for b in B) / 1e6
    mass = cover_area * 0.0028 * grp["rho"] + ix * iy / 1e6 * 0.004 * grp["rho"] + tray_area * 0.002 * 2700 + refl * 0.002 * 2700 + 4.0
    return {"cover_inner_mm": [round(ix, 1), round(iz, 1), round(iy, 1)], "wall_mm": {"uhf_zone": t_u, "4g5g_zone": t_s},
            "flange_mm": fl, "tray_depth_mm": td, "corner_radius_mm": 25,
            "overall_mm": [round(ox + 2 * fl), round(oz + 2 * fl), round(iy + t_u + td + 3)],
            "z_uhf_mm": round(zU, 1), "z_small_mm": round(zS, 1), "z_rib_mm": round(zr, 1), "x_small_mm": xs,
            "front_deflection_mm": {"uhf_zone": round(w_u * 1000, 1), "4g5g_zone": round(w_s * 1000, 2)},
            "stress_safety_factor": {"uhf_zone": round(grp["sigma_MPa"] / (s_u / 1e6), 1),
                                     "4g5g_zone": round(grp["sigma_MPa"] / (s_s / 1e6), 1)},
            "wind_load_N": round(CD * q * area_front), "mass_kg": round(mass, 1),
            "bulkheads": "16 x N female on the bottom face, 4 per band (S1-S4), plus vent and drain", "rf": rf}


def figure(out):
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.4))
    th = np.linspace(0, 60, 61)
    for band, p in out["panels"].items():
        m = MATERIALS[p["material"]]
        lay = [(m["er"] * (1 - 1j * m["tand"]), p["wall_mm"])]
        f = BANDS[band][1] / 1000
        loss = [slant(lay, f, x)["loss_dB"] for x in th]
        xpd = [slant(lay, f, x)["xpd_dB"] for x in th]
        wet = [slant([(water_er(f), 0.2)] + lay, f, x)["loss_dB"] for x in th]
        lab = f"{band} {p['material']} {p['wall_mm']} mm @ {f * 1000:.0f} MHz"
        axs[0].plot(th, loss, label=lab)
        axs[1].plot(th, xpd, label=lab)
        axs[2].plot(th, wet, label=lab)
    axs[0].set_title("Dry: +45° slant transmission loss")
    axs[1].set_title("Dry: cross-pol discrimination (slant)")
    axs[2].set_title("Wet: + 0.2 mm water film")
    for a, yl in zip(axs, ("loss (dB)", "XPD (dB)", "loss (dB)")):
        a.set_xlabel("angle off broadside, azimuth (°)")
        a.set_ylabel(yl)
        a.grid(alpha=0.3)
        a.axvline(50, color="k", lw=0.8, ls=":")
    axs[1].set_ylim(0, 60)
    axs[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "radome_transmission.png"), dpi=120)


if __name__ == "__main__":
    o = design()
    json.dump(o, open(os.path.join(HERE, "radome.json"), "w"), indent=1)
    figure(o)
    for band, p in o["panels"].items():
        print(band, p["material"], p["wall_mm"], "outer", p["outer_LxHxD_mm"], "defl", p["front_deflection_mm"], "SF",
              p["stress_safety_factor"], "wind", p["wind_load_N"], "kg", p["mass_kg"], "phase", p["phase_spread_deg_for_pm0.2mm"])
        for k, v in p["rf"].items():
            print("   ", k, v)
    print("lpda_h", o["lpda_h"]["outer_mm"], o["lpda_h"]["rf"])
