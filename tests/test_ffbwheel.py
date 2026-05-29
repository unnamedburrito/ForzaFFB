"""FFB-wheel backend: scaling math + lazy-import behavior (no SDL2/hardware needed).

The SDL_Haptic calls themselves can't run without the SDL2 runtime + a real wheel, but the
force->level scaling is pure and is verified here; and we prove the module imports and the
backend constructs WITHOUT importing pysdl2 (so the rest of the bridge stays cross-platform).
"""

import copy
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from forza_ffb.config import DEFAULTS  # noqa: E402
from forza_ffb.outputs import make_output  # noqa: E402
from forza_ffb.outputs.base import (  # noqa: E402
    HAPTIC_MAX, force_to_level, rumble_magnitude,
)


class TestForceToLevel(unittest.TestCase):
    def test_center_and_extremes(self):
        self.assertEqual(force_to_level(0.0), 0)
        self.assertEqual(force_to_level(1.0), HAPTIC_MAX)
        self.assertEqual(force_to_level(-1.0), -HAPTIC_MAX)

    def test_gain_and_clamp(self):
        self.assertLessEqual(abs(force_to_level(0.5, gain=1.0) - HAPTIC_MAX / 2), 1)
        # Over-driven gain is clamped to the device range, never overflows Sint16.
        self.assertEqual(force_to_level(1.0, gain=4.0), HAPTIC_MAX)
        self.assertEqual(force_to_level(-1.0, gain=4.0), -HAPTIC_MAX)

    def test_non_finite_is_zero(self):
        # NaN and inf are both non-finite -> sanitized to 0 (never push garbage to the motor).
        self.assertEqual(force_to_level(float("nan")), 0)
        self.assertEqual(force_to_level(float("inf")), 0)
        self.assertEqual(force_to_level(float("-inf")), 0)


class TestRumbleMagnitude(unittest.TestCase):
    def test_combines_and_clamps(self):
        self.assertEqual(rumble_magnitude(0.0, 0.0, 0.6, 1.0), 0)
        self.assertGreater(rumble_magnitude(0.5, 0.0, 0.6, 1.0), 0)
        # Always within 0..MAX, and unsigned.
        m = rumble_magnitude(1.0, 1.0, 2.0, 2.0)
        self.assertEqual(m, HAPTIC_MAX)
        self.assertGreaterEqual(rumble_magnitude(-5.0, -5.0, 1.0, 1.0), 0)

    def test_nan_ignored(self):
        self.assertEqual(rumble_magnitude(float("nan"), float("nan"), 1.0, 1.0), 0)


class TestLazyImportAndFactory(unittest.TestCase):
    def test_module_imports_without_sdl2(self):
        # Importing the backend module must NOT require pysdl2.
        import forza_ffb.outputs.ffbwheel as fw
        self.assertTrue(hasattr(fw, "FFBWheelOutput"))

    def test_factory_constructs_without_sdl2(self):
        # Construction reads config only; pysdl2 is imported lazily in open() (not called here).
        for name in ("ffbwheel", "moza", "wheel", "sdl"):
            cfg = copy.deepcopy(DEFAULTS)
            cfg["output"]["backend"] = name
            backend = make_output(cfg)
            self.assertEqual(type(backend).__name__, "FFBWheelOutput")
        # config knobs are read through
        cfg = copy.deepcopy(DEFAULTS)
        cfg["output"]["backend"] = "moza"
        cfg["output"]["ffbwheel"]["constant_gain"] = 2.5
        b = make_output(cfg)
        self.assertEqual(b.constant_gain, 2.5)
        self.assertEqual(b.device_name_match, "moza")


if __name__ == "__main__":
    unittest.main()
