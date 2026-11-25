"""Run the real app/C/recorder through tray commands with synthetic input."""

import csv
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import blink_app
import app_runtime

import test_measurement_log as fixtures

temporary_directory = fixtures.temporary_directory


class BackgroundTests(unittest.TestCase):
    def run_app(self, directory, **options):
        # Reuse the camera/MediaPipe fixture, not its test methods.
        return fixtures.MeasurementLogTests().run_synthetic_app(directory, **options)

    def records(self, directory):
        path, = Path(directory).glob("*.csv")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        events = [json.loads(line) for line in path.with_suffix(".events.jsonl").read_text(encoding="utf-8").splitlines()]
        return rows, events

    def test_hidden_measurement_records_and_alerts_without_preview(self):
        for mode in ("baseline", "rebound-conservative"):
            with self.subTest(mode=mode), temporary_directory() as temp:
                _, notice, cv = self.run_app(Path(temp), background=True, mode=mode)
                rows, events = self.records(temp)
                self.assertEqual(len(rows), 80)
                self.assertEqual(sum(int(row["blink"]) for row in rows), 1)
                self.assertEqual({row["preview_visible"] for row in rows}, {"0"})
                self.assertEqual(rows[-1]["active_ms"], "69901")
                notice.show.assert_called_once()
                cv.imshow.assert_not_called()
                cv.getWindowProperty.assert_not_called()
                cv.controls.close.assert_called_once()
                self.assertEqual([e["action"] for e in events], ["start", "quit"])

    def test_hide_show_recreates_preview_and_keeps_one_session(self):
        with temporary_directory() as temp:
            capture, _, cv = self.run_app(Path(temp), background=True,
                desktop_actions=[[], ["show"], ["hide"], ["show"], ["quit"]])
            rows, events = self.records(temp)
            self.assertEqual([row["preview_visible"] for row in rows], ["0", "1", "0", "1"])
            self.assertEqual(cv.imshow.call_count, 2)
            self.assertEqual(cv.setMouseCallback.call_count, 2)
            cv.destroyWindow.assert_called_once()
            capture.release.assert_called_once()
            self.assertEqual([e["action"] for e in events], ["start", "show", "hide", "show", "quit"])

    def test_rapid_blink_policy_also_applies_when_hidden(self):
        for mode, expected in (("baseline", 1), ("rebound-conservative", 2)):
            with self.subTest(mode=mode), temporary_directory() as temp:
                self.run_app(Path(temp), background=True, rapid_fixture=True, mode=mode)
                rows, _ = self.records(temp)
                self.assertEqual(sum(int(row["blink"]) for row in rows), expected)
                self.assertEqual({row["preview_visible"] for row in rows}, {"0"})

    def test_short_pause_releases_camera_freezes_time_and_breaks_blink(self):
        for mode in ("baseline", "rebound-conservative"):
            observations = []
            def observe(index, capture, notice):
                observations.append((index, capture.read.call_count, capture.release.call_count))
            with self.subTest(mode=mode), temporary_directory() as temp:
                capture, notice, cv = self.run_app(Path(temp), mode=mode,
                    desktop_actions=[[], [], [], [], ["pause_toggle"], [], ["pause_toggle"], [], ["quit"]],
                    clock_ms=[0, 33, 66, 99, 110, 120, 132, 165], desktop_observer=observe)
                rows, events = self.records(temp)
                self.assertEqual(len(rows), 6)
                self.assertEqual(sum(int(row["blink"]) for row in rows), 0)
                self.assertEqual([row["active_ms"] for row in rows], ["0", "33", "66", "99", "99", "132"])
                self.assertEqual([e["action"] for e in events], ["start", "pause", "resume", "quit"])
                self.assertEqual(events[1]["active_ms"], events[2]["active_ms"])
                self.assertTrue(events[1]["paused"])
                self.assertFalse(events[2]["paused"])
                self.assertEqual(observations[5], (5, 4, 1))
                self.assertEqual(observations[6], (6, 4, 1))
                self.assertEqual(cv.VideoCapture.call_count, 2)
                self.assertEqual(capture.release.call_count, 2)
                notice.hide.assert_called_once()
                notice.show.assert_not_called()
                self.assertEqual(rows[4]["fps"], "")

    def test_quit_while_hidden_and_paused_does_not_reopen_camera(self):
        with temporary_directory() as temp:
            capture, _, cv = self.run_app(Path(temp), background=True,
                desktop_actions=[[], [], ["pause_toggle"], ["quit"]], clock_ms=[0, 33, 40])
            rows, events = self.records(temp)
            self.assertEqual(len(rows), 2)
            self.assertTrue(events[-1]["paused"])
            cv.VideoCapture.assert_called_once()
            capture.release.assert_called_once()
            cv.controls.close.assert_called_once()

    def test_long_pause_preserves_completed_events_and_observation_time(self):
        with temporary_directory() as temp:
            self.run_app(Path(temp), background=True,
                desktop_actions=[[], [], [], [], [], [], ["pause_toggle"], [], ["pause_toggle"], [], ["quit"]],
                clock_ms=[0, 33, 66, 99, 132, 165, 180, 5000, 5100, 5133])
            rows, events = self.records(temp)
            self.assertEqual(len(rows), 8)
            self.assertEqual(sum(int(row["blink"]) for row in rows), 1)
            self.assertEqual(rows[-1]["count_60s"], "1")
            self.assertEqual(rows[-1]["active_ms"], "165")
            self.assertEqual(events[1]["active_ms"], events[2]["active_ms"])

    def test_preview_x_turns_off_preview_without_hiding_controls(self):
        with temporary_directory() as temp:
            capture, _, cv = self.run_app(Path(temp), close_window=True,
                desktop_actions=[[], [], ["show"], ["quit"]])
            rows, events = self.records(temp)
            self.assertEqual(len(rows), 3)
            self.assertEqual([row["preview_visible"] for row in rows], ["1", "0", "0"])
            self.assertIn("preview_off", [event["action"] for event in events])
            self.assertEqual(events[-1]["action"], "quit")
            capture.release.assert_called_once()
            self.assertEqual(cv.controls.set_visible.call_args.args, (True,))

    def test_failed_resume_stays_paused_and_allows_retry(self):
        original = app_runtime.open_camera
        attempts = []
        def open_camera(cv, camera):
            attempts.append(camera)
            if len(attempts) == 2:
                raise RuntimeError("synthetic camera busy")
            return original(cv, camera)
        with temporary_directory() as temp, patch.object(app_runtime, "open_camera", side_effect=open_camera), \
                patch("tkinter.messagebox.showerror") as error:
            capture, _, cv = self.run_app(Path(temp), background=True,
                desktop_actions=[[], [], ["pause_toggle"], ["pause_toggle"], ["pause_toggle"], ["quit"]],
                clock_ms=[0, 33, 40, 50, 66])
            rows, events = self.records(temp)
            self.assertEqual(len(rows), 3)
            self.assertEqual([e["action"] for e in events], ["start", "pause", "points", "resume_failed", "resume", "quit"])
            self.assertTrue(events[3]["paused"])
            self.assertEqual(rows[-1]["active_ms"], "33")
            self.assertEqual(capture.release.call_count, 2)
            error.assert_called_once()
            cv.controls.set_visible.assert_called_once_with(True)

    def test_lost_tray_closes_recording_and_releases_hidden_camera(self):
        observed = []
        def observe(index, capture, notice):
            observed.append((capture, notice))
        with temporary_directory() as temp:
            with self.assertRaisesRegex(RuntimeError, "synthetic lost tray"):
                self.run_app(Path(temp), background=True,
                    desktop_actions=[[], RuntimeError("synthetic lost tray")], desktop_observer=observe)
            rows, _ = self.records(temp)
            self.assertEqual(len(rows), 1)
            capture, notice = observed[0]
            capture.release.assert_called_once()
            notice.close.assert_called_once()

    def test_compact_panel_defaults_to_preview_off_but_keeps_measurement(self):
        with temporary_directory() as temp:
            capture, _, cv = self.run_app(Path(temp), preview=False,
                desktop_actions=[[], [], [], ["quit"]])
            rows, _ = self.records(temp)
            self.assertEqual(len(rows), 3)
            self.assertEqual({row["preview_visible"] for row in rows}, {"0"})
            self.assertEqual(rows[-1]["active_ms"], "66")
            cv.imshow.assert_not_called()
            self.assertFalse(cv.controls.update.call_args.kwargs["preview_enabled"])
            capture.release.assert_called_once()

    def test_panel_target_preview_and_points_commands_reach_c_and_csv(self):
        with temporary_directory() as temp:
            capture, _, cv = self.run_app(Path(temp), preview=False, no_keys=True,
                desktop_actions=[[], ["target_up", "preview_toggle"], ["target_down", "points"], ["preview_toggle"], ["quit"]])
            rows, events = self.records(temp)
            self.assertEqual([row["target"] for row in rows], ["12", "13", "12", "12"])
            self.assertEqual([row["preview_visible"] for row in rows], ["0", "1", "1", "0"])
            self.assertEqual([row["landmarks_visible"] for row in rows], ["1", "1", "0", "0"])
            self.assertEqual([event["action"] for event in events],
                ["start", "target_up", "preview_on", "target_down", "points", "preview_off", "quit"])
            self.assertEqual(events[1]["target"], 13)
            self.assertFalse(events[4]["landmarks_visible"])
            self.assertEqual(cv.imshow.call_count, 2)
            self.assertFalse(cv.controls.update.call_args.kwargs["preview_enabled"])
            capture.release.assert_called_once()

    def test_tray_restore_respects_preview_off(self):
        with temporary_directory() as temp:
            _, _, cv = self.run_app(Path(temp), background=True, preview=False,
                desktop_actions=[[], ["show"], ["hide"], ["show"], ["quit"]])
            rows, _ = self.records(temp)
            self.assertEqual({row["preview_visible"] for row in rows}, {"0"})
            cv.imshow.assert_not_called()
            self.assertEqual([call.args[0] for call in cv.controls.set_visible.call_args_list], [True, False, True])

    def test_preview_controls_while_measurement_off_do_not_reopen_camera(self):
        with temporary_directory() as temp:
            capture, _, cv = self.run_app(Path(temp), preview=False, no_keys=True,
                desktop_actions=[[], ["pause_toggle"], ["preview_toggle"], ["preview_toggle"], ["quit"]],
                clock_ms=[0, 10])
            rows, events = self.records(temp)
            self.assertEqual(len(rows), 1)
            capture.read.assert_called_once()
            capture.release.assert_called_once()
            cv.VideoCapture.assert_called_once()
            self.assertEqual([event["action"] for event in events],
                             ["start", "pause", "preview_on", "preview_off", "quit"])
            self.assertTrue(all(event["paused"] for event in events[1:]))
            self.assertTrue(cv.controls.update.call_args.kwargs["paused"])


if __name__ == "__main__":
    unittest.main()
