"""The bridge: listen -> parse -> synthesize FFB -> output. Plus the CLI entry point."""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any, Dict, Optional

from .config import DEFAULTS, load_config
from .ffb import FFBEngine
from .outputs import make_output
from .telemetry import TelemetryListener

log = logging.getLogger("forza_ffb.bridge")


# --- Auto-generated "set any config key" flags ------------------------------------------
# Every leaf in DEFAULTS gets a `--section-key` flag, typed from its default value, so the
# whole config is overridable from the command line. Generated from DEFAULTS so it can never
# drift: new config options get a flag automatically.

def _parse_bool(s: str) -> bool:
    sl = str(s).strip().lower()
    if sl in ("true", "1", "yes", "on"):
        return True
    if sl in ("false", "0", "no", "off"):
        return False
    raise argparse.ArgumentTypeError(f"expected true/false, got {s!r}")


def _config_flag_specs(defaults: Dict[str, Any]):
    """Yield (flag, dest, path, kind, default) for every leaf in *defaults*."""
    specs = []

    def walk(d: Dict[str, Any], path: tuple) -> None:
        for k, v in d.items():
            p = path + (k,)
            if isinstance(v, dict):
                walk(v, p)
            else:
                flag = "--" + "-".join(p).replace("_", "-")
                dest = "set__" + "__".join(p)
                if isinstance(v, bool):       # bool before int (bool is a subclass of int)
                    kind = "bool"
                elif isinstance(v, int):
                    kind = "int"
                elif isinstance(v, float):
                    kind = "float"
                else:
                    kind = "str"
                specs.append((flag, dest, p, kind, v))

    walk(defaults, ())
    return specs


# Computed once; used both to build the parser and to apply the overrides.
_CONFIG_SPECS = _config_flag_specs(DEFAULTS)
_TYPES = {"int": int, "float": float, "str": str}


def run_bridge(cfg: Dict[str, Any], stop: "Optional[StopFlag]" = None) -> None:
    """Run the bridge loop until *stop* is set (or KeyboardInterrupt)."""
    listen = cfg["listen"]
    stale_timeout = float(cfg.get("stale_timeout_s", 0.5))
    recv_timeout = max(0.05, min(0.25, stale_timeout / 2.0))

    rate_hz = float(cfg.get("output", {}).get("rate_hz", 0) or 0)
    min_interval = (1.0 / rate_hz) if rate_hz > 0 else 0.0

    engine = FFBEngine(cfg["ffb"])
    listener = TelemetryListener(listen["ip"], int(listen["port"]), recv_timeout=recv_timeout)
    output = make_output(cfg)

    last_rx = time.monotonic()
    last_emit = 0.0
    relaxed = False

    with listener, output:
        log.info("bridge running — backend=%s. Ctrl+C to stop.",
                 cfg.get("output", {}).get("backend"))
        while stop is None or not stop.is_set():
            frame = listener.recv()
            now = time.monotonic()

            if frame is not None:
                effects = engine.update(frame)
                relaxed = False
                last_rx = now
                if now - last_emit >= min_interval:
                    output.write(effects)
                    last_emit = now
            elif not relaxed and (now - last_rx) > stale_timeout:
                # No telemetry for a while (menu/pause/game closed): relax to neutral once.
                output.write(engine.neutral())
                relaxed = True
                log.debug("telemetry stale (%.2fs) — output relaxed to neutral", now - last_rx)


class StopFlag:
    """Minimal cooperative stop signal (threading.Event-compatible subset)."""

    def __init__(self) -> None:
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        return self._set


