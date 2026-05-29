"""forza_ffb — Forza Horizon 6 Data Out telemetry -> synthesized force-feedback channels.

Public API:
    parse(buf) -> Telemetry            packet parsing (forza_ffb.packet)
    FFBEngine                          physics -> Effects channels (forza_ffb.ffb)
    TelemetryListener                  UDP listener (forza_ffb.telemetry)
    make_output(cfg)                   output backend factory (forza_ffb.outputs)
    run_bridge(cfg)                    full pipeline (forza_ffb.bridge)
"""

from __future__ import annotations

from .ffb import CHANNELS, Effects, FFBEngine
from .packet import HORIZON, Telemetry, parse
from .telemetry import TelemetryListener

__version__ = "1.0.0"

__all__ = [
    "parse",
    "Telemetry",
    "HORIZON",
    "FFBEngine",
    "Effects",
    "CHANNELS",
    "TelemetryListener",
    "__version__",
]
