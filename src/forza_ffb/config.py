"""Configuration: built-in defaults with a deep merge over an optional user JSON file.

Everything is plain JSON so it's easy to hand-edit while tuning the feel of the FFB.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    # Where Forza sends "Data Out" telemetry. Set these to match the in-game settings.
    "listen": {"ip": "127.0.0.1", "port": 2066},

    "output": {
        # "console"  -> print channels (works anywhere, used for tuning/verification)
        # "vjoy"     -> feed channels to vJoy axes (Windows + vJoy driver)
        # "ffbwheel" -> REAL force feedback to a physical wheel (MOZA R3 etc.) via SDL_Haptic
        "backend": "console",
        # Output rate cap in Hz. 0 = emit once per received packet (Forza's frame rate).
        "rate_hz": 0,
        "console": {"every": 10},  # print 1 of every N updates so the terminal stays readable
        "vjoy": {
            "device_id": 1,
            # Map synthesized effect channels -> vJoy axes. Any channel may be omitted.
            # Signed channels [-1,1] are centred at mid-axis; unsigned [0,1] use the
            # lower half upward. Axis names: X Y Z RX RY RZ SL0 SL1.
            "axis_map": {
                "steer_force": "X",
                "g_long": "Y",
                "road_texture": "Z",
                "kerb": "RX",
                "understeer": "RY",
                "oversteer": "RZ",
            },
        },
        "ffbwheel": {
            # Pick the wheel: -1 = first FFB-capable device; or set device_index, or match
            # by name substring (case-insensitive), e.g. "moza". Use --list-devices to find it.
            "device_index": -1,
            "device_name_match": "moza",
            "constant_gain": 1.0,        # scales steer_force -> motor torque (raise for more)
            "invert": False,             # flip force direction if the wheel pulls the wrong way
            "disable_autocenter": True,  # stop the wheel's own spring fighting our force
            "rumble": True,              # add a sine vibration from road_texture + kerb
            "rumble_road_gain": 0.6,
            "rumble_kerb_gain": 1.0,
            "rumble_period_ms": 20,
        },
    },

    # FFB synthesis tunables. These shape *feel*; defaults are a sane neutral starting point.
    "ffb": {
        "master_gain": 1.0,          # overall strength of steer_force
        "invert_steer": False,       # flip steering force sign to match your wheel/preference
        "steer_deadzone": 0.02,      # suppress tiny center forces (anti-hum)

        # steer_force = master * (w_lat*lateral + w_slip*aligning), gated by speed,
        # then reduced as the front tyres lose grip (understeer lightening).
        "weight_lateral": 0.6,       # contribution of lateral G (cornering load)
        "weight_aligning": 0.4,      # contribution of front slip-angle (self-aligning torque)
        # How much cornering load it takes to reach full force. HIGHER = more progressive /
        # gentler build-up (force isn't pegged in every corner). Raise these if the wheel gets
        # heavy too fast; lower them for a quicker, heavier build.
        "lateral_g_ref_mps2": 18.0,  # accel mapped to full scale (~1.8 g)
        "slip_angle_ref_rad": 0.22,  # front slip angle (~12.6 deg) mapped to full aligning term

        "speed_ref_mps": 6.0,        # below this the wheel goes progressively light (parking)

        "understeer": {"threshold": 1.0, "limit": 1.8, "drop": 0.6},
        "oversteer": {"threshold": 1.0, "limit": 2.0},

        "road_gain": 1.0,            # surface-rumble -> road_texture channel
        "kerb_gain": 6.0,            # suspension-compression spikes -> kerb channel
        "kerb_strip_boost": 0.4,     # added kerb when a wheel is on a rumble strip

        "smoothing_alpha": 0.5,      # EMA per channel: 1.0 = none, lower = smoother/laggier
    },

    # If no packet arrives within this many seconds, output neutral (wheel relaxes).
    "stale_timeout_s": 0.5,
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> Dict[str, Any]:
    """Return DEFAULTS, deep-merged with the JSON at *path* if given."""
    if not path:
        return copy.deepcopy(DEFAULTS)
    with open(path, "r", encoding="utf-8") as fh:
        user = json.load(fh)
    if not isinstance(user, dict):
        raise ValueError(f"config root must be a JSON object, got {type(user).__name__}")
    return _deep_merge(DEFAULTS, user)
