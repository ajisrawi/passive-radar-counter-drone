"""Moving targets: trajectories, RCS and micro-Doppler signatures."""
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import geometry as geo


@dataclass
class Trajectory:
    """Constant-altitude path driven by a speed and a heading-vs-time function."""

    p0: np.ndarray  # (x, y, z) at t = 0
    speed_mps: float
    heading_fn: Callable[[float], float]  # degrees, counter-clockwise from east
    duration_s: float
    dt: float = 0.01

    def __post_init__(self):
        self.t = np.arange(0, self.duration_s + 2 * self.dt, self.dt)
        hd = np.radians([self.heading_fn(x) for x in self.t])
        self.vel = np.stack([self.speed_mps * np.cos(hd), self.speed_mps * np.sin(hd), 0 * hd], axis=1)
        self.pos = np.asarray(self.p0, float) + np.vstack([np.zeros(3), np.cumsum(self.vel[:-1] * self.dt, axis=0)])

    def state(self, t):
        pos = np.array([np.interp(t, self.t, self.pos[:, i]) for i in range(3)])
        vel = np.array([np.interp(t, self.t, self.vel[:, i]) for i in range(3)])
        return pos, vel


@dataclass
class Target:
    label: str
    kind: str  # "uav" or "bird" (ground truth class)
    traj: Trajectory
    rcs_m2: float
    signature: object  # RotorSignature / WingBeatSignature
    swerling1: bool = True  # RCS fluctuates CPI to CPI (exponential power)


def echo_params(target, t_mid, tx, rx, wavelength, boresight_deg):
    """Bistatic delay/Doppler/angle and wave-vector magnitudes at the CPI centre."""
    pos, vel = target.traj.state(t_mid)
    b = geo.bistatic(tx, rx, pos, vel, wavelength)
    u_sum = (pos - tx) / b["r_tx"] + (pos - rx) / b["r_rx"]
    k = 2 * np.pi / wavelength * u_sum
    return {
        **b,
        "pos": pos,
        "vel": vel,
        "angle": float(geo.wrap180(geo.azimuth_deg(rx, pos) - boresight_deg)),
        "k_h": float(np.hypot(k[0], k[1])),
        "k_full": float(np.linalg.norm(k)),
    }
