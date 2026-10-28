"""Bistatic geometry helpers.

Positions are (x, y, z) in metres in a local east-north-up frame.
Azimuth is measured counter-clockwise from +x (east), in degrees.
"""
import numpy as np


def bistatic(tx, rx, pos, vel, wavelength):
    """Bistatic range (R1 + R2 - L) and bistatic Doppler for a target."""
    tx, rx, pos, vel = (np.asarray(v, float) for v in (tx, rx, pos, vel))
    r_tx = np.linalg.norm(pos - tx)
    r_rx = np.linalg.norm(pos - rx)
    baseline = np.linalg.norm(tx - rx)
    rate = vel @ ((pos - tx) / r_tx) + vel @ ((pos - rx) / r_rx)  # d(R1+R2)/dt
    return {
        "rb": r_tx + r_rx - baseline,
        "fd": -rate / wavelength,
        "r_tx": r_tx,
        "r_rx": r_rx,
        "baseline": baseline,
    }


def azimuth_deg(frm, to):
    d = np.asarray(to, float) - np.asarray(frm, float)
    return np.degrees(np.arctan2(d[1], d[0]))


def wrap180(a):
    return (np.asarray(a) + 180.0) % 360.0 - 180.0


def localize_2d(rb, az_deg, tx, rx):
    """Place a target from bistatic range + receiver azimuth (horizontal plane).

    Solves R1 + R2 = rb + L with R1 = |tx - (rx + R2*u)| for the receiver range R2:
        R2 = (S^2 - L^2) / (2 (S - L cos(phi)))
    where S = rb + L and phi is the angle between the target direction and the baseline.
    """
    tx2, rx2 = np.asarray(tx, float)[:2], np.asarray(rx, float)[:2]
    b = tx2 - rx2
    L = np.linalg.norm(b)
    u = np.array([np.cos(np.radians(az_deg)), np.sin(np.radians(az_deg))])
    s = rb + L
    r_rx = (s**2 - L**2) / (2 * (s - u @ b))
    return rx2 + r_rx * u, r_rx


def bistatic_ellipse(rb, tx, rx, n=360):
    """Points on the constant-bistatic-range ellipse (horizontal plane), for plotting."""
    tx2, rx2 = np.asarray(tx, float)[:2], np.asarray(rx, float)[:2]
    az = np.linspace(-180, 180, n)
    return np.array([localize_2d(rb, a, tx, rx)[0] for a in az])
