"""Verify saved values and the real app loop using synthetic camera inputs."""

import csv
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import blink_app
from measurement_log import FrameRate, SessionRecorder


@contextmanager
def temporary_directory():
    # Some Windows sandbox temp directories have unusable inherited ACLs.
    # Keep disposable test data in an explicitly bounded workspace directory.
    parent = Path(__file__).resolve().parent / ".cache" / "measurement-tests"
    path = parent / uuid4().hex
    path.mkdir(parents=True)
    try:
        yield str(path)
    finally:
        resolved = path.resolve()
        if resolved.parent != parent.resolve() or resolved == parent.resolve():
            raise RuntimeError("테스트 임시 경로가 지정 폴더를 벗어났습니다.")
        shutil.rmtree(resolved)


def eye_landmarks(ear=.30):
    points = [SimpleNamespace(x=0., y=0.) for _ in range(478)]
    # At 200x100 pixels, eye width=40 and lid gap=40*EAR.
    for indices, x in ((blink_app.LEFT_EYE, .2), (blink_app.RIGHT_EYE, .6)):
        gap = ear * .4
        coords = ((x, .3), (x + .05, .3 - gap / 2),
                  (x + .15, .3 - gap / 2), (x + .2, .3),
                  (x + .15, .3 + gap / 2), (x + .05, .3 + gap / 2))
        for index, (px, py) in zip(indices, coords):
            points[index] = SimpleNamespace(x=px, y=py)
    return points


