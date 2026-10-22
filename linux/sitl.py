"""Local PX4/RealFlight lifecycle and diagnostics. Requires Linux only for run/stop."""
import contextlib
import datetime
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

from udp_relay import UdpRelay

PX4_URL = "https://github.com/PX4/PX4-Autopilot.git"
BRIDGE_URL = "https://github.com/evandas11/PX4-FlightAxis-Bridge.git"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_settings(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cfg["LinuxDirectory"]):
        raise ValueError("LinuxDirectory must be a single directory name.")
    if cfg.get("AircraftProfile", "generic") not in ("generic", "AeroScoutAPM"):
        raise ValueError("AircraftProfile must be generic or AeroScoutAPM.")
    if cfg["Px4Ref"] != "v1.16.0":
        raise ValueError("This initial integration targets v1.16.0; use a separate validated workspace for another PX4 revision.")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", cfg["BridgeRef"]) or cfg["BridgeRef"].startswith("-"):
        raise ValueError("Invalid bridge revision.")
    for field in ("WindowsHostAddress", "FlightAxisAddress"):
        if cfg[field] != "auto":
            ipaddress.IPv4Address(cfg[field])
    home = cfg["Home"]
    for key in ("Latitude", "Longitude", "AltitudeMslMetres", "YawDegrees"):
        if not math.isfinite(float(home[key])):
            raise ValueError("Home coordinates must be finite numbers.")
    if not -90 <= float(home["Latitude"]) <= 90 or not -180 <= float(home["Longitude"]) <= 180:
        raise ValueError("Invalid home latitude/longitude.")
    return cfg


