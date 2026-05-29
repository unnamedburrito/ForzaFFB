"""Forza "Data Out" UDP telemetry packet parsing.

Forza Horizon 6 (like FH4/FH5) emits the **Horizon "Car Dash"** wire format: a fixed
**324-byte, little-endian** packet, once per rendered frame, only while actively driving.

There is no "force feedback" field anywhere in this stream — it carries vehicle *physics*
(slip angles, lateral G, surface rumble, suspension travel, ...). The FFB signal is
synthesised from those values elsewhere (see :mod:`forza_ffb.ffb`).

The layout below is expressed as a single ordered table of ``(type, name)`` pairs per
format.  Byte offsets are *computed* from that table (never hand-typed), and the resulting
packet sizes are asserted at import time, so the offsets cannot silently drift:

    Sled            232 bytes   (motion-sled subset, all Forza titles)
    FM7 Car Dash    311 bytes   (Forza Motorsport 7)
    Horizon         324 bytes   (Forza Horizon 4 / 5 / 6)   <-- our primary target
    FM 2023 Dash    331 bytes   (Forza Motorsport 2023)

Cross-validation: the offsets computed here put Accel@315, Brake@316, Gear@319, Steer@320,
Speed@256 in the Horizon format — exactly matching the offsets reported by independent
real-world FH6 tools.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# --- Type system ---------------------------------------------------------------------
# Map our type tokens to (struct char, size in bytes).
_TYPES: Dict[str, Tuple[str, int]] = {
    "s32": ("i", 4),
    "u32": ("I", 4),
    "f32": ("f", 4),
    "u16": ("H", 2),
    "u8": ("B", 1),
    "s8": ("b", 1),
}

Field = Tuple[str, str]  # (type_token, name)

# --- Field tables (single source of truth) -------------------------------------------
# The "Sled" subset — identical across every Forza title, always at the front.
_SLED: List[Field] = [
    ("s32", "IsRaceOn"),
    ("u32", "TimestampMS"),
    ("f32", "EngineMaxRpm"),
    ("f32", "EngineIdleRpm"),
    ("f32", "CurrentEngineRpm"),
    ("f32", "AccelerationX"),  # right (+) / left (-), m/s^2  -> lateral G source
    ("f32", "AccelerationY"),  # up
    ("f32", "AccelerationZ"),  # forward (+) / back (-)
    ("f32", "VelocityX"),
    ("f32", "VelocityY"),
    ("f32", "VelocityZ"),
    ("f32", "AngularVelocityX"),  # pitch rate
    ("f32", "AngularVelocityY"),  # yaw rate
    ("f32", "AngularVelocityZ"),  # roll rate
    ("f32", "Yaw"),
    ("f32", "Pitch"),
    ("f32", "Roll"),
    ("f32", "NormalizedSuspensionTravelFrontLeft"),
    ("f32", "NormalizedSuspensionTravelFrontRight"),
    ("f32", "NormalizedSuspensionTravelRearLeft"),
    ("f32", "NormalizedSuspensionTravelRearRight"),
    ("f32", "TireSlipRatioFrontLeft"),
    ("f32", "TireSlipRatioFrontRight"),
    ("f32", "TireSlipRatioRearLeft"),
    ("f32", "TireSlipRatioRearRight"),
    ("f32", "WheelRotationSpeedFrontLeft"),
    ("f32", "WheelRotationSpeedFrontRight"),
    ("f32", "WheelRotationSpeedRearLeft"),
    ("f32", "WheelRotationSpeedRearRight"),
    ("s32", "WheelOnRumbleStripFrontLeft"),
    ("s32", "WheelOnRumbleStripFrontRight"),
    ("s32", "WheelOnRumbleStripRearLeft"),
    ("s32", "WheelOnRumbleStripRearRight"),
    ("f32", "WheelInPuddleDepthFrontLeft"),
    ("f32", "WheelInPuddleDepthFrontRight"),
    ("f32", "WheelInPuddleDepthRearLeft"),
    ("f32", "WheelInPuddleDepthRearRight"),
    ("f32", "SurfaceRumbleFrontLeft"),
    ("f32", "SurfaceRumbleFrontRight"),
    ("f32", "SurfaceRumbleRearLeft"),
    ("f32", "SurfaceRumbleRearRight"),
    ("f32", "TireSlipAngleFrontLeft"),
    ("f32", "TireSlipAngleFrontRight"),
    ("f32", "TireSlipAngleRearLeft"),
    ("f32", "TireSlipAngleRearRight"),
    ("f32", "TireCombinedSlipFrontLeft"),
    ("f32", "TireCombinedSlipFrontRight"),
    ("f32", "TireCombinedSlipRearLeft"),
    ("f32", "TireCombinedSlipRearRight"),
    ("f32", "SuspensionTravelMetersFrontLeft"),
    ("f32", "SuspensionTravelMetersFrontRight"),
    ("f32", "SuspensionTravelMetersRearLeft"),
    ("f32", "SuspensionTravelMetersRearRight"),
    ("s32", "CarOrdinal"),
    ("s32", "CarClass"),
    ("s32", "CarPerformanceIndex"),
    ("s32", "DrivetrainType"),
    ("s32", "NumCylinders"),
]

# The Horizon (FH4/FH5/FH6) titles insert a 12-byte block here before the dash data.
_HORIZON_MID: List[Field] = [
    ("s32", "CarCategory"),
    ("u32", "HorizonUnknown1"),
    ("u32", "HorizonUnknown2"),
]

# Shared "dash" block (position, speed, lap, and — importantly — driver inputs).
_DASH: List[Field] = [
    ("f32", "PositionX"),
    ("f32", "PositionY"),
    ("f32", "PositionZ"),
    ("f32", "Speed"),  # m/s
    ("f32", "Power"),
    ("f32", "Torque"),
    ("f32", "TireTempFrontLeft"),
    ("f32", "TireTempFrontRight"),
    ("f32", "TireTempRearLeft"),
    ("f32", "TireTempRearRight"),
    ("f32", "Boost"),
    ("f32", "Fuel"),
    ("f32", "DistanceTraveled"),
    ("f32", "BestLap"),
    ("f32", "LastLap"),
    ("f32", "CurrentLap"),
    ("f32", "CurrentRaceTime"),
    ("u16", "LapNumber"),
    ("u8", "RacePosition"),
    ("u8", "Accel"),       # 0..255
    ("u8", "Brake"),       # 0..255
    ("u8", "Clutch"),      # 0..255
    ("u8", "HandBrake"),   # 0..255
    ("u8", "Gear"),
    ("s8", "Steer"),       # signed byte (type range -128..127); Forza observed range -127..127
    ("s8", "NormalizedDrivingLine"),
    ("s8", "NormalizedAIBrakeDifference"),
]

_HORIZON_TRAIL: List[Field] = [("u8", "HorizonExpansion")]

# FM 2023 appends tire wear + track ordinal instead of the Horizon block/trailer.
_FM2023_TAIL: List[Field] = [
    ("f32", "TireWearFrontLeft"),
    ("f32", "TireWearFrontRight"),
    ("f32", "TireWearRearLeft"),
    ("f32", "TireWearRearRight"),
    ("s32", "TrackOrdinal"),
]


@dataclass(frozen=True)
class _Format:
    name: str
    fields: List[Field]
    fmt: str = field(init=False)          # struct format string ("<iIff...")
    size: int = field(init=False)         # total bytes
    names: Tuple[str, ...] = field(init=False)
    offsets: Dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        fmt = "<"
        offsets: Dict[str, int] = {}
        off = 0
        for tok, name in self.fields:
            char, sz = _TYPES[tok]
            fmt += char
            offsets[name] = off
            off += sz
        # frozen dataclass: assign computed attrs via object.__setattr__
        object.__setattr__(self, "fmt", fmt)
        object.__setattr__(self, "size", off)
        object.__setattr__(self, "names", tuple(n for _, n in self.fields))
        object.__setattr__(self, "offsets", offsets)
        object.__setattr__(self, "_struct", struct.Struct(fmt))

    def unpack(self, buf: bytes) -> Dict[str, float]:
        # Tolerate trailing bytes (forward-compat with future title expansions).
        values = self._struct.unpack_from(buf, 0)
        return dict(zip(self.names, values))


# Concrete formats.
SLED = _Format("Sled", _SLED)
FM7_DASH = _Format("FM7 Car Dash", _SLED + _DASH)
HORIZON = _Format("Horizon (FH4/FH5/FH6)", _SLED + _HORIZON_MID + _DASH + _HORIZON_TRAIL)
FM2023_DASH = _Format("FM 2023 Car Dash", _SLED + _DASH + _FM2023_TAIL)

# Self-validation: the computed sizes MUST match the documented wire sizes. If a field
# table is edited incorrectly this fails loudly at import instead of producing silent
# offset corruption downstream.
assert SLED.size == 232, f"Sled size {SLED.size} != 232"
assert FM7_DASH.size == 311, f"FM7 size {FM7_DASH.size} != 311"
assert HORIZON.size == 324, f"Horizon size {HORIZON.size} != 324"
assert FM2023_DASH.size == 331, f"FM2023 size {FM2023_DASH.size} != 331"
# Spot-check the Horizon offsets we cross-validated against real FH6 tools.
assert HORIZON.offsets["Speed"] == 256
assert HORIZON.offsets["Accel"] == 315
assert HORIZON.offsets["Brake"] == 316
assert HORIZON.offsets["Gear"] == 319
assert HORIZON.offsets["Steer"] == 320

# Length -> format for exact matches.
_BY_SIZE: Dict[int, _Format] = {
    SLED.size: SLED,
    FM7_DASH.size: FM7_DASH,
    HORIZON.size: HORIZON,
    FM2023_DASH.size: FM2023_DASH,
}


def format_for_length(n: int) -> _Format:
    """Pick the packet format for a payload of *n* bytes.

    Exact matches win. Otherwise we degrade to the largest format that still fits entirely
    within *n* bytes, so we never claim more fields than the payload can supply: Horizon
    (>=324) -> FM7 Car Dash (>=311) -> Sled (>=232). Below sled size is an error. (Trailing
    bytes beyond the chosen format are tolerated by ``unpack_from``.)
    """
    fmt = _BY_SIZE.get(n)
    if fmt is not None:
        return fmt
    if n >= HORIZON.size:
        return HORIZON
    if n >= FM7_DASH.size:
        return FM7_DASH
    if n >= SLED.size:
        return SLED
    raise ValueError(f"packet too short to be Forza telemetry: {n} bytes")


@dataclass
class Telemetry:
    """A parsed packet: raw field dict plus convenient typed accessors.

    Field access falls back to ``0`` for fields absent in the detected format (e.g. Steer
    in a Sled-only packet), so the FFB engine can read uniformly without guarding.
    """

    format_name: str
    raw: Dict[str, float]

    def __getattr__(self, name: str) -> float:
        # Only reached for attributes not found normally (raw/format_name are real attrs).
        try:
            return self.raw[name]
        except KeyError:
            return 0.0

    # --- Frequently used, with correct semantics --------------------------------------
    @property
    def is_race_on(self) -> bool:
        return bool(self.raw.get("IsRaceOn", 0))

    @property
    def speed_mps(self) -> float:
        return float(self.raw.get("Speed", 0.0))

    @property
    def steer(self) -> float:
        """Player steering input normalised to [-1, 1] (raw is -127..127)."""
        return _clamp(float(self.raw.get("Steer", 0.0)) / 127.0, -1.0, 1.0)

    def get(self, name: str, default: float = 0.0) -> float:
        return float(self.raw.get(name, default))


def parse(buf: bytes) -> Telemetry:
    """Parse a UDP payload into :class:`Telemetry`. Raises ``ValueError`` if too short."""
    fmt = format_for_length(len(buf))
    return Telemetry(format_name=fmt.name, raw=fmt.unpack(buf))


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def pack(format_obj: _Format, values: Dict[str, float]) -> bytes:
    """Build a wire packet from a name->value mapping (missing fields default to 0).

    Used by the synthetic packet generator and the test-suite for exact round-trips.
    """
    ordered = []
    for tok, name in format_obj.fields:
        v = values.get(name, 0)
        ordered.append(float(v) if tok == "f32" else int(v))
    try:
        return format_obj._struct.pack(*ordered)
    except struct.error as exc:
        # Identify the offending field so the caller gets an actionable message instead of
        # a bare "B format requires 0 <= number <= 255".
        for (tok, name), val in zip(format_obj.fields, ordered):
            try:
                struct.pack("<" + _TYPES[tok][0], val)
            except struct.error:
                raise ValueError(
                    f"value {val!r} out of range for field '{name}' ({tok})"
                ) from exc
        raise  # pragma: no cover - re-raise if the culprit couldn't be isolated
