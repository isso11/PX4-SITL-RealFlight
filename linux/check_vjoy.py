"""Prove four independent RF RC axes, then enable RC-only on this disarmed SITL.

Never arms, assigns axes, calibrates, changes modes, or sends actuator commands.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time

from sitl import check_build, load_settings, process_matches, workspace, write_json
from smoke_test import boolean, instance_number, number, sample_age, timestamp


def parse_rc(output):
    match = re.search(r"^\s*values(?:\[\d+\])?:\s*\[([^\]]+)\]", output, re.M)
    count = number(output, "channel_count")
    age = sample_age(output)
    if not match or count is None or age is None or not 0 <= age <= 0.5:
        raise RuntimeError("Missing or stale input_rc. Check RF Link and the bridge.")
    values = [int(value.strip()) for value in match.group(1).split(",") if value.strip()]
    count = int(count)
    if not 4 <= count <= 18 or len(values) < count:
        raise RuntimeError("Incomplete RC channel array.")
    if boolean(output, "rc_lost") is not False or boolean(output, "rc_failsafe") is not False:
        raise RuntimeError("RC is lost, failsafe, or its status is unreadable.")
    values = values[:count]
    if any(not 800 <= value <= 2200 for value in values):
        raise RuntimeError("RC pulse widths are outside the expected range.")
    return {"timestamp": timestamp(output), "values": values, "age_seconds": age}


def axis_result(samples):
    if len(samples) < 10 or len({s["timestamp"] for s in samples}) < 10:
        raise RuntimeError("Too few fresh advancing RC samples.")
    count = len(samples[0]["values"])
    if any(len(s["values"]) != count for s in samples):
        raise RuntimeError("RC channel count changed during the test.")
    ranges = [{"channel": i + 1, "min": min(s["values"][i] for s in samples),
               "max": max(s["values"][i] for s in samples)} for i in range(count)]
    moving = [r for r in ranges if r["max"] - r["min"] >= 400]
    if len(moving) != 1:
        raise RuntimeError("Expected one axis with at least 400 us travel; found " + str(len(moving)))
    chosen = moving[0]
    if any(r["channel"] != chosen["channel"] and r["max"] - r["min"] > 150 for r in ranges):
        raise RuntimeError("Another channel moved too far. Repeat with only the named axis moving.")
    return {"channel": chosen["channel"], "ranges": ranges}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("settings", type=Path)
    parser.add_argument("reports", type=Path)
    parser.add_argument("--enable-rc", action="store_true")
    args = parser.parse_args()
    report = {"checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "result": "INCOMPLETE", "stages": {}, "evidence": [], "changes": []}
    args.reports.mkdir(parents=True, exist_ok=True)
    def save():
        write_json(args.reports / "vjoy-check.json", report)

    try:
        cfg = load_settings(args.settings)
        build = check_build(cfg)
        rootfs = (workspace(cfg) / "rootfs/plane").resolve()

        def identify():
            servers = process_matches(build / "bin/px4")
            bridges = process_matches(build / "build_flightaxis_bridge/flightaxis_bridge", "flightaxis_bridge")
            if len(servers) != 1 or len(bridges) != 1:
                raise RuntimeError("Expected one project PX4/bridge pair. Run 7-Start-and-Test.cmd first.")
            for proc in servers + bridges:
                if proc["uid"] != os.getuid() or Path(proc["cwd"]).resolve() != rootfs:
                    raise RuntimeError("Runtime user/rootfs differs from this project's plane session.")
            return servers[0], bridges[0]

        server, bridge = identify()
        identity = [(p["pid"], p["birth"]) for p in (server, bridge)]
        report["runtime"] = [server, bridge]
        instance = instance_number(server["args"])

        def command(module, *arguments):
            current = identify()
            if [(p["pid"], p["birth"]) for p in current] != identity:
                raise RuntimeError("SITL restarted during the check. Run this check again.")
            result = subprocess.run([str(build / "bin" / ("px4-" + module)), "--instance", str(instance), *arguments],
                                    cwd=rootfs, capture_output=True, text=True, errors="replace", timeout=4)
            output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.stdout + result.stderr)
            report["evidence"].append({"command": [module, *arguments], "returncode": result.returncode, "output": output})
            if result.returncode:
                raise RuntimeError("PX4 command failed: " + module + " " + " ".join(arguments))
            return output

        def param(name):
            output = command("param", "show", name)
            match = re.search(re.escape(name) + r"[^\r\n:]*:\s*(-?\d+(?:\.\d+)?)", output)
            if not match:
                raise RuntimeError("Cannot read " + name)
            return float(match.group(1))

        def disarmed():
            output = command("listener", "vehicle_status", "-n", "1")
            age = sample_age(output)
            if number(output, "arming_state") != 1 or age is None or not 0 <= age <= 1:
                raise RuntimeError("A fresh DISARMED vehicle_status is required. Do not arm during this check.")

        disarmed()
        if cfg.get("AircraftProfile") != "AeroScoutAPM" or param("SYS_AUTOSTART") != 1200 or param("PWM_MAIN_FUNC5") != 0:
            raise RuntimeError("AeroScout profile / airframe 1200 / neutral channel 5 is not active. Run 7-Start-and-Test.cmd.")
        report["parameters_before"] = {name: param(name) for name in (
            "COM_RC_IN_MODE", "SYS_AUTOCONFIG", "RC_MAP_ROLL", "RC_MAP_PITCH", "RC_MAP_THROTTLE", "RC_MAP_YAW")}
        if report["parameters_before"]["SYS_AUTOCONFIG"] != 0:
            raise RuntimeError("SYS_AUTOCONFIG is pending. Resolve the airframe selection before calibration.")
        save()
        print("\nKeep the virtual aircraft DISARMED. Use the same vJoy feeder/controller you use with RealFlight.", flush=True)
        print("Each stage records for 8 seconds. Sweep ONLY the named axis repeatedly through full travel.", flush=True)
        for axis in ("roll", "pitch", "throttle", "yaw"):
            input(f"\nPrepare to move {axis.upper()} only. Press Enter when ready, then move it for 8 seconds: ")
            disarmed()
            samples = []
            report["stages"][axis] = {"samples": samples}
            print("MOVE " + axis.upper() + " NOW", flush=True)
            end = time.monotonic() + 8
            last_stamp = None
            while time.monotonic() < end:
                disarmed()
                sample = parse_rc(command("listener", "input_rc", "-n", "1"))
                if last_stamp is not None and sample["timestamp"] <= last_stamp:
                    raise RuntimeError("RC timestamps stopped advancing.")
                samples.append(sample)
                last_stamp = sample["timestamp"]
                time.sleep(0.08)
            result = axis_result(samples)
            report["stages"][axis].update(result)
            print(f"Observed {axis}: RF RC channel {result['channel']}", flush=True)
            save()
        channels = [stage["channel"] for stage in report["stages"].values()]
        if len(set(channels)) != 4:
            raise RuntimeError("The four controls did not produce four independent channels.")
        input("\nReturn throttle to LOW and center the other controls. Press Enter when ready: ")
        disarmed()
        resting = parse_rc(command("listener", "input_rc", "-n", "1"))
        report["resting_input"] = resting
        throttle = report["stages"]["throttle"]
        endpoint = throttle["ranges"][throttle["channel"] - 1]
        value = resting["values"][throttle["channel"] - 1]
        if min(abs(value - endpoint["min"]), abs(value - endpoint["max"])) > 100:
            raise RuntimeError("Throttle is not near a measured endpoint. Return it to LOW and repeat.")
        if args.enable_rc:
            disarmed()
            if param("SYS_AUTOSTART") != 1200 or param("PWM_MAIN_FUNC5") != 0 or param("SYS_AUTOCONFIG") != 0:
                raise RuntimeError("Airframe settings changed during the check.")
            old = param("COM_RC_IN_MODE")
            report["changes"].append({"parameter": "COM_RC_IN_MODE", "before": old, "requested": 0, "verified": False})
            save()  # Preserve the old value before the only parameter mutation.
            command("param", "set", "COM_RC_IN_MODE", "0")
            if param("COM_RC_IN_MODE") != 0:
                raise RuntimeError("RC-only setting could not be verified; inspect changes/evidence before continuing.")
            report["changes"][-1]["verified"] = True
        report["result"] = "INPUT_VERIFIED_CALIBRATION_REQUIRED"
        print("\nFour independent raw RC axes verified." + (" COM_RC_IN_MODE=0 verified." if args.enable_rc else " No parameters changed."), flush=True)
        print("Next: QGroundControl > Vehicle Setup > Radio > Calibrate. Follow its stick prompts with vJoy.", flush=True)
        print("This check does not establish calibrated direction, aircraft readiness, or flight safety. Remain disarmed.", flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        report["result"] = "STOPPED"
        report["error"] = str(error) or "Interrupted"
        print("\nSTOPPED: " + report["error"], flush=True)
        return 1
    finally:
        save()
        print("Report: " + str(args.reports / "vjoy-check.json"), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
