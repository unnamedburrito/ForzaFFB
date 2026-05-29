"""FFB synthesis: gating, sign, clamping, understeer lightening, smoothing, deadzone."""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from forza_ffb.config import DEFAULTS  # noqa: E402
from forza_ffb.ffb import FFBEngine  # noqa: E402
from forza_ffb.packet import Telemetry  # noqa: E402


def cfg(**overrides):
    c = copy.deepcopy(DEFAULTS["ffb"])
    c["smoothing_alpha"] = 1.0  # no smoothing by default in tests -> instantaneous mapping
    c.update(overrides)
    return c


def tel(**raw):
    raw.setdefault("IsRaceOn", 1)
    return Telemetry(format_name="test", raw=raw)


# A steady right-hand corner at speed, front tyres still gripping.
CORNER = dict(IsRaceOn=1, Speed=30.0, AccelerationX=9.0,
              TireSlipAngleFrontLeft=0.10, TireSlipAngleFrontRight=0.10)


class TestGatingAndNeutral(unittest.TestCase):
    def test_not_racing_is_neutral(self):
        e = FFBEngine(cfg()).update(tel(IsRaceOn=0, AccelerationX=9.0, Speed=30))
        for v in e.as_dict().values():
            self.assertEqual(v, 0.0)

    def test_standstill_has_no_steer_force(self):
        eng = FFBEngine(cfg())
        e = eng.update(tel(**{**CORNER, "Speed": 0.0}))
        self.assertAlmostEqual(e.steer_force, 0.0, places=6)


class TestSteerForce(unittest.TestCase):
    def test_corner_produces_force(self):
        e = FFBEngine(cfg()).update(tel(**CORNER))
        self.assertGreater(abs(e.steer_force), 0.1)
        self.assertLessEqual(abs(e.steer_force), 1.0)

    def test_invert_flips_sign(self):
        base = FFBEngine(cfg()).update(tel(**CORNER)).steer_force
        inv = FFBEngine(cfg(invert_steer=True)).update(tel(**CORNER)).steer_force
        self.assertAlmostEqual(base, -inv, places=6)

    def test_clamped_to_unit(self):
        e = FFBEngine(cfg(master_gain=10.0)).update(
            tel(IsRaceOn=1, Speed=60, AccelerationX=50.0,
                TireSlipAngleFrontLeft=1.0, TireSlipAngleFrontRight=1.0))
        self.assertLessEqual(abs(e.steer_force), 1.0)

    def test_deadzone_suppresses_tiny_force(self):
        e = FFBEngine(cfg(master_gain=0.02, steer_deadzone=0.05)).update(tel(**CORNER))
        self.assertEqual(e.steer_force, 0.0)


class TestUndersteerLightening(unittest.TestCase):
    def test_understeer_reduces_force_and_reports(self):
        gripping = FFBEngine(cfg()).update(tel(**CORNER))
        sliding = FFBEngine(cfg()).update(tel(
            **{**CORNER,
               "TireCombinedSlipFrontLeft": 1.8, "TireCombinedSlipFrontRight": 1.8}))
        self.assertGreater(sliding.understeer, 0.9)              # reported as understeer
        self.assertLess(abs(sliding.steer_force), abs(gripping.steer_force))  # lightens


class TestAuxChannels(unittest.TestCase):
    def test_g_lat_sign_and_clamp(self):
        c = cfg()
        right = FFBEngine(c).update(tel(IsRaceOn=1, Speed=30, AccelerationX=9.0))
        left = FFBEngine(c).update(tel(IsRaceOn=1, Speed=30, AccelerationX=-9.0))
        self.assertGreater(right.g_lat, 0)
        self.assertLess(left.g_lat, 0)
        big = FFBEngine(c).update(tel(IsRaceOn=1, Speed=30, AccelerationX=999.0))
        self.assertLessEqual(big.g_lat, 1.0)

    def test_road_texture_tracks_surface_rumble(self):
        c = cfg()
        quiet = FFBEngine(c).update(tel(IsRaceOn=1, Speed=30, SurfaceRumbleFrontLeft=0.0,
                                        SurfaceRumbleFrontRight=0.0))
        rough = FFBEngine(c).update(tel(IsRaceOn=1, Speed=30, SurfaceRumbleFrontLeft=0.6,
                                        SurfaceRumbleFrontRight=0.6))
        self.assertAlmostEqual(quiet.road_texture, 0.0, places=6)
        self.assertGreater(rough.road_texture, 0.3)
        self.assertLessEqual(rough.road_texture, 1.0)

    def test_kerb_fires_on_suspension_delta(self):
        eng = FFBEngine(cfg())
        eng.update(tel(IsRaceOn=1, Speed=30, SuspensionTravelMetersFrontLeft=0.0))
        hit = eng.update(tel(IsRaceOn=1, Speed=30, SuspensionTravelMetersFrontLeft=0.06))
        self.assertGreater(hit.kerb, 0.0)
        self.assertLessEqual(hit.kerb, 1.0)


class TestRobustness(unittest.TestCase):
    def test_nan_input_does_not_latch_or_crash(self):
        import math
        eng = FFBEngine(cfg(smoothing_alpha=0.5))
        eng.update(tel(**CORNER))                                   # seed smoothing state
        bad = eng.update(tel(IsRaceOn=1, Speed=30.0, AccelerationX=float("nan"),
                             TireSlipAngleFrontLeft=float("inf")))
        for v in bad.as_dict().values():
            self.assertTrue(math.isfinite(v), "NaN/inf leaked into a channel")
        # A subsequent clean frame must recover (NaN did not latch in the EMA state).
        good = eng.update(tel(**CORNER))
        self.assertTrue(all(math.isfinite(v) for v in good.as_dict().values()))
        self.assertGreater(abs(good.steer_force), 0.0)


class TestSmoothing(unittest.TestCase):
    def test_ema_converges_toward_target(self):
        eng = FFBEngine(cfg(smoothing_alpha=0.5))
        vals = [eng.update(tel(**CORNER)).steer_force for _ in range(6)]
        # Monotonic approach to the steady target; each step closer than the last.
        diffs = [abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)]
        for i in range(len(diffs) - 1):
            self.assertLessEqual(diffs[i + 1], diffs[i] + 1e-9)
        self.assertGreater(vals[-1], vals[0])  # rising toward target


if __name__ == "__main__":
    unittest.main()
