"""Notification settings, lifecycle, animation, and actual app routing."""

from contextlib import contextmanager
import json
import csv
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import blink_app
import app_runtime
import notifications
import notification_settings as settings
import test_measurement_log as fixtures


class FakeRoot:
    def __init__(self):
        self.callbacks = {}
        self.counter = 0
        self.destroyed = False
    def withdraw(self): pass
    def winfo_fpixels(self, _): return 96
    def update(self): pass
    def after(self, delay, callback):
        self.counter += 1
        self.callbacks[self.counter] = callback
        return self.counter
    def after_cancel(self, key): self.callbacks.pop(key, None)
    def fire(self):
        key = next(iter(self.callbacks))
        self.callbacks.pop(key)()
    def destroy(self): self.destroyed = True


class FakeWindow:
    def __init__(self, _): self.visible = False
    def withdraw(self): self.visible = False
    def overrideredirect(self, _): pass
    def configure(self, **_): pass
    def attributes(self, *args): pass
    def destroy(self): self.visible = False


class FakeCanvas:
    def __init__(self, *args, **kwargs): self.drawings = {}
    def configure(self, **_): pass
    def pack(self, **_): pass
    def delete(self, key): self.drawings.pop(key, None)
    def create_text(self, *args, **kwargs): pass
    def create_rectangle(self, *args, **kwargs): self.drawings[kwargs["tags"]] = args
    def create_oval(self, *args, **kwargs): self.drawings[kwargs["tags"]] = args
    def create_line(self, *args, **kwargs): self.drawings[kwargs["tags"]] = args


@contextmanager
def manager_fixture():
    root = FakeRoot()
    clock = SimpleNamespace(now=0.)
    class Backend:
        failed = False
        def bounds(self): return (-1280, 0, 0, 720)
        def show(self, window, rectangle):
            if self.failed:
                raise OSError("synthetic display failure")
            window.visible = True
            window.rectangle = rectangle
    backend = Backend()
    with patch("tkinter.Tk", return_value=root), patch("tkinter.Toplevel", FakeWindow), \
            patch("tkinter.Canvas", FakeCanvas), patch.object(notifications, "WindowsOverlay", return_value=backend), \
            patch("builtins.print"):
        manager = notifications.NotificationManager(clock=lambda: clock.now)
        try:
            yield manager, root, clock, backend
        finally:
            manager.close()


