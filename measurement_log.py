"""프레임 처리 시간과 측정값을 저장한다. 영상은 저장하지 않는다."""

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

from build import library_path


ROOT = Path(__file__).resolve().parent
DEFAULT_RECORD_DIR = ROOT / "data" / "records"


@dataclass(frozen=True)
class FrameTiming:
    elapsed_ms: float
    interval_ms: float | None
    fps: float | None


class FrameRate:
    """최근 약 1초 동안 실제 처리한 프레임으로 FPS를 계산한다."""

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
        # 프레임이 느리게 들어오거나 끊긴 시간도 계산에 포함한다.
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
        "engine_mode", "blink_reason", "event_active_ms",
        "preview_visible",
        "notification_mode",
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
                       "blink_engine.c", "blink_engine.h", "build.py", "desktop_controls.py", "compact_panel.py",
                       "notifications.py", "notification_windows.py", "notification_settings.py",
                       "input_tracking.py", "preview_window.py", "app_runtime.py", "ui_design.py")
            library = library_path()
            metadata = dict(
                schema_version=4, input_kind=input_kind, started_at=started.isoformat(),
                initial_settings=self.settings, clock="active_ms excludes missing/invalid observations",
                fps_definition="delivered frame rate over approximately the last second; first frame unavailable",
                eye_states={"0": "UNKNOWN", "1": "OPEN", "2": "CLOSED"},
                blink_reasons={"none": "no event", "normal_reopen": "confirmed complete reopening",
                               "relative_reclosure": "relative rise then second closure"},
                event_time_definition="event_active_ms is the decision-frame active_ms, never backdated",
                control_events=self.path.with_suffix(".events.jsonl").name,
                pause_definition="no camera frames or active time while paused; history retained",
                notification_test_definition="control event only; manual tests do not set CSV alert or change C cooldown",
                library_name=library.name,
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
              left, right, result, target, landmarks_visible, preview_visible=True, notification_mode="pill"):
        self.frames += 1
        row = dict(
            local_time=local_time, frame_index=self.frames, monotonic_ms=timestamp_ms,
            elapsed_ms=round(timing.elapsed_ms, 3), active_ms=result.active_ms,
            frame_interval_ms=(round(timing.interval_ms, 3) if timing.interval_ms is not None else ""),
            fps=round(timing.fps, 3) if timing.fps is not None else "",
            face_detected=int(face_detected), measurement_valid=int(result.face_visible),
            # 얼굴이 없으면 비워 두고, 잘못된 EAR은 원인 확인을 위해 그대로 남긴다.
            left_ear=left if face_detected else "", right_ear=right if face_detected else "",
            eye_state=result.state, blink=result.blink, count_60s=result.count_60s,
            alert=result.alert, low_for_ms=result.low_for_ms, target=target,
            closed_ear=self.settings["closed_ear"], open_ear=self.settings["open_ear"],
            stable_frames=self.settings["stable_frames"], low_seconds=self.settings["low_seconds"],
            cooldown_seconds=self.settings["cooldown_seconds"],
            landmarks_visible=int(landmarks_visible),
            engine_mode=getattr(result, "engine_mode", self.settings.get("engine_mode", "baseline")),
            blink_reason=getattr(result, "blink_reason", "normal_reopen" if result.blink else "none"),
            event_active_ms=result.active_ms if result.blink else "",
            preview_visible=int(preview_visible), notification_mode=notification_mode)
        self.writer.writerow(row)
        now = time.monotonic()
        if now - self.last_flush >= 1:
            self.file.flush()
            self.last_flush = now

    def close(self):
        self.file.close()

    def write_control(self, action, *, timestamp_ms, active_ms, paused, preview_visible,
                      target=None, landmarks_visible=None, notification_mode=None):
        """버튼 조작은 영상 프레임과 구분해서 기록한다."""
        self.file.flush()
        event = dict(local_time=datetime.now().astimezone().isoformat(timespec="milliseconds"),
                     action=action, monotonic_ms=timestamp_ms if timestamp_ms >= 0 else None,
                     active_ms=active_ms, paused=bool(paused), preview_visible=bool(preview_visible))
        if target is not None:
            event["target"] = target
        if landmarks_visible is not None:
            event["landmarks_visible"] = bool(landmarks_visible)
        if notification_mode is not None:
            event["notification_mode"] = notification_mode
        with self.path.with_suffix(".events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
