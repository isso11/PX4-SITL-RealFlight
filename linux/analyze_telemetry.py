"""Summarize QGC timestamped MAVLink logs without connecting to a vehicle."""
import argparse
from collections import Counter, defaultdict, deque
import datetime
import json
import math
from pathlib import Path
import struct

# Common MAVLink message CRC extras. Unknown messages are counted, not decoded.
MESSAGES = {
    0: ("HEARTBEAT", 50), 1: ("SYS_STATUS", 124),
    24: ("GPS_RAW_INT", 24), 30: ("ATTITUDE", 39),
    32: ("LOCAL_POSITION_NED", 185), 33: ("GLOBAL_POSITION_INT", 104),
    148: ("AUTOPILOT_VERSION", 178), 230: ("ESTIMATOR_STATUS", 163),
    245: ("EXTENDED_SYS_STATE", 130), 253: ("STATUSTEXT", 83),
    22: ("PARAM_VALUE", 220), 23: ("PARAM_SET", 168),
    36: ("SERVO_OUTPUT_RAW", 222), 83: ("ATTITUDE_TARGET", 22),
    65: ("RC_CHANNELS", 118),
}


def crc_accumulate(value, crc):
    temporary = value ^ (crc & 255)
    temporary ^= (temporary << 4) & 255
    return ((crc >> 8) ^ (temporary << 8) ^ (temporary << 3) ^ (temporary >> 4)) & 65535


def iso(microseconds):
    return datetime.datetime.fromtimestamp(microseconds / 1e6, datetime.timezone.utc).isoformat()


