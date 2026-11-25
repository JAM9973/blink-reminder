"""알림이 클릭과 키보드 포커스를 가로채지 않도록 Windows 창을 설정한다."""

import ctypes
from ctypes import wintypes
import sys


WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_LAYERED = 0x80000
WS_EX_NOACTIVATE = 0x08000000
OVERLAY_STYLES = WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE


class MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class WindowsOverlay:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("클릭 관통 알림은 Windows에서 지원합니다.")
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.api.GetAncestor.restype = wintypes.HWND
        self.api.GetForegroundWindow.argtypes = []
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.api.MonitorFromWindow.restype = wintypes.HANDLE
        self.api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        self.api.GetMonitorInfoW.restype = wintypes.BOOL
        pointer_sized = ctypes.c_ssize_t
        self.get_style = getattr(self.api, "GetWindowLongPtrW", self.api.GetWindowLongW)
        self.get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        self.get_style.restype = pointer_sized
        self.set_style = getattr(self.api, "SetWindowLongPtrW", self.api.SetWindowLongW)
        self.set_style.argtypes = [wintypes.HWND, ctypes.c_int, pointer_sized]
        self.set_style.restype = pointer_sized
        self.api.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.api.SetWindowPos.restype = wintypes.BOOL
        self.api.GetDC.argtypes = [wintypes.HWND]
        self.api.GetDC.restype = wintypes.HDC
        self.api.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.api.ReleaseDC.restype = ctypes.c_int
        self.graphics = ctypes.WinDLL("gdi32", use_last_error=True)
        self.graphics.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.graphics.GetPixel.restype = wintypes.DWORD

    def handle(self, window):
        return self.api.GetAncestor(window.winfo_id(), 2) or window.winfo_id()

    def bounds(self):
        monitor = self.api.MonitorFromWindow(self.api.GetForegroundWindow(), 1)
        info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
        if not self.api.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return tuple(getattr(info.rcWork, name) for name in ("left", "top", "right", "bottom"))

    def prepare(self, window):
        window.update_idletasks()
        handle = self.handle(window)
        style = self.get_style(handle, -20)
        ctypes.set_last_error(0)
        previous = self.set_style(handle, -20, (style | OVERLAY_STYLES) & ~0x40000)
        if not previous and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def is_dark(self, rectangle):
        """글자 뒤의 점 여섯 개로 밝기를 확인한다. 이미지는 저장하지 않는다."""
        x, y, width, height = rectangle
        context = self.api.GetDC(None)
        if not context:
            return False
        luminance = []
        try:
            for fx in (.25, .5, .75):
                for fy in (.25, .6):
                    color = self.graphics.GetPixel(context, round(x+width*fx), round(y+height*fy))
                    if color != 0xffffffff:
                        red, green, blue = color & 255, (color >> 8) & 255, (color >> 16) & 255
                        luminance.append(.2126*red + .7152*green + .0722*blue)
        finally:
            self.api.ReleaseDC(None, context)
        return bool(luminance) and sum(luminance) / len(luminance) < 140

    def show(self, window, rectangle):
        x, y, width, height = rectangle
        window.geometry(f"{width}x{height}")
        handle = self.prepare(window)
        window.deiconify()
        # 창을 보여 주되 포커스는 바꾸지 않는다. 보조 화면의 음수 위치도 허용한다.
        if not self.api.SetWindowPos(handle, wintypes.HWND(-1), x, y, width, height, 0x40 | 0x10 | 0x20):
            raise ctypes.WinError(ctypes.get_last_error())
