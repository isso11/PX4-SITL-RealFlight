from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "linux"))
from check_vjoy import axis_result, parse_rc


class VjoyTests(unittest.TestCase):
    def sample(self):
        return ("timestamp: 1000000 (0.010 seconds ago)\nchannel_count: 4\n"
                "values: [1000, 1500, 2000, 1500, 65535]\nrc_lost: False\nrc_failsafe: False\n")

    def test_valid_input_uses_reported_count(self):
        self.assertEqual(parse_rc(self.sample())["values"], [1000, 1500, 2000, 1500])

    def test_stale_lost_missing_and_invalid_input_rejected(self):
        for invalid in (self.sample().replace("0.010", "2.000"),
                        self.sample().replace("rc_lost: False", "rc_lost: True"),
                        self.sample().replace("rc_failsafe: False", ""),
                        self.sample().replace("1000,", "65535,"),
                        self.sample().replace("channel_count: 4", "channel_count: 18")):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                parse_rc(invalid)

    def series(self):
        return [{"timestamp": i + 1, "values": [1000 + i * 100, 1500, 1000, 1500]} for i in range(10)]

    def test_distinct_axis_identified(self):
        self.assertEqual(axis_result(self.series())["channel"], 1)

    def test_static_frozen_and_coupled_channels_rejected(self):
        frozen = self.series()
        for sample in frozen:
            sample["timestamp"] = 1
        coupled = self.series()
        for sample in coupled:
            sample["values"][1] = sample["values"][0]
        static = [{"timestamp": i, "values": [1500] * 4} for i in range(10)]
        for samples in (frozen, coupled, static, self.series()[:3]):
            with self.subTest(samples=samples), self.assertRaises(RuntimeError):
                axis_result(samples)


if __name__ == "__main__":
    unittest.main()
