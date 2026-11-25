"""날짜별 분당 깜빡임을 5분 간격으로 보여준다."""

from datetime import date
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from daily_log import BIN_MINUTES, csv_path, daily_rates, export_daily_csv, recorded_dates
from ui_design import ACCENT, BACKGROUND, BORDER, FONT_FAMILY, FOREGROUND, MUTED


class StatisticsWindow:
    def __init__(self, parent, directory):
        self.directory = directory
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title("일일 깜빡임 통계")
        self.window.configure(bg=BACKGROUND)
        self.window.minsize(540, 340)
        self.window.geometry("720x400")
        self.window.protocol("WM_DELETE_WINDOW", self.window.withdraw)

        header = ttk.Frame(self.window)
        header.pack(fill="x", padx=18, pady=(14, 6))
        ttk.Label(header, text="날짜").pack(side="left")
        self.day = tk.StringVar()
        self.picker = ttk.Combobox(header, width=14, state="readonly", textvariable=self.day)
        self.picker.pack(side="left", padx=8)
        self.picker.bind("<<ComboboxSelected>>", self.refresh)
        self.export_button = ttk.Button(header, text="CSV 내보내기", command=self.export_csv)
        self.export_button.pack(side="right")
        self.export_status = ttk.Label(header)
        self.export_status.pack(side="right", padx=8)

        self.chart = tk.Canvas(self.window, bg=BACKGROUND, highlightthickness=0)
        self.chart.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.chart.bind("<Configure>", self.draw)
        self.rates = []
        self.message = ""

    def show(self):
        self.export_status.configure(text="")
        self.refresh()
        self.window.deiconify()
        self.window.lift()

    def refresh(self, _event=None):
        if _event is not None:
            self.export_status.configure(text="")
        today = date.today()
        self.rates = []
        self.message = "측정 기록 없음"
        self.export_button.state(["disabled"])
        try:
            days = sorted({today, *recorded_dates(self.directory)}, reverse=True)
            choices = [day.isoformat() for day in days]
            self.picker.configure(values=choices)
            if self.day.get() not in choices:
                self.day.set(today.isoformat())
            selected = date.fromisoformat(self.day.get())
            if csv_path(self.directory, selected).is_file():
                self.export_button.state(["!disabled"])
            self.rates = daily_rates(self.directory, selected)
        except (OSError, ValueError, TypeError, OverflowError):
            self.message = "통계 기록을 읽지 못했습니다."
        self.draw()

    def export_csv(self):
        selected = date.fromisoformat(self.day.get())
        path = filedialog.asksaveasfilename(parent=self.window, title="선택 날짜 CSV 내보내기",
            initialfile=csv_path(self.directory, selected).name, defaultextension=".csv",
            filetypes=[("CSV 파일", "*.csv")])
        if not path:
            return
        try:
            export_daily_csv(self.directory, selected, Path(path))
        except ValueError as exc:
            messagebox.showerror("CSV 내보내기", str(exc), parent=self.window)
        except OSError as exc:
            print(f"CSV 내보내기 오류: {exc}")
            messagebox.showerror("CSV 내보내기", "파일을 저장하지 못했습니다. 경로와 권한을 확인하세요.",
                                 parent=self.window)
        else:
            self.export_status.configure(text="저장 완료")

    def draw(self, _event=None):
        chart = self.chart
        chart.delete("all")
        width, height = chart.winfo_width(), chart.winfo_height()
        if width < 100 or height < 100:
            return
        font = (FONT_FAMILY, 9)
        left, top, right, bottom = 56, 34, width - 32, height - 50
        chart.create_text(left, 14, text="분당 깜빡임 (회/분)", anchor="w", fill=FOREGROUND, font=font)
        chart.create_text((left + right) / 2, height - 12, text="시각", fill=FOREGROUND, font=font)

        values = [value for value in self.rates if value is not None]
        step = max(1, math.ceil(max(values, default=0) / 4))
        for tick in range(5):
            y = bottom - tick * (bottom - top) / 4
            chart.create_line(left, y, right, y, fill=BORDER)
            chart.create_text(left - 8, y, text=str(tick * step), anchor="e", fill=MUTED, font=font)
        for hour in range(0, 25, 4):
            x = left + hour * (right - left) / 24
            chart.create_line(x, bottom, x, bottom + 5, fill=BORDER)
            chart.create_text(x, bottom + 9, text=f"{hour:02}:00", anchor="n", fill=MUTED, font=font)

        if not values:
            chart.create_text((left + right) / 2, (top + bottom) / 2,
                              text=self.message, fill=MUTED, font=(FONT_FAMILY, 11))
            return
        previous = None
        for index, rate in enumerate(self.rates):
            if rate is None:
                previous = None
                continue
            x = left + index * BIN_MINUTES * (right - left) / (24 * 60)
            y = bottom - rate * (bottom - top) / (4 * step)
            if previous is not None:
                chart.create_line(*previous, x, y, fill=ACCENT, width=2, tags="rate")
            chart.create_oval(x - 2, y - 2, x + 2, y + 2, fill=ACCENT, outline="", tags="rate")
            previous = (x, y)
