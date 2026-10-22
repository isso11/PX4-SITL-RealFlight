"""Apply the selected model's narrow startup overrides in this dedicated SITL checkout."""
import hashlib

from sitl import write_json

UPSTREAM_AIRFRAME_SHA256 = "9c8a38ba6d63f7f2b63128ef8f22cc20e665cd5ebd0046d0585699e951622e64"
PROFILE_BLOCK = (
    b"\n# Local AeroScout APM profile: RF ch1 drives the combined ailerons.\n"
    b"# RF ch5 drives nose-wheel steering, so it must not receive Servo 2.\n"
    b"# Disabled output is converted to neutral 0.5 by the identity bridge map.\n"
    b"param set PWM_MAIN_FUNC5 0\n"
)


def apply_aircraft_profile(base, build, profile):
    if profile not in ("generic", "AeroScoutAPM"):
        raise ValueError("Unsupported aircraft profile.")
    relative = "ROMFS/px4fmu_common/init.d-posix/airframes/1200_flightaxis_plane"
    paths = {
        (base / "PX4-Autopilot" / relative).resolve(),
        (build / "etc/init.d-posix/airframes/1200_flightaxis_plane").resolve(),
    }
    planned = []
    # Validate every destination before modifying any file. Preserve unknown edits.
    for path in sorted(paths):
        contents = path.read_bytes()
        original = contents[:-len(PROFILE_BLOCK)] if contents.endswith(PROFILE_BLOCK) else contents
        if profile == "generic" and original == contents:
            continue
        if hashlib.sha256(original).hexdigest() != UPSTREAM_AIRFRAME_SHA256:
            raise RuntimeError(f"Airframe has unrecognized edits: {path}. Aircraft profile was not applied.")
        desired = original + PROFILE_BLOCK if profile == "AeroScoutAPM" else original
        planned.append((path, contents, desired))
    changes = []
    for path, before, after in planned:
        if before != after:
            path.write_bytes(after)
        changes.append({"path": str(path), "changed": before != after, "sha256": hashlib.sha256(after).hexdigest()})
    record = {
        "profile": profile, "upstream_airframe_sha256": UPSTREAM_AIRFRAME_SHA256,
        "overrides": {"PWM_MAIN_FUNC5": 0} if profile == "AeroScoutAPM" else {},
        "files": changes, "roll_direction_validated": False,
    }
    write_json(base / "run/aircraft-profile.json", record)
    print(f"Aircraft profile: {profile}" + ("; channel 5 steering held neutral." if profile == "AeroScoutAPM" else ""), flush=True)
    return record
