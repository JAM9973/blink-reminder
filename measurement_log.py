"""Frame timing and numeric session records; camera images are never saved."""

from collections import deque
import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import sys
import time


ROOT = Path(__file__).resolve().parent
DEFAULT_RECORD_DIR = ROOT / "data" / "records"


@dataclass(frozen=True)
class FrameTiming:
    elapsed_ms: float
    interval_ms: float | None
    fps: float | None


class FrameRate:
    """Measure delivered frame intervals, averaging roughly the last second."""

    def __init__(self):
        self.samples = deque()
        self.started_ns = None

    def update(self, now_ns):
        if self.started_ns is None:
            self.started_ns = now_ns
        interval = None
        if self.samples:
            if now_ns <= self.samples[-1]:
                raise ValueError("프레임 시각은 증가해야 합니다.")
            interval = (now_ns - self.samples[-1]) / 1_000_000
        self.samples.append(now_ns)
        # Keep the sample immediately before the window to avoid a zero span
        # when delivery is slow. Long gaps are included, never hidden.
        while len(self.samples) > 2 and self.samples[1] <= now_ns - 1_000_000_000:
            self.samples.popleft()
        fps = None
        if len(self.samples) > 1:
            fps = (len(self.samples) - 1) * 1_000_000_000 / (now_ns - self.samples[0])
        return FrameTiming((now_ns - self.started_ns) / 1_000_000, interval, fps)


class SessionRecorder:
    COLUMNS = (
        "local_time", "frame_index", "monotonic_ms", "elapsed_ms", "active_ms",
        "frame_interval_ms", "fps", "face_detected", "measurement_valid",
        "left_ear", "right_ear", "eye_state", "blink", "count_60s", "alert",
        "low_for_ms", "target", "closed_ear", "open_ear", "stable_frames",
        "low_seconds", "cooldown_seconds", "landmarks_visible",
    )

    def __init__(self, directory, settings, *, input_kind="webcam"):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        started = datetime.now().astimezone()
        self.path = directory / f"blink_{started:%Y%m%d_%H%M%S_%f}.csv"
        self.settings = dict(settings)
        self.frames = 0
        self.file = self.path.open("x", newline="", encoding="utf-8-sig")
        try:
            self.writer = csv.DictWriter(self.file, fieldnames=self.COLUMNS)
            self.writer.writeheader()
            self.file.flush()
            sources = ("blink_app.py", "measurement_log.py", "engine.py",
                       "blink_engine.c", "blink_engine.h")
            library = ROOT / ("blink_engine.dll" if sys.platform == "win32" else
                              "libblink_engine.dylib" if sys.platform == "darwin" else
                              "libblink_engine.so")
            metadata = dict(
                schema_version=1, input_kind=input_kind, started_at=started.isoformat(),
                initial_settings=self.settings, clock="active_ms excludes missing/invalid observations",
                fps_definition="delivered frame rate over approximately the last second; first frame unavailable",
                eye_states={"0": "UNKNOWN", "1": "OPEN", "2": "CLOSED"},
                environment=dict(os=platform.platform(), python=sys.version,
                                 python_machine=platform.machine()),
                source_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                               for name in sources},
                library_sha256=(hashlib.sha256(library.read_bytes()).hexdigest()
                                if library.exists() else None))
            with self.path.with_suffix(".json").open("x", encoding="utf-8") as sidecar:
                json.dump(metadata, sidecar, ensure_ascii=False, indent=2)
        except BaseException:
            self.file.close()
            raise
        self.last_flush = time.monotonic()

    def write(self, *, local_time, timestamp_ms, timing, face_detected,
              left, right, result, target, landmarks_visible):
        self.frames += 1
        row = dict(
            local_time=local_time, frame_index=self.frames, monotonic_ms=timestamp_ms,
            elapsed_ms=round(timing.elapsed_ms, 3), active_ms=result.active_ms,
            frame_interval_ms=(round(timing.interval_ms, 3) if timing.interval_ms is not None else ""),
            fps=round(timing.fps, 3) if timing.fps is not None else "",
            face_detected=int(face_detected), measurement_valid=int(result.face_visible),
            # Preserve invalid numbers when a face was detected for diagnosis.
            # A missing face has no EAR measurement, represented by empty cells.
            left_ear=left if face_detected else "", right_ear=right if face_detected else "",
            eye_state=result.state, blink=result.blink, count_60s=result.count_60s,
            alert=result.alert, low_for_ms=result.low_for_ms, target=target,
            closed_ear=self.settings["closed_ear"], open_ear=self.settings["open_ear"],
            stable_frames=self.settings["stable_frames"], low_seconds=self.settings["low_seconds"],
            cooldown_seconds=self.settings["cooldown_seconds"],
            landmarks_visible=int(landmarks_visible))
        self.writer.writerow(row)
        now = time.monotonic()
        if now - self.last_flush >= 1:
            self.file.flush()
            self.last_flush = now

    def close(self):
        self.file.close()
