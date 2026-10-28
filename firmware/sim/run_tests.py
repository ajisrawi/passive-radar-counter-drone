"""Run the HDL testbenches in Icarus Verilog and compare bit-for-bit with the Python models.

    python firmware/sim/run_tests.py            (all)      python firmware/sim/run_tests.py md   (one)

Needs Icarus Verilog (OSS CAD Suite); set OSS_CAD to its folder if it is not C:/Users/<you>/tools/oss-cad-suite.
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(FW, "model"))
import fixedpoint as fx  # noqa: E402

OSS = os.environ.get("OSS_CAD", os.path.join(os.path.expanduser("~"), "tools", "oss-cad-suite"))
HDL = os.path.join(FW, "hdl")
RNG = np.random.default_rng(7)


def env():
    e = dict(os.environ)
    e["PATH"] = os.pathsep.join([os.path.join(OSS, "bin"), os.path.join(OSS, "lib"), e["PATH"]])
    return e


def hexw(path, values, bits):
    m = (1 << bits) - 1
    with open(path, "w") as f:
        for v in values:
            f.write(f"{int(v) & m:0{(bits + 3) // 4}x}\n")


def sim(top, srcs, params, workdir):
    vvp = os.path.join(workdir, "sim.vvp")
    cmd = [os.path.join(OSS, "bin", "iverilog.exe"), "-g2012", "-o", vvp, "-s", top] + [f"-P{top}.{k}={v}" for k, v in params.items()] + srcs
    r = subprocess.run(cmd, capture_output=True, text=True, env=env())
    if r.returncode:
        raise RuntimeError("iverilog:\n" + r.stdout + r.stderr)
    r = subprocess.run([os.path.join(OSS, "bin", "vvp.exe"), "-n", vvp], capture_output=True, text=True, env=env(), cwd=workdir)
    if r.returncode or "DONE" not in r.stdout:
        raise RuntimeError("vvp:\n" + r.stdout[-2000:] + r.stderr[-2000:])
    return r.stdout


def samples(n, nch, amp=2047):
    ref_i = RNG.integers(-amp, amp + 1, n)
    ref_q = RNG.integers(-amp, amp + 1, n)
    s_i = RNG.integers(-amp, amp + 1, (nch, n))
    s_q = RNG.integers(-amp, amp + 1, (nch, n))
    return ref_i, ref_q, s_i, s_q


def write_samples(path, ref_i, ref_q, s_i, s_q):
    vals = []
    for k in range(len(ref_i)):
        vals += [ref_i[k], ref_q[k], *s_i[:, k], *s_q[:, k]]
    hexw(path, vals, 16)


# ---------------------------------------------------------------------------------------------- canceller
def test_canceller():
    NTAPS, NCH, N, CPI = 128, 4, 600, 300
    ref_i, ref_q, s_i, s_q = samples(N, NCH)
    ta = RNG.integers(-(1 << 15), 1 << 15, (2, NCH, NTAPS))
    tb = RNG.integers(-(1 << 15), 1 << 15, (2, NCH, NTAPS))
    tb[:, :, 0] = [[(1 << 17) - 1] * NCH, [-(1 << 17)] * NCH]   # extremes, and saturation at the output
    s_i[:, 400:430] = 32767                                     # full-scale samples: y must saturate
    s_q[:, 430:460] = -32768
    with tempfile.TemporaryDirectory() as w:
        write_samples(os.path.join(w, "in.hex"), ref_i, ref_q, s_i, s_q)
        for name, t in (("tapsA.hex", ta), ("tapsB.hex", tb)):
            hexw(os.path.join(w, name), [v for c in range(NCH) for k in range(NTAPS) for v in (t[0, c, k], t[1, c, k])], 18)
        sim("tb_canceller", [os.path.join(HERE, "tb_canceller.v"), os.path.join(HDL, "canceller.v")],
            {"NTAPS": NTAPS, "NCH": NCH, "N": N, "CPI": CPI}, w)
        got = np.loadtxt(os.path.join(w, "out.txt"), dtype=np.int64)
    bad = 0
    for c in range(NCH):
        ya = fx.canceller(ref_i, ref_q, s_i[c], s_q[c], ta[0, c], ta[1, c])
        yb = fx.canceller(ref_i, ref_q, s_i[c], s_q[c], tb[0, c], tb[1, c])
        yi = np.concatenate([ya[0][:CPI], yb[0][CPI:]])
        yq = np.concatenate([ya[1][:CPI], yb[1][CPI:]])
        bad += int(np.sum(got[:, 2 * c] != yi) + np.sum(got[:, 2 * c + 1] != yq))
    bad += int(np.sum(got[:, 2 * NCH] != ref_i) + np.sum(got[:, 2 * NCH + 1] != ref_q))
    sat = int(np.sum(np.abs(got[:, :2 * NCH]) == 32767) + np.sum(got[:, :2 * NCH] == -32768))
    return {"samples": len(got), "mismatches": bad, "saturated_outputs_exercised": sat}


# ---------------------------------------------------------------------------------------------- md engine
def md_params(ntgt, nch, rng, delays):
    tg = []
    for t in range(ntgt):
        wi, wq = fx.steering_weights(rng.uniform(-60, 60), nch)
        tg.append({"tau": int(delays[t]), "w_i": wi, "w_q": wq, "en": t % 3 != 2})
    return tg


def prm_words(tg, nch):
    out = []
    for t in tg:
        out.append((int(t["en"]) << 31) | t["tau"])
        out += [((int(t["w_i"][c]) & 0xFFFF) << 16) | (int(t["w_q"][c]) & 0xFFFF) for c in range(nch)]
    return out


def md_expected(ref_i, ref_q, s_i, s_q, tg, blog2, osh):
    exp = {}
    res = fx.md_engine(ref_i, ref_q, s_i, s_q, tg, blog2, osh)
    for t, (yi, yq, first) in res.items():
        for m in range(len(yi)):
            exp[(t, first + m)] = (int(yi[m]), int(yq[m]))
    return exp


def test_md():
    NCH, NTGT, BLOG2, OSH, NB, SWAPB = 4, 8, 6, 4, 6, 3
    N = NB << BLOG2
    ref_i, ref_q, s_i, s_q = samples(N, NCH)
    A = md_params(NTGT, NCH, RNG, [0, 1, 5, 37, 63, 64, 300, 4095])
    B = md_params(NTGT, NCH, RNG, [3, 0, 99, 12, 200, 7, 64, 1])
    with tempfile.TemporaryDirectory() as w:
        write_samples(os.path.join(w, "in.hex"), ref_i, ref_q, s_i, s_q)
        hexw(os.path.join(w, "prmA.hex"), prm_words(A, NCH), 32)
        hexw(os.path.join(w, "prmB.hex"), prm_words(B, NCH), 32)
        sim("tb_md_engine", [os.path.join(HERE, "tb_md_engine.v"), os.path.join(HDL, "md_engine.v")],
            {"NCH": NCH, "NTGT": NTGT, "N": N, "BLOG2": BLOG2, "OSH": OSH, "SWAPB": SWAPB}, w)
        got = np.loadtxt(os.path.join(w, "out.txt"), dtype=np.int64, ndmin=2)
    ea = md_expected(ref_i, ref_q, s_i, s_q, A, BLOG2, OSH)
    eb = md_expected(ref_i, ref_q, s_i, s_q, B, BLOG2, OSH)
    exp = {}
    for (t, m), v in ea.items():
        if m < SWAPB and A[t]["en"]:
            exp[(t, m)] = v
    for (t, m), v in eb.items():
        if m >= SWAPB and B[t]["en"]:
            exp[(t, m)] = v
    gotd = {(int(r[0]), int(r[1])): (int(r[2]), int(r[3])) for r in got}
    bad = sum(1 for k in exp if gotd.get(k) != exp[k]) + sum(1 for k in gotd if k not in exp)
    return {"records": len(got), "expected": len(exp), "mismatches": bad}


# ---------------------------------------------------------------------------------------------- whole core
def test_core():
    NCH, NTAPS, NTGT, N, BLOG2, OSH, SVSH = 4, 128, 8, 4096, 9, 12, 2
    # realistic levels: the surveillance channels carry a strong copy of the reference (direct signal)
    ref_i, ref_q, _, _ = samples(N, NCH, 1500)
    ref = ref_i + 1j * ref_q
    h = (RNG.normal(size=(NCH, 6)) + 1j * RNG.normal(size=(NCH, 6))) * 0.25
    s = np.array([np.convolve(ref, h[c])[:N] for c in range(NCH)]) + (RNG.normal(size=(NCH, N)) + 1j * RNG.normal(size=(NCH, N))) * 20
    s_i = np.clip(np.round(s.real), -2048, 2047).astype(np.int64)
    s_q = np.clip(np.round(s.imag), -2048, 2047).astype(np.int64)
    taps = np.zeros((2, NCH, NTAPS), np.int64)
    for c in range(NCH):
        hf = fx.ls_taps(ref.astype(complex), (s_i[c] + 1j * s_q[c]).astype(complex), NTAPS)
        ti, tq = fx.to_fixed(hf, fx.CANC_TAP_FRAC, fx.CANC_TAP_BITS)
        taps[0, c], taps[1, c] = ti, tq
    tg = md_params(NTGT, NCH, RNG, [0, 2, 17, 100, 511, 1000, 3, 40])
    with tempfile.TemporaryDirectory() as w:
        write_samples(os.path.join(w, "in.hex"), ref_i, ref_q, s_i, s_q)
        hexw(os.path.join(w, "taps.hex"), [v for c in range(NCH) for k in range(NTAPS) for v in (taps[0, c, k], taps[1, c, k])], 18)
        hexw(os.path.join(w, "prm.hex"), prm_words(tg, NCH), 32)
        sim("tb_core", [os.path.join(HERE, "tb_core.v")] + [os.path.join(HDL, f) for f in
                                                             ("pcl_core.v", "canceller.v", "md_engine.v", "stream_pack.v")],
            {"N": N, "BLOG2": BLOG2, "OSH": OSH, "SVSH": SVSH}, w)
        words = [int(l.split()[0], 16) for l in open(os.path.join(w, "stream.txt"))]
        lasts = [int(l.split()[1]) for l in open(os.path.join(w, "stream.txt"))]
        md = np.loadtxt(os.path.join(w, "md.txt"), dtype=np.int64, ndmin=2)
        regs = dict(l.split() for l in open(os.path.join(w, "regs.txt")))
    yi = np.zeros((NCH, N), np.int64)
    yq = np.zeros((NCH, N), np.int64)
    for c in range(NCH):
        yi[c], yq[c] = fx.canceller(ref_i, ref_q, s_i[c], s_q[c], taps[0, c], taps[1, c])
    exp_words = fx.pack_samples(fx.requant(ref_i, 0, 12), fx.requant(ref_q, 0, 12),
                                [fx.requant(yi[c], SVSH, 8) for c in range(NCH)], [fx.requant(yq[c], SVSH, 8) for c in range(NCH)])
    n_full = (N * 88) // 64
    bad_stream = sum(1 for a, b in zip(words[:n_full], exp_words[:n_full]) if a != b)
    tlast_ok = all((l == 1) == ((k % 176) == 175) for k, l in enumerate(lasts))
    exp = md_expected(ref_i, ref_q, yi, yq, tg, BLOG2, OSH)
    exp = {k: v for k, v in exp.items() if tg[k[0]]["en"]}
    gotd = {(int(r[0]), int(r[1])): (int(r[2]), int(r[3])) for r in md}
    bad_md = sum(1 for k in exp if gotd.get(k) != exp[k]) + sum(1 for k in gotd if k not in exp)
    # direct-signal suppression achieved by the fixed-point canceller (dB)
    p_in = np.mean(s_i.astype(float) ** 2 + s_q.astype(float) ** 2)
    p_out = np.mean(yi.astype(float) ** 2 + yq.astype(float) ** 2)
    return {"stream_words": len(words), "stream_mismatches": bad_stream, "tlast_every_176": tlast_ok,
            "md_records": len(md), "md_expected": len(exp), "md_mismatches": bad_md,
            "cancellation_dB": round(10 * np.log10(p_in / p_out), 1),
            "regs": regs}


def test_merge():
    with tempfile.TemporaryDirectory() as w:
        out = sim("tb_ad_merge", [os.path.join(HERE, "tb_ad_merge.v"), os.path.join(HDL, "ad_merge.v")], {}, w)
    line = [l for l in out.splitlines() if l.startswith("samples")][0].split()
    return {"samples": int(line[1]), "mismatches": int(line[3]) + (0 if "PASS" in out else 1), "overflow": line[5]}


TESTS = {"canceller": test_canceller, "md": test_md, "core": test_core, "merge": test_merge}

if __name__ == "__main__":
    names = sys.argv[1:] or list(TESTS)
    ok = True
    for name in names:
        r = TESTS[name]()
        bad = sum(v for k, v in r.items() if "mismatch" in k)
        ok &= bad == 0 and r.get("tlast_every_176", True)
        print(f"{name:10s} {'PASS' if bad == 0 else 'FAIL'}  {r}", flush=True)
    sys.exit(0 if ok else 1)
