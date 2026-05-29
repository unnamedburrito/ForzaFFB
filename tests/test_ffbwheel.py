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
        cfg["output"]["ffbwheel"]["rumble_gain"] = 0.4
        b = make_output(cfg)
        self.assertEqual(b.constant_gain, 2.5)
        self.assertEqual(b.rumble_gain, 0.4)
        self.assertEqual(b.device_name_match, "moza")


class TestCLIOverrides(unittest.TestCase):
    """The live-tuning CLI flags must land on the right config keys."""

    def _cfg(self, argv):
        from forza_ffb.bridge import _build_parser, _apply_overrides
        from forza_ffb.config import load_config
        args = _build_parser().parse_args(argv)
        cfg = load_config(None)
        _apply_overrides(cfg, args)
        return cfg

    def test_rumble_flags(self):
        cfg = self._cfg(["--backend", "ffbwheel", "--rumble-gain", "0.3"])
        self.assertEqual(cfg["output"]["ffbwheel"]["rumble_gain"], 0.3)
        self.assertTrue(cfg["output"]["ffbwheel"]["rumble"])  # still enabled
        cfg = self._cfg(["--backend", "ffbwheel", "--no-rumble"])
        self.assertFalse(cfg["output"]["ffbwheel"]["rumble"])

    def test_force_tuning_flags(self):
        cfg = self._cfg(["--wheel-gain", "1.4", "--lat-g-ref", "24", "--gain", "0.8", "--invert"])
        self.assertEqual(cfg["output"]["ffbwheel"]["constant_gain"], 1.4)
        self.assertEqual(cfg["ffb"]["lateral_g_ref_mps2"], 24.0)
        self.assertEqual(cfg["ffb"]["master_gain"], 0.8)
        self.assertTrue(cfg["ffb"]["invert_steer"])

    def test_no_overrides_leaves_defaults(self):
        cfg = self._cfg(["--backend", "ffbwheel"])
        self.assertEqual(cfg["output"]["ffbwheel"]["rumble_gain"], 1.0)
        self.assertTrue(cfg["output"]["ffbwheel"]["rumble"])


class TestGenericConfigFlags(unittest.TestCase):
    """Every config leaf must be settable via an auto-generated --section-key flag."""

    def _leaf_count(self, d):
        return sum(self._leaf_count(v) if isinstance(v, dict) else 1 for v in d.values())

    def test_every_leaf_has_a_flag(self):
        from forza_ffb.bridge import _CONFIG_SPECS
        from forza_ffb.config import DEFAULTS
        self.assertEqual(len(_CONFIG_SPECS), self._leaf_count(DEFAULTS))

    def _cfg(self, argv):
        from forza_ffb.bridge import _build_parser, _apply_overrides
        from forza_ffb.config import load_config
        args = _build_parser().parse_args(argv)
        cfg = load_config(None)
        _apply_overrides(cfg, args)
        return cfg

    def test_float_nested_bool_and_axismap(self):
        cfg = self._cfg([
            "--ffb-smoothing-alpha", "0.3",
            "--ffb-understeer-drop", "0.4",
            "--output-ffbwheel-disable-autocenter", "false",
            "--output-vjoy-axis-map-steer-force", "RZ",
            "--stale-timeout-s", "1.5",
            "--output-console-every", "5",
        ])
        self.assertEqual(cfg["ffb"]["smoothing_alpha"], 0.3)
        self.assertEqual(cfg["ffb"]["understeer"]["drop"], 0.4)
        self.assertFalse(cfg["output"]["ffbwheel"]["disable_autocenter"])
        self.assertEqual(cfg["output"]["vjoy"]["axis_map"]["steer_force"], "RZ")
        self.assertEqual(cfg["stale_timeout_s"], 1.5)
        self.assertEqual(cfg["output"]["console"]["every"], 5)

    def test_bad_bool_value_rejected(self):
        from forza_ffb.bridge import _build_parser
        with self.assertRaises(SystemExit):  # argparse exits on a bad --...-rumble value
            _build_parser().parse_args(["--output-ffbwheel-rumble", "maybe"])

    def test_short_alias_takes_precedence_over_generic(self):
        # If both forms are given, the friendly short flag wins (applied last).
        cfg = self._cfg(["--gain", "1.0", "--ffb-master-gain", "2.0"])
        self.assertEqual(cfg["ffb"]["master_gain"], 1.0)


if __name__ == "__main__":
    unittest.main()
