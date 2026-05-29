"""Output backends + factory."""

from __future__ import annotations

from typing import Any, Dict

from .base import OutputBackend, channel_to_axis, force_to_level, rumble_magnitude
from .console import ConsoleOutput

# Aliases the user may type for the physical-FFB-wheel backend.
_FFBWHEEL_NAMES = ("ffbwheel", "wheel", "moza", "sdl")


def make_output(cfg: Dict[str, Any]) -> OutputBackend:
    """Construct the backend named by ``cfg['output']['backend']``."""
    name = str(cfg.get("output", {}).get("backend", "console")).lower()
    if name == "console":
        return ConsoleOutput(cfg)
    if name == "vjoy":
        from .vjoy import VJoyOutput  # lazy: avoids importing pyvjoy unless requested
        return VJoyOutput(cfg)
    if name in _FFBWHEEL_NAMES:
        from .ffbwheel import FFBWheelOutput  # lazy: avoids importing pysdl2 unless requested
        return FFBWheelOutput(cfg)
    if name in ("null", "none"):
        return OutputBackend()
    raise ValueError(
        f"unknown output backend '{name}' (use: console, vjoy, ffbwheel, null)")


__all__ = [
    "OutputBackend", "ConsoleOutput", "make_output",
    "channel_to_axis", "force_to_level", "rumble_magnitude",
]