class NotificationTests(unittest.TestCase):
    def test_each_mode_is_exclusive_expires_and_cancels_its_timer(self):
        with manager_fixture() as (manager, root, clock, _):
            for mode, surfaces in (("pill",1), ("edge",4), ("blink",1)):
                with self.subTest(mode=mode):
                    manager.set_mode(mode)
                    clock.now = 0
                    self.assertTrue(manager.show())
                    windows = list(manager.active_windows)
                    self.assertEqual(len(windows), surfaces)
                    self.assertTrue(all(w.visible for w in windows))
                    self.assertEqual(len(root.callbacks), 1)
                    clock.now = notifications.DURATION_SECONDS
                    root.fire()
                    self.assertFalse(any(w.visible for w in windows))
                    self.assertFalse(root.callbacks)

    def test_repeated_show_and_mode_switch_do_not_stack_or_leak_timers(self):
        with manager_fixture() as (manager, root, _, _):
            manager.show()
            first = list(manager.active_windows)
            manager.show(preview=True)
            self.assertEqual(manager.active_windows, first)
            self.assertEqual(len(root.callbacks), 1)
            manager.set_mode("edge")
            self.assertFalse(any(w.visible for w in first))
            self.assertFalse(root.callbacks)
            manager.show()
            manager.hide()
            self.assertFalse(manager.active_windows)
            self.assertFalse(root.callbacks)
            manager.close()
            self.assertTrue(root.destroyed)
            self.assertFalse(root.callbacks)

    def test_invalid_mode_does_not_discard_current_notification(self):
        with manager_fixture() as (manager, _, _, _):
            manager.show()
            with self.assertRaises(ValueError): manager.set_mode("other")
            self.assertEqual(manager.mode, "pill")
            self.assertTrue(manager.active_windows[0].visible)

    def test_display_failure_hides_every_surface_and_can_retry(self):
        with manager_fixture() as (manager, root, _, backend):
            manager.set_mode("edge")
            backend.failed = True
            self.assertFalse(manager.show())
            self.assertTrue(manager.last_error)
            self.assertFalse(root.callbacks)
            self.assertFalse(any(w.visible for w,_ in manager.surfaces["edge"]))
            backend.failed = False
            self.assertTrue(manager.show())
            self.assertFalse(manager.last_error)

    def test_animation_progress_pulses_and_three_blinks(self):
        for mode in settings.MODES:
            values = [notifications.animation_values(mode, i/100) for i in range(351)]
            self.assertEqual(values[0][0], 0)
            self.assertEqual(values[-1][0], 1)
            self.assertTrue(all(0 <= alpha <= .94 for _,alpha,_ in values))
        for index in range(3):
            _,_,opening = notifications.animation_values("blink", .35 + .95*index + .95*.125)
            self.assertAlmostEqual(opening, 0, places=10)
        self.assertEqual(notifications.animation_values("blink", 3.4)[2], 1)
        self.assertLessEqual(max(notifications.animation_values("edge", i/100)[1] for i in range(350)), .26)

    def test_settings_round_trip_missing_and_invalid_values(self):
        with fixtures.temporary_directory() as temp:
            path = Path(temp)/"notification_settings.json"
            self.assertEqual(settings.load_mode(path), ("pill", ""))
            for mode in settings.MODES:
                settings.save_mode(mode, path)
                self.assertEqual(settings.load_mode(path), (mode, ""))
            before = path.read_bytes()
            with self.assertRaises(ValueError): settings.save_mode("unknown", path)
            self.assertEqual(path.read_bytes(), before)
            for invalid in ("not-json", "[]", '{"schema_version":1,"mode":[]}'):
                path.write_text(invalid,encoding="utf-8")
                mode, warning = settings.load_mode(path)
                self.assertEqual(mode, "pill")
                self.assertTrue(warning)

    def test_failed_atomic_save_preserves_previous_choice(self):
        with fixtures.temporary_directory() as temp:
            path = Path(temp)/"notification_settings.json"
            settings.save_mode("pill",path)
            with patch.object(Path,"replace",side_effect=OSError("synthetic write failure")):
                with self.assertRaises(OSError): settings.save_mode("edge",path)
            self.assertEqual(settings.load_mode(path), ("pill", ""))
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_mute_choices_persist_and_expire_at_deadline(self):
        with fixtures.temporary_directory() as temp:
            path = Path(temp) / "mute.json"
            self.assertEqual(settings.load_mute(path), (None, ""))
            with patch.object(app_runtime, "save_mute", side_effect=lambda value: settings.save_mute(value, path)), \
                    patch.object(app_runtime, "load_mute", side_effect=lambda: settings.load_mute(path)):
                app = app_runtime.BlinkApplication(blink_app.parse_args([]))
                app.notice = Mock()
                for choice, minutes, label in (("10", 10, "10분"), ("60", 60, "1시간"),
                                               ("120", 120, "2시간"), ("1440", 1440, "24시간")):
                    with self.subTest(choice=choice), patch.object(app_runtime.time, "time", return_value=100.25):
                        app._handle_action(f"mute:{choice}")
                        self.assertEqual(settings.load_mute(path), (100250 + minutes * 60_000, ""))
                        self.assertEqual(app._mute_label(), f"꺼짐 · {label} 남음")
                        reopened = app_runtime.BlinkApplication(blink_app.parse_args([]))
                        self.assertEqual(reopened._mute_label(), app._mute_label())
                saved = settings.load_mute(path)[0]
                with patch.object(app_runtime.time, "time", return_value=(saved - 1) / 1000):
                    self.assertEqual(app._mute_label(), "꺼짐 · 1분 남음")
                with patch.object(app_runtime.time, "time", return_value=saved / 1000):
                    self.assertEqual(app._mute_label(), "켜짐")
                app._handle_action("mute:off")
                self.assertEqual(settings.load_mute(path), ("off", ""))
                self.assertEqual(app._mute_label(), "꺼짐")
                reopened = app_runtime.BlinkApplication(blink_app.parse_args([]))
                self.assertEqual(reopened._mute_label(), "꺼짐")
                app._handle_action("mute:on")
                self.assertEqual(settings.load_mute(path), (None, ""))
            self.assertEqual(app.notice.hide.call_count, 5)

    def test_muted_alert_preserves_measurement_and_expired_mute_allows_alert(self):
        for saved, displayed in (("off", 0), (1, 1)):
            with self.subTest(saved=saved), fixtures.temporary_directory() as temp:
                folder = Path(temp)
                _, notice, _ = fixtures.MeasurementLogTests().run_synthetic_app(folder, mute_until=saved)
                self.assertEqual(notice.show.call_count, displayed)
                trace, = folder.glob("*.csv")
                with trace.open(encoding="utf-8", newline="") as stream:
                    raw = list(csv.DictReader(stream))
                self.assertEqual(sum(int(row["alert"]) for row in raw), 1)
                saved_rows = []
                for path in (folder / "daily").glob("*.csv"):
                    with path.open(encoding="utf-8", newline="") as stream:
                        saved_rows.extend(csv.DictReader(stream))
                self.assertEqual(sum(int(row["alerts"]) for row in saved_rows), displayed)
                self.assertEqual(sum(int(row["blinks"]) for row in saved_rows), 1)
                self.assertAlmostEqual(sum(float(row["valid_seconds"]) for row in saved_rows),
                                       int(raw[-1]["active_ms"]) / 1000)

    def test_app_selection_test_and_csv_use_selected_mode(self):
        with fixtures.temporary_directory() as temp:
            folder=Path(temp)
            pref=folder/"choice.json"
            with patch.object(app_runtime,"save_mode",side_effect=lambda mode: settings.save_mode(mode,pref)):
                _, notice, cv = fixtures.MeasurementLogTests().run_synthetic_app(folder, preview=False, no_keys=True,
                    desktop_actions=[[],["notification:edge"],["notification_test"],["notification:blink"],["quit"]])
            path,=folder.glob("*.csv")
            with path.open(encoding="utf-8-sig",newline="") as stream: rows=list(csv.DictReader(stream))
            self.assertEqual([r["notification_mode"] for r in rows],["pill","edge","edge","blink"])
            self.assertEqual(sum(int(r["alert"]) for r in rows),0)
            notice.show.assert_called_once_with(preview=True)
            self.assertEqual([call.args[0] for call in notice.set_mode.call_args_list],["pill","edge","blink"])
            self.assertEqual(settings.load_mode(pref),("blink",""))
            events=[json.loads(line) for line in path.with_suffix(".events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([e["action"] for e in events],["start","notification_mode","notification_test","notification_mode","quit"])
            self.assertEqual(cv.controls.update.call_args.kwargs["notification_mode"],"blink")

    def test_saved_choice_and_cli_override_are_loaded_without_rewriting(self):
        for cli, expected in ((None,"blink"),("edge","edge")):
            with self.subTest(cli=cli), fixtures.temporary_directory() as temp, patch.object(app_runtime,"save_mode") as save:
                _,notice,_=fixtures.MeasurementLogTests().run_synthetic_app(Path(temp), no_keys=True,
                    notification_start="blink",notification_cli=cli,desktop_actions=[[],["quit"]])
                notice.set_mode.assert_called_once_with(expected)
                save.assert_not_called()

    def test_manual_test_while_off_does_not_open_camera_or_generate_c_alert(self):
        with fixtures.temporary_directory() as temp, patch.object(app_runtime,"save_mode"):
            capture, notice, cv=fixtures.MeasurementLogTests().run_synthetic_app(Path(temp), preview=False, no_keys=True,
                desktop_actions=[[],["pause_toggle"],["notification:blink","notification_test"],["quit"]],clock_ms=[0,10])
            capture.read.assert_called_once()
            cv.VideoCapture.assert_called_once()
            capture.release.assert_called_once()
            notice.show.assert_called_once_with(preview=True)

    def test_save_error_applies_session_choice_and_shows_warning(self):
        with fixtures.temporary_directory() as temp, patch.object(app_runtime,"save_mode",side_effect=OSError("synthetic readonly folder")):
            _,notice,cv=fixtures.MeasurementLogTests().run_synthetic_app(Path(temp),no_keys=True,
                desktop_actions=[[],["notification:edge"],["quit"]])
            self.assertEqual(cv.controls.update.call_args.kwargs["notification_mode"],"edge")
            self.assertTrue(cv.controls.update.call_args.kwargs["notification_warning"])
            notice.set_mode.assert_called_with("edge")

    def test_real_c_alert_uses_each_saved_mode_while_hidden(self):
        for mode in settings.MODES:
            with self.subTest(mode=mode), fixtures.temporary_directory() as temp:
                _,notice,_=fixtures.MeasurementLogTests().run_synthetic_app(Path(temp),
                    background=True,notification_start=mode)
                notice.set_mode.assert_called_once_with(mode)
                notice.show.assert_called_once_with()
                path,=Path(temp).glob("*.csv")
                with path.open(encoding="utf-8-sig",newline="") as stream: rows=list(csv.DictReader(stream))
                alerts=[row for row in rows if row["alert"]=="1"]
                self.assertEqual([row["monotonic_ms"] for row in alerts],["61000"])
                self.assertEqual(alerts[0]["notification_mode"],mode)

    def test_manual_preview_does_not_change_c_time_count_or_cooldown(self):
        results=[]
        for manual in (False,True):
            with fixtures.temporary_directory() as temp:
                actions=[[] for _ in range(80)]
                if manual: actions[20]=["notification_test"]
                _,notice,_=fixtures.MeasurementLogTests().run_synthetic_app(Path(temp),background=True,
                    desktop_actions=actions)
                path,=Path(temp).glob("*.csv")
                with path.open(encoding="utf-8-sig",newline="") as stream: rows=list(csv.DictReader(stream))
                results.append([(row["active_ms"],row["count_60s"],row["alert"]) for row in rows])
                self.assertEqual(notice.show.call_count,2 if manual else 1)
        self.assertEqual(results[0],results[1])


if __name__ == "__main__":
    unittest.main()
