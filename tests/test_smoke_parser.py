from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "linux"))
from smoke_test import boolean, capture_runtime_context, field, instance_number, named_constant, readiness_checks, sample_age, timestamp, wait_for_estimator, wait_for_runtime


class SmokeParserTests(unittest.TestCase):
    def test_listener_snapshot_fields(self):
        text = "TOPIC: vehicle_status\n timestamp: 1234567 (0.020000 seconds ago)\n vehicle_type: 1\n gcs_connection_lost: False\n failsafe: false\n"
        self.assertEqual(timestamp(text), 1234567)
        self.assertAlmostEqual(sample_age(text), 0.02)
        self.assertEqual(field(text, "vehicle_type"), "1")
        self.assertIs(boolean(text, "gcs_connection_lost"), False)
        self.assertIs(boolean(text, "failsafe"), False)

    def test_missing_or_malformed_data_cannot_pass_as_false(self):
        self.assertIsNone(boolean("", "failsafe"))
        self.assertIsNone(boolean("failsafe: unexpected", "failsafe"))
        self.assertIsNone(timestamp("Command timed out"))
        self.assertIsNone(sample_age("timestamp: 12345"))
        self.assertGreater(sample_age("timestamp: 12345 (12.4 seconds ago)"), 3)

    def test_instance_selection(self):
        self.assertEqual(instance_number(["px4", "-i", "2"]), 2)
        self.assertEqual(instance_number(["px4", "-i3"]), 3)
        self.assertEqual(instance_number(["px4", "--instance=4"]), 4)
        self.assertEqual(instance_number(["px4", "--instance", "5"]), 5)

    def test_vehicle_class_uses_firmware_constants(self):
        self.assertEqual(named_constant("static constexpr uint8_t VEHICLE_TYPE_FIXED_WING = 2;", "VEHICLE_TYPE_FIXED_WING"), 2)
        self.assertEqual(named_constant("uint8 VEHICLE_TYPE_FIXED_WING = 1", "VEHICLE_TYPE_FIXED_WING"), 1)
        self.assertEqual(named_constant("#define vehicle_status_s_VEHICLE_TYPE_FIXED_WING 2", "VEHICLE_TYPE_FIXED_WING"), 2)
        self.assertIsNone(named_constant("vehicle_type: 2", "VEHICLE_TYPE_FIXED_WING"))

    def test_regression_stationary_sensor_streams_do_not_imply_flight_readiness(self):
        evidence = {"topic/" + name: {"output": output} for name, output in {
            "vehicle_status": "pre_flight_checks_pass: False",
            "vehicle_local_position": "xy_valid: True\nz_valid: True\nvz: -8.43458\nheading_good_for_control: False",
            "vehicle_gps_position": "vel_d_m_s: 0\naltitude_msl_m: 487.972",
            "vehicle_global_position": "alt: 534.37036",
            "vehicle_land_detected": "at_rest: True\nlanded: True",
            "failsafe_flags": "manual_control_signal_lost: True",
        }.items()}
        checks = {name: state for name, state, _ in readiness_checks(evidence)}
        for name in ("Preflight checks", "Stationary vertical-speed consistency", "Stationary MSL-altitude consistency"):
            self.assertEqual(checks[name], "FAIL")
        self.assertEqual(checks["Heading usable for control"], "WARN")

    def test_stationary_consistency_is_not_applied_to_a_moving_aircraft(self):
        evidence = {"topic/vehicle_land_detected": {"output": "at_rest: False\nlanded: False"}}
        checks = {name: state for name, state, _ in readiness_checks(evidence)}
        self.assertEqual(checks["Stationary vertical-speed consistency"], "UNVERIFIED")

    def test_wait_requires_a_stable_pair_after_a_restart(self):
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        def processes(executable, expected_name="px4"):
            if expected_name == "flightaxis_bridge":
                return [{"pid": 20}]
            return [{"pid": 10 if clock[0] < 1 else 11}]

        with patch("smoke_test.time.monotonic", side_effect=lambda: clock[0]), patch("smoke_test.time.sleep", side_effect=sleep), patch("smoke_test.process_matches", side_effect=processes):
            wait_for_runtime(Path("build"), wait_seconds=10, settle_seconds=2)
        self.assertEqual(clock[0], 3)

    def test_wait_times_out_when_no_server_is_running(self):
        clock = [0.0]
        with patch("smoke_test.time.monotonic", side_effect=lambda: clock[0]), patch("smoke_test.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), patch("smoke_test.process_matches", return_value=[]):
            wait_for_runtime(Path("build"), wait_seconds=2, settle_seconds=1)
        self.assertEqual(clock[0], 2)

    def test_wait_does_not_choose_among_duplicate_instances(self):
        with patch("smoke_test.process_matches", return_value=[{"pid": 10}, {"pid": 11}]), patch("smoke_test.time.sleep") as sleep:
            wait_for_runtime(Path("build"), wait_seconds=2, settle_seconds=1)
        sleep.assert_not_called()

    def test_estimator_wait_accepts_only_fresh_advancing_output(self):
        clock = [0.0]
        samples = iter(["TOPIC: vehicle_attitude", "timestamp: 100 (0.01 seconds ago)", "timestamp: 200 (0.01 seconds ago)"])
        with patch("smoke_test.time.monotonic", side_effect=lambda: clock[0]), patch("smoke_test.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), patch("builtins.print"):
            result = wait_for_estimator(lambda: next(samples), 5)
        self.assertTrue(result["ready"])
        self.assertEqual(result["elapsed_seconds"], 2)

    def test_missing_or_retained_attitude_does_not_pass_estimator_wait(self):
        for output in ("TOPIC: vehicle_attitude", "timestamp: 100 (0.01 seconds ago)", "timestamp: 100 (10 seconds ago)"):
            with self.subTest(output=output):
                clock = [0.0]
                with patch("smoke_test.time.monotonic", side_effect=lambda: clock[0]), patch("smoke_test.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), patch("builtins.print"):
                    result = wait_for_estimator(lambda: output, 3)
                self.assertFalse(result["ready"])
                self.assertEqual(result["elapsed_seconds"], 3)

    def test_exit_log_is_collected_without_a_running_process(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            base = Path(directory)
            self.assertTrue(base.resolve().is_relative_to(Path(__file__).resolve().parent))
            (base / "logs").mkdir()
            (base / "logs/session.txt").write_text("bridge connected\nPX4 exited\n")
            report = {}
            capture_runtime_context(base, report)
        self.assertIsNone(report["tracked_launcher"])
        self.assertEqual(report["recent_launcher_log"]["tail"][-1], "PX4 exited")


if __name__ == "__main__":
    unittest.main()
