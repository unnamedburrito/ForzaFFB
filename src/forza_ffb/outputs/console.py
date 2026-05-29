"""Console output backend — prints synthesized channels. Works on any OS.

Primary use: verifying the pipeline and tuning the FFB feel without vJoy/a wheel.
"""

from __future__ import annotations

from typing import Any, Dict

from ..ffb import CHANNELS, Effects
from .base import OutputBackend


def _bar(value: float, width: int = 11) -> str:
    """A small signed/unsigned ASCII meter in [-1,1] (center) or [0,1]."""
    half = width // 2
    n = int(round(value * half))
    n = max(-half, min(half, n))
    cells = ["-"] * width
    cells[half] = "|"
    if n >= 0:
        for i in range(half, half + n + 1):
            cells[i] = "#"
    else:
        for i in range(half + n, half + 1):
            cells[i] = "#"
    return "".join(cells)


class ConsoleOutput(OutputBackend):
    def __init__(self, cfg: Dict[str, Any]):
        self.every = max(1, int(cfg.get("output", {}).get("console", {}).get("every", 10)))
        self._n = 0

    def write(self, effects: Effects) -> None:
        self._n += 1
        if self._n % self.every:
            return
        d = effects.as_dict()
        parts = [f"{ch}={d[ch]:+.2f}" for ch in CHANNELS]
        steer = d["steer_force"]
        print(f"steer[{_bar(steer)}] " + "  ".join(parts))

    def close(self) -> None:
        pass
