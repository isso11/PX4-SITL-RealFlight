import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "linux"))
from udp_relay import UdpRelay
from sitl import load_settings


class SetupTests(unittest.TestCase):
    def test_example_settings_work_without_local_configuration(self):
        cfg = load_settings(ROOT / "settings.example.json")
        self.assertEqual(cfg["Px4Ref"], "v1.16.0")
        self.assertEqual(len(cfg["BridgeRef"]), 40)
        self.assertEqual(cfg["AircraftProfile"], "generic")

    def test_bidirectional_udp_preserves_payloads_and_endpoints(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as qgc, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as px4:
            qgc.bind(("127.0.0.1", 0))
            px4.bind(("127.0.0.1", 0))
            qgc.settimeout(2)
            px4.settimeout(2)
            # Establish that the host permits UDP loopback before testing the relay.
            px4.sendto(b"loopback-probe", qgc.getsockname())
            try:
                baseline, _ = qgc.recvfrom(4096)
            except TimeoutError:
                self.skipTest("Host blocks direct UDP loopback; rerun this integration test outside the restricted session.")
            self.assertEqual(baseline, b"loopback-probe")
            relay = UdpRelay(qgc.getsockname(), ("127.0.0.1", 0)).start()
            try:
                for index in range(20):
                    payload = bytes([253, index, 0, 255]) + bytes(range(256))
                    px4.sendto(payload, relay.address)
                    received, reply_to = qgc.recvfrom(4096)
                    self.assertEqual(received, payload)
                    response = bytes(reversed(payload))
                    qgc.sendto(response, reply_to)
                    returned, sender = px4.recvfrom(4096)
                    self.assertEqual(returned, response)
                    self.assertEqual(sender, relay.address)
                self.assertEqual(relay.to_qgc, 20)
                self.assertEqual(relay.to_px4, 20)
            finally:
                relay.close()
            self.assertFalse(relay.thread.is_alive())

    def test_workspace_and_network_values_cannot_be_shell_text(self):
        cfg = json.loads((ROOT / "settings.example.json").read_text())
        for field, invalid in (("LinuxDirectory", "../other-project"), ("LinuxDirectory", "x\nother"), ("FlightAxisAddress", "127.0.0.1; command"), ("BridgeRef", "-bad-option"), ("AircraftProfile", "unknown-model")):
            with self.subTest(field=field, invalid=invalid), tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
                changed = {**cfg, field: invalid}
                path = Path(directory) / "settings.json"
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    load_settings(path)

    def test_unusable_navigation_origin_is_rejected(self):
        cfg = json.loads((ROOT / "settings.example.json").read_text())
        cfg["Home"]["Latitude"] = 95
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(cfg))
            with self.assertRaises(ValueError):
                load_settings(path)


if __name__ == "__main__":
    unittest.main()
