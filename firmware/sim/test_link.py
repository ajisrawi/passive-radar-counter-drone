"""Loopback test of the host <-> node control link: pcl_noded (with SimRegs) in a thread on 127.0.0.1, the host
NodeLink cues two tracks, loads taps, reconfigures, drops a track; checks that the node applied it and reports.

    python firmware/sim/test_link.py
"""
import json
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ps"))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
from hw import SimRegs  # noqa: E402
from pcl_noded import Node  # noqa: E402
from pcl.cueing import NodeLink  # noqa: E402


def main():
    cfg = json.load(open(os.path.join(HERE, "..", "ps", "node_config.json")))
    cfg.update({"control_port": 50110, "host_port": 50111, "host_ip": "127.0.0.1", "report_s": 0.2})
    hw = SimRegs()
    node = Node(cfg, hw)
    th = threading.Thread(target=node.run, kwargs={"duration": 2.5}, daemon=True)
    th.start()
    link = NodeLink(("127.0.0.1", 50110), fs=cfg["sample_rate"], local_port=50111)
    s1 = link.cue(1001, 1125.0, 20.0)          # 1125 m bistatic -> 30 samples at 8 MS/s
    s2 = link.cue(1002, 4500.0, -35.0)
    taps = (np.random.default_rng(1).normal(size=(4, 128)) + 1j * np.random.default_rng(2).normal(size=(4, 128))) * 0.01
    link.load_taps(taps)
    link.configure(sv_shift=3, stream=True)
    time.sleep(0.6)
    link.drop(1002)
    reps = []
    t0 = time.time()
    while time.time() - t0 < 1.5:
        reps += link.poll()
        time.sleep(0.05)
    th.join()
    checks = {
        "slots assigned": (s1, s2) == (0, 1),
        "slot 0 cued: delay 30, enabled": hw.tg[0]["tau"] == 30 and hw.tg[0]["en"],
        "slot 1 cleared": not hw.tg[1]["en"],
        "taps loaded (Q2.16)": bool(np.all(hw.taps_i == np.round(taps.real * 65536))),
        "reconfigured (sv_shift 3)": node.cfg["sv_shift"] == 3,
        "MD_REPORT received for track 1001": any(r["track_id"] == 1001 for r in reps),
        "no report for dropped track after drop": all(r["track_id"] != 1002 for r in reps[-3:]),
        "STATUS received": link.status is not None,
        "no bad frames": node.stats["bad_frames"] == 0,
    }
    for k, v in checks.items():
        print(f"  {'ok  ' if v else 'FAIL'} {k}")
    ok = all(checks.values())
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
