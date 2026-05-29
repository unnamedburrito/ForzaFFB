"""End-to-end loopback: synthetic UDP packets -> listener -> FFB engine -> channels.

Plus the channel->vJoy-axis scaling. All stdlib; no game, no vJoy, no Windows required.
"""

import copy
import math
import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from forza_ffb.config import DEFAULTS  # noqa: E402
from forza_ffb.ffb import FFBEngine  # noqa: E402
from forza_ffb.outputs.base import channel_to_axis, VJOY_CENTER, VJOY_MIN, VJOY_MAX  # noqa: E402
from forza_ffb.packet import HORIZON, pack  # noqa: E402
from forza_ffb.telemetry import TelemetryListener  # noqa: E402
from fake_forza_sender import frame_values  # noqa: E402


class TestAxisScaling(unittest.TestCase):
    def test_signed_center_and_extremes(self):
        self.assertEqual(channel_to_axis("steer_force", 0.0), VJOY_CENTER)
        # Centered axis: +1 and -1 are SYMMETRIC about center (16383 either side),
        # so +1 -> 32767 (not 32768) and -1 -> 1.
        hi = channel_to_axis("steer_force", 1.0)
        lo = channel_to_axis("steer_force", -1.0)
        self.assertEqual(lo, VJOY_MIN)
        self.assertEqual(hi, VJOY_MAX - 1)
        self.assertEqual(VJOY_CENTER - lo, hi - VJOY_CENTER)  # symmetry
        # Out-of-range is clamped to the same extremes.
        self.assertEqual(channel_to_axis("steer_force", 5.0), hi)
        self.assertEqual(channel_to_axis("steer_force", -5.0), lo)

    def test_unsigned_spans_full_axis(self):
        self.assertEqual(channel_to_axis("road_texture", 0.0), VJOY_MIN)
        self.assertEqual(channel_to_axis("road_texture", 1.0), VJOY_MAX)
        self.assertGreater(channel_to_axis("road_texture", 0.5), VJOY_CENTER - 100)


class TestLoopback(unittest.TestCase):
    def test_pipeline_over_udp(self):
        # Bind to an ephemeral port to avoid clashing with a real Forza session.
        listener = TelemetryListener("127.0.0.1", 0, recv_timeout=0.5).open()
        port = listener.port_bound
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        engine = FFBEngine(copy.deepcopy(DEFAULTS["ffb"]))

        forces = []
        try:
            # Send a quarter-period sweep of corner packets and process each.
            for frame in range(60):
                t = frame / 60.0
                sender.sendto(pack(HORIZON, frame_values("sweep", t, frame)), ("127.0.0.1", port))
                tele = listener.recv()
                self.assertIsNotNone(tele, "expected to receive the packet we just sent")
                eff = engine.update(tele)
                forces.append(eff.steer_force)
                self.assertLessEqual(abs(eff.steer_force), 1.0)
        finally:
            sender.close()
            listener.close()

        self.assertEqual(len(forces), 60)
        # The sweep must produce a varying (non-constant) steering force.
        self.assertGreater(max(forces) - min(forces), 0.1)
        self.assertGreater(max(abs(f) for f in forces), 0.1)

    def test_stale_returns_none_on_timeout(self):
        listener = TelemetryListener("127.0.0.1", 0, recv_timeout=0.05).open()
        try:
            self.assertIsNone(listener.recv())  # nothing sent -> timeout -> None
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()
