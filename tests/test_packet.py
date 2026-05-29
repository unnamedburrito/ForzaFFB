"""Packet parsing: sizes, offsets, round-trip, format autodetect, graceful degradation."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from forza_ffb import packet as p  # noqa: E402


class TestFormats(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(p.SLED.size, 232)
        self.assertEqual(p.FM7_DASH.size, 311)
        self.assertEqual(p.HORIZON.size, 324)
        self.assertEqual(p.FM2023_DASH.size, 331)

    def test_horizon_key_offsets(self):
        # Cross-validated against real FH6 tooling.
        off = p.HORIZON.offsets
        self.assertEqual(off["IsRaceOn"], 0)
        self.assertEqual(off["AccelerationX"], 20)
        self.assertEqual(off["TireSlipAngleFrontLeft"], 164)
        self.assertEqual(off["TireCombinedSlipFrontLeft"], 180)
        self.assertEqual(off["SurfaceRumbleFrontLeft"], 148)
        self.assertEqual(off["SuspensionTravelMetersFrontLeft"], 196)
        self.assertEqual(off["Speed"], 256)
        self.assertEqual(off["Accel"], 315)
        self.assertEqual(off["Brake"], 316)
        self.assertEqual(off["Gear"], 319)
        self.assertEqual(off["Steer"], 320)

    def test_sled_is_prefix_of_all(self):
        # Sled fields must occupy identical offsets in every format.
        for fmt in (p.FM7_DASH, p.HORIZON, p.FM2023_DASH):
            for name, off in p.SLED.offsets.items():
                self.assertEqual(fmt.offsets[name], off, f"{name} moved in {fmt.name}")


class TestRoundTrip(unittest.TestCase):
    def test_horizon_roundtrip(self):
        vals = {
            "IsRaceOn": 1, "Speed": 42.5, "Steer": -100, "Accel": 255, "Brake": 12,
            "Gear": 4, "AccelerationX": 9.81, "AccelerationZ": -3.2,
            "TireSlipAngleFrontLeft": 0.13, "TireSlipAngleFrontRight": 0.11,
            "TireCombinedSlipFrontLeft": 1.5, "SurfaceRumbleFrontLeft": 0.4,
            "SuspensionTravelMetersFrontLeft": 0.05, "WheelOnRumbleStripFrontLeft": 1,
        }
        buf = p.pack(p.HORIZON, vals)
        self.assertEqual(len(buf), 324)
        t = p.parse(buf)
        self.assertEqual(t.format_name, p.HORIZON.name)
        self.assertTrue(t.is_race_on)
        self.assertAlmostEqual(t.speed_mps, 42.5, places=3)
        self.assertEqual(t.get("Gear"), 4)
        self.assertEqual(t.get("Accel"), 255)
        self.assertAlmostEqual(t.get("AccelerationX"), 9.81, places=3)
        self.assertAlmostEqual(t.get("TireSlipAngleFrontLeft"), 0.13, places=5)
        self.assertEqual(t.get("WheelOnRumbleStripFrontLeft"), 1)
        # Steer normalisation: -100/127
        self.assertAlmostEqual(t.steer, -100 / 127, places=4)


class TestAutodetect(unittest.TestCase):
    def test_exact_lengths(self):
        self.assertIs(p.format_for_length(232), p.SLED)
        self.assertIs(p.format_for_length(311), p.FM7_DASH)
        self.assertIs(p.format_for_length(324), p.HORIZON)
        self.assertIs(p.format_for_length(331), p.FM2023_DASH)

    def test_degrade(self):
        # Longer-than-Horizon (future expansion) -> parse as Horizon.
        self.assertIs(p.format_for_length(400), p.HORIZON)
        # Between FM7 and Horizon -> FM7 Car Dash (NOT sled — must keep the dash fields).
        self.assertIs(p.format_for_length(315), p.FM7_DASH)
        self.assertIs(p.format_for_length(323), p.FM7_DASH)
        # Between sled and FM7 -> sled (best effort).
        self.assertIs(p.format_for_length(250), p.SLED)

    def test_too_short(self):
        with self.assertRaises(ValueError):
            p.format_for_length(100)
        with self.assertRaises(ValueError):
            p.parse(b"\x00" * 50)

    def test_pack_out_of_range_names_the_field(self):
        # u8 Accel can't hold 256 — the error must name the offending field, not be a bare
        # struct.error.
        with self.assertRaises(ValueError) as ctx:
            p.pack(p.HORIZON, {"Accel": 256})
        self.assertIn("Accel", str(ctx.exception))

    def test_missing_field_defaults_zero(self):
        # A sled-only packet has no Steer field; accessor must default to 0.
        buf = p.pack(p.SLED, {"IsRaceOn": 1})
        t = p.parse(buf)
        self.assertEqual(t.format_name, p.SLED.name)
        self.assertEqual(t.steer, 0.0)
        self.assertEqual(t.get("Speed"), 0.0)


if __name__ == "__main__":
    unittest.main()
