"""Real force-feedback output to a physical wheel (MOZA R3 and any DirectInput FFB wheel).

Sends the synthesized steering force to the wheel as an SDL_Haptic **constant-force** effect
(SDL wraps DirectInput on Windows), and optionally a **sine** periodic effect driven by the
road-texture/kerb channels for vibration. Works on any FFB-capable wheel SDL can see.

Requires ``pysdl2`` + the SDL2 runtime. The easiest install bundles the DLL:
``pip install pysdl2 pysdl2-dll``. ``sdl2`` is imported lazily inside :meth:`open`, so this
module imports fine on machines without it (the rest of the bridge stays cross-platform).

IMPORTANT — device ownership: only one app can drive a wheel's FFB at a time. Run Forza with
its own wheel force feedback turned **down/off** (e.g. in MOZA Pit House / in-game FFB = 0) so
this tool and the game don't fight over the motor. See the README.

The SDL_Haptic field names/constants used here are taken verbatim from SDL_haptic.h:
  SDL_HAPTIC_CONSTANT=1<<0, SDL_HAPTIC_SINE=1<<1, SDL_HAPTIC_CARTESIAN=1, SDL_HAPTIC_INFINITY=0xFFFFFFFF
  SDL_HapticConstant{type,direction,length,delay,button,interval,level(Sint16),attack/fade...}
  SDL_HapticDirection{type(Uint8), dir[3](Sint32)}
"""

from __future__ import annotations

import ctypes
import logging
from typing import Any, Dict, List, Optional, Tuple

from ..ffb import Effects
from .base import HAPTIC_MAX, OutputBackend, force_to_level, rumble_magnitude

log = logging.getLogger("forza_ffb.output.ffbwheel")


def list_devices() -> List[Tuple[int, str, bool]]:
    """Return [(index, name, is_haptic)] for all joysticks SDL can see.

    Used by ``--list-devices`` so the user can find their wheel's index/name. Raises
    RuntimeError with install guidance if pysdl2/SDL2 is unavailable.
    """
    sdl2 = _import_sdl2()
    if sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK | sdl2.SDL_INIT_HAPTIC) != 0:
        raise RuntimeError(f"SDL_Init failed: {_err(sdl2)}")
    out: List[Tuple[int, str, bool]] = []
    try:
        for i in range(sdl2.SDL_NumJoysticks()):
            joy = sdl2.SDL_JoystickOpen(i)
            if not joy:
                continue
            name = sdl2.SDL_JoystickName(joy)
            name = name.decode("utf-8", "replace") if name else f"joystick {i}"
            out.append((i, name, bool(sdl2.SDL_JoystickIsHaptic(joy))))
            sdl2.SDL_JoystickClose(joy)
    finally:
        sdl2.SDL_Quit()
    return out


def _import_sdl2():
    try:
        import sdl2  # type: ignore
        return sdl2
    except ImportError as exc:  # pragma: no cover - environment specific
        raise RuntimeError(
            "the FFB-wheel backend needs pysdl2 + the SDL2 runtime. Install with: "
            "`pip install pysdl2 pysdl2-dll` (the -dll package bundles SDL2.dll)."
        ) from exc


def _err(sdl2) -> str:
    e = sdl2.SDL_GetError()
    return e.decode("utf-8", "replace") if e else "unknown error"


