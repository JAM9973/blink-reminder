"""Regression checks for unusable measurements, without a camera."""

import math
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from blink_app import eye_aspect_ratio, LEFT_EYE
from engine import BlinkEngine
from input_tracking import camera_session, open_camera


class InvalidEarTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows 카메라 중복 실행 검사")
    def test_camera_session_allows_other_cameras_and_reopens_after_exit(self):
        with camera_session(921):
            with self.assertRaisesRegex(RuntimeError, "이미 실행 중"), camera_session(921):
                self.fail("same camera slot was acquired twice")
            with camera_session(922):
                pass
        with camera_session(921):
            pass

    def test_windows_tries_another_backend_when_open_camera_yields_no_frame(self):
        first = Mock()
        first.grab.return_value = False
        second = Mock()
        second.retrieve.return_value = (True, SimpleNamespace(size=6))
        cv = SimpleNamespace(CAP_DSHOW=700, CAP_MSMF=1400,
                             VideoCapture=Mock(side_effect=[first, second]))
        with patch("input_tracking.sys.platform", "win32"):
            self.assertIs(open_camera(cv, 0), second)
        self.assertEqual(cv.VideoCapture.call_args_list, [call(0), call(0, 700)])
        first.release.assert_called_once()
        second.release.assert_not_called()

    def test_either_invalid_eye_pauses_time_and_requires_new_open(self):
        for bad in (float("nan"), float("inf"), -float("inf"), -.1):
            for side in (0, 1):
                with self.subTest(bad=bad, side=side), BlinkEngine() as engine:
                    engine.update(.30, .30, True, 0)
                    engine.update(.30, .30, True, 33)
                    eyes = [.30, .30]
                    eyes[side] = bad
                    result = engine.update(*eyes, True, 66)
                    self.assertEqual((result.active_ms, result.face_visible,
                                      result.state, result.blink, result.alert),
                                     (33, 0, 0, 0, 0))
                    result = engine.update(.30, .30, True, 99)
                    self.assertEqual((result.active_ms, result.state), (33, 0))
                    result = engine.update(.30, .30, True, 132)
                    self.assertEqual((result.active_ms, result.state, result.count_60s),
                                     (66, 1, 0))

    def test_invalid_sample_breaks_closed_to_open_transition(self):
        for side in (0, 1):
            with self.subTest(side=side), BlinkEngine() as engine:
                engine.update(.30, .30, True, 0)
                engine.update(.30, .30, True, 33)
                engine.update(.10, .10, True, 66)
                engine.update(.10, .10, True, 99)
                eyes = [.10, .10]
                eyes[side] = float("nan")
                engine.update(*eyes, True, 132)
                engine.update(.30, .30, True, 165)
                result = engine.update(.30, .30, True, 198)
                self.assertEqual((result.blink, result.count_60s, result.state), (0, 0, 1))

    def test_valid_history_survives_and_new_blink_counts_after_recovery(self):
        with BlinkEngine() as engine:
            for t, ear in ((0, .30), (33, .30), (66, .10), (99, .10),
                           (132, .30), (165, .30)):
                result = engine.update(ear, ear, True, t)
            self.assertEqual(result.count_60s, 1)
            for t in (198, 231):
                result = engine.update(float("nan"), .30, True, t)
                self.assertEqual((result.active_ms, result.count_60s, result.alert),
                                 (165, 1, 0))
            # Starting closed after the interruption is not a new blink.
            for t, ear in ((264, .10), (297, .10), (330, .30), (363, .30)):
                result = engine.update(ear, ear, True, t)
                self.assertEqual((result.blink, result.count_60s), (0, 1))
            for t, ear in ((396, .10), (429, .10), (462, .30), (495, .30)):
                result = engine.update(ear, ear, True, t)
            self.assertEqual((result.blink, result.count_60s, result.active_ms), (1, 2, 396))

    def test_invalid_measurements_pause_pending_alert_and_cooldown(self):
        with BlinkEngine(target=1, low_seconds=10, cooldown_seconds=60) as engine:
            for t in range(0, 65001, 1000):
                result = engine.update(.30, .30, True, t)
                self.assertFalse(result.alert)
            for t in (66000, 99000):
                result = engine.update(float("nan"), .30, True, t)
                self.assertEqual((result.alert, result.active_ms, result.low_for_ms), (0, 65000, 5000))
            alerts = []
            for t in range(100000, 105001, 1000):
                result = engine.update(.30, .30, True, t)
                if result.alert:
                    alerts.append(t)
            self.assertEqual(alerts, [105000])
            for t in (106000, 199000):
                result = engine.update(.30, float("inf"), True, t)
                self.assertEqual((result.alert, result.active_ms), (0, 70000))
            alerts = []
            for t in range(200000, 260001, 1000):
                result = engine.update(.30, .30, True, t)
                if result.alert:
                    alerts.append(t)
            self.assertEqual(alerts, [260000])

    def test_zero_ear_is_valid_closed_input(self):
        with BlinkEngine() as engine:
            for frame, ear in enumerate((.30, .30, 0., 0., .30, .30)):
                result = engine.update(ear, ear, True, frame * 33)
                self.assertEqual(result.face_visible, 1)
            self.assertEqual((result.blink, result.count_60s), (1, 1))

    def test_small_finite_ear_is_not_discarded(self):
        with BlinkEngine(closed_ear=.10, open_ear=.15) as engine:
            for frame, ear in enumerate((.17, .17, .08, .08, .17, .17)):
                result = engine.update(ear, ear, True, frame * 33)
                self.assertEqual(result.face_visible, 1)
            self.assertEqual((result.blink, result.count_60s), (1, 1))

    def test_degenerate_eye_coordinates_do_not_extend_observation(self):
        landmarks = [SimpleNamespace(x=0., y=0.) for _ in range(478)]
        ear = eye_aspect_ratio(landmarks, LEFT_EYE, 640, 480)
        self.assertTrue(math.isnan(ear))
        with BlinkEngine() as engine:
            engine.update(.30, .30, True, 0)
            engine.update(.30, .30, True, 33)
            result = engine.update(ear, .30, True, 66)
            self.assertEqual((result.active_ms, result.state, result.face_visible), (33, 0, 0))


if __name__ == "__main__":
    unittest.main()
