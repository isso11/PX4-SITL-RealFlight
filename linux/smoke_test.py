"""Read-only live checks against one identified PX4 SITL process in this project."""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys
import time

from sitl import check_build, load_settings, process_matches, workspace, write_json


def field(text, name):
    match = re.search(r"^\s*" + re.escape(name) + r":\s*([^\r\n]+)", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def boolean(text, name):
    value = field(text, name)
    if value is None:
        return None
    return {"true": True, "false": False, "1": True, "0": False}.get(value.lower())


def timestamp(text):
    value = field(text, "timestamp")
    match = re.match(r"\d+", value or "")
    return int(match.group()) if match else None


def sample_age(text):
    value = field(text, "timestamp")
    match = re.search(r"\(([0-9.eE+-]+)\s+seconds? ago\)", value or "")
    return float(match.group(1)) if match else None


def wait_for_estimator(read_attitude, timeout_seconds):
    """Wait for two fresh advancing outputs, keeping missing/stale samples as evidence."""
    started = time.monotonic()
    deadline = started + timeout_seconds
    previous_stamp = None
    last_notice = None
    samples = []
    while True:
        output = read_attitude()
        stamp, age = timestamp(output), sample_age(output)
        now = time.monotonic()
        fresh = stamp is not None and age is not None and 0 <= age <= 1.0
        ready = fresh and previous_stamp is not None and stamp > previous_stamp
        samples.append({"elapsed_seconds": now - started, "timestamp": stamp, "age_seconds": age})
        if ready or now >= deadline:
            return {"ready": bool(ready), "elapsed_seconds": now - started, "samples": samples}
        previous_stamp = stamp if fresh else None
        if last_notice is None or now - last_notice >= 5:
            print(f"Waiting for live EKF attitude output: {now - started:.0f}/{timeout_seconds:g} s...", flush=True)
            last_notice = now
        time.sleep(min(1.0, deadline - now))


def number(text, name):
    value = field(text, name)
    try:
        parsed = float((value or "").split()[0])
        return parsed if math.isfinite(parsed) else None
    except (ValueError, IndexError):
        return None


def named_constant(text, name):
    for pattern in (r"\b" + re.escape(name) + r"\s*=\s*(\d+)", r"^\s*#define\s+\w*" + re.escape(name) + r"\s+(\d+)"):
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return int(match.group(1))
    return None


def firmware_fixed_wing_constant(base, build):
    for path in (build / "uORB/topics/vehicle_status.h", base / "PX4-Autopilot/msg/versioned/VehicleStatus.msg", base / "PX4-Autopilot/msg/VehicleStatus.msg"):
        if path.is_file():
            constant = named_constant(path.read_text(errors="replace"), "VEHICLE_TYPE_FIXED_WING")
            if constant is not None:
                return constant, str(path)
    return None, None


def readiness_checks(evidence):
    def topic(name):
        return evidence.get("topic/" + name, {}).get("output", "")
    status, local = topic("vehicle_status"), topic("vehicle_local_position")
    gps, global_position = topic("vehicle_gps_position"), topic("vehicle_global_position")
    landed = topic("vehicle_land_detected")
    checks = []
    preflight = boolean(status, "pre_flight_checks_pass")
    checks.append(("Preflight checks", "PASS" if preflight is True else "FAIL" if preflight is False else "UNVERIFIED", f"pre_flight_checks_pass={preflight}"))
    heading = boolean(local, "heading_good_for_control")
    checks.append(("Heading usable for control", "PASS" if heading is True else "WARN" if heading is False else "UNVERIFIED", f"heading_good_for_control={heading}; interpret against the selected mode and installed estimator logic"))
    manual_lost = boolean(topic("failsafe_flags"), "manual_control_signal_lost")
    checks.append(("Manual-control input", "WARN" if manual_lost is True else "PASS" if manual_lost is False else "UNVERIFIED", f"manual_control_signal_lost={manual_lost}; inspect the required input for the selected flight mode"))
    gps_vz, estimated_vz = number(gps, "vel_d_m_s"), number(local, "vz")
    stationary = boolean(landed, "at_rest") is True and boolean(landed, "landed") is True and gps_vz is not None and abs(gps_vz) <= 0.2
    if stationary and estimated_vz is not None:
        error = abs(estimated_vz - gps_vz)
        checks.append(("Stationary vertical-speed consistency", "PASS" if error <= 1.0 else "FAIL", f"GPS NED vz={gps_vz:.3f} m/s; EKF vz={estimated_vz:.3f} m/s; difference={error:.3f} m/s (bench threshold 1 m/s)"))
    else:
        checks.append(("Stationary vertical-speed consistency", "UNVERIFIED", "Stationary bench conditions or required measurements are unavailable."))
    gps_alt, estimated_alt = number(gps, "altitude_msl_m"), number(global_position, "alt")
    if stationary and gps_alt is not None and estimated_alt is not None:
        error = abs(estimated_alt - gps_alt)
        checks.append(("Stationary MSL-altitude consistency", "PASS" if error <= 5.0 else "FAIL", f"GPS MSL={gps_alt:.3f} m; EKF MSL={estimated_alt:.3f} m; difference={error:.3f} m (bench threshold 5 m)"))
    return checks


def capture_source_snapshot(base, build, output_dir):
    paths = [
        base / "PX4-Autopilot/msg/VehicleStatus.msg",
        base / "PX4-Autopilot/msg/versioned/VehicleStatus.msg",
        build / "uORB/topics/vehicle_status.h",
        build / ".config",
        base / "PX4-Autopilot/src/modules/simulation/simulator_mavlink/SimulatorMavlink.cpp",
        base / "PX4-Autopilot/src/modules/simulation/simulator_mavlink/SimulatorMavlink.hpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF2.cpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF2.hpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF2Selector.cpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF2Selector.hpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF/ekf.cpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF/ekf.h",
        base / "PX4-Autopilot/src/modules/ekf2/EKF/estimator_interface.cpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF/estimator_interface.h",
        base / "PX4-Autopilot/src/modules/ekf2/EKF/imu_down_sampler.cpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF/imu_down_sampler.hpp",
        base / "PX4-Autopilot/src/lib/mathlib/math/filter/AlphaFilter.hpp",
        base / "PX4-Autopilot/src/modules/sensors/vehicle_imu/VehicleIMU.cpp",
        base / "PX4-Autopilot/src/lib/drivers/accelerometer/PX4Accelerometer.cpp",
        base / "PX4-Autopilot/src/lib/drivers/gyroscope/PX4Gyroscope.cpp",
        base / "PX4-Autopilot/msg/HealthReport.msg",
        base / "PX4-Autopilot/src/modules/commander/HealthAndArmingChecks/checks/estimatorCheck.cpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF/control.cpp",
        base / "PX4-Autopilot/src/modules/ekf2/EKF/ekf_helper.cpp",
        base / "PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/1200_flightaxis_plane",
        base / "PX4-Autopilot/Tools/simulation/flightaxis/sitl_run.sh",
        base / "PX4-Autopilot/Tools/simulation/flightaxis/flightaxis_bridge/models/plane.json",
        base / "PX4-FlightAxis-Bridge/FLIGHTAXIS_PX4_INTEGRATION.md",
    ]
    source_root = base / "PX4-Autopilot/Tools/simulation/flightaxis/flightaxis_bridge/src"
    if source_root.is_dir():
        paths.extend(path for path in source_root.iterdir() if path.is_file() and path.suffix in (".cpp", ".h", ".hpp"))
    manifest = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(base)
        destination = output_dir / "debug-source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        manifest.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    write_json(output_dir / "debug-source/manifest.json", manifest)
    return manifest


def instance_number(args):
    for index, item in enumerate(args):
        if item in ("-i", "--instance") and index + 1 < len(args):
            return int(args[index + 1])
        if re.fullmatch(r"-i\d+", item):
            return int(item[2:])
        if item.startswith("--instance="):
            return int(item.split("=", 1)[1])
    return 0


def wait_for_runtime(build, wait_seconds, settle_seconds):
    """Wait for one exact-build server pair, resetting the settle time on restart."""
    deadline = time.monotonic() + wait_seconds
    stable_identity = None
    stable_since = None
    while True:
        servers = process_matches(build / "bin/px4")
        bridges = process_matches(build / "build_flightaxis_bridge/flightaxis_bridge", "flightaxis_bridge")
        now = time.monotonic()
        if len(servers) > 1 or len(bridges) > 1:
            return
        if len(servers) == 1 and len(bridges) == 1:
            identity = (servers[0]["pid"], bridges[0]["pid"])
            if identity != stable_identity:
                stable_identity, stable_since = identity, now
            if now - stable_since >= settle_seconds:
                return
        else:
            stable_identity, stable_since = None, None
        if now >= deadline:
            return
        time.sleep(min(0.5, deadline - now))


def capture_runtime_context(base, report):
    """Keep exit evidence even when the simulator is no longer running."""
    try:
        session = base / "run/launcher.json"
        report["tracked_launcher"] = json.loads(session.read_text()) if session.is_file() else None
        profile = base / "run/aircraft-profile.json"
        if profile.is_file():
            report["aircraft_profile"] = json.loads(profile.read_text())
        logs = sorted((base / "logs").glob("*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)
        if logs:
            report["recent_launcher_log"] = {
                "path": str(logs[0]),
                "modified_utc": datetime.datetime.fromtimestamp(logs[0].stat().st_mtime, datetime.timezone.utc).isoformat(),
                "tail": logs[0].read_text(errors="replace").splitlines()[-150:],
            }
    except (OSError, ValueError) as error:
        report["runtime_context_error"] = str(error)


def main(config_path, output_dir, wait_seconds=0, settle_seconds=0, estimator_wait_seconds=60):
    cfg = load_settings(config_path)
    base = workspace(cfg)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Read-only live integration check; no arming, flight, control inputs, mission upload, or parameter changes.",
        "workspace": str(base), "checks": [], "evidence": {},
        "flight_test": "NOT_RUN", "actuator_direction_test": "NOT_RUN",
    }

    def check(name, status, detail):
        report["checks"].append({"name": name, "status": status, "detail": detail})
        print(f"[{status}] {name}: {detail}", flush=True)

    def finish():
        statuses = [item["status"] for item in report["checks"]]
        report["overall"] = "FAIL" if "FAIL" in statuses else "INCOMPLETE" if "UNVERIFIED" in statuses else "PASS"
        write_json(output_dir / "sitl-smoke-test.json", report)
        lines = ["# Live SITL check", "", "UTC: " + report["checked_utc"], "", "Result: **" + report["overall"] + "**", "", report["scope"], "", "| Check | Result | Detail |", "|---|---|---|"]
        for item in report["checks"]:
            detail = str(item["detail"]).replace("|", "/").replace("\n", " ")
            lines.append(f"| {item['name']} | {item['status']} | {detail} |")
        lines += ["", "Flight and actuator-direction tests were not run. Passing this check confirms only the observed process/link/sensor/estimator conditions.", "", "Raw command output is retained in sitl-smoke-test.json."]
        (output_dir / "sitl-smoke-test.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\nDiagnostic result: " + report["overall"], flush=True)
        print("Report: " + str(output_dir / "sitl-smoke-test.md"), flush=True)
        if wait_seconds:
            print("Collection finished. Keep this launcher open to keep SITL running; Ctrl+C stops it.", flush=True)
        return 0 if report["overall"] == "PASS" else 1

    try:
        build = check_build(cfg)
        report["build"] = json.loads((base / "build-state.json").read_text())
        check("PX4 and bridge build", "PASS", "Required binaries, fixed-wing airframe and pinned source record exist.")
    except Exception as error:
        check("PX4 and bridge build", "FAIL", str(error))
        return finish()
    try:
        report["source_snapshot"] = capture_source_snapshot(base, build, output_dir)
    except Exception as error:
        report["source_snapshot_error"] = str(error)
        check("Installed source capture", "UNVERIFIED", str(error))
    expected_fixed_wing, enum_source = firmware_fixed_wing_constant(base, build)
    report["fixed_wing_definition"] = {"value": expected_fixed_wing, "source": enum_source}
    if wait_seconds:
        print(f"Waiting up to {wait_seconds:g} s for PX4 and bridge, including {settle_seconds:g} s to settle...", flush=True)
        started_wait = time.monotonic()
        wait_for_runtime(build, wait_seconds, settle_seconds)
        report["startup_wait"] = {"elapsed_seconds": time.monotonic() - started_wait, "settle_seconds": settle_seconds}
        # Timestamp the observation after waiting, rather than before startup.
        report["checked_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    capture_runtime_context(base, report)

    bridges = process_matches(build / "build_flightaxis_bridge/flightaxis_bridge", "flightaxis_bridge")
    report["bridge_processes"] = bridges
    check("Running FlightAxis bridge", "PASS" if len(bridges) == 1 else "FAIL", f"Found {len(bridges)} bridge processes from this exact build.")
    processes = process_matches(build / "bin/px4")
    report["px4_processes"] = processes
    if len(processes) != 1:
        check("Running PX4 SITL", "FAIL", f"Found {len(processes)} server processes from this exact build; expected one. Use 7-Start-and-Test.cmd to start SITL and collect automatically.")
        return finish()
    server = processes[0]
    instance = instance_number(server["args"])
    check("Running PX4 SITL", "PASS", f"Identified local Linux SITL PID {server['pid']}, instance {instance}.")
    report["instance"] = instance
    if len(bridges) != 1:
        # Do not report health from an old server while another launch waits
        # forever for that server's occupied instance number.
        return finish()

    def command(label, module, *arguments):
        binary = build / "bin" / ("px4-" + module)
        if not binary.is_file():
            result = {"returncode": None, "output": "Module client does not exist: " + str(binary)}
        else:
            try:
                completed = subprocess.run([str(binary), "--instance", str(instance), *arguments], cwd=server["cwd"], capture_output=True, text=True, errors="replace", timeout=4)
                output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", completed.stdout + completed.stderr)
                result = {"returncode": completed.returncode, "output": output}
            except subprocess.TimeoutExpired as error:
                result = {"returncode": None, "output": "Command timed out after 4 seconds."}
                for part in (error.stdout, error.stderr):
                    if part:
                        result["output"] += "\n" + (part.decode(errors="replace") if isinstance(part, bytes) else part)
        report["evidence"][label] = result
        return result

    version = command("version", "ver", "all")
    check("SITL command connection", "PASS" if version["returncode"] == 0 else "FAIL", "Queried the identified local PX4 instance." if version["returncode"] == 0 else version["output"][:250])
    if version["returncode"] != 0:
        return finish()
    autostart = command("SYS_AUTOSTART", "param", "show", "SYS_AUTOSTART")
    match = re.search(r"SYS_AUTOSTART[^\r\n:]*:\s*(\d+)", autostart["output"])
    check("Fixed-wing airframe", "PASS" if match and int(match.group(1)) == 1200 else "FAIL", "SYS_AUTOSTART=" + (match.group(1) if match else "unreadable"))
    if cfg.get("AircraftProfile") == "AeroScoutAPM":
        steering = command("PWM_MAIN_FUNC5", "param", "show", "PWM_MAIN_FUNC5")
        assignment = re.search(r"PWM_MAIN_FUNC5[^\r\n:]*:\s*(\d+)", steering["output"])
        neutral = assignment is not None and int(assignment.group(1)) == 0
        check("AeroScout channel 5 steering", "PASS" if neutral else "FAIL", "PWM_MAIN_FUNC5=" + (assignment.group(1) if assignment else "unreadable") + "; the model's nose-wheel steering must not receive the second aileron output.")

    startup_probe_index = 0

    def read_startup_attitude():
        nonlocal startup_probe_index
        result = command(f"estimator-startup/attitude/{startup_probe_index}", "listener", "vehicle_attitude", "-n", "1")
        if startup_probe_index % 5 == 0:
            command(f"estimator-startup/ekf2/{startup_probe_index}", "ekf2", "status")
        startup_probe_index += 1
        return result["output"] if result["returncode"] == 0 else ""

    report["estimator_wait"] = wait_for_estimator(read_startup_attitude, estimator_wait_seconds)
    check("EKF attitude initialization", "PASS" if report["estimator_wait"]["ready"] else "FAIL", f"Waited {report['estimator_wait']['elapsed_seconds']:.1f} s for fresh advancing attitude output (limit {estimator_wait_seconds:g} s).")

    topics = {}

    def topic(name, suffix=""):
        key = name + suffix
        if key not in topics:
            result = command("topic/" + key, "listener", name, "-n", "1")
            topics[key] = result["output"] if result["returncode"] == 0 else ""
        return topics[key]

    before = topic("vehicle_attitude")
    status = topic("vehicle_status")
    local_position = topic("vehicle_local_position")
    topic("vehicle_global_position")
    topic("vehicle_control_mode")
    topic("failsafe_flags")
    topic("estimator_status_flags")
    topic("vehicle_land_detected")
    topic("actuator_outputs")
    topic("mission_result")
    for diagnostic_topic in ("health_report", "vehicle_attitude_groundtruth", "vehicle_local_position_groundtruth", "vehicle_global_position_groundtruth", "vehicle_imu", "vehicle_imu_status", "vehicle_acceleration", "sensor_combined", "sensor_selection", "vehicle_magnetometer", "vehicle_air_data", "ekf2_timestamps", "estimator_selector_status", "estimator_attitude", "estimator_sensor_bias", "distance_sensor", "estimator_status", "estimator_innovations", "estimator_innovation_test_ratios", "estimator_aid_src_gnss_vel", "estimator_aid_src_gnss_hgt", "estimator_aid_src_baro_hgt", "estimator_aid_src_rng_hgt", "airspeed_validated", "manual_control_setpoint", "input_rc", "rc_channels"):
        topic(diagnostic_topic)
    for label, candidates in (
        ("Gyroscope stream", ("sensor_gyro", "vehicle_angular_velocity")),
        ("Accelerometer stream", ("sensor_accel", "vehicle_acceleration")),
        ("Magnetometer stream", ("sensor_mag",)),
        ("GPS stream", ("vehicle_gps_position", "sensor_gps")),
        ("Pressure stream", ("sensor_baro", "vehicle_air_data")),
        ("Airspeed stream", ("airspeed", "airspeed_validated")),
    ):
        samples = []
        for name in candidates:
            text = topic(name)
            age = sample_age(text)
            samples.append({"topic": name, "timestamp": timestamp(text), "age_seconds": age})
            if age is not None and age <= 3.0:
                break
        fresh = [sample for sample in samples if sample["age_seconds"] is not None and sample["age_seconds"] <= 3.0]
        result = "PASS" if fresh else "FAIL" if all(sample["timestamp"] is None for sample in samples) or any(sample["age_seconds"] is not None for sample in samples) else "UNVERIFIED"
        check(label, result, json.dumps(samples))

    # Do not treat an old retained sample as a working simulator.
    time.sleep(0.25)
    after = topic("vehicle_attitude", "/second")
    first_stamp, second_stamp = timestamp(before), timestamp(after)
    check("Attitude updates advance", "PASS" if first_stamp is not None and second_stamp is not None and second_stamp > first_stamp else "FAIL", f"timestamp {first_stamp} -> {second_stamp}")
    xy, z = boolean(local_position, "xy_valid"), boolean(local_position, "z_valid")
    check("Estimator position validity", "PASS" if xy is True and z is True else "UNVERIFIED" if xy is None or z is None else "FAIL", f"xy_valid={xy}; z_valid={z}")
    vehicle_type = field(status, "vehicle_type")
    match = re.match(r"\d+", vehicle_type or "")
    class_result = "UNVERIFIED" if expected_fixed_wing is None else "PASS" if match and int(match.group()) == expected_fixed_wing else "FAIL"
    check("Reported vehicle class", class_result, f"vehicle_type={vehicle_type}; compiled fixed-wing constant={expected_fixed_wing}; source={enum_source}")
    gcs_lost = boolean(status, "gcs_connection_lost")
    check("Ground station heartbeat", "PASS" if gcs_lost is False else "UNVERIFIED" if gcs_lost is None else "FAIL", "gcs_connection_lost=" + str(gcs_lost))
    failsafe = boolean(status, "failsafe")
    check("Active failsafe state", "PASS" if failsafe is False else "UNVERIFIED" if failsafe is None else "FAIL", "failsafe=" + str(failsafe))
    for readiness_check in readiness_checks(report["evidence"]):
        check(*readiness_check)
    command("commander/status", "commander", "status")
    command("mavlink/status", "mavlink", "status")
    command("ekf2/status", "ekf2", "status")
    if not report["estimator_wait"]["ready"]:
        command("ekf2/verbose-status", "ekf2", "status", "-v")
    command("work_queue/status", "work_queue", "status")
    command("simulator/status", "simulator_mavlink", "status")
    for pattern in ("EKF2_*", "SIM_*", "COM_ARM_*", "COM_RC_IN_MODE", "RC_MAP_*", "RC1_*", "RC2_*", "RC3_*", "RC4_*", "RC5_*", "NAV_RCL_ACT", "FW_AIRSPD_*", "SENS_DPRES_*", "CAL_ACC*", "CAL_GYRO*", "CAL_MAG*", "SENS_IMU_*", "SENS_MAG_AUTOCAL", "IMU_GYRO_CAL_EN", "PWM_MAIN_FUNC*", "PWM_MAIN_REV", "CA_SV_CS*", "FD_*", "SYS_AUTOCONFIG"):
        command("parameters/" + pattern, "param", "show", pattern)
    report["stationary_trace"] = []
    for index in range(3):
        if index:
            time.sleep(1.0)
        trace = {"monotonic_seconds": time.monotonic()}
        for name in ("vehicle_local_position", "vehicle_gps_position", "vehicle_global_position", "vehicle_local_position_groundtruth"):
            result = command(f"trace/{index}/{name}", "listener", name, "-n", "1")
            trace[name] = result["output"]
        report["stationary_trace"].append(trace)
    for module in ("fw_att_control", "fw_rate_control", "fw_pos_control"):
        result = command(module + "/status", module, "status")
        check(module, "PASS" if result["returncode"] == 0 else "FAIL", result["output"].strip()[:200])

    try:
        sockets = subprocess.run(["ss", "-tnp"], capture_output=True, text=True, timeout=4)
        socket_lines = [line for line in sockets.stdout.splitlines() if re.search(r":(4560|18083)\b", line)]
        report["evidence"]["tcp_sockets"] = socket_lines
        for label, port in (("Bridge to RealFlight TCP", 18083), ("PX4 simulator TCP", 4560)):
            relevant = [line for line in socket_lines if re.search(r":" + str(port) + r"\b", line) and line.startswith("ESTAB")]
            owned = [line for line in relevant if any(f"pid={proc['pid']}," in line for proc in bridges + processes)]
            check(label, "PASS" if owned else "UNVERIFIED" if relevant else "FAIL", f"Established connections: {len(relevant)}; identified project process ownership: {len(owned)}.")
    except (OSError, subprocess.TimeoutExpired) as error:
        report["evidence"]["tcp_sockets_error"] = str(error)
        check("TCP transport inspection", "UNVERIFIED", str(error))
    final_servers = process_matches(build / "bin/px4")
    final_bridges = process_matches(build / "build_flightaxis_bridge/flightaxis_bridge", "flightaxis_bridge")
    same_servers = [item["pid"] for item in final_servers] == [item["pid"] for item in processes]
    same_bridges = [item["pid"] for item in final_bridges] == [item["pid"] for item in bridges]
    check("Runtime stable during collection", "PASS" if same_servers and same_bridges else "FAIL", "PX4 and bridge identities unchanged." if same_servers and same_bridges else "PX4 or bridge stopped/restarted during the capture; rerun with the simulator stationary.")
    capture_runtime_context(base, report)
    if report.get("recent_launcher_log"):
        factors = [float(value) for value in re.findall(r"realtime factor ([0-9.]+)", "\n".join(report["recent_launcher_log"]["tail"]))]
        if factors:
            check("Bridge timing warnings", "WARN", f"Logged realtime factors: min={min(factors):.3f}, max={max(factors):.3f}, last={factors[-1]:.3f}. These values come from the current launcher log, not a new clock measurement.")
    return finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config_path", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--wait-seconds", type=float, default=0)
    parser.add_argument("--settle-seconds", type=float, default=0)
    parser.add_argument("--estimator-wait-seconds", type=float, default=60)
    args = parser.parse_args()
    if not 0 <= args.settle_seconds <= args.wait_seconds <= 180:
        parser.error("Require 0 <= settle-seconds <= wait-seconds <= 180.")
    if not 0 <= args.estimator_wait_seconds <= 90:
        parser.error("Require 0 <= estimator-wait-seconds <= 90.")
    try:
        sys.exit(main(args.config_path, args.output_dir, args.wait_seconds, args.settle_seconds, args.estimator_wait_seconds))
    except Exception as error:
        directory = args.output_dir
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / "sitl-smoke-test.json", {"overall": "ERROR", "error": str(error), "flight_test": "NOT_RUN"})
        (directory / "sitl-smoke-test.md").write_text("# Live SITL check\n\nResult: **ERROR**\n\n" + str(error) + "\n", encoding="utf-8")
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