class FFBWheelOutput(OutputBackend):
    def __init__(self, cfg: Dict[str, Any]):
        wcfg = cfg.get("output", {}).get("ffbwheel", {})
        self.device_index = int(wcfg.get("device_index", -1))     # -1 = first FFB-capable
        self.device_name_match = str(wcfg.get("device_name_match", "")).lower()
        self.constant_gain = float(wcfg.get("constant_gain", 1.0))
        self.invert = bool(wcfg.get("invert", False))
        self.disable_autocenter = bool(wcfg.get("disable_autocenter", True))
        self.rumble_enabled = bool(wcfg.get("rumble", True))
        self.rumble_gain = float(wcfg.get("rumble_gain", 1.0))  # master multiplier on rumble
        self.rumble_road_gain = float(wcfg.get("rumble_road_gain", 0.6))
        self.rumble_kerb_gain = float(wcfg.get("rumble_kerb_gain", 1.0))
        self.rumble_period_ms = int(wcfg.get("rumble_period_ms", 20))

        self._sdl2 = None
        self._joy = None
        self._haptic = None
        self._const_id: Optional[int] = None
        self._sine_id: Optional[int] = None
        self._const_effect = None
        self._sine_effect = None

    # -- lifecycle --------------------------------------------------------------------
    def open(self) -> "FFBWheelOutput":
        sdl2 = self._sdl2 = _import_sdl2()

        # Let FFB keep updating while Forza is the foreground window.
        sdl2.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        if sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK | sdl2.SDL_INIT_HAPTIC) != 0:
            raise RuntimeError(f"SDL_Init failed: {_err(sdl2)}")

        self._joy = self._open_joystick(sdl2)
        if not sdl2.SDL_JoystickIsHaptic(self._joy):
            raise RuntimeError("selected device has no force-feedback (haptic) support")

        self._haptic = sdl2.SDL_HapticOpenFromJoystick(self._joy)
        if not self._haptic:
            raise RuntimeError(f"SDL_HapticOpenFromJoystick failed: {_err(sdl2)}")

        supported = sdl2.SDL_HapticQuery(self._haptic)
        if not (supported & sdl2.SDL_HAPTIC_CONSTANT):
            raise RuntimeError("device does not support a constant-force effect")

        if self.disable_autocenter:
            # Stop the device fighting our force with its own centering spring. NOTE: on a MOZA
            # the centering is usually a Pit House setting, not the DirectInput autocenter, so
            # also set "Spring" to 0 in MOZA Pit House if a centering force persists.
            try:
                rc = sdl2.SDL_HapticSetAutocenter(self._haptic, 0)
                if rc == 0:
                    log.info("device autocenter disabled")
                else:
                    log.info("autocenter not adjustable via SDL (%s); set 'Spring' to 0 in MOZA Pit House",
                             _err(sdl2))
            except Exception as exc:  # pragma: no cover - older bindings
                log.info("autocenter API unavailable (%s); set 'Spring' to 0 in MOZA Pit House", exc)

        self._create_constant(sdl2)
        if self.rumble_enabled and (supported & sdl2.SDL_HAPTIC_SINE):
            self._create_sine(sdl2)
        elif self.rumble_enabled:
            log.info("device lacks SINE effect; rumble (road/kerb) disabled")
            self.rumble_enabled = False

        log.info("FFB wheel ready (constant force%s)",
                 " + sine rumble" if self.rumble_enabled else "")
        return self

    def _open_joystick(self, sdl2):
        n = sdl2.SDL_NumJoysticks()
        if n <= 0:
            raise RuntimeError("no joysticks/wheels detected by SDL")

        # Explicit index wins.
        if self.device_index >= 0:
            if self.device_index >= n:
                raise RuntimeError(f"device_index {self.device_index} out of range (0..{n-1})")
            joy = sdl2.SDL_JoystickOpen(self.device_index)
            if not joy:
                raise RuntimeError(f"SDL_JoystickOpen({self.device_index}) failed: {_err(sdl2)}")
            return joy

        # Else: name substring match (e.g. "moza"), else first haptic-capable device.
        first_haptic = None
        for i in range(n):
            joy = sdl2.SDL_JoystickOpen(i)
            if not joy:
                continue
            nm = sdl2.SDL_JoystickName(joy)
            nm = nm.decode("utf-8", "replace").lower() if nm else ""
            is_haptic = bool(sdl2.SDL_JoystickIsHaptic(joy))
            if self.device_name_match and self.device_name_match in nm:
                return joy
            if is_haptic and first_haptic is None:
                first_haptic = joy
        if self.device_name_match:
            raise RuntimeError(f"no device whose name contains '{self.device_name_match}'")
        if first_haptic is None:
            raise RuntimeError("no force-feedback-capable device found")
        return first_haptic

    def _new_effect(self, sdl2):
        eff = sdl2.SDL_HapticEffect()
        eff.constant.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
        eff.constant.direction.dir[0] = 1  # force along the wheel's X axis; sign = level sign
        return eff

    def _create_constant(self, sdl2):
        eff = self._new_effect(sdl2)
        eff.type = sdl2.SDL_HAPTIC_CONSTANT
        eff.constant.type = sdl2.SDL_HAPTIC_CONSTANT
        eff.constant.length = sdl2.SDL_HAPTIC_INFINITY
        eff.constant.level = 0
        eid = sdl2.SDL_HapticNewEffect(self._haptic, ctypes.byref(eff))
        if eid < 0:
            raise RuntimeError(f"SDL_HapticNewEffect(constant) failed: {_err(sdl2)}")
        if sdl2.SDL_HapticRunEffect(self._haptic, eid, 1) != 0:
            raise RuntimeError(f"SDL_HapticRunEffect(constant) failed: {_err(sdl2)}")
        self._const_effect, self._const_id = eff, eid

    def _create_sine(self, sdl2):
        eff = sdl2.SDL_HapticEffect()
        eff.type = sdl2.SDL_HAPTIC_SINE
        eff.periodic.type = sdl2.SDL_HAPTIC_SINE
        eff.periodic.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
        eff.periodic.direction.dir[0] = 1
        eff.periodic.period = max(1, min(65535, self.rumble_period_ms))  # fits Uint16
        eff.periodic.magnitude = 0
        eff.periodic.length = sdl2.SDL_HAPTIC_INFINITY
        eid = sdl2.SDL_HapticNewEffect(self._haptic, ctypes.byref(eff))
        if eid < 0:
            log.warning("SDL_HapticNewEffect(sine) failed: %s; disabling rumble", _err(sdl2))
            self.rumble_enabled = False
            return
        sdl2.SDL_HapticRunEffect(self._haptic, eid, 1)
        self._sine_effect, self._sine_id = eff, eid

    # -- per-frame --------------------------------------------------------------------
    def write(self, effects: Effects) -> None:
        sdl2 = self._sdl2
        if sdl2 is None or self._const_id is None:  # pragma: no cover - guard
            return
        force = -effects.steer_force if self.invert else effects.steer_force
        self._const_effect.constant.level = force_to_level(force, self.constant_gain)
        sdl2.SDL_HapticUpdateEffect(self._haptic, self._const_id, ctypes.byref(self._const_effect))

        if self.rumble_enabled and self._sine_id is not None:
            self._sine_effect.periodic.magnitude = rumble_magnitude(
                effects.road_texture, effects.kerb,
                self.rumble_road_gain * self.rumble_gain,
                self.rumble_kerb_gain * self.rumble_gain)
            sdl2.SDL_HapticUpdateEffect(self._haptic, self._sine_id, ctypes.byref(self._sine_effect))

    def close(self) -> None:
        sdl2 = self._sdl2
        if sdl2 is None:
            return
        try:
            if self._haptic:
                # Relax the wheel before releasing it.
                if self._const_id is not None and self._const_effect is not None:
                    self._const_effect.constant.level = 0
                    sdl2.SDL_HapticUpdateEffect(self._haptic, self._const_id, ctypes.byref(self._const_effect))
                try:
                    sdl2.SDL_HapticStopAll(self._haptic)
                except Exception:  # pragma: no cover
                    pass
                for eid in (self._const_id, self._sine_id):
                    if eid is not None:
                        sdl2.SDL_HapticDestroyEffect(self._haptic, eid)
                sdl2.SDL_HapticClose(self._haptic)
            if self._joy:
                sdl2.SDL_JoystickClose(self._joy)
        finally:
            sdl2.SDL_Quit()
            self._haptic = self._joy = self._sdl2 = None
            self._const_id = self._sine_id = None
