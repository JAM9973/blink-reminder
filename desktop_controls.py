"""기본 창과 트레이에서 누른 버튼을 앱에 전달한다."""

import queue
import sys
import threading


class DesktopControls:
    def __init__(self, root, *, hidden=False):
        if sys.platform != "win32":
            raise RuntimeError("트레이 실행은 Windows에서 지원합니다.")
        if root is None:
            raise RuntimeError("제어 창을 만들지 못했습니다. Windows Tk 설치를 확인하세요.")
        try:
            import tkinter as tk
            import pystray
            from PIL import Image, ImageDraw
            from compact_panel import CompactPanel
        except ImportError as exc:
            raise RuntimeError("트레이 패키지가 없습니다. python -m pip install -r requirements.txt를 실행하세요.") from exc

        self.actions = queue.Queue()
        self.paused = False
        self.icon = None
        self.thread = None
        self.statistics = None
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.title("눈 깜빡임 알림")
        self.window.configure(bg="#ffffff")
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", lambda: self.actions.put("hide"))
        self.panel = CompactPanel(self.window, self.actions.put)
        self.panel.pack(fill="both", expand=True)
        self.panel.resize_window()

        picture = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(picture)
        draw.ellipse((3, 15, 61, 49), fill="#ffffff", outline="#265b84", width=5)
        draw.ellipse((24, 23, 40, 41), fill="#265b84")
        self.ready = threading.Event()
        self.error = None
        try:
            self.icon = pystray.Icon("blink-reminder", picture, "눈 깜빡임 알림 · 측정 중",
                menu=pystray.Menu(
                    pystray.MenuItem("창 다시 열기", lambda icon, item: self.actions.put("show"), default=True),
                    pystray.MenuItem(lambda item: "다시 시작" if self.paused else "일시정지",
                                     lambda icon, item: self.actions.put("pause_toggle")),
                    pystray.MenuItem("창 숨기기", lambda icon, item: self.actions.put("hide")),
                    pystray.MenuItem("프로그램 종료", lambda icon, item: self.actions.put("quit"))))
            self.thread = threading.Thread(target=self._run_tray, name="blink-tray", daemon=True)
            self.thread.start()
            if not self.ready.wait(3) or self.error:
                raise RuntimeError(f"트레이 아이콘을 시작하지 못했습니다: {self.error or '시간 초과'}")
            if not hidden:
                self.window.deiconify()
        except BaseException:
            self.close()
            raise

    def _run_tray(self):
        def setup(icon):
            try:
                icon.visible = True
            except Exception as exc:
                self.error = exc
            finally:
                self.ready.set()
        try:
            self.icon.run(setup=setup)
        except Exception as exc:
            self.error = exc
            self.ready.set()

    def poll(self):
        # 트레이가 없어졌을 때 숨겨진 앱만 계속 남지 않게 한다.
        if not self.thread.is_alive():
            raise RuntimeError("트레이가 종료되어 프로그램을 안전하게 종료합니다.")
        actions = []
        while True:
            try:
                actions.append(self.actions.get_nowait())
            except queue.Empty:
                return actions

    def set_visible(self, visible):
        if visible:
            self.window.deiconify()
            self.window.lift()
        else:
            self.window.withdraw()
            if self.statistics:
                self.statistics.window.withdraw()

    def open_statistics(self, directory):
        if self.statistics is None:
            from statistics_window import StatisticsWindow
            self.statistics = StatisticsWindow(self.window, directory)
        self.statistics.show()

    def refresh_statistics(self):
        if self.statistics and self.statistics.window.state() != "withdrawn":
            self.statistics.refresh()

    def update(self, *, paused, result, target, recording, mode,
               preview_enabled=False, landmarks_visible=True,
               notification_mode="pill", notification_warning="", mute_status="켜짐"):
        if self.paused != paused:
            self.paused = paused
            self.icon.title = "눈 깜빡임 알림 · " + ("일시정지" if paused else "측정 중")
            self.icon.update_menu()
        self.panel.update_values(paused=paused, result=result, target=target,
                                 preview_enabled=preview_enabled, landmarks_visible=landmarks_visible,
                                 notification_mode=notification_mode, notification_warning=notification_warning,
                                 mute_status=mute_status)
        suffix = " · 기록 오류" if recording == "오류" else ""
        self.window.title("눈 깜빡임 알림" + suffix)

    def close(self):
        try:
            if self.icon:
                self.icon.stop()
        finally:
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=2)
            self.window.destroy()
