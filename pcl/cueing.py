"""Host side of the receiver-node link: cue tracks to the FPGA micro-Doppler engine, load canceller taps,
collect the node's MD_REPORT / STATUS (protocol: pcl/node_protocol.py).

    link = NodeLink(("192.168.1.10", 50000), fs=8e6)
    link.cue(track_id, bistatic_range_m, azimuth_deg)     # every CPI for the tracks worth classifying
    link.load_taps(taps)                                  # complex float taps [channel, k] from ECA, every few s
    for rep in link.poll(): ...                           # {"track_id", "class", "z_far", ...}
"""
import socket

import numpy as np

from . import node_protocol as npr

C0 = 299_792_458.0


class NodeLink:
    def __init__(self, node_addr, fs, slots=8, local_port=50000, tap_frac=16, tap_bits=18):
        self.node, self.fs, self.nslots = node_addr, fs, slots
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", local_port))
        self.sock.setblocking(False)
        self.slot_of = {}          # track_id -> slot
        self.seq = 0
        self.tap_frac, self.tap_bits = tap_frac, tap_bits
        self.reports, self.status = {}, None

    def _send(self, b):
        self.sock.sendto(b, self.node)
        self.seq += 1

    def delay_samples(self, bistatic_range_m):
        """bistatic range (Rtx + Rrx - L) -> integer delay of the echo behind the direct signal"""
        return int(round(bistatic_range_m / C0 * self.fs))

    def cue(self, track_id, bistatic_range_m, azimuth_deg):
        slot = self.slot_of.get(track_id)
        if slot is None:
            used = set(self.slot_of.values())
            free = [s for s in range(self.nslots) if s not in used]
            if not free:
                return None        # all slots busy: the caller drops its least interesting track first
            slot = self.slot_of[track_id] = free[0]
        self._send(npr.target_set(slot, self.delay_samples(bistatic_range_m), azimuth_deg, track_id, True, self.seq))
        return slot

    def drop(self, track_id):
        slot = self.slot_of.pop(track_id, None)
        if slot is not None:
            self._send(npr.target_clear(slot, self.seq))

    def load_taps(self, taps):
        """taps: complex array [channel, ntaps] (float, from ECA on a raw snapshot)"""
        s = float(1 << self.tap_frac)
        lim = (1 << (self.tap_bits - 1)) - 1
        for ch, h in enumerate(np.atleast_2d(taps)):
            ti = np.clip(np.round(h.real * s), -lim - 1, lim).astype(int)
            tq = np.clip(np.round(h.imag * s), -lim - 1, lim).astype(int)
            for first in range(0, len(ti), 128):
                self._send(npr.taps(ch, first, ti[first:first + 128].tolist(), tq[first:first + 128].tolist(), self.seq))
        self._send(npr.taps_commit(self.seq))

    def configure(self, **kw):
        self._send(npr.config(kw, self.seq))

    def poll(self):
        out = []
        while True:
            try:
                data, _ = self.sock.recvfrom(9000)
            except (BlockingIOError, OSError):
                break
            try:
                mtype, _, m = npr.unpack(data)
            except ValueError:
                continue
            if mtype == npr.MD_REPORT:
                self.reports[m["track_id"]] = m
                out.append(m)
            elif mtype == npr.STATUS:
                self.status = m
        return out
