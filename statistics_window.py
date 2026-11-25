"""오늘 요약과 날짜별 분당 깜빡임을 보여준다."""

from datetime import date
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from daily_log import BIN_MINUTES, csv_path, daily_statistics, export_daily_csv, recorded_dates
from ui_design import (DASHBOARD_ACCENT as ACCENT, DASHBOARD_BACKGROUND as BACKGROUND,
                       DASHBOARD_BORDER as BORDER, DASHBOARD_FOREGROUND as FOREGROUND,
                       DASHBOARD_MUTED as MUTED, DASHBOARD_SURFACE as SURFACE, FONT_FAMILY)


class StatisticsPanel(tk.Frame):
    def __init__(self, parent, directory):
        super().__init__(parent, bg=BACKGROUND)
        self.directory = directory
        self.window = parent

        tk.Label(self, text="일일 깜빡임 통계", bg=BACKGROUND, fg=FOREGROUND,
                 font=(FONT_FAMILY, 16, "bold"), anchor="w").pack(fill="x")
        summary = tk.Frame(self, bg=BACKGROUND)
        summary.pack(fill="x", pady=(16, 0))
        self.summary_heading = tk.Label(summary, bg=BACKGROUND, fg=FOREGROUND,
                                        font=(FONT_FAMILY, 11, "bold"), anchor="w")
        self.summary_heading.pack(fill="x")
        self.summary_metrics = tk.Frame(summary, bg=BACKGROUND)
        self.summary_empty = tk.Label(summary, bg=BACKGROUND, fg=MUTED, font=(FONT_FAMILY, 10), anchor="w")
        self.summary_values = []
        for column, name in enumerate(("유효 측정 시간", "깜빡임 총횟수", "분당 깜빡임", "표시된 알림")):
            self.summary_metrics.columnconfigure(column, weight=1, uniform="metric")
            metric = tk.Frame(self.summary_metrics, bg=SURFACE, padx=7, pady=8)
            metric.grid(row=0, column=column, sticky="nsew", padx=(0, 5 if column < 3 else 0))
            tk.Label(metric, text=name, bg=SURFACE, fg=MUTED,
                     font=(FONT_FAMILY, 9)).pack()
            value = tk.Label(metric, bg=SURFACE, fg=ACCENT, font=(FONT_FAMILY, 12, "bold"))
            value.pack()
            self.summary_values.append(value)

        header = tk.Frame(self, bg=BACKGROUND)
        header.pack(fill="x", pady=(14, 9))
        tk.Label(header, text="날짜", bg=BACKGROUND, fg=FOREGROUND,
                 font=(FONT_FAMILY, 9)).pack(side="left")
        self.day = tk.StringVar()
        self.picker = ttk.Combobox(header, width=12, state="readonly", textvariable=self.day,
                                   font=(FONT_FAMILY, 9))
        self.picker.pack(side="left", padx=8)
        self.picker.bind("<<ComboboxSelected>>", self.refresh)
        self.export_button = tk.Button(header, text="CSV 내보내기", command=self.export_csv,
            font=(FONT_FAMILY, 9, "bold"), bg=ACCENT, fg=SURFACE, activebackground=FOREGROUND,
            activeforeground=SURFACE, disabledforeground=BORDER, relief="flat", bd=0,
            highlightthickness=1, highlightbackground=BACKGROUND, highlightcolor=ACCENT, padx=12, pady=4)
        self.export_button.pack(side="right")
        self.export_status = tk.Label(header, bg=BACKGROUND, fg=MUTED, font=(FONT_FAMILY, 9))
        self.export_status.pack(side="right", padx=8)

        self.chart = tk.Canvas(self, bg=SURFACE, highlightthickness=0, width=1, height=1)
        self.chart.pack(fill="both", expand=True)
        self.chart.bind("<Configure>", self.draw)
        self.chart.tag_bind("rate", "<Enter>", lambda _event: self.chart.configure(cursor="hand2"))
        self.chart.tag_bind("rate", "<Leave>", lambda _event: self.chart.configure(cursor=""))
        self.chart.bind("<Button-1>", self.select_rate)
        self.rates = []
        self.points = {}
        self.selected_index = None
        self.plotted_day = None
        self.message = ""
        self.today = None
        self.date_check = self.after(1000, self._check_date)
        self.bind("<Destroy>", self._cancel_date_check)

    def refresh(self, _event=None):
        if _event is not None:
            self.export_status.configure(text="")
        today = date.today()
        self.today = today
        self.rates = []
        self.message = "측정 기록 없음"
        self.export_button.configure(state="disabled", bg=MUTED)
        selected = today
        statistics = None
        try:
            days = sorted({today, *recorded_dates(self.directory)}, reverse=True)
            choices = [day.isoformat() for day in days]
            self.picker.configure(values=choices)
            if self.day.get() not in choices:
                self.day.set(today.isoformat())
            selected = date.fromisoformat(self.day.get())
            if csv_path(self.directory, selected).is_file():
                self.export_button.configure(state="normal", bg=ACCENT)
            statistics = daily_statistics(self.directory, selected)
            self.rates = statistics.rates
        except (OSError, ValueError, TypeError, OverflowError):
            self.message = "통계 기록을 읽지 못했습니다."
        if selected != today:
            try:
                statistics = daily_statistics(self.directory, today)
            except (OSError, ValueError, TypeError, OverflowError):
                statistics = None
        if selected != self.plotted_day:
            self.plotted_day = selected
            self.selected_index = None
        self._show_summary(today, statistics)
        self.draw()

    def _check_date(self):
        if self.window.state() != "withdrawn" and date.today() != self.today:
            self.refresh()
        self.date_check = self.after(1000, self._check_date)

    def _cancel_date_check(self, event):
        if event.widget == self:
            self.after_cancel(self.date_check)

    def _show_summary(self, today, statistics):
        self.summary_heading.configure(text=f"오늘 요약  {today:%Y-%m-%d}")
        if statistics is None or not statistics.valid_seconds:
            self.summary_metrics.pack_forget()
            message = "오늘 기록을 읽지 못했습니다." if statistics is None else "측정 기록 없음"
            self.summary_empty.configure(text=message)
            self.summary_empty.pack(fill="x", pady=(7, 0))
            return
        self.summary_empty.pack_forget()
        values = (f"{statistics.valid_seconds:,.3f}초", f"{statistics.blinks:,}회",
                  f"{statistics.blinks_per_minute:,.2f}회/분", f"{statistics.alerts:,}회")
        for label, value in zip(self.summary_values, values):
            label.configure(text=value)
        self.summary_metrics.pack(fill="x", pady=(7, 0))

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
        self.points.clear()
        width, height = chart.winfo_width(), chart.winfo_height()
        if width < 120 or height < 120:
            return
        font = (FONT_FAMILY, 9)
        left, top, right, bottom = 56, 34, width - 32, height - 50
        chart.create_text(left, 15, text="분당 깜빡임 (회/분)", anchor="w", fill=FOREGROUND,
                          font=(FONT_FAMILY, 10, "bold"))

        measured = [(index, rate) for index, rate in enumerate(self.rates) if rate is not None]
        step = max(1, math.ceil(max((rate for _, rate in measured), default=0) / 4))
        for tick in range(5):
            y = bottom - tick * (bottom - top) / 4
            chart.create_line(left, y, right, y, fill=BORDER)
            chart.create_text(left - 8, y, text=str(tick * step), anchor="e", fill=MUTED, font=font)
        if not measured:
            chart.create_text((left + right) / 2, (top + bottom) / 2,
                              text=self.message, fill=MUTED, font=(FONT_FAMILY, 11))
            return
        first = measured[0][0] * BIN_MINUTES // 60 * 60
        end = (measured[-1][0] * BIN_MINUTES // 60 + 1) * 60
        label_interval = next(interval for interval in (15, 30, 60, 120, 240, 360)
                              if (end - first) / interval <= 6)
        for minute in range(first, end + 1, label_interval):
            x = left + (minute - first) * (right - left) / (end - first)
            chart.create_line(x, bottom, x, bottom + 5, fill=BORDER)
            chart.create_text(x, bottom + 9, text=self.clock_label(minute), anchor="n", fill=MUTED, font=font)

        previous = None
        for index, rate in measured:
            minute = index * BIN_MINUTES
            x = left + (minute - first) * (right - left) / (end - first)
            y = bottom - rate * (bottom - top) / (4 * step)
            self.points[index] = (x, y)
            if previous == index - 1:
                chart.create_line(*self.points[previous], x, y, fill=ACCENT, width=2,
                                  tags=("rate", f"bin:{previous}", f"bin:{index}"))
            chart.create_oval(x - 2, y - 2, x + 2, y + 2, fill=ACCENT, outline="",
                              tags=("rate", f"bin:{index}"))
            previous = index
        self.draw_selection()

    @staticmethod
    def clock_label(minute):
        return f"{minute // 60:02}:{minute % 60:02}"

    def select_rate(self, event):
        chart = self.chart
        indices = set()
        for item in chart.find_overlapping(event.x - 5, event.y - 5, event.x + 5, event.y + 5):
            tags = chart.gettags(item)
            if "rate" in tags:
                indices.update(int(tag[4:]) for tag in tags if tag.startswith("bin:"))
        self.selected_index = min(
            indices, key=lambda i: (abs(event.x - self.points[i][0]),
                                    abs(event.y - self.points[i][1]), i), default=None)
        self.draw_selection()

    def draw_selection(self):
        chart = self.chart
        chart.delete("selection")
        index = self.selected_index
        if index not in self.points:
            return
        x, y = self.points[index]
        chart.create_oval(x - 5, y - 5, x + 5, y + 5, fill=ACCENT, outline=SURFACE,
                          width=2, tags="selection")
        start = index * BIN_MINUTES
        rate = f"{self.rates[index]:,.2f}".rstrip("0").rstrip(".")
        text = f"{self.clock_label(start)}–{self.clock_label(start + BIN_MINUTES)}  ·  {rate}회/분"
        label = chart.create_text(x, y - 13, text=text, anchor="s", fill=SURFACE,
                                  font=(FONT_FAMILY, 9, "bold"), tags="selection")
        left, top, right, _ = chart.bbox(label)
        shift = max(8 - left, min(0, chart.winfo_width() - 8 - right))
        chart.move(label, shift, 34 if top < 32 else 0)
        left, top, right, bottom = chart.bbox(label)
        box = chart.create_rectangle(left - 6, top - 3, right + 6, bottom + 3,
                                     fill=ACCENT, outline="", tags="selection")
        chart.tag_lower(box, label)