def summarize(path, timeline_window=None):
    data = path.read_bytes()
    offset, skipped = 0, 0
    counts = Counter()
    bad_crc = Counter()
    last = {}
    spans = {}
    text_messages = deque(maxlen=100)
    recent = defaultdict(lambda: deque(maxlen=5))
    first_time, last_time = None, None
    parameters = {}
    parameter_changes = []
    timeline = []
    timeline_last = {}
    rc_ranges = {}
    while offset + 16 <= len(data):
        logged_us = struct.unpack_from(">Q", data, offset)[0]
        frame_start = offset + 8
        magic = data[frame_start]
        if not 1500000000000000 <= logged_us <= 4102444800000000 or magic not in (253, 254):
            offset += 1
            skipped += 1
            continue
        length = data[frame_start + 1]
        header_length = 10 if magic == 253 else 6
        signature_length = 13 if magic == 253 and data[frame_start + 2] & 1 else 0
        end = frame_start + header_length + length + 2 + signature_length
        if end > len(data):
            break
        if magic == 253:
            sysid, compid = data[frame_start + 5:frame_start + 7]
            message_id = int.from_bytes(data[frame_start + 7:frame_start + 10], "little")
        else:
            sysid, compid, message_id = data[frame_start + 3:frame_start + 6]
        payload_start = frame_start + header_length
        checksum_offset = payload_start + length
        known = MESSAGES.get(message_id)
        key = f"{sysid}:{compid}/{known[0] if known else message_id}"
        if known:
            crc = 65535
            for value in data[frame_start + 1:checksum_offset]:
                crc = crc_accumulate(value, crc)
            crc = crc_accumulate(known[1], crc)
            if crc != struct.unpack_from("<H", data, checksum_offset)[0]:
                bad_crc[key] += 1
                offset = end
                continue
        counts[key] += 1
        first_time = logged_us if first_time is None else min(first_time, logged_us)
        last_time = logged_us if last_time is None else max(last_time, logged_us)
        if known:
            payload = data[payload_start:checksum_offset].ljust(80, b"\0")
            sample = {"logged_utc": iso(logged_us), "system": sysid, "component": compid}
            if message_id == 0:
                custom, kind, autopilot, base_mode, system_status, version = struct.unpack_from("<IBBBBB", payload)
                sample.update(custom_mode=custom, mav_type=kind, autopilot=autopilot, base_mode=base_mode, armed=bool(base_mode & 128), system_status=system_status)
            elif message_id == 30:
                values = struct.unpack_from("<I6f", payload)
                sample.update(boot_ms=values[0], roll_rad=values[1], pitch_rad=values[2], yaw_rad=values[3])
            elif message_id == 83:
                values = struct.unpack_from("<I8fB", payload)
                w, x, y, z = values[1:5]
                sample.update(boot_ms=values[0], roll_target_rad=math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)), pitch_target_rad=math.asin(max(-1, min(1, 2 * (w * y - z * x)))), thrust=values[8], type_mask=values[9])
            elif message_id == 36:
                values = struct.unpack_from("<I8HB", payload)
                sample.update(servo_time_us=values[0], channels=list(values[1:9]), port=values[9])
            elif message_id == 65:
                values = struct.unpack_from("<I18H2B", payload)
                channels = list(values[1:19])
                sample.update(boot_ms=values[0], channels=channels, channel_count=values[19], rssi=values[20])
                ranges = rc_ranges.setdefault(key, {})
                for index, value in enumerate(channels[:min(values[19], 18)], 1):
                    if value == 65535:
                        continue
                    bounds = ranges.setdefault(str(index), {"min": value, "max": value})
                    bounds["min"] = min(bounds["min"], value)
                    bounds["max"] = max(bounds["max"], value)
            elif message_id in (22, 23):
                name_offset, type_offset = (8, 24) if message_id == 22 else (6, 22)
                name = payload[name_offset:name_offset + 16].split(b"\0", 1)[0].decode(errors="replace")
                dtype = payload[type_offset]
                value = struct.unpack_from("<i" if dtype in (2, 4, 6) else "<I" if dtype in (1, 3, 5) else "<f", payload)[0]
                sample.update(parameter=name, value=value, parameter_type=dtype)
                if message_id == 22:
                    parameters[name] = sample
                else:
                    parameter_changes.append(sample)
            elif message_id == 32:
                values = struct.unpack_from("<I6f", payload)
                sample.update(boot_ms=values[0], x=values[1], y=values[2], z=values[3], vx=values[4], vy=values[5], vz=values[6])
            elif message_id == 33:
                boot_ms, lat, lon, altitude, relative, vn, ve, vd, heading = struct.unpack_from("<I4i3hH", payload)
                sample.update(boot_ms=boot_ms, latitude=lat / 1e7, longitude=lon / 1e7, altitude_msl_m=altitude / 1000, relative_altitude_m=relative / 1000, vn=vn / 100, ve=ve / 100, vd=vd / 100)
            elif message_id == 24:
                clock, lat, lon, altitude, eph, epv, speed, cog, fix, satellites = struct.unpack_from("<Q3i4H2B", payload)
                sample.update(gps_clock=clock, latitude=lat / 1e7, longitude=lon / 1e7, altitude_msl_m=altitude / 1000, ground_speed_m_s=speed / 100, fix_type=fix, satellites=satellites)
            elif message_id == 148:
                capabilities, uid, flight, middleware, operating_system, board = struct.unpack_from("<QQ4I", payload)
                sample.update(uid=uid, flight_version=f"{flight >> 24}.{flight >> 16 & 255}.{flight >> 8 & 255}", firmware_type=flight & 255, board_version=board, flight_custom_version=payload[36:44].hex())
            elif message_id == 230:
                values = struct.unpack_from("<Q8fH", payload)
                sample.update(estimator_time_us=values[0], velocity_ratio=values[1], horizontal_position_ratio=values[2], vertical_position_ratio=values[3], magnetometer_ratio=values[4], flags=values[-1])
            elif message_id == 245:
                sample.update(vtol_state=payload[0], landed_state=payload[1])
            elif message_id == 253:
                sample.update(severity=payload[0], text=payload[1:51].split(b"\0", 1)[0].decode(errors="replace"))
                text_messages.append(sample)
            sample = {name: None if isinstance(value, float) and not math.isfinite(value) else value for name, value in sample.items()}
            if timeline_window and timeline_window[0] <= logged_us <= timeline_window[1] and message_id in (0, 30, 32, 33, 36, 83, 230, 245, 253):
                if message_id == 253 or logged_us - timeline_last.get(key, 0) >= 200000:
                    timeline.append({"message": known[0], **sample})
                    timeline_last[key] = logged_us
            last[key] = sample
            recent[key].append(sample)
            if "boot_ms" in sample:
                span = spans.setdefault(key, {"first_boot_ms": sample["boot_ms"], "last_boot_ms": sample["boot_ms"], "first_logged_utc": sample["logged_utc"]})
                span.update(last_boot_ms=sample["boot_ms"], last_logged_utc=sample["logged_utc"])
        offset = end
    return {
        "path": str(path), "bytes": len(data), "first_logged_utc": iso(first_time) if first_time else None,
        "last_logged_utc": iso(last_time) if last_time else None,
        "message_counts": dict(counts), "known_message_crc_failures": dict(bad_crc),
        "skipped_bytes": skipped, "last_samples": last, "boot_time_spans": spans,
        "recent_state_samples": {key: list(value) for key, value in recent.items() if any(name in key for name in ("ATTITUDE", "GLOBAL_POSITION_INT", "LOCAL_POSITION_NED", "ESTIMATOR_STATUS"))},
        "recent_statustext": list(text_messages),
        "parameters": parameters, "parameter_changes": parameter_changes,
        "rc_channel_ranges": rc_ranges,
        "analysis_timeline": timeline,
        "scope": "Saved QGC telemetry only; no vehicle commands or live connection. Unknown message types are counted structurally without CRC validation or payload decoding.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeline-from")
    parser.add_argument("--timeline-to")
    args = parser.parse_args()
    window = None
    if args.timeline_from or args.timeline_to:
        if not args.timeline_from or not args.timeline_to:
            parser.error("Both timeline bounds are required.")
        window = tuple(int(datetime.datetime.fromisoformat(value).timestamp() * 1e6) for value in (args.timeline_from, args.timeline_to))
    result = [summarize(path, window) for path in args.logs]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for item in result:
        print(json.dumps({**{key: item[key] for key in ("path", "first_logged_utc", "last_logged_utc", "known_message_crc_failures", "boot_time_spans")}, "parameters": len(item["parameters"]), "timeline_samples": len(item["analysis_timeline"])}, indent=2))