def workspace(cfg):
    return Path.home() / cfg["LinuxDirectory"]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def git_output(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def source_lock(cfg):
    base = workspace(cfg)
    actual = {"px4_ref": cfg["Px4Ref"], "bridge_ref": cfg["BridgeRef"]}
    for name, folder, url in (("px4", "PX4-Autopilot", PX4_URL), ("bridge", "PX4-FlightAxis-Bridge", BRIDGE_URL)):
        repo = base / folder
        if git_output(repo, "remote", "get-url", "origin") != url:
            raise RuntimeError(f"Unexpected {name} repository origin.")
        actual[name + "_commit"] = git_output(repo, "rev-parse", "HEAD")
    path = base / "source-lock.json"
    if path.exists():
        old = json.loads(path.read_text())
        if old != actual:
            raise RuntimeError("Source revisions differ from source-lock.json. Use a fresh LinuxDirectory for different revisions.")
    else:
        expected_px4 = git_output(base / "PX4-Autopilot", "rev-parse", cfg["Px4Ref"] + "^{commit}")
        expected_bridge = git_output(base / "PX4-FlightAxis-Bridge", "rev-parse", cfg["BridgeRef"] + "^{commit}")
        if actual["px4_commit"] != expected_px4 or actual["bridge_commit"] != expected_bridge:
            raise RuntimeError("Checked-out sources do not match the configured revisions.")
        write_json(path, actual)
    return actual


def check_build(cfg):
    base = workspace(cfg)
    build = base / "PX4-Autopilot/build/px4_sitl_nolockstep"
    required = (build / "bin/px4", build / "build_flightaxis_bridge/flightaxis_bridge", build / "etc/init.d-posix/airframes/1200_flightaxis_plane")
    for path in required:
        if not path.is_file():
            raise RuntimeError(f"Build missing: {path}. Run 2-Build-SITL.cmd.")
    lock = source_lock(cfg)
    state_path = base / "build-state.json"
    if not state_path.is_file():
        raise RuntimeError("No successful build record. Run 2-Build-SITL.cmd.")
    if json.loads(state_path.read_text())["sources"] != lock:
        raise RuntimeError("Build record does not match the checked-out sources.")
    return build


def network_host(cfg):
    mode = "nat"
    try:
        result = subprocess.run(["wslinfo", "--networking-mode"], capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip() == "mirrored":
            mode = "mirrored"
    except (OSError, subprocess.TimeoutExpired):
        pass
    if cfg["WindowsHostAddress"] != "auto":
        return cfg["WindowsHostAddress"], mode
    if mode == "mirrored":
        return "127.0.0.1", mode
    result = subprocess.check_output(["ip", "-j", "-4", "route", "show", "default"], text=True)
    routes = json.loads(result)
    for route in routes:
        if "gateway" in route:
            return str(ipaddress.IPv4Address(route["gateway"])), mode
    raise RuntimeError("Cannot identify the Windows host. Set WindowsHostAddress in settings.json.")


def probe_flightaxis(address):
    try:
        with socket.create_connection((address, 18083), timeout=1):
            return True
    except OSError:
        return False


def process_birth(pid):
    # Linux /proc field 22, parsed after the process name which can contain spaces.
    return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]


def read_runtime_process(proc, executable, expected_name):
    if (proc / "exe").resolve(strict=True) != executable.resolve(strict=True):
        return None
    args = (proc / "cmdline").read_bytes().decode(errors="replace").strip("\0").split("\0")
    if not args or Path(args[0]).name != expected_name:
        return None
    fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
    return {
        "pid": int(proc.name), "args": args, "cwd": str((proc / "cwd").resolve(strict=True)),
        "birth": fields[19], "state": fields[0], "ppid": int(fields[1]),
        "pgid": int(fields[2]), "uid": proc.stat().st_uid,
        "executable": str(executable.resolve(strict=True)), "name": expected_name,
    }


def process_matches(executable, expected_name="px4"):
    matches = []
    if not Path("/proc").exists():
        return matches
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            item = read_runtime_process(proc, executable, expected_name)
            if item is not None:
                matches.append(item)
        except (OSError, ValueError):
            continue
    return matches


def runtime_processes(build):
    return process_matches(build / "bin/px4") + process_matches(build / "build_flightaxis_bridge/flightaxis_bridge", "flightaxis_bridge")


def validate_cleanup_target(proc, build, rootfs):
    expected = {
        "px4": build / "bin/px4",
        "flightaxis_bridge": build / "build_flightaxis_bridge/flightaxis_bridge",
    }
    binary = expected.get(proc["name"])
    if binary is None or Path(proc["executable"]).resolve() != binary.resolve() or Path(proc["cwd"]).resolve() != rootfs.resolve() or proc["uid"] != os.getuid():
        raise RuntimeError(f"Refusing to stop PID {proc['pid']}: executable, Linux user or rootfs differs from this project's plane session.")


def signal_runtime_process(proc, build, rootfs, signum):
    """Signal an exact process through a pidfd, checking its birth identity again."""
    validate_cleanup_target(proc, build, rootfs)
    try:
        descriptor = os.pidfd_open(proc["pid"])
    except ProcessLookupError:
        return False
    try:
        try:
            current = read_runtime_process(Path("/proc") / str(proc["pid"]), Path(proc["executable"]), proc["name"])
        except FileNotFoundError:
            return False
        if current is None or current["birth"] != proc["birth"]:
            return False
        validate_cleanup_target(current, build, rootfs)
        try:
            signal.pidfd_send_signal(descriptor, signum)
        except ProcessLookupError:
            return False
        return True
    finally:
        os.close(descriptor)


def cleanup_runtime(build, rootfs, report_path):
    """Stop leftover simulator processes belonging to this exact plane workspace."""
    before = runtime_processes(build)
    report = {"checked_utc": utc_now(), "rootfs": str(rootfs), "before": before, "signals": [], "complete": False}
    try:
        # Validate the whole set before sending any signal.
        for proc in before:
            validate_cleanup_target(proc, build, rootfs)
        remaining = before
        for signum, grace_seconds in ((signal.SIGINT, 5), (signal.SIGTERM, 3), (getattr(signal, "SIGKILL", 9), 2)):
            if not remaining:
                break
            for proc in remaining:
                sent = signal_runtime_process(proc, build, rootfs, signum)
                report["signals"].append({"pid": proc["pid"], "name": proc["name"], "signal": int(signum), "sent": sent})
            deadline = time.monotonic() + grace_seconds
            while True:
                remaining = runtime_processes(build)
                if not remaining or time.monotonic() >= deadline:
                    break
                time.sleep(0.1)
        if remaining:
            raise RuntimeError("Project SITL processes did not exit; a new bridge was not started.")
        report["complete"] = True
        print(f"Restart preparation: cleared {len(before)} leftover PX4/bridge processes from this project's plane rootfs.", flush=True)
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report["after"] = runtime_processes(build)
        write_json(report_path, report)


def require_no_runtime(build):
    existing = runtime_processes(build)
    if existing:
        ids = ", ".join(str(proc["pid"]) for proc in existing)
        raise RuntimeError(f"PX4/bridge processes already exist for this build (PIDs {ids}). Use 7-Start-and-Test.cmd for a controlled restart, or 6-Test-SITL.cmd to inspect the current session.")


def request_launcher_stop(cfg):
    path = workspace(cfg) / "run/launcher.json"
    if not path.exists():
        print("No tracked SITL session.")
        return
    state = json.loads(path.read_text())
    pid = int(state["pid"])
    try:
        alive = process_birth(pid) == state["birth"]
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
        script_match = str(Path(__file__).resolve()).encode() in command
        if alive and script_match:
            os.kill(pid, signal.SIGINT)
            print("Stop requested for this workspace's tracked launcher.")
            return
        raise RuntimeError("Stored PID belongs to a different process; it was not signalled.")
    except FileNotFoundError:
        path.unlink(missing_ok=True)
        print("Cleared stale session metadata; tracked launcher has exited.")


@contextlib.contextmanager
def workspace_guard(base, wait_seconds=0):
    import fcntl
    run_dir = base / "run"
    run_dir.mkdir(exist_ok=True)
    with (base / ".build.lock").open("a") as build_guard, (run_dir / "launcher.lock").open("a") as run_guard:
        try:
            fcntl.flock(build_guard, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A build is running in this workspace.")
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(run_guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("The previous SITL launcher still holds the session lock. No additional bridge was started.")
                time.sleep(0.2)
        yield


def stop(cfg, report_directory=None):
    build = check_build(cfg)
    base = workspace(cfg)
    request_launcher_stop(cfg)
    with workspace_guard(base, wait_seconds=30):
        report_directory = report_directory or base / "run"
        cleanup_runtime(build, base / "rootfs/plane", report_directory / "stop-cleanup.json")


def run(cfg, config_path, test_after_start=False):
    build = check_build(cfg)
    base = workspace(cfg)
    run_dir = base / "run"
    run_dir.mkdir(exist_ok=True)
    if test_after_start:
        # The previous launcher may have lost its console while its separately
        # grouped simulator children survived. Stop the tracked owner first.
        request_launcher_stop(cfg)
    with workspace_guard(base, wait_seconds=30 if test_after_start else 0):
        if test_after_start:
            cleanup_runtime(build, base / "rootfs/plane", config_path.parent / "reports/restart-cleanup.json")
        require_no_runtime(build)
        from aircraft_profile import apply_aircraft_profile
        aircraft_profile = apply_aircraft_profile(base, build, cfg.get("AircraftProfile", "generic"))
        host, mode = network_host(cfg)
        flightaxis = host if cfg["FlightAxisAddress"] == "auto" else cfg["FlightAxisAddress"]
        print(f"Windows host: {host}; networking: {mode}; FlightAxis: {flightaxis}:18083", flush=True)
        print("Waiting up to 30 seconds for RealFlight Link...", flush=True)
        deadline = time.monotonic() + 30
        while not probe_flightaxis(flightaxis):
            if time.monotonic() >= deadline:
                raise RuntimeError("FlightAxis TCP is unreachable. Enable RealFlight Link, check its Windows firewall rule, and run 5-Check-Setup.cmd.")
            time.sleep(0.5)
        relay = None
        child = None
        diagnostic = None
        session_path = run_dir / "launcher.json"
        stopped = False

        def interrupt(_signum, _frame):
            nonlocal stopped
            stopped = True
            if child is not None and child.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGINT)

        old_handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        try:
            if mode != "mirrored":
                relay = UdpRelay((host, 14550)).start()
                print("QGC relay: WSL UDP 14550 -> Windows UDP 14550", flush=True)
            rootfs = base / "rootfs/plane"
            logs = base / "logs"
            rootfs.mkdir(parents=True, exist_ok=True)
            logs.mkdir(exist_ok=True)
            env = os.environ.copy()
            env.update({"PX4_FLIGHTAXIS_IP": flightaxis, "PX4_FLIGHTAXIS_ROOTFS": str(rootfs)})
            for key, field in (("PX4_HOME_LAT", "Latitude"), ("PX4_HOME_LON", "Longitude"), ("PX4_HOME_ALT", "AltitudeMslMetres"), ("PX4_HOME_YAW", "YawDegrees")):
                env[key] = str(cfg["Home"][field])
            log_metadata = logs / "session-latest.json"
            log_output = logs / "session-latest.txt"
            write_json(log_metadata, {"started_utc": utc_now(), "sources": source_lock(cfg), "settings": cfg, "aircraft_profile": aircraft_profile, "windows_host": host, "networking": mode, "rootfs": str(rootfs)})
            child = subprocess.Popen(["make", "px4_sitl_nolockstep", "flightaxis_plane"], cwd=base / "PX4-Autopilot", env=env, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
            write_json(session_path, {"pid": os.getpid(), "birth": process_birth(os.getpid()), "config": str(config_path), "started_utc": utc_now()})
            if test_after_start:
                # Keep the simulator alive after collection, in this same console.
                # This child only reads the identified local SITL instance.
                diagnostic = subprocess.Popen([
                    sys.executable, str(Path(__file__).with_name("smoke_test.py")),
                    str(config_path), str(config_path.parent / "reports"),
                    "--wait-seconds", "90", "--settle-seconds", "15",
                ], start_new_session=True)
            with log_output.open("w", encoding="utf-8") as log:
                for line in child.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                    log.flush()
            result = child.wait()
            if result != 0 and not stopped:
                raise RuntimeError(f"PX4/FlightAxis launcher exited with code {result}. See {logs}.")
        finally:
            if diagnostic is not None and diagnostic.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(diagnostic.pid, signal.SIGTERM)
                try:
                    diagnostic.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(diagnostic.pid, signal.SIGKILL)
                    diagnostic.wait()
            if child is not None and child.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
            if relay is not None:
                relay.close()
                print(f"Relay packets: PX4 -> QGC {relay.to_qgc}; QGC -> PX4 {relay.to_px4}; UDP errors {relay.errors}")
            session_path.unlink(missing_ok=True)
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)


def main():
    if len(sys.argv) != 3:
        raise ValueError("Usage: sitl.py SETTINGS_JSON ACTION")
    config_path, action = Path(sys.argv[1]).resolve(), sys.argv[2]
    cfg = load_settings(config_path)
    base = workspace(cfg)
    if action == "settings":
        print(cfg["LinuxDirectory"] + "\n" + cfg["Px4Ref"] + "\n" + cfg["BridgeRef"])
    elif action == "lock":
        print(json.dumps(source_lock(cfg), indent=2))
    elif action == "mark-built":
        build = base / "PX4-Autopilot/build/px4_sitl_nolockstep"
        for file in (build / "bin/px4", build / "build_flightaxis_bridge/flightaxis_bridge", build / "etc/init.d-posix/airframes/1200_flightaxis_plane"):
            if not file.is_file():
                raise RuntimeError(f"Installer did not produce {file}")
        write_json(base / "build-state.json", {"built_utc": utc_now(), "sources": source_lock(cfg)})
    elif action == "check":
        print("Build verified: " + str(check_build(cfg)))
    elif action == "doctor":
        host, mode = network_host(cfg)
        address = host if cfg["FlightAxisAddress"] == "auto" else cfg["FlightAxisAddress"]
        print(f"Linux workspace: {base}\nWindows host: {host}\nNetwork mode: {mode}\nFlightAxis TCP reachable: {probe_flightaxis(address)}")
        check_build(cfg)
        print("PX4/bridge build record and required files: OK")
    elif action in ("run", "run-test"):
        run(cfg, config_path, test_after_start=action == "run-test")
    elif action == "stop":
        stop(cfg, config_path.parent / "reports")
    else:
        raise ValueError("Unknown action: " + action)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