class MeasurementLogTests(unittest.TestCase):
    def test_fps_measures_intervals_and_includes_long_gap(self):
        rate = FrameRate()
        first = rate.update(0)
        self.assertIsNone(first.fps)
        self.assertIsNone(first.interval_ms)
        for timestamp in (33_000_000, 66_000_000, 99_000_000):
            timing = rate.update(timestamp)
        self.assertAlmostEqual(timing.fps, 1000 / 33)
        self.assertEqual((timing.interval_ms, timing.elapsed_ms), (33, 99))
        gap = rate.update(2_000_000_000)
        self.assertEqual(gap.interval_ms, 1901)
        self.assertAlmostEqual(gap.fps, 1000 / 1901)

    def test_points_use_width_and_height_and_stay_inside_image(self):
        drawing = Mock()
        frame = SimpleNamespace(shape=(100, 200, 3))
        points = eye_landmarks()
        points[blink_app.LEFT_EYE[0]] = SimpleNamespace(x=.25, y=.4)
        points[blink_app.LEFT_EYE[1]] = SimpleNamespace(x=1.2, y=-.2)
        points[blink_app.LEFT_EYE[2]] = SimpleNamespace(x=float("nan"), y=.2)
        blink_app.draw_eye_points(drawing, frame, points)
        self.assertEqual(drawing.circle.call_count, 11)
        self.assertEqual(drawing.circle.call_args_list[0].args[1], (50, 40))
        self.assertEqual(drawing.circle.call_args_list[1].args[1], (199, 0))

    def run_synthetic_app(self, directory, *, no_csv=False, fail_read=False,
                          recorder_factory=None, exit_key=None, close_window=False,
                          mouse_commands=None):
        import cv2
        import numpy as np

        timestamps = [0, 33, 66, 99, 132, 165, 198, 231, 264, 297]
        timestamps += list(range(1000, 70001, 1000))
        detections = [SimpleNamespace(face_landmarks=[eye_landmarks(ear)])
                      for ear in (.30, .30, .10, .10, .30, .30)]
        detections += [SimpleNamespace(face_landmarks=[]),
                       SimpleNamespace(face_landmarks=[eye_landmarks(float("nan"))])]
        detections += [SimpleNamespace(face_landmarks=[eye_landmarks()])
                       for _ in timestamps[8:]]
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.side_effect = [(True, np.zeros((100, 200, 3), dtype=np.uint8))
                                    for _ in timestamps]
        if fail_read:
            capture.read.side_effect = [(True, np.zeros((100, 200, 3), dtype=np.uint8)),
                                        (False, None)]
        detector = Mock()
        detector.detect_for_video.side_effect = detections
        detector_context = Mock()
        detector_context.__enter__ = Mock(return_value=detector)
        detector_context.__exit__ = Mock(return_value=False)

        fake_cv = ModuleType("cv2")
        for name in ("CAP_DSHOW", "CAP_MSMF", "COLOR_BGR2RGB", "FONT_HERSHEY_SIMPLEX",
                     "WND_PROP_VISIBLE", "EVENT_LBUTTONUP", "error"):
            setattr(fake_cv, name, getattr(cv2, name))
        fake_cv.VideoCapture = Mock(return_value=capture)
        fake_cv.flip = cv2.flip
        fake_cv.cvtColor = cv2.cvtColor
        fake_cv.circle = Mock(wraps=cv2.circle)
        fake_cv.rectangle = cv2.rectangle
        fake_cv.putText = Mock()
        fake_cv.imshow = Mock()
        fake_cv.destroyAllWindows = Mock()
        fake_cv.getWindowProperty = Mock(return_value=0 if close_window else 1)
        fake_cv.setMouseCallback = Mock()
        keys = [ord("l"), ord("+"), ord("l"), ord("-")]
        fake_cv.waitKey = Mock(side_effect=keys + [-1] * (len(timestamps) - 5) + [ord("q")])
        if exit_key is not None or close_window:
            fake_cv.waitKey = Mock(return_value=exit_key if exit_key is not None else -1)
        if mouse_commands:
            commands = iter(mouse_commands)

            def mouse_wait(delay):
                command = next(commands)
                callback = fake_cv.setMouseCallback.call_args.args[1]
                # The 200x100 fixture has button centers x=52 and 148, y=78.
                if command:
                    callback(cv2.EVENT_LBUTTONUP, 52 if command == "points" else 148,
                             78, 0, None)
                return -1

            fake_cv.waitKey = Mock(side_effect=mouse_wait)

        mp = ModuleType("mediapipe")
        tasks = ModuleType("mediapipe.tasks")
        python = ModuleType("mediapipe.tasks.python")
        vision = ModuleType("mediapipe.tasks.python.vision")
        mp.Image = Mock()
        mp.ImageFormat = SimpleNamespace(SRGB=1)
        tasks.python = python
        python.BaseOptions = Mock()
        python.vision = vision
        vision.FaceLandmarkerOptions = Mock()
        vision.RunningMode = SimpleNamespace(VIDEO=1)
        vision.FaceLandmarker = SimpleNamespace(create_from_options=Mock(return_value=detector_context))
        model = directory / "synthetic.task"
        model.write_bytes(b"synthetic detector - not a real MediaPipe model")
        args = blink_app.parse_args(["--csv-dir", str(directory), "--model", str(model),
                                     "--low-seconds", "0"] + (["--no-csv"] if no_csv else []))
        factory = recorder_factory or (
            lambda folder, settings: SessionRecorder(folder, settings, input_kind="synthetic"))
        notice = Mock()
        modules = {"cv2": fake_cv, "mediapipe": mp, "mediapipe.tasks": tasks,
                   "mediapipe.tasks.python": python, "mediapipe.tasks.python.vision": vision}
        with patch.dict("sys.modules", modules), \
                patch.object(blink_app, "EyeNotice", return_value=notice), \
                patch.object(blink_app, "SessionRecorder", side_effect=factory), \
                patch.object(blink_app.time, "monotonic_ns", side_effect=[t * 1_000_000 for t in timestamps]), \
                patch("builtins.print"):
            blink_app.run(args)
        return capture, notice, fake_cv

    def test_real_app_loop_saves_raw_values_settings_and_events(self):
        with temporary_directory() as temp:
            directory = Path(temp) / "한글 기록"
            directory.mkdir()
            capture, notice, drawing = self.run_synthetic_app(directory)
            path, = directory.glob("*.csv")
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 80)
            self.assertEqual(sum(int(row["blink"]) for row in rows), 1)
            self.assertEqual([row["monotonic_ms"] for row in rows if row["alert"] == "1"], ["61000"])
            self.assertEqual([row["target"] for row in rows[:5]], ["12", "12", "13", "13", "12"])
            self.assertEqual([row["landmarks_visible"] for row in rows[:4]], ["1", "0", "0", "1"])
            self.assertEqual((rows[6]["face_detected"], rows[6]["measurement_valid"], rows[6]["left_ear"]),
                             ("0", "0", ""))
            self.assertEqual((rows[7]["face_detected"], rows[7]["measurement_valid"], rows[7]["left_ear"]),
                             ("1", "0", "nan"))
            self.assertEqual(rows[5]["active_ms"], rows[8]["active_ms"])
            self.assertEqual(rows[0]["fps"], "")
            self.assertEqual(rows[1]["frame_interval_ms"], "33.0")
            self.assertAlmostEqual(float(rows[1]["fps"]), 30.303, places=3)
            self.assertEqual(rows[0]["stable_frames"], "2")
            metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["input_kind"], "synthetic")
            self.assertEqual(metadata["initial_settings"]["target"], 12)
            self.assertIn("blink_engine.c", metadata["source_sha256"])
            capture.release.assert_called_once()
            notice.close.assert_called_once()
            notice.show.assert_called_once()
            # 80 frames, 2 hidden and 2 unusable frames => 76*12 eye points.
            self.assertEqual(drawing.circle.call_count, 76 * 12)

    def test_csv_disabled_keeps_app_running_without_creating_records(self):
        with temporary_directory() as temp:
            directory = Path(temp)
            capture, notice, _ = self.run_synthetic_app(directory, no_csv=True)
            self.assertEqual(list(directory.glob("*.csv")), [])
            capture.release.assert_called_once()
            notice.show.assert_called_once()

    def test_csv_open_error_does_not_stop_measurement_or_alert(self):
        with temporary_directory() as temp:
            capture, notice, _ = self.run_synthetic_app(
                Path(temp), recorder_factory=Mock(side_effect=OSError("synthetic storage error")))
            capture.release.assert_called_once()
            notice.show.assert_called_once()

    def test_camera_error_closes_record_file_and_releases_camera(self):
        with temporary_directory() as temp:
            directory = Path(temp)
            with self.assertRaisesRegex(RuntimeError, "영상을 읽지"):
                self.run_synthetic_app(directory, fail_read=True)
            path, = directory.glob("*.csv")
            # Buffered row must be readable after the exception unwinds.
            with path.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)

    def test_csv_write_error_closes_recorder_and_keeps_alert_running(self):
        recorder = Mock()
        recorder.write.side_effect = OSError("synthetic disk full")
        recorder.path = Path("synthetic.csv")
        with temporary_directory() as temp:
            capture, notice, _ = self.run_synthetic_app(
                Path(temp), recorder_factory=Mock(return_value=recorder))
        self.assertEqual(recorder.write.call_count, 1)
        recorder.close.assert_called_once()
        capture.release.assert_called_once()
        notice.show.assert_called_once()

    def test_uppercase_q_escape_and_window_close_save_and_exit(self):
        for key, closed in ((ord("Q"), False), (27, False), (None, True)):
            with self.subTest(key=key, closed=closed), temporary_directory() as temp:
                directory = Path(temp)
                capture, notice, _ = self.run_synthetic_app(
                    directory, exit_key=key, close_window=closed)
                path, = directory.glob("*.csv")
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    self.assertEqual(len(list(csv.DictReader(stream))), 1)
                capture.release.assert_called_once()
                notice.close.assert_called_once()

    def test_mouse_points_and_exit_work_without_keyboard_events(self):
        with temporary_directory() as temp:
            directory = Path(temp)
            capture, notice, _ = self.run_synthetic_app(
                directory, mouse_commands=["points", "quit"])
            path, = directory.glob("*.csv")
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["landmarks_visible"] for row in rows], ["1", "0"])
            capture.release.assert_called_once()
            notice.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
