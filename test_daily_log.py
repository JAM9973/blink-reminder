"""날짜 경계와 C 판정에서 날짜별 CSV까지의 집계를 검증한다."""

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from daily_log import FIELDS, DailyRecorder, csv_path, daily_rates, daily_statistics, export_daily_csv, recorded_dates


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class DailyLogTests(unittest.TestCase):
    def setUp(self):
        self.cache = Path(__file__).resolve().parent / ".cache"
        self.cache.mkdir(exist_ok=True)

    def test_midnight_splits_duration_and_keeps_event_on_new_date(self):
        with TemporaryDirectory(dir=self.cache) as temp:
            directory = Path(temp)
            first_day = date(2026, 11, 24)
            next_day = first_day + timedelta(days=1)
            start = datetime(2026, 11, 24, 23, 59, 59, 750000).astimezone()
            recorder = DailyRecorder(directory)
            recorder.observe(start, 0, tracked=True)
            self.assertTrue(recorder.observe(start + timedelta(milliseconds=500), 500, tracked=True,
                                             blink=True, alert=True))
            self.assertTrue(recorder.close())
            old, = rows(csv_path(directory, first_day))
            new, = rows(csv_path(directory, next_day))
            self.assertEqual(old["end_time"], new["start_time"])
            self.assertEqual(old["valid_seconds"], "0.250")
            self.assertEqual(new["valid_seconds"], "0.250")
            self.assertEqual((old["blinks"], old["alerts"]), ("0", "0"))
            self.assertEqual((new["blinks"], new["alerts"]), ("1", "1"))
            self.assertEqual(old["session_id"], new["session_id"])
            self.assertFalse(recorder.close())
            self.assertEqual(recorded_dates(directory), [next_day, first_day])

    def test_sessions_append_and_rates_distinguish_zero_from_gap(self):
        with TemporaryDirectory(dir=self.cache) as temp:
            directory = Path(temp)
            start = datetime(2026, 11, 24, 8, 14, 59, 500000).astimezone()
            for blink in (False, True):
                recorder = DailyRecorder(directory)
                recorder.observe(start, 0, tracked=True)
                recorder.observe(start + timedelta(seconds=1), 1000, tracked=True, blink=blink)
                recorder.observe(start + timedelta(seconds=76), 0, tracked=False)
                recorder.close()
            csv_rows = rows(csv_path(directory, start.date()))
            self.assertEqual(len(csv_rows), 4)
            self.assertEqual(len({row["session_id"] for row in csv_rows}), 2)
            self.assertEqual(sum(float(row["valid_seconds"]) for row in csv_rows), 2)
            rates = daily_rates(directory, start.date())
            self.assertEqual(rates[8 * 12 + 1:8 * 12 + 5], [None, 0, 60, None])

    def test_app_writes_blinks_and_only_successful_alerts(self):
        import test_measurement_log as fixtures

        for shown in (True, False):
            with self.subTest(shown=shown), fixtures.temporary_directory() as temp:
                directory = Path(temp)
                fixtures.MeasurementLogTests().run_synthetic_app(directory, alert_shown=shown)
                trace, = directory.glob("*.csv")
                raw = rows(trace)
                saved = [row for path in (directory / "daily").glob("*.csv") for row in rows(path)]
                self.assertEqual(sum(int(row["blinks"]) for row in saved), 1)
                self.assertEqual(sum(int(row["alerts"]) for row in saved), int(shown))
                self.assertAlmostEqual(sum(float(row["valid_seconds"]) for row in saved),
                                       int(raw[-1]["active_ms"]) / 1000)

    def test_export_copies_selected_date_and_protects_recordings(self):
        with TemporaryDirectory(dir=self.cache) as temp:
            folder = Path(temp)
            directory = folder / "logs"
            start = datetime(2026, 11, 24, 12).astimezone()
            for at, blink in ((start, True), (start + timedelta(days=1), False)):
                recorder = DailyRecorder(directory)
                recorder.observe(at, 0, tracked=True, blink=blink)
                recorder.close()
            source = csv_path(directory, start.date())
            other = csv_path(directory, start.date() + timedelta(days=1))
            target = folder / "selected.csv"
            export_daily_csv(directory, start.date(), target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            for unsafe in (source, other, directory / ".daily.lock"):
                with self.assertRaises(ValueError):
                    export_daily_csv(directory, start.date(), unsafe)
            self.assertNotEqual(target.read_bytes(), other.read_bytes())

    def test_summary_uses_requested_date_and_weights_by_total_valid_time(self):
        with TemporaryDirectory(dir=self.cache) as temp:
            directory = Path(temp)
            today = date(2026, 11, 25)
            yesterday = today - timedelta(days=1)
            empty = daily_statistics(directory, today)
            self.assertEqual((empty.valid_seconds, empty.blinks, empty.alerts), (Decimal(0), 0, 0))
            self.assertIsNone(empty.blinks_per_minute)
            for day, samples in ((today, (("first", "08:00:00", 12, "30.001", 1),
                                          ("second", "08:05:00", 3, "59.999", 2))),
                                 (yesterday, (("earlier", "15:00:00", 80, "0.000", 13),))):
                with csv_path(directory, day).open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(FIELDS)
                    for session, start, blinks, duration, alerts in samples:
                        timestamp = f"{day}T{start}+09:00"
                        writer.writerow((session, timestamp, timestamp, blinks, duration, alerts))
            summary = daily_statistics(directory, today)
            self.assertEqual(summary.valid_seconds, Decimal("90.000"))
            self.assertEqual((summary.blinks, summary.blinks_per_minute, summary.alerts), (15, 10, 3))
            self.assertIsNone(daily_statistics(directory, yesterday).blinks_per_minute)

    def test_recorder_and_reader_agree_when_clocks_differ_by_one_millisecond(self):
        with TemporaryDirectory(dir=self.cache) as temp:
            directory = Path(temp)
            start = datetime(2026, 11, 25, 8).astimezone()
            recorder = DailyRecorder(directory)
            recorder.observe(start, 0, tracked=True)
            for second in range(1, 61):
                timestamp = start + timedelta(seconds=second, milliseconds=-1)
                recorder.observe(timestamp, 1000, tracked=True, blink=second <= 18, alert=second == 1)
            self.assertTrue(recorder.observe(start + timedelta(minutes=1), 1, tracked=True))
            recording, = rows(csv_path(directory, start.date()))
            self.assertEqual(recording["valid_seconds"], "60.001")
            self.assertEqual(daily_statistics(directory, start.date()).valid_seconds, Decimal("60.001"))

    def test_reader_rejects_invalid_durations_and_headers(self):
        with TemporaryDirectory(dir=self.cache) as temp:
            directory = Path(temp)
            day = date(2026, 11, 25)
            timestamp = f"{day}T08:00:00+09:00"
            for header, duration in ((FIELDS, "-0.001"), (FIELDS, "NaN"), (FIELDS, "Infinity"),
                                     (FIELDS, "bad"), (FIELDS, "1E+999999"), (FIELDS, "0.0001"),
                                     (("bad_column", *FIELDS[1:]), "60.001")):
                with self.subTest(header=header, duration=duration):
                    with csv_path(directory, day).open("w", encoding="utf-8", newline="") as stream:
                        writer = csv.writer(stream)
                        writer.writerow(header)
                        writer.writerow(("one", timestamp, timestamp, 0, duration, 0))
                    with self.assertRaises(ValueError):
                        daily_statistics(directory, day)

    @unittest.skipUnless(os.name == "nt", "Windows 통계 화면 검증")
    def test_windows_chart_and_summary_read_mixed_minute_durations(self):
        import tkinter as tk
        from unittest.mock import patch

        from compact_panel import CompactPanel
        from statistics_window import StatisticsPanel

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Windows 통계 창을 열 수 없습니다: {exc}")
        self.addCleanup(root.destroy)
        root.withdraw()
        with TemporaryDirectory(dir=self.cache) as temp:
            directory = Path(temp)
            day = date(2026, 11, 25)
            path = csv_path(directory, day)
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(FIELDS)
                writer.writerow(("one", f"{day}T08:00:00+09:00", f"{day}T08:01:00+09:00", 18, "60.001", 1))
                writer.writerow(("two", f"{day}T08:05:00+09:00", f"{day}T08:05:30+09:00", 4, "30.000", 2))
            original = path.read_bytes()
            with patch("statistics_window.date", wraps=date) as calendar:
                calendar.today.return_value = day
                root.geometry("1020x590")
                actions = []
                controls = CompactPanel(root, actions.append)
                controls.pack(side="left", fill="y")
                stats = StatisticsPanel(root, directory)
                stats.pack(side="left", fill="both", expand=True)
                stats.refresh()
                root.deiconify()
                root.update()
                self.assertIs(controls.winfo_toplevel(), stats.winfo_toplevel())
                self.assertEqual(stats.day.get(), day.isoformat())
                self.assertAlmostEqual(stats.rates[96], 18 * 60 / 60.001)
                self.assertEqual(stats.rates[97], 8)
                self.assertEqual([stats.chart.type(item) for item in stats.chart.find_withtag("rate")],
                                 ["oval", "line", "oval"])
                self.assertTrue(stats.summary_metrics.winfo_ismapped())
                self.assertEqual(tuple(label.cget("text") for label in stats.summary_values),
                                 ("90.001초", "22회", "14.67회/분", "3회"))
                self.assertFalse(controls.settings.winfo_ismapped())
                controls.settings_button.invoke()
                root.update_idletasks()
                self.assertTrue(controls.settings.winfo_ismapped())
                self.assertTrue(controls.notification_test.winfo_viewable())
                controls.plus_button.invoke()
                controls.notification_buttons["edge"].invoke()
                controls.notification_test.invoke()
                controls.mute_menu.invoke(0)
                self.assertEqual(actions[:3], ["target_up", "notification:edge", "notification_test"])
                self.assertTrue(actions[3].startswith("mute:"))
                start_x, start_y = stats.points[96]
                end_x, end_y = stats.points[97]
                stats.chart.event_generate("<Button-1>", x=round(start_x * .75 + end_x * .25),
                                           y=round(start_y * .75 + end_y * .25))
                self.assertEqual(stats.selected_index, 96)
                label, = [item for item in stats.chart.find_withtag("selection")
                          if stats.chart.type(item) == "text"]
                self.assertIn("08:00–08:05  ·  18회/분", stats.chart.itemcget(label, "text"))
                stats.refresh()
                self.assertEqual(stats.selected_index, 96)
                stats.chart.event_generate("<Button-1>", x=round(end_x + 25), y=round(end_y))
                self.assertIsNone(stats.selected_index)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
