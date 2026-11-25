"""선택한 알림을 표시하고 시간이 지나면 숨긴다."""

import math
import time

from notification_settings import MODES
from notification_windows import WindowsOverlay
from ui_design import (ACCENT, BACKGROUND, FOREGROUND, TRANSPARENT, SURFACE_SIZES,
                       paint_popup, draw_eye)


DURATION_SECONDS = 3.5


def animation_values(mode, elapsed, duration=DURATION_SECONDS):
    progress = max(0., min(1., elapsed / duration))
    envelope = max(0., min(1., elapsed / .18, (duration - elapsed) / .25))
    alpha = .94 * envelope
    opening = 1.
    if mode == "edge":
        alpha = (.06 + .20 * (.5 - .5 * math.cos(2 * math.pi * elapsed / .95))) * envelope
    elif mode == "blink" and .35 <= elapsed < .35 + .95 * 3:
        phase = ((elapsed - .35) % .95) / .95
        if phase < .25:
            opening = abs(phase - .125) / .125
    return progress, alpha, opening


class NotificationManager:
    def __init__(self, *, clock=time.monotonic):
        self.root = None
        self.window = None
        self.mode = "pill"
        self.last_error = ""
        self.clock = clock
        self.started = None
        self.after_id = None
        self.surfaces = {}
        self.active_windows = []
        try:
            import tkinter as tk
            self.tk = tk
            self.root = tk.Tk()
            self.root.withdraw()
            self.scale = self.root.winfo_fpixels("1i") / 96
            self.backend = WindowsOverlay()
        except Exception as exc:
            self.last_error = "알림 창을 사용할 수 없습니다."
            print(f"알림 창 대신 콘솔에 표시합니다: {exc}")
            if self.root:
                self.root.destroy()
            self.root = None

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError("지원하지 않는 알림 방식입니다.")
        self.hide()
        self.mode = mode
        self.last_error = ""

    def _surface(self, width, height, color):
        window = self.tk.Toplevel(self.root)
        try:
            window.withdraw()
            window.overrideredirect(True)
            window.configure(bg=color)
            if color == TRANSPARENT:
                window.attributes("-transparentcolor", TRANSPARENT)
            window.attributes("-alpha", .001)
            window.attributes("-topmost", True)
            canvas = self.tk.Canvas(window, width=self.px(width), height=self.px(height),
                                    bg=color, highlightthickness=0, bd=0)
            canvas.pack(fill="both", expand=True)
            return window, canvas
        except BaseException:
            window.destroy()
            raise

    def px(self, value):
        return max(1, round(value * self.scale))

    def _get_surfaces(self):
        if self.mode not in self.surfaces:
            items = []
            # 만들다 실패한 창은 남기지 않는다.
            try:
                if self.mode == "edge":
                    for _ in range(4):
                        items.append(self._surface(1, 1, ACCENT))
                elif self.mode == "blink":
                    items.append(self._surface(*SURFACE_SIZES["blink"], TRANSPARENT))
                else:
                    items.append(self._surface(*SURFACE_SIZES["pill"], TRANSPARENT))
                    self._paint_popup(items[0][1], dark=False)
            except BaseException:
                for window, _ in items:
                    window.destroy()
                raise
            self.surfaces[self.mode] = items
        return self.surfaces[self.mode]

    def _paint_popup(self, canvas, *, dark):
        paint_popup(canvas, self.px, dark=dark)

    def _draw_eye(self, canvas, opening):
        draw_eye(canvas, self.px, opening)

    def show(self, *, preview=False):
        print(f"시험 알림: {MODES[self.mode]}" if preview else "최근 60초 깜빡임이 설정 기준보다 적습니다.")
        self.hide()
        self.last_error = ""
        if self.root is None:
            self.last_error = "알림 창을 사용할 수 없습니다."
            return False
        try:
            left, top, right, bottom = self.backend.bounds()
            items = self._get_surfaces()
            if self.mode == "edge":
                thickness = self.px(4)
                rectangles = [(left, top, right-left, thickness),
                    (left, bottom-thickness, right-left, thickness),
                    (left, top+thickness, thickness, max(1,bottom-top-2*thickness)),
                    (right-thickness, top+thickness, thickness, max(1,bottom-top-2*thickness))]
            else:
                width, height = SURFACE_SIZES[self.mode]
                width, height = self.px(width), self.px(height)
                rectangles = [(max(left, right-width-self.px(24)), top+self.px(28), width, height)]
            self.active_windows = [window for window, _ in items]
            self.window = self.active_windows[0]
            if self.mode == "pill":
                dark = getattr(self.backend, "is_dark", lambda rect: False)(rectangles[0])
                self._paint_popup(items[0][1], dark=dark)
                key = FOREGROUND if dark else BACKGROUND
                self.window.configure(bg=key)
                self.window.attributes("-transparentcolor", key)
            for (window, _), rectangle in zip(items, rectangles):
                self.backend.show(window, rectangle)
            self.started = self.clock()
            self._tick()
            return self.started is not None
        except Exception as exc:
            self._failed(exc)
            return False

    def _failed(self, exc):
        self.hide()
        self.last_error = "알림 표시 실패 · 콘솔 기록을 확인하세요."
        print(f"알림 표시 오류: {exc}")

    def _tick(self):
        self.after_id = None
        if self.started is None:
            return
        try:
            elapsed = self.clock() - self.started
            if elapsed >= DURATION_SECONDS:
                self.hide()
                return
            _, alpha, opening = animation_values(self.mode, elapsed)
            for window, canvas in self.surfaces[self.mode]:
                window.attributes("-alpha", max(.001, alpha))
                if self.mode == "blink":
                    self._draw_eye(canvas, opening)
            self.after_id = self.root.after(33, self._tick)
        except Exception as exc:
            self._failed(exc)

    def update(self):
        if self.root:
            self.root.update()

    def hide(self):
        if self.after_id is not None and self.root is not None:
            self.root.after_cancel(self.after_id)
        self.after_id = None
        self.started = None
        for window in self.active_windows:
            window.withdraw()
        self.active_windows = []

    def close(self):
        self.hide()
        if self.root:
            self.root.destroy()
            self.root = None
        self.surfaces.clear()
