"""유효 측정 시간과 이벤트를 날짜별 CSV에 기록한다."""

from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from uuid import uuid4


DEFAULT_LOG_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "BlinkReminder" / "logs"
FIELDS = ("session_id", "start_time", "end_time", "blinks", "valid_seconds", "alerts")
MINUTE_MS = 60_000
MILLISECOND = Decimal("0.001")
MAX_VALID_SECONDS = ((1 << 63) - 1) * MILLISECOND  # C의 int64_t 누적 밀리초 상한
BIN_MINUTES = 5
BINS_PER_DAY = 24 * 60 // BIN_MINUTES


def csv_path(directory, day):
    return directory / f"blink_{day.isoformat()}.csv"


def recorded_dates(directory):
    days = []
    for path in directory.glob("blink_????-??-??.csv"):
        try:
            days.append(date.fromisoformat(path.stem.removeprefix("blink_")))
        except ValueError:
            continue
    return sorted(days, reverse=True)


@contextmanager
def log_lock(directory):
    # 동시에 열린 앱이 CSV 헤더나 행을 중복·교차해서 쓰지 않게 한다.
    with (directory / ".daily.lock").open("a+b") as lock:
        lock.seek(0)
        if os.name == "nt":
            from msvcrt import locking, LK_LOCK, LK_UNLCK
            locking(lock.fileno(), LK_LOCK, 1)
        else:
            from fcntl import flock, LOCK_EX, LOCK_UN
            flock(lock, LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                locking(lock.fileno(), LK_UNLCK, 1)
            else:
                flock(lock, LOCK_UN)


@dataclass(frozen=True)
class DailyStatistics:
    rates: list[float | None]
    valid_seconds: Decimal
    blinks: int
    alerts: int

    @property
    def blinks_per_minute(self):
        return self.blinks * 60 / self.valid_seconds if self.valid_seconds else None


def _daily_rows(directory, day):
    path = csv_path(directory, day)
    if not path.is_file():
        return
    with log_lock(directory), path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise ValueError("CSV 열 형식이 올바르지 않습니다.")
        for row in reader:
            start = datetime.fromisoformat(row["start_time"])
            blinks, alerts = int(row["blinks"]), int(row["alerts"])
            try:
                duration = Decimal(row["valid_seconds"])
            except InvalidOperation as exc:
                raise ValueError("CSV 측정 시간이 올바르지 않습니다.") from exc
            # 행은 PC 시계의 분 경계로 나누고, 유효 시간은 C의 단조 시계로 잰다.
            if (blinks < 0 or alerts < 0 or not duration.is_finite()
                    or not 0 <= duration <= MAX_VALID_SECONDS
                    or duration != duration.quantize(MILLISECOND)):
                raise ValueError("CSV 측정값이 올바르지 않습니다.")
            yield start, blinks, duration, alerts


def daily_statistics(directory, day):
    totals = [0] * BINS_PER_DAY
    seconds = [Decimal(0)] * BINS_PER_DAY
    alerts = 0
    for start, blinks, duration, displayed in _daily_rows(directory, day):
        index = (start.hour * 60 + start.minute) // BIN_MINUTES
        totals[index] += blinks
        seconds[index] += duration
        alerts += displayed
    rates = [float(count * 60 / duration) if duration else None for count, duration in zip(totals, seconds)]
    return DailyStatistics(rates, sum(seconds), sum(totals), alerts)


def daily_rates(directory, day):
    return daily_statistics(directory, day).rates


def export_daily_csv(directory, day, destination):
    source = csv_path(directory, day)
    log_directory = directory.resolve()
    target = destination.resolve()
    if target.parent == log_directory and (
            target.match("blink_????-??-??.csv") or target == log_directory / ".daily.lock"):
        raise ValueError("내보내기 파일은 앱이 기록하는 파일과 다른 이름 또는 폴더를 선택하세요.")
    temporary = None
    try:
        with log_lock(directory), source.open("rb") as stream, NamedTemporaryFile(
                dir=destination.parent, suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            copyfileobj(stream, output)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def local_time(epoch_ms):
    return datetime.fromtimestamp(epoch_ms / 1000).astimezone()


class DailyRecorder:
    def __init__(self, directory, *, checkpoint_ms=None):
        self.directory = directory
        self.checkpoint_ms = checkpoint_ms
        self.session_id = uuid4().hex
        self.previous_ms = None
        self.start_ms = None
        self.valid_ms = self.blinks = self.alerts = 0

    def observe(self, observed_at, valid_ms, *, tracked, blink=False, alert=False):
        now_ms = round(observed_at.timestamp() * 1000)
        previous = self.previous_ms
        self.previous_ms = now_ms
        saved = False
        if previous is not None and (now_ms < previous or
                                     (valid_ms and abs(now_ms - previous - valid_ms) > 1000)):
            # PC 시각이 바뀌어도 C가 확인한 유효 시간만 기록한다.
            saved = self._save(previous)
            previous = now_ms - valid_ms

        if valid_ms and previous is not None:
            boundary = (previous // MINUTE_MS + 1) * MINUTE_MS
            if self.start_ms is None:
                self.start_ms = previous
            if boundary <= now_ms:
                span = now_ms - previous
                before = round(valid_ms * (boundary - previous) / span)
                self.valid_ms += before
                saved = self._save(boundary) or saved
                valid_ms -= before
                self.start_ms = boundary if valid_ms else now_ms
            self.valid_ms += valid_ms
        elif self.start_ms is not None:
            boundary = (self.start_ms // MINUTE_MS + 1) * MINUTE_MS
            if boundary <= now_ms:
                saved = self._save(boundary) or saved

        if tracked and self.start_ms is None:
            self.start_ms = now_ms
        self.blinks += int(blink)
        self.alerts += int(alert)
        if (self.checkpoint_ms is not None and self.start_ms is not None
                and (self.valid_ms or self.blinks or self.alerts)
                and now_ms - self.start_ms >= self.checkpoint_ms):
            saved = self.flush() or saved
        return saved

    def _save(self, end_ms):
        if self.start_ms is None:
            return False
        start = local_time(self.start_ms)
        end = local_time(end_ms)
        path = csv_path(self.directory, start.date())
        self.directory.mkdir(parents=True, exist_ok=True)
        with log_lock(self.directory), path.open("a+", encoding="utf-8", newline="") as stream:
            stream.seek(0, os.SEEK_END)
            writer = csv.writer(stream)
            if not stream.tell():
                writer.writerow(FIELDS)
            writer.writerow((self.session_id, start.isoformat(timespec="milliseconds"),
                             end.isoformat(timespec="milliseconds"), self.blinks,
                             f"{self.valid_ms * MILLISECOND:.3f}", self.alerts))
        self.start_ms = None
        self.valid_ms = self.blinks = self.alerts = 0
        return True

    def flush(self):
        return self._save(self.previous_ms)

    def close(self):
        return self.flush()
