"""Bistatic radar link budget for a DVB-T passive radar against small drones.

Run directly for a summary table:
    python -m pcl.link_budget
"""
from dataclasses import dataclass

import numpy as np

K_B = 1.380649e-23  # Boltzmann constant, J/K
T0 = 290.0  # reference temperature, K
C = 299_792_458.0  # speed of light, m/s


def db(x):
    return 10.0 * np.log10(x)


@dataclass
class LinkBudget:
    erp_dbw: float = 40.0  # transmitter ERP (10 kW, a typical regional DVB-T site)
    freq_hz: float = 600e6  # UHF channel centre
    surv_gain_dbi: float = 5.0  # one surveillance array element (patch / dipole + reflector)
    ref_gain_dbi: float = 12.0  # reference Yagi pointed at the transmitter
    front_to_back_db: float = 20.0  # surveillance element rejection toward the transmitter
    noise_figure_db: float = 4.0  # LNA + receiver, incl. external UHF noise
    losses_db: float = 3.0  # cables, polarisation, atmosphere
    fs_hz: float = 64e6 / 7  # DVB-T 8 MHz channel sample rate (9.142857 MHz)
    cpi_s: float = 0.25  # coherent processing interval

    @property
    def wavelength(self):
        return C / self.freq_hz

    def noise_power_dbw(self):
        """Thermal noise power per sample (noise bandwidth = sample rate)."""
        return db(K_B * T0) + self.noise_figure_db + db(self.fs_hz)

    def echo_power_dbw(self, r_tx, r_rx, rcs_m2):
        """Bistatic radar equation: Pr = ERP * Gr * lambda^2 * sigma / ((4pi)^3 R1^2 R2^2)."""
        lam = self.wavelength
        return (
            self.erp_dbw
            + self.surv_gain_dbi
            + db(lam**2 * rcs_m2 / (4 * np.pi) ** 3)
            - 20 * np.log10(r_tx)
            - 20 * np.log10(r_rx)
            - self.losses_db
        )

    def direct_power_dbw(self, baseline_m, gain_dbi):
        """Free-space direct signal from the transmitter."""
        return self.erp_dbw + gain_dbi + db((self.wavelength / (4 * np.pi * baseline_m)) ** 2)

    def integration_gain_db(self):
        return db(self.fs_hz * self.cpi_s)

    def echo_snr_sample_db(self, r_tx, r_rx, rcs_m2):
        """Echo-to-noise ratio per sample, before any processing."""
        return self.echo_power_dbw(r_tx, r_rx, rcs_m2) - self.noise_power_dbw()

    def echo_snr_caf_db(self, r_tx, r_rx, rcs_m2):
        """Echo SNR in the range-Doppler map after coherent integration."""
        return self.echo_snr_sample_db(r_tx, r_rx, rcs_m2) + self.integration_gain_db()

    def dsi_snr_db(self, baseline_m):
        """Direct-signal interference in one surveillance element, relative to noise."""
        return self.direct_power_dbw(baseline_m, self.surv_gain_dbi - self.front_to_back_db) - self.noise_power_dbw()

    def ref_snr_db(self, baseline_m):
        return self.direct_power_dbw(baseline_m, self.ref_gain_dbi) - self.noise_power_dbw()

    def max_rx_range(self, r_tx, rcs_m2, required_snr_db=16.0, array_gain_db=0.0):
        """Receiver-to-target range at which the CAF SNR equals the required value.

        Assumes the transmitter-to-target range stays ~constant (target near the receiver).
        """
        snr_at_1m = self.echo_snr_caf_db(r_tx, 1.0, rcs_m2) + array_gain_db
        return 10 ** ((snr_at_1m - required_snr_db) / 20)


def _summary():
    lb = LinkBudget()
    baseline = 15e3
    print("DVB-T passive radar link budget")
    print(f"  ERP {lb.erp_dbw:.0f} dBW, f = {lb.freq_hz/1e6:.0f} MHz (lambda {lb.wavelength:.2f} m), "
          f"CPI {lb.cpi_s*1e3:.0f} ms, baseline {baseline/1e3:.0f} km")
    print(f"  Noise per sample          {lb.noise_power_dbw():7.1f} dBW")
    print(f"  Integration gain (fs*T)   {lb.integration_gain_db():7.1f} dB")
    print(f"  Direct signal in surv el. {lb.dsi_snr_db(baseline):7.1f} dB above noise  (must be cancelled)")
    print(f"  Reference channel SNR     {lb.ref_snr_db(baseline):7.1f} dB")
    print(f"  Bistatic range resolution {C/7.61e6:7.1f} m   velocity resolution "
          f"{lb.wavelength/(2*lb.cpi_s):.2f} m/s\n")

    print("  CAF SNR (dB), one array element, target 15 km from transmitter")
    ranges = [500, 1000, 2000, 3000, 5000]
    print("    RCS m^2 | " + " ".join(f"{r/1e3:5.1f}km" for r in ranges) + " | max range* (1 el / 4 el)")
    for rcs in (0.001, 0.01, 0.05, 0.1):
        row = " ".join(f"{lb.echo_snr_caf_db(15e3, r, rcs):7.1f}" for r in ranges)
        r1 = lb.max_rx_range(15e3, rcs)
        r4 = lb.max_rx_range(15e3, rcs, array_gain_db=db(4))
        print(f"    {rcs:7.3f} | {row} | {r1/1e3:5.1f} / {r4/1e3:5.1f} km")
    print("  * required SNR 16 dB (Pd~0.9, Pfa 1e-6, incl. 3 dB processing loss)")


if __name__ == "__main__":
    _summary()
