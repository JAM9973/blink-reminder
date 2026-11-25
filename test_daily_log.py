"""날짜 경계와 C 판정에서 날짜별 CSV까지의 집계를 검증한다."""

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
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


if __name__ == "__main__":
    unittest.main()
