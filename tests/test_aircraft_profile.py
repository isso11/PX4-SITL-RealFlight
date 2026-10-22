import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "linux"))
from aircraft_profile import PROFILE_BLOCK, apply_aircraft_profile


class AircraftProfileTests(unittest.TestCase):
    def paths(self, base):
        build = base / "PX4-Autopilot/build/px4_sitl_nolockstep"
        source = base / "PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/1200_flightaxis_plane"
        installed = build / "etc/init.d-posix/airframes/1200_flightaxis_plane"
        for path in (source, installed):
            path.parent.mkdir(parents=True, exist_ok=True)
        return build, source, installed

    def test_profile_is_idempotent_and_can_restore_the_original(self):
        original = b"param set-default PWM_MAIN_FUNC5 202\n"
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            base = Path(directory).resolve()
            self.assertTrue(base.is_relative_to(ROOT / "tests"))
            build, source, installed = self.paths(base)
            source.write_bytes(original)
            installed.write_bytes(original)
            with patch("aircraft_profile.UPSTREAM_AIRFRAME_SHA256", hashlib.sha256(original).hexdigest()), patch("builtins.print"):
                apply_aircraft_profile(base, build, "AeroScoutAPM")
                apply_aircraft_profile(base, build, "AeroScoutAPM")
                self.assertEqual(source.read_bytes(), original + PROFILE_BLOCK)
                self.assertEqual(installed.read_bytes(), original + PROFILE_BLOCK)
                apply_aircraft_profile(base, build, "generic")
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(installed.read_bytes(), original)

    def test_unrecognized_edits_prevent_all_profile_writes(self):
        original = b"param set-default PWM_MAIN_FUNC5 202\n"
        changed = original + b"# user edit\n"
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            base = Path(directory).resolve()
            self.assertTrue(base.is_relative_to(ROOT / "tests"))
            build, source, installed = self.paths(base)
            source.write_bytes(original)
            installed.write_bytes(changed)
            with patch("aircraft_profile.UPSTREAM_AIRFRAME_SHA256", hashlib.sha256(original).hexdigest()):
                with self.assertRaisesRegex(RuntimeError, "unrecognized edits"):
                    apply_aircraft_profile(base, build, "AeroScoutAPM")
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(installed.read_bytes(), changed)


if __name__ == "__main__":
    unittest.main()