# --- CLI --------------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forza_ffb",
        description="Bridge Forza Horizon 6 Data Out telemetry into synthesized FFB "
                    "channels for vJoy / Joystick Gremlin (or the console).",
    )
    p.add_argument("--config", help="path to a JSON config file (merged over defaults)")
    p.add_argument("--ip", help="listen IP (overrides config)")
    p.add_argument("--port", type=int, help="listen UDP port (overrides config; Forza default here is 2066)")
    p.add_argument("--backend", choices=["console", "vjoy", "ffbwheel", "wheel", "moza", "sdl", "null"],
                   help="output backend (ffbwheel/wheel/moza/sdl all select the SDL FFB-wheel backend)")
    p.add_argument("--device-id", type=int, help="vJoy device id (vjoy backend)")
    p.add_argument("--device-index", type=int, help="wheel device index (ffbwheel backend; see --list-devices)")
    p.add_argument("--device-name", help="wheel name substring to match, e.g. moza (ffbwheel backend)")
    p.add_argument("--gain", type=float, help="FFB master_gain override (overall force strength)")
    p.add_argument("--wheel-gain", type=float,
                   help="ffbwheel constant_gain: peak force the wheel can reach (raise if too light)")
    p.add_argument("--lat-g-ref", type=float,
                   help="lateral_g_ref_mps2: RAISE to soften how fast force builds with cornering/speed")
    p.add_argument("--rumble-gain", type=float,
                   help="ffbwheel rumble_gain: master vibration multiplier (LOWER for less off-road buzz; 0 = none)")
    p.add_argument("--no-rumble", action="store_true",
                   help="disable the ffbwheel sine vibration entirely (steering force only)")
    p.add_argument("--invert", action="store_true", help="invert steering force sign")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    p.add_argument("--show-format", action="store_true",
                   help="print the parsed Forza packet formats & key offsets, then exit")
    p.add_argument("--list-devices", action="store_true",
                   help="list FFB-capable wheels/joysticks SDL can see, then exit")

    # Generic overrides for EVERY config key (e.g. --ffb-smoothing-alpha 0.3,
    # --output-ffbwheel-disable-autocenter false, --ffb-understeer-drop 0.4).
    group = p.add_argument_group(
        "config overrides (one per config key)",
        "Set any config value directly; booleans take true/false. The short flags above are "
        "convenient aliases for the most-used keys and take precedence if both are given.")
    for flag, dest, path, kind, default in _CONFIG_SPECS:
        dotted = ".".join(path)
        if kind == "bool":
            group.add_argument(flag, dest=dest, type=_parse_bool, default=None, metavar="BOOL",
                               help=f"{dotted} (default: {str(default).lower()})")
        else:
            group.add_argument(flag, dest=dest, type=_TYPES[kind], default=None,
                               metavar=kind.upper(), help=f"{dotted} (default: {default})")
    return p


def _apply_overrides(cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    # 1) Generic per-key overrides (any --section-key flag the user passed).
    for _flag, dest, path, _kind, _default in _CONFIG_SPECS:
        val = getattr(args, dest, None)
        if val is None:
            continue
        d = cfg
        for k in path[:-1]:
            d = d.setdefault(k, {})
        d[path[-1]] = val

    # 2) Short friendly aliases (take precedence over the generic forms above).
    if args.ip:
        cfg["listen"]["ip"] = args.ip
    if args.port:
        cfg["listen"]["port"] = args.port
    if args.backend:
        cfg["output"]["backend"] = args.backend
    if args.device_id is not None:
        cfg["output"].setdefault("vjoy", {})["device_id"] = args.device_id
    if args.device_index is not None:
        cfg["output"].setdefault("ffbwheel", {})["device_index"] = args.device_index
    if args.device_name is not None:
        cfg["output"].setdefault("ffbwheel", {})["device_name_match"] = args.device_name
    if args.gain is not None:
        cfg["ffb"]["master_gain"] = args.gain
    if args.wheel_gain is not None:
        cfg["output"].setdefault("ffbwheel", {})["constant_gain"] = args.wheel_gain
    if args.lat_g_ref is not None:
        cfg["ffb"]["lateral_g_ref_mps2"] = args.lat_g_ref
    if args.rumble_gain is not None:
        cfg["output"].setdefault("ffbwheel", {})["rumble_gain"] = args.rumble_gain
    if args.no_rumble:
        cfg["output"].setdefault("ffbwheel", {})["rumble"] = False
    if args.invert:
        cfg["ffb"]["invert_steer"] = True


def _show_format() -> None:
    from . import packet as pk
    for fmt in (pk.SLED, pk.FM7_DASH, pk.HORIZON, pk.FM2023_DASH):
        print(f"{fmt.name:24s} {fmt.size} bytes")
    print("\nHorizon (FH6) key offsets:")
    for name in ("IsRaceOn", "AccelerationX", "TireSlipAngleFrontLeft",
                 "TireCombinedSlipFrontLeft", "SurfaceRumbleFrontLeft",
                 "SuspensionTravelMetersFrontLeft", "Speed", "Accel", "Brake", "Gear", "Steer"):
        print(f"  {name:34s} @ {pk.HORIZON.offsets[name]}")


def main(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)
    level = logging.WARNING - 10 * min(args.verbose, 2)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    if args.show_format:
        _show_format()
        return 0

    if args.list_devices:
        from .outputs.ffbwheel import list_devices
        try:
            devices = list_devices()
        except RuntimeError as exc:
            log.error("%s", exc)
            return 1
        if not devices:
            print("no joysticks/wheels detected by SDL.")
        for idx, name, haptic in devices:
            print(f"  [{idx}] {name}  {'(FFB-capable)' if haptic else '(no FFB)'}")
        return 0

    cfg = load_config(args.config)
    _apply_overrides(cfg, args)

    try:
        run_bridge(cfg)
    except KeyboardInterrupt:
        print("\nstopped.")
    except (RuntimeError, ValueError, OSError) as exc:
        log.error("%s", exc)
        return 1
    return 0
