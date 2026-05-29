"""Force-feedback synthesis.

Forza's telemetry carries no FFB signal, so we *derive* one from the physics. The engine
turns each :class:`~forza_ffb.packet.Telemetry` frame into a set of normalised effect
channels that an output backend maps to vJoy axes (or prints):

    steer_force   [-1, 1]  main wheel torque: cornering load + tyre self-aligning torque,
                           speed-gated and reduced as the front tyres lose grip
    g_lat         [-1, 1]  lateral acceleration (cornering G)
    g_long        [-1, 1]  longitudinal acceleration (accel/brake G)
    road_texture  [ 0, 1]  surface roughness / fine vibration from surface rumble
    kerb          [ 0, 1]  sharp suspension impacts + rumble strips
    understeer    [ 0, 1]  how much the front axle is sliding (wheel goes light)
    oversteer     [ 0, 1]  how much the rear axle is sliding (wheelspin / slide)

The model is intentionally simple and *tunable* rather than a full tyre model — every
weight/threshold lives in config so the feel can be dialled in. See README for the rationale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Dict

from .packet import Telemetry

# The channels this engine produces, and whether each is signed ([-1,1]) or unsigned ([0,1]).
SIGNED_CHANNELS = ("steer_force", "g_lat", "g_long")
UNSIGNED_CHANNELS = ("road_texture", "kerb", "understeer", "oversteer")
CHANNELS = SIGNED_CHANNELS + UNSIGNED_CHANNELS


@dataclass
class Effects:
    steer_force: float = 0.0
    g_lat: float = 0.0
    g_long: float = 0.0
    road_texture: float = 0.0
    kerb: float = 0.0
    understeer: float = 0.0
    oversteer: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


def _clamp(x: float, lo: float, hi: float) -> float:
    # Treat NaN/inf as 0 first: Forza can emit non-finite values on resets/glitches, and a
    # NaN must never reach the EMA state (where it would latch permanently) or an output axis.
    if not math.isfinite(x):
        return 0.0
    return lo if x < lo else hi if x > hi else x


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    """Smooth 0->1 ramp between the two edges (Hermite)."""
    if edge1 <= edge0:
        return 0.0 if x < edge0 else 1.0
    t = _clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class FFBEngine:
    """Stateful synthesizer. One instance per session; call :meth:`update` per packet."""

    def __init__(self, ffb_cfg: Dict[str, Any]):
        self.cfg = ffb_cfg
        self._smooth = Effects()          # last smoothed output (for EMA)
        self._prev_susp = None            # previous front suspension travel (for kerb deltas)

    # -- helpers ----------------------------------------------------------------------
    def _g(self, key: str, default: float) -> float:
        return float(self.cfg.get(key, default))

    def reset(self) -> None:
        self._smooth = Effects()
        self._prev_susp = None

    def neutral(self) -> Effects:
        """Relax everything (used when not racing or telemetry is stale)."""
        self.reset()
        return Effects()

    # -- main -------------------------------------------------------------------------
    def update(self, t: Telemetry) -> Effects:
        if not t.is_race_on:
            return self.neutral()

        speed = t.speed_mps
        speed_gate = _smoothstep(0.0, self._g("speed_ref_mps", 6.0), speed)

        target = Effects()

        # --- Lateral / longitudinal G -----------------------------------------------
        g_ref = self._g("lateral_g_ref_mps2", 11.77)
        target.g_lat = _clamp(t.get("AccelerationX") / g_ref, -1.0, 1.0)
        target.g_long = _clamp(t.get("AccelerationZ") / g_ref, -1.0, 1.0)

        # --- Front grip state (drives understeer + lightening) ----------------------
        front_combined = 0.5 * (t.get("TireCombinedSlipFrontLeft") + t.get("TireCombinedSlipFrontRight"))
        us = self.cfg.get("understeer", {})
        us_t, us_l, us_drop = float(us.get("threshold", 1.0)), float(us.get("limit", 1.8)), float(us.get("drop", 0.6))
        target.understeer = _smoothstep(us_t, us_l, front_combined)

        rear_combined = 0.5 * (t.get("TireCombinedSlipRearLeft") + t.get("TireCombinedSlipRearRight"))
        ov = self.cfg.get("oversteer", {})
        target.oversteer = _smoothstep(float(ov.get("threshold", 1.0)), float(ov.get("limit", 2.0)), rear_combined)

        # --- Steering force ----------------------------------------------------------
        # Cornering load (lateral G) + tyre self-aligning torque (front slip angle).
        front_sa = 0.5 * (t.get("TireSlipAngleFrontLeft") + t.get("TireSlipAngleFrontRight"))
        aligning = _clamp(front_sa / self._g("slip_angle_ref_rad", 0.16), -1.0, 1.0)
        lateral = target.g_lat

        w_lat = self._g("weight_lateral", 0.6)
        w_align = self._g("weight_aligning", 0.4)
        raw = w_lat * lateral + w_align * aligning

        # Front tyres past the grip limit -> self-aligning torque collapses (wheel lightens).
        raw *= (1.0 - us_drop * target.understeer)

        force = raw * speed_gate * self._g("master_gain", 1.0)
        if self.cfg.get("invert_steer", False):
            force = -force

        dz = self._g("steer_deadzone", 0.0)
        if abs(force) < dz:
            force = 0.0
        target.steer_force = _clamp(force, -1.0, 1.0)

        # --- Road texture (fine vibration) ------------------------------------------
        surf = 0.5 * (t.get("SurfaceRumbleFrontLeft") + t.get("SurfaceRumbleFrontRight"))
        target.road_texture = _clamp(surf * self._g("road_gain", 1.0) * speed_gate, 0.0, 1.0)

        # --- Kerb / impacts ---------------------------------------------------------
        target.kerb = self._kerb(t, speed_gate)

        return self._apply_smoothing(target)

    def _kerb(self, t: Telemetry, speed_gate: float) -> float:
        fl = t.get("SuspensionTravelMetersFrontLeft")
        fr = t.get("SuspensionTravelMetersFrontRight")
        impact = 0.0
        if self._prev_susp is not None:
            d = max(abs(fl - self._prev_susp[0]), abs(fr - self._prev_susp[1]))
            impact = d * self._g("kerb_gain", 6.0)
        self._prev_susp = (fl, fr)

        on_strip = (t.get("WheelOnRumbleStripFrontLeft") or t.get("WheelOnRumbleStripFrontRight"))
        if on_strip:
            impact += self._g("kerb_strip_boost", 0.4)
        return _clamp(impact * speed_gate, 0.0, 1.0)

    def _apply_smoothing(self, target: Effects) -> Effects:
        alpha = _clamp(self._g("smoothing_alpha", 0.5), 0.0, 1.0)
        prev = self._smooth
        out = Effects()
        for ch in CHANNELS:
            new = getattr(target, ch)
            old = getattr(prev, ch)
            setattr(out, ch, alpha * new + (1.0 - alpha) * old)
        self._smooth = out
        return out
