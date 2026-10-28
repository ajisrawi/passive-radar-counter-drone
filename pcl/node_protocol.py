"""UDP protocol between the GPU host and a receiver node (Board C / C2 running firmware/ps/pcl_noded.py).

Control port (default 50000), both directions, little-endian. Every message starts with
    magic b"PCLN", version u8, type u8, length u16 (bytes after this 16-byte header), seq u32
Host -> node
    TARGET_SET   0x01  slot u8, enable u8, rsvd u16, track_id u32, delay_samples u32, azimuth_deg f32
                       cue the micro-Doppler engine: range gate (bistatic delay in samples) and beam direction
    TARGET_CLEAR 0x02  slot u8
    TAPS         0x03  channel u8, rsvd u8, first u16, count u16, rsvd u16, then count x (I i32, Q i32), Q2.16
    TAPS_COMMIT  0x04  (empty)  new taps take effect at the next CPI boundary
    CONFIG       0x05  UTF-8 JSON, e.g. {"stream": true, "sv_shift": 2, "cpi_len": 2000000, "block_log2": 11}
Node -> host
    MD_REPORT    0x81  slot u8, cls u8, looks u16, track_id u32, z_near f32, z_far f32, body_doppler_hz f32,
                       body_snr_db f32, rotor_line_hz f32, rsvd u32, sample u64
                       cls: 0 pending, 1 UAV, 2 bird, 3 unknown, 4 no signal in the gate
    STATUS       0x82  UTF-8 JSON (sample counter, PPS, overflow flags, ring lag, CPU)
Stream port (default 50001), node -> host: 16-byte header b"PCLS", seq u32, first_sample u64, then 1408 bytes =
128 samples packed by the FPGA (firmware/model/fixedpoint.py unpack_samples).
"""
import json
import struct

MAGIC = b"PCLN"
VERSION = 1
HDR = struct.Struct("<4sBBHI")

TARGET_SET, TARGET_CLEAR, TAPS, TAPS_COMMIT, CONFIG = 0x01, 0x02, 0x03, 0x04, 0x05
MD_REPORT, STATUS = 0x81, 0x82
CLASSES = {0: "pending", 1: "UAV", 2: "bird", 3: "unknown", 4: "no signal"}
CLASS_CODE = {v: k for k, v in CLASSES.items()}

_TARGET_SET = struct.Struct("<BBHIIf")
_TARGET_CLEAR = struct.Struct("<B")
_TAPS_HDR = struct.Struct("<BBHHH")
_MD_REPORT = struct.Struct("<BBHIfffffIQ")
STREAM_HDR = struct.Struct("<4sIQ")
STREAM_MAGIC = b"PCLS"
STREAM_PAYLOAD = 1408


def pack(mtype, body, seq=0):
    return HDR.pack(MAGIC, VERSION, mtype, len(body), seq & 0xFFFFFFFF) + body


def unpack(data):
    """-> (type, seq, decoded body) ; raises ValueError on a bad frame"""
    if len(data) < HDR.size:
        raise ValueError("short frame")
    magic, ver, mtype, n, seq = HDR.unpack_from(data)
    if magic != MAGIC or ver != VERSION or len(data) < HDR.size + n:
        raise ValueError("bad header")
    body = data[HDR.size: HDR.size + n]
    if mtype == TARGET_SET:
        slot, en, _, tid, delay, az = _TARGET_SET.unpack(body)
        return mtype, seq, {"slot": slot, "enable": bool(en), "track_id": tid, "delay": delay, "azimuth_deg": az}
    if mtype == TARGET_CLEAR:
        return mtype, seq, {"slot": _TARGET_CLEAR.unpack(body)[0]}
    if mtype == TAPS:
        ch, _, first, count, _ = _TAPS_HDR.unpack_from(body)
        vals = struct.unpack_from(f"<{2 * count}i", body, _TAPS_HDR.size)
        return mtype, seq, {"channel": ch, "first": first, "i": list(vals[0::2]), "q": list(vals[1::2])}
    if mtype == TAPS_COMMIT:
        return mtype, seq, {}
    if mtype in (CONFIG, STATUS):
        return mtype, seq, json.loads(body.decode())
    if mtype == MD_REPORT:
        slot, cls, looks, tid, zn, zf, fd, snr, fr, _, smp = _MD_REPORT.unpack(body)
        return mtype, seq, {"slot": slot, "class": CLASSES.get(cls, "?"), "looks": looks, "track_id": tid,
                            "z_near": zn, "z_far": zf, "body_doppler_hz": fd, "body_snr_db": snr,
                            "rotor_line_hz": fr, "sample": smp}
    raise ValueError(f"unknown type {mtype:#x}")


def target_set(slot, delay, azimuth_deg, track_id=0, enable=True, seq=0):
    return pack(TARGET_SET, _TARGET_SET.pack(slot, int(enable), 0, track_id, int(delay), float(azimuth_deg)), seq)


def target_clear(slot, seq=0):
    return pack(TARGET_CLEAR, _TARGET_CLEAR.pack(slot), seq)


def taps(channel, first, ti, tq, seq=0):
    body = _TAPS_HDR.pack(channel, 0, first, len(ti), 0) + struct.pack(f"<{2 * len(ti)}i", *[v for p in zip(ti, tq) for v in p])
    return pack(TAPS, body, seq)


def taps_commit(seq=0):
    return pack(TAPS_COMMIT, b"", seq)


def config(d, seq=0):
    return pack(CONFIG, json.dumps(d).encode(), seq)


def status(d, seq=0):
    return pack(STATUS, json.dumps(d).encode(), seq)


def md_report(r, seq=0):
    return pack(MD_REPORT, _MD_REPORT.pack(r["slot"], CLASS_CODE.get(r["class"], 3), min(r["looks"], 65535), r.get("track_id", 0),
                                           r["z_near"], r["z_far"], r["body_doppler_hz"], r["body_snr_db"],
                                           r.get("rotor_line_hz", 0.0), 0, r.get("sample", 0)), seq)
