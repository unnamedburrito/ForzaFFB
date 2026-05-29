"""Output backend interface + shared axis-scaling helpers."""

from __future__ import annotations

import math
from typing import Any, Dict

from ..ffb import Effects, SIGNED_CHANNELS

# vJoy logical axis range.
VJOY_MIN = 1
VJOY_MAX = 0x8000        # 32768
VJOY_CENTER = 0x4000     # 16384


def channel_to_axis(channel: str, value: float) -> int:
    """Scale a normalised effect channel to a vJoy axis integer (1..32768).

    Signed channels ([-1,1]) are centred at 16384; unsigned channels ([0,1]) span the
    full axis from bottom to top.
    """
    if not math.isfinite(value):  # defensive: never feed NaN/inf to a vJoy axis
        value = 0.0
    if channel in SIGNED_CHANNELS:
        v = max(-1.0, min(1.0, value))
        raw = VJOY_CENTER + v * (VJOY_CENTER - 1)
    else:
        v = max(0.0, min(1.0, value))
        raw = VJOY_MIN + v * (VJOY_MAX - VJOY_MIN)
    return int(round(max(VJOY_MIN, min(VJOY_MAX, raw))))


# SDL_Haptic effect level range (Sint16). Used by the FFB-wheel backend.
HAPTIC_MAX = 0x7FFF  # 32767


def force_to_level(value: float, gain: float = 1.0, max_level: int = HAPTIC_MAX) -> int:
    """Scale a signed force ([-1,1]) to a signed SDL_Haptic constant-force level.

    The result is clamped to +/-``max_level`` so an over-driven gain can never exceed the
    device range, and NaN/inf collapses to 0 (never push a garbage torque to a real wheel).
    """
    if not math.isfinite(value):
        value = 0.0
    lvl = int(round(value * gain * max_level))
    return max(-max_level, min(max_level, lvl))


def rumble_magnitude(road: float, kerb: float, road_gain: float, kerb_gain: float,
                     max_level: int = HAPTIC_MAX) -> int:
    """Combine the unsigned road-texture and kerb channels into a periodic-effect magnitude
    (0..``max_level``)."""
    m = 0.0
    for v, g in ((road, road_gain), (kerb, kerb_gain)):
        if math.isfinite(v):
            m += max(0.0, v) * g
    return max(0, min(max_level, int(round(m * max_level))))


class OutputBackend:
    """Base class. Subclasses implement open/write/close."""

    def open(self) -> "OutputBackend":
        return self

    def write(self, effects: Effects) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> "OutputBackend":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()
