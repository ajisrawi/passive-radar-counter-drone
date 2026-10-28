"""pcl_noded: receiver-node daemon on the Zynq ARM (ADI Kuiper Linux, Python 3 + numpy).

    python3 pcl_noded.py --config node_config.json           (on the board)
    python3 pcl_noded.py --config node_config.json --sim     (on a PC: SimRegs, no radios, for protocol tests)

Duties:
  * radios: the three AD9361s via libiio (radio.py): sample rate, LO, bandwidth, manual gain, multi-chip sync;
  * control port: target cues, canceller taps and configuration from the host (pcl/node_protocol.py);
  * micro-Doppler: copy new slow-time records from the PL ring every POLL_S, feed one TargetMd per cue slot,
    send MD_REPORT for every active slot every report_s;
  * STATUS once a second (sample counter, PPS latch, overflow flags).
The sample stream (FPGA -> DMA -> UDP) is a separate C program, pcl_streamd (firmware/ps/streamd/).
"""
import argparse
import json
import math
import os
import select
import socket
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import fixedpoint as fx  # noqa: E402
from md_classifier import TargetMd  # noqa: E402
from pcl import node_protocol as npr  # noqa: E402

POLL_S = 0.02


class Node:
    def __init__(self, cfg, hw):
        self.cfg, self.hw = cfg, hw
        self.nch = cfg.get("channels", 4)
        self.ntgt = cfg.get("md_slots", 8)
        self.fs = cfg["sample_rate"]
        self.block_log2 = cfg.get("block_log2", 11)
        self.fs_slow = self.fs / (1 << self.block_log2)
        # element pitch in wavelengths at the stack's carrier (steering weights for the cues)
        self.d_lambda = cfg["element_pitch_m"] * cfg["carrier_hz"] / 299_792_458.0
        hw.configure(cfg.get("cpi_len", int(self.fs * 0.25)), cfg.get("sv_shift", 2), cfg.get("ref_shift", 0),
                     self.block_log2, cfg.get("md_out_shift", 4))
        self.slots = {}             # slot -> {"track_id", "md": TargetMd}
        self.pending_taps = {}
        self.seq = 0
        self.host = (cfg.get("host_ip", "0.0.0.0"), cfg.get("host_port", 50000))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", cfg.get("control_port", 50000)))
        self.sock.setblocking(False)
        self.stats = {"md_records": 0, "md_lost": 0, "bad_frames": 0}

    # ------------------------------------------------------------------ control messages
    def handle(self, data, addr):
        try:
            mtype, _, m = npr.unpack(data)
        except ValueError:
            self.stats["bad_frames"] += 1
            return
        self.host = (addr[0], self.cfg.get("host_port", addr[1]))
        if mtype == npr.TARGET_SET:
            s = m["slot"]
            if s >= self.ntgt:
                return
            wi, wq = fx.steering_weights(m["azimuth_deg"], self.nch, self.d_lambda)
            self.hw.set_target(s, m["delay"], wi, wq, m["enable"])
            self.hw.commit_targets()
            old = self.slots.get(s)
            if old is None or old["track_id"] != m["track_id"]:
                # a new track in this slot starts a fresh spectrum; a re-cue of the same track keeps averaging
                self.slots[s] = {"track_id": m["track_id"], "md": TargetMd(self.fs_slow, **self.cfg.get("md", {}))}
            if not m["enable"]:
                self.slots.pop(s, None)
        elif mtype == npr.TARGET_CLEAR:
            self.hw.set_target(m["slot"], 0, [0] * self.nch, [0] * self.nch, False)
            self.hw.commit_targets()
            self.slots.pop(m["slot"], None)
        elif mtype == npr.TAPS:
            t = self.pending_taps.setdefault(m["channel"], ({}, {}))
            for k, (a, b) in enumerate(zip(m["i"], m["q"])):
                t[0][m["first"] + k], t[1][m["first"] + k] = a, b
        elif mtype == npr.TAPS_COMMIT:
            for ch, (ti, tq) in self.pending_taps.items():
                n = max(ti) + 1 if ti else 0
                self.hw.load_taps(ch, [ti.get(k, 0) for k in range(n)], [tq.get(k, 0) for k in range(n)])
            self.pending_taps = {}
            self.hw.commit_taps()
        elif mtype == npr.CONFIG:
            if "stream" in m:
                self.hw.stream(m["stream"])
            if any(k in m for k in ("cpi_len", "sv_shift", "ref_shift", "md_out_shift")):
                self.cfg.update(m)
                self.hw.configure(self.cfg.get("cpi_len", int(self.fs * 0.25)), self.cfg.get("sv_shift", 2),
                                  self.cfg.get("ref_shift", 0), self.block_log2, self.cfg.get("md_out_shift", 4))

    def send(self, data):
        try:
            self.sock.sendto(data, self.host)
        except OSError:
            pass
        self.seq += 1

    # ------------------------------------------------------------------ micro-Doppler
    def poll_md(self):
        rec, lost = self.hw.read_md()
        self.stats["md_records"] += len(rec["tgt"])
        self.stats["md_lost"] += lost
        for s, sl in self.slots.items():
            m = rec["tgt"] == s
            if m.any():
                sl["md"].feed(rec["blk"][m], rec["y"][m])

    def report(self):
        smp = self.hw.status()["sample"]
        for s, sl in self.slots.items():
            r = sl["md"].report()
            r.update({"slot": s, "track_id": sl["track_id"], "sample": smp})
            self.send(npr.md_report(r, self.seq))

    def run(self, duration=None):
        t_end = None if duration is None else time.time() + duration
        t_rep = t_stat = time.time()
        while t_end is None or time.time() < t_end:
            r, _, _ = select.select([self.sock], [], [], POLL_S)
            if r:
                while True:
                    try:
                        data, addr = self.sock.recvfrom(9000)
                    except BlockingIOError:
                        break
                    self.handle(data, addr)
            self.poll_md()
            now = time.time()
            if now - t_rep >= self.cfg.get("report_s", 0.5):
                self.report()
                t_rep = now
            if now - t_stat >= 1.0:
                st = self.hw.status()
                st.update(self.stats)
                st["slots"] = sorted(self.slots)
                self.send(npr.status(st, self.seq))
                t_stat = now


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "node_config.json"))
    ap.add_argument("--sim", action="store_true", help="no hardware: bit-true model, no radios")
    ap.add_argument("--duration", type=float, default=None)
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.sim:
        from hw import SimRegs
        hw = SimRegs(nch=cfg.get("channels", 4))
    else:
        from hw import PclRegs
        import radio
        radio.setup(cfg)
        hw = PclRegs(cfg.get("uio", "/dev/uio0"))
    Node(cfg, hw).run(a.duration)


if __name__ == "__main__":
    main()
