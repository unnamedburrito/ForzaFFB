#!/usr/bin/env python3
"""Synthetic Forza Horizon 6 telemetry sender.

Emits real 324-byte Horizon "Car Dash" UDP packets so the bridge can be exercised end to
end without the game (and on any OS). Useful for tuning the FFB feel and for tests.

Examples:
    python tools/fake_forza_sender.py --scenario sweep --port 2066
    python tools/fake_forza_sender.py --scenario kerbs --duration 5
"""

from __future__ import annotations

import argparse
import math
import os
import socket
import sys
import time

# Make 'forza_ffb' importable when run from the repo without installation.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from forza_ffb.packet import HORIZON, pack  # noqa: E402


def frame_values(scenario: str, t: float, frame: int) -> dict:
    """Return a physics dict for time *t* (s). Coherent enough to exercise every channel."""
    v = {"IsRaceOn": 1, "TimestampMS": int(t * 1000) & 0xFFFFFFFF, "Gear": 3,
         "EngineMaxRpm": 7000.0, "CurrentEngineRpm": 4000.0}

    if scenario == "idle":
        v["IsRaceOn"] = 0
        return v

    if scenario == "straight":
        v.update(Speed=40.0, Accel=180, AccelerationZ=1.0)
        return v

    # A periodic corner used by 'corner'/'sweep'/'kerbs' (0.2 Hz => 5 s period).
    corner = math.sin(2 * math.pi * 0.2 * t)
    speed = 30.0
    v.update(
        Speed=speed,
        Accel=200,
        AccelerationX=corner * 9.0,                 # lateral G
        AccelerationZ=0.5,
        Steer=int(max(-127, min(127, corner * 100))),
        TireSlipAngleFrontLeft=corner * 0.10,       # rad
        TireSlipAngleFrontRight=corner * 0.10,
        # combined slip peaks above 1.0 near the apex -> triggers understeer lightening
        TireCombinedSlipFrontLeft=abs(corner) * 1.4,
        TireCombinedSlipFrontRight=abs(corner) * 1.4,
        TireCombinedSlipRearLeft=abs(corner) * 1.2,
        TireCombinedSlipRearRight=abs(corner) * 1.2,
        # gentle road texture (deterministic ripple)
        SurfaceRumbleFrontLeft=0.12 + 0.05 * abs(math.sin(13.0 * t)),
        SurfaceRumbleFrontRight=0.12 + 0.05 * abs(math.cos(11.0 * t)),
    )

    if scenario == "kerbs":
        # A sharp suspension impact + rumble strip for ~3 frames every 2 seconds.
        in_kerb = (frame % 120) < 3
        if in_kerb:
            v.update(
                SuspensionTravelMetersFrontLeft=0.06,
                SuspensionTravelMetersFrontRight=0.06,
                WheelOnRumbleStripFrontLeft=1,
                WheelOnRumbleStripFrontRight=1,
            )
    return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Send synthetic FH6 telemetry packets.")
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2066)
    ap.add_argument("--rate", type=float, default=60.0, help="packets per second")
    ap.add_argument("--duration", type=float, default=0.0, help="seconds (0 = forever)")
    ap.add_argument("--scenario", default="sweep",
                    choices=["sweep", "corner", "kerbs", "straight", "idle"])
    args = ap.parse_args(argv)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (args.ip, args.port)
    period = 1.0 / args.rate
    start = time.monotonic()
    frame = 0
    print(f"sending {args.scenario} -> {args.ip}:{args.port} at {args.rate:.0f} Hz "
          f"({'forever' if args.duration == 0 else f'{args.duration:g}s'})")
    try:
        while True:
            t = time.monotonic() - start
            if args.duration and t >= args.duration:
                break
            sock.sendto(pack(HORIZON, frame_values(args.scenario, t, frame)), dest)
            frame += 1
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print(f"sent {frame} packets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
