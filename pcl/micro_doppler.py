"""Micro-Doppler echo models: drone rotors and bird wing beats.

Each model returns a complex modulation m(t) that multiplies the body echo.

Bistatic phase: a scatterer displaced by d (metres) from the body centre changes
the echo phase by -k . d, where k = (2*pi/lambda) * (u_tx + u_rx) is the bistatic
wave-vector (u_tx: unit vector transmitter->target, u_rx: receiver->target).
For a target near the receiver and far from the transmitter, |k| ~ 4*pi/lambda.
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Rotor:
    blade_len_m: float = 0.12  # hub-to-tip (a 9.5" prop is ~0.12 m)
    rev_per_s: float = 100.0  # 6000 rpm
    n_blades: int = 2
    phase0: float = 0.0


def rotor_return(t, rotor, k_h):
    """Rotating-blade return (V.C. Chen's line-scatterer model), horizontal rotor plane.

    A blade of length L at angle phi to the horizontal wave-vector k_h returns
        L * sinc(k_h L/2 cos phi) * exp(-j k_h L/2 cos phi).
    The sinc term produces "blade flashes" when a blade is perpendicular to k_h; the
    phase term produces a sinusoidal Doppler of up to +/- k_h * v_tip / (2 pi) Hz.
    """
    out = np.zeros(t.shape, np.complex128)
    x = k_h * rotor.blade_len_m / 2
    for b in range(rotor.n_blades):
        c = np.cos(2 * np.pi * rotor.rev_per_s * t + rotor.phase0 + 2 * np.pi * b / rotor.n_blades)
        out += np.sinc(x * c / np.pi) * np.exp(-1j * x * c)
    return out


@dataclass
class RotorSignature:
    """Multirotor or propeller aircraft: body echo + rotating blades (and motor bells)."""

    rotors: list = field(default_factory=list)
    rel_power_db: float = -12.0  # total rotor echo power relative to body

    def modulation(self, t, k_h, k_full):
        r = sum(rotor_return(t, rot, k_h) for rot in self.rotors)
        r *= np.sqrt(10 ** (self.rel_power_db / 10) / np.mean(np.abs(r) ** 2))
        return 1.0 + r


@dataclass
class WingBeatSignature:
    """Flapping bird: wing-beat amplitude modulation + wing micro-motion."""

    beat_hz: float = 6.0
    excursion_m: float = 0.12  # effective wing-tip displacement along the wave-vector
    am_depth: float = 0.3  # body RCS modulation through the beat cycle
    rel_power_db: float = -3.0  # wing echo power relative to body
    phase0: float = 0.0

    def modulation(self, t, k_h, k_full):
        w = 2 * np.pi * self.beat_hz * t + self.phase0
        body = 1.0 + self.am_depth * np.cos(w)
        wing = np.sqrt(10 ** (self.rel_power_db / 10)) * np.exp(-1j * k_full * self.excursion_m * np.sin(w))
        return body + wing


def quadcopter_rotors(rng, rev_per_s=100.0, spread=0.08, blade_len_m=0.12):
    """Four 2-blade rotors at slightly different speeds (attitude control) and random phases."""
    return [Rotor(blade_len_m, rev_per_s * (1 + spread * rng.uniform(-1, 1)), 2, rng.uniform(0, 2 * np.pi))
            for _ in range(4)]
