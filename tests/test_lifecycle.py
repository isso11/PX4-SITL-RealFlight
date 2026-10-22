import json
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "linux"))
from sitl import cleanup_runtime, require_no_runtime, signal_runtime_process


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.build = ROOT / "tests/fixture-build"
        self.rootfs = ROOT / "tests/fixture-rootfs/plane"

    def process(self, pid, name="px4", **changes):
        executable = self.build / ("bin/px4" if name == "px4" else "build_flightaxis_bridge/flightaxis_bridge")
        return {
            "pid": pid, "name": name, "executable": str(executable),
            "cwd": str(self.rootfs), "birth": str(pid * 10), "uid": 1000,
            **changes,
        }

    def test_old_server_and_four_bridges_block_an_ordinary_launch(self):
        old = [self.process(10)] + [self.process(pid, "flightaxis_bridge") for pid in range(20, 24)]
        with patch("sitl.runtime_processes", return_value=old):
            with self.assertRaisesRegex(RuntimeError, "already exist.*10, 20, 21, 22, 23"):
                require_no_runtime(self.build)

    def test_restart_clears_old_server_and_four_bridges_before_success(self):
        old = [self.process(10)] + [self.process(pid, "flightaxis_bridge") for pid in range(20, 24)]
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(ROOT / "tests"))
            report_path = Path(directory) / "cleanup.json"
            with patch("sitl.os.getuid", return_value=1000, create=True), patch("sitl.runtime_processes", side_effect=[old, [], []]), patch("sitl.signal_runtime_process", return_value=True) as send:
                cleanup_runtime(self.build, self.rootfs, report_path)
            report = json.loads(report_path.read_text())
        self.assertTrue(report["complete"])
        self.assertEqual(report["after"], [])
        self.assertEqual([item.args[0]["pid"] for item in send.call_args_list], [10, 20, 21, 22, 23])
        self.assertTrue(all(item.args[-1] == signal.SIGINT for item in send.call_args_list))

    def test_foreign_rootfs_user_or_executable_prevents_all_signals(self):
        for changes in (
            {"cwd": str(ROOT / "other-plane")},
            {"uid": 2000},
            {"executable": str(ROOT / "other-build/bin/px4")},
        ):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
                self.assertTrue(Path(directory).resolve().is_relative_to(ROOT / "tests"))
                processes = [self.process(10), self.process(20, "flightaxis_bridge", **changes)]
                with patch("sitl.os.getuid", return_value=1000, create=True), patch("sitl.runtime_processes", return_value=processes), patch("sitl.signal_runtime_process") as send:
                    with self.assertRaisesRegex(RuntimeError, "Refusing to stop PID 20"):
                        cleanup_runtime(self.build, self.rootfs, Path(directory) / "cleanup.json")
                send.assert_not_called()

    def test_pid_reuse_cannot_signal_the_replacement_process(self):
        original = self.process(10)
        replacement = {**original, "birth": "999"}
        with patch("sitl.os.getuid", return_value=1000, create=True), patch("sitl.os.pidfd_open", return_value=97, create=True), patch("sitl.os.close") as close, patch("sitl.read_runtime_process", return_value=replacement), patch("sitl.signal.pidfd_send_signal", create=True) as send:
            self.assertFalse(signal_runtime_process(original, self.build, self.rootfs, signal.SIGINT))
        send.assert_not_called()
        close.assert_called_once_with(97)

    def test_verified_process_is_signalled_through_its_pidfd(self):
        original = self.process(10)
        with patch("sitl.os.getuid", return_value=1000, create=True), patch("sitl.os.pidfd_open", return_value=97, create=True), patch("sitl.os.close") as close, patch("sitl.read_runtime_process", return_value=original), patch("sitl.signal.pidfd_send_signal", create=True) as send:
            self.assertTrue(signal_runtime_process(original, self.build, self.rootfs, signal.SIGINT))
        send.assert_called_once_with(97, signal.SIGINT)
        close.assert_called_once_with(97)


if __name__ == "__main__":
    unittest.main()
