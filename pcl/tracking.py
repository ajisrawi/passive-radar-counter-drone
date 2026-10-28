"""Multi-target tracker: EKF in Cartesian coordinates with bistatic measurements.

State   x = [px, py, vx, vy]   (horizontal plane, constant-velocity model)
Measure z = [bistatic range (m), bistatic Doppler (Hz), azimuth (deg)]

Measuring Doppler directly gives velocity information on the first update, so
tracks converge in a few CPIs. Association is global nearest neighbour (Hungarian
algorithm) with a chi-square gate. Tracks are confirmed M-of-N and deleted after
consecutive misses (they coast through the zero-Doppler blind zone).
"""
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import geometry as geo


@dataclass
class Measurement:
    rb: float
    fd: float
    az_deg: float  # absolute azimuth
    snr_db: float = 0.0
    features: dict = field(default_factory=dict)  # micro-Doppler features (classify.py)


@dataclass
class Track:
    tid: int
    x: np.ndarray
    P: np.ndarray
    status: str = "tentative"  # tentative -> confirmed -> deleted
    hits: int = 1
    updates: int = 1
    misses: int = 0
    history: list = field(default_factory=list)  # (t, x copy, associated?)
    meas: list = field(default_factory=list)  # (t, Measurement)


class Tracker:
    def __init__(self, tx, rx, wavelength, dt, target_alt_m=100.0, sigma_rb=8.0, sigma_fd=0.5, sigma_az=0.8,
                 sigma_acc=3.0, sigma_v0=20.0, gate=16.3, confirm=(3, 4), max_miss_confirmed=6,
                 max_miss_tentative=2):
        self.tx, self.rx = np.asarray(tx, float), np.asarray(rx, float)
        self.lam, self.dt, self.alt = wavelength, dt, target_alt_m
        self.R = np.diag([sigma_rb**2, sigma_fd**2, sigma_az**2])
        self.sigma_acc, self.sigma_v0, self.gate = sigma_acc, sigma_v0, gate
        self.confirm, self.max_miss_c, self.max_miss_t = confirm, max_miss_confirmed, max_miss_tentative
        self.tracks, self.dead, self._next = [], [], 1
        self.F = np.eye(4)
        self.F[0, 2] = self.F[1, 3] = dt
        g = np.array([[dt**2 / 2, 0], [0, dt**2 / 2], [dt, 0], [0, dt]])
        self.Q = sigma_acc**2 * g @ g.T

    # ---- measurement model ----
    def h(self, x):
        pos = np.array([x[0], x[1], self.alt])
        vel = np.array([x[2], x[3], 0.0])
        b = geo.bistatic(self.tx, self.rx, pos, vel, self.lam)
        return np.array([b["rb"], b["fd"], geo.azimuth_deg(self.rx, pos)])

    def H(self, x):
        J = np.zeros((3, 4))
        for i, step in enumerate((1.0, 1.0, 0.1, 0.1)):
            d = np.zeros(4)
            d[i] = step
            diff = self.h(x + d) - self.h(x - d)
            diff[2] = geo.wrap180(diff[2])
            J[:, i] = diff / (2 * step)
        return J

    def _innovation(self, trk, m):
        z = np.array([m.rb, m.fd, m.az_deg])
        nu = z - self.h(trk.x)
        nu[2] = geo.wrap180(nu[2])
        Hj = self.H(trk.x)
        S = Hj @ trk.P @ Hj.T + self.R
        return nu, Hj, S

    def _update(self, trk, m):
        nu, Hj, S = self._innovation(trk, m)
        K = trk.P @ Hj.T @ np.linalg.inv(S)
        trk.x = trk.x + K @ nu
        trk.P = (np.eye(4) - K @ Hj) @ trk.P

    def _new_track(self, m, t):
        xy, _ = geo.localize_2d(m.rb, m.az_deg, self.tx, self.rx)
        x = np.array([xy[0], xy[1], 0.0, 0.0])
        Hj = self.H(x)[[0, 2], :2]  # position covariance from range + azimuth errors
        Rp = np.diag([self.R[0, 0], self.R[2, 2]])
        Pp = np.linalg.inv(Hj.T @ np.linalg.inv(Rp) @ Hj)
        P = np.zeros((4, 4))
        P[:2, :2] = Pp
        P[2:, 2:] = np.eye(2) * self.sigma_v0**2
        trk = Track(self._next, x, P)
        self._next += 1
        self._update(trk, m)  # pulls the velocity from the Doppler measurement
        trk.history.append((t, trk.x.copy(), True))
        trk.meas.append((t, m))
        self.tracks.append(trk)

    # ---- one scan ----
    def step(self, measurements, t):
        for trk in self.tracks:
            trk.x = self.F @ trk.x
            trk.P = self.F @ trk.P @ self.F.T + self.Q

        n_t, n_m = len(self.tracks), len(measurements)
        cost = np.full((n_t, n_m), 1e6)
        for i, trk in enumerate(self.tracks):
            for j, m in enumerate(measurements):
                nu, _, S = self._innovation(trk, m)
                d2 = float(nu @ np.linalg.solve(S, nu))
                if d2 < self.gate:
                    cost[i, j] = d2 + (0 if trk.status == "confirmed" else 1.0)  # prefer confirmed tracks
        rows, cols = linear_sum_assignment(cost) if n_t and n_m else ([], [])
        assigned_t, assigned_m = set(), set()
        for i, j in zip(rows, cols):
            if cost[i, j] < 1e6:
                trk, m = self.tracks[i], measurements[j]
                self._update(trk, m)
                trk.hits += 1
                trk.misses = 0
                trk.meas.append((t, m))
                assigned_t.add(i)
                assigned_m.add(j)

        alive = []
        for i, trk in enumerate(self.tracks):
            hit = i in assigned_t
            if not hit:
                trk.misses += 1
            trk.updates += 1
            trk.history.append((t, trk.x.copy(), hit))
            m_req, n_win = self.confirm
            if trk.status == "tentative" and trk.hits >= m_req and trk.updates <= n_win:
                trk.status = "confirmed"
            dead = (trk.status == "confirmed" and trk.misses >= self.max_miss_c) or \
                   (trk.status == "tentative" and (trk.misses >= self.max_miss_t or trk.updates > n_win))
            if dead:
                trk.status = "deleted" if trk.status == "confirmed" else "dropped"
                self.dead.append(trk)
            else:
                alive.append(trk)
        self.tracks = alive

        for j, m in enumerate(measurements):
            if j not in assigned_m:
                self._new_track(m, t)

    def all_tracks(self):
        return self.tracks + self.dead
