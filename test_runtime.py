"""시작 실패와 기록 실패가 생겨도 자원을 정리하는지 확인한다."""

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import app_runtime
import test_measurement_log as fixtures


class RuntimeTests(unittest.TestCase):
    def test_control_window_start_failure_releases_camera(self):
        capture = Mock()
        with fixtures.temporary_directory() as temp, patch.object(app_runtime, "open_camera", return_value=capture):
            with self.assertRaisesRegex(RuntimeError, "synthetic window failure"):
                fixtures.MeasurementLogTests().run_synthetic_app(Path(temp), desktop_actions=[],
                    controls_error=RuntimeError("synthetic window failure"))
            capture.release.assert_called_once()
            self.assertEqual(list(Path(temp).glob("*.csv")), [])

    def test_control_record_failure_closes_file_but_keeps_alert_working(self):
        recorder = Mock(path=Path("synthetic.csv"))
        recorder.write_control.side_effect = OSError("synthetic control log failure")
        with fixtures.temporary_directory() as temp:
            capture, notice, _ = fixtures.MeasurementLogTests().run_synthetic_app(Path(temp),
                background=True, recorder_factory=Mock(return_value=recorder))
        recorder.close.assert_called_once()
        recorder.write.assert_not_called()
        capture.release.assert_called_once()
        notice.show.assert_called_once()


if __name__ == "__main__":
    unittest.main()
