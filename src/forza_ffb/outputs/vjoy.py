"""vJoy output backend — feeds synthesized channels to a vJoy virtual joystick's axes.

Requires Windows + the vJoy driver + the ``pyvjoy`` package. ``pyvjoy`` (and the vJoy DLL)
are imported lazily inside :meth:`open`, so importing this module never fails on a machine
without vJoy — the rest of the bridge (and the test-suite) stays cross-platform.

Note on intent: a vJoy axis is a virtual *input*. Writing a "force" to an axis does not by
itself move a wheel's motor — something downstream must consume the axis (Joystick Gremlin
mapping, SimHub, DIY-wheel firmware, a bass-shaker driver, etc.). For driving a real FFB
wheel's motor directly, see the DirectInput note in the README.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..ffb import CHANNELS, Effects
from .base import OutputBackend, channel_to_axis

log = logging.getLogger("forza_ffb.output.vjoy")


class VJoyOutput(OutputBackend):
    def __init__(self, cfg: Dict[str, Any]):
        vcfg = cfg.get("output", {}).get("vjoy", {})
        self.device_id = int(vcfg.get("device_id", 1))
        self.axis_map: Dict[str, str] = dict(vcfg.get("axis_map", {}))
        self._dev = None
        self._usage: Dict[str, int] = {}
        self._warned_axes = set()

    def open(self) -> "VJoyOutput":
        try:
            import pyvjoy  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment specific
            raise RuntimeError(
                "vJoy backend needs the 'pyvjoy' package and the vJoy driver. "
                "Install vJoy (https://github.com/jshafer817/vJoy or sourceforge) and "
                "`pip install pyvjoy`, or use the 'console' backend."
            ) from exc

        # Resolve axis-name strings -> pyvjoy HID_USAGE_* constants, validating the map.
        for channel, axis in self.axis_map.items():
            if channel not in CHANNELS:
                raise ValueError(f"axis_map references unknown channel '{channel}'")
            const_name = f"HID_USAGE_{str(axis).upper()}"
            usage = getattr(pyvjoy, const_name, None)
            if usage is None:
                raise ValueError(f"unknown vJoy axis '{axis}' (use X Y Z RX RY RZ SL0 SL1)")
            self._usage[channel] = usage

        try:
            self._dev = pyvjoy.VJoyDevice(self.device_id)
        except Exception as exc:  # pragma: no cover - environment specific
            raise RuntimeError(
                f"could not acquire vJoy device #{self.device_id}. Is it enabled in "
                f"'Configure vJoy', and not owned by another app? ({exc})"
            ) from exc

        log.info("vJoy device #%d ready; axis map: %s", self.device_id, self.axis_map)
        return self

    def write(self, effects: Effects) -> None:
        if self._dev is None:  # pragma: no cover - guard
            return
        d = effects.as_dict()
        for channel, usage in self._usage.items():
            try:
                self._dev.set_axis(usage, channel_to_axis(channel, d[channel]))
            except Exception as exc:  # pragma: no cover - environment specific
                if channel not in self._warned_axes:
                    self._warned_axes.add(channel)
                    log.warning(
                        "failed to set axis for '%s' — is that axis enabled in vJoy config? (%s)",
                        channel, exc,
                    )

    def close(self) -> None:
        # Re-centre on exit so a consumer doesn't latch the last force value.
        if self._dev is not None:
            try:
                self.write(Effects())
            except Exception:  # pragma: no cover
                pass
            self._dev = None
