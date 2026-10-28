"""AD9361 setup through libiio (ADI Kuiper Linux, the ad9361 IIO driver), for the three chips on Board B.

Per chip: sample rate (8.000 MS/s for the TV stack: the AD9361's own programmable FIR does the anti-alias
filtering, so the PL needs no resampler), RX LO, RF bandwidth, manual gain (AGC off: the canceller assumes a
steady gain inside a CPI; the host sets the gain from the reference RMS, target -14 dBFS). Then the ADI multi-chip
synchronisation sequence so the three chips' samples line up (the residual LO phase is calibrated with the noise
source). Attribute names are the ad9361 driver's (Linux/drivers/iio/adc/ad9361.c).
"""


def _attr(dev, chan, name, value, output=False):
    ch = dev.find_channel(chan, output)
    if ch is None:
        raise RuntimeError(f"{dev.name}: no channel {chan}")
    ch.attrs[name].value = str(value)


def setup(cfg):
    import iio  # libiio Python bindings (pylibiio), part of Kuiper
    ctx = iio.Context(cfg.get("iio_uri", "local:"))
    r = cfg["radio"]
    phys = []
    for name in r["phy_devices"]:                  # e.g. ad9361-phy, ad9361-phy-B, ad9361-phy-C
        dev = ctx.find_device(name)
        if dev is None:
            raise RuntimeError(f"no IIO device {name}")
        phys.append(dev)
    for dev in phys:
        _attr(dev, "voltage0", "sampling_frequency", int(cfg["sample_rate"]))
        _attr(dev, "voltage0", "rf_bandwidth", int(r["rf_bandwidth_hz"]))
        _attr(dev, "altvoltage0", "frequency", int(r["rx_lo_hz"]), output=True)     # RX_LO
        for c in ("voltage0", "voltage1"):
            _attr(dev, c, "gain_control_mode", "manual")
            _attr(dev, c, "hardwaregain", r.get("rx_gain_db", 30))
        if r.get("fir_file"):                       # sharper anti-alias FIR for the 8 MS/s DVB-T rate
            dev.attrs["filter_fir_config"].value = open(r["fir_file"]).read()
            _attr(dev, "voltage0", "filter_fir_en", 1)
    # multi-chip sync (ADI FMCOMMS5 sequence): steps 1..5 written to every chip's debug attribute
    if len(phys) > 1 and r.get("mcs", True):
        for step in range(1, 6):
            for dev in phys:
                dev.debug_attrs["multichip_sync"].value = str(step)
    return phys


def set_gain(cfg, gain_db):
    import iio
    ctx = iio.Context(cfg.get("iio_uri", "local:"))
    for name in cfg["radio"]["phy_devices"]:
        dev = ctx.find_device(name)
        for c in ("voltage0", "voltage1"):
            _attr(dev, c, "hardwaregain", gain_db)
