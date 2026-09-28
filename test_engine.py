"""Synthetic eye readings verify the C library without a webcam."""

import unittest

from build import build
from engine import BlinkEngine


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def test_open_closed_open_counts_once(self):
        with BlinkEngine() as engine:
            engine.update(.30, .30, True, 0)
            engine.update(.30, .30, True, 33)
            engine.update(.10, .10, True, 66)
            engine.update(.10, .10, True, 99)
            for t in (132, 165, 198, 231):
                result = engine.update(.10, .10, True, t)
            self.assertEqual(result.count_60s, 0)  # held closed is not repeated
            engine.update(.30, .30, True, 264)
            result = engine.update(.30, .30, True, 297)
            self.assertEqual((result.blink, result.count_60s), (1, 1))
            result = engine.update(.30, .30, True, 330)
            self.assertEqual((result.blink, result.count_60s), (0, 1))

    def test_noise_disagreement_and_missing_face(self):
        with BlinkEngine() as engine:
            engine.update(.30, .30, True, 0)
            engine.update(.30, .30, True, 33)
            engine.update(.10, .30, True, 66)  # eyes disagree
            engine.update(.30, .30, True, 99)
            engine.update(.10, .10, True, 132)  # one-frame noise
            engine.update(.30, .30, True, 165)
            self.assertEqual(engine.update(.30, .30, True, 198).count_60s, 0)
            engine.update(.10, .10, True, 231)
            engine.update(.10, .10, True, 264)
            engine.update(0, 0, False, 297)  # interrupted closed period
            engine.update(.30, .30, True, 330)
            self.assertEqual(engine.update(.30, .30, True, 363).count_60s, 0)
            self.assertEqual(engine.update(.30, .30, True, 396).active_ms, 330)

    def test_window_persistence_and_cooldown(self):
        with BlinkEngine(target=1, low_seconds=10, cooldown_seconds=60) as engine:
            alerts = []
            for t in range(0, 131_000, 1_000):
                result = engine.update(.30, .30, True, t)
                if result.alert:
                    alerts.append(t)
            self.assertEqual(alerts, [70_000, 130_000])
            self.assertEqual(result.count_60s, 0)

    def test_missing_face_pauses_observation_and_alert(self):
        with BlinkEngine(target=1, low_seconds=0) as engine:
            for t in range(0, 50_001, 1_000):
                result = engine.update(.30, .30, True, t)
            self.assertEqual(result.active_ms, 50_000)
            self.assertFalse(engine.update(0, 0, False, 500_000).alert)
            self.assertEqual(engine.update(.30, .30, True, 501_000).active_ms, 50_000)
            for t in range(502_000, 512_000, 1_000):
                result = engine.update(.30, .30, True, t)
            self.assertEqual((result.active_ms, result.alert), (60_000, 1))

    def test_target_change(self):
        with BlinkEngine(target=0, low_seconds=0) as engine:
            for t in range(0, 61_000, 1_000):
                result = engine.update(.30, .30, True, t)
            self.assertFalse(result.alert)
            engine.set_target(1)
            self.assertTrue(engine.update(.30, .30, True, 61_000).alert)


if __name__ == "__main__":
    unittest.main()
