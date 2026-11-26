"""선택한 날짜의 요약과 분당 깜빡임을 보여준다."""

from datetime import date
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from daily_log import BIN_MINUTES, csv_path, daily_statistics, export_daily_csv, recorded_dates
from ui_design import (DASHBOARD_ACCENT as ACCENT, DASHBOARD_BACKGROUND as BACKGROUND,
                       DASHBOARD_BORDER as BORDER, DASHBOARD_FOREGROUND as FOREGROUND,
                       DASHBOARD_MUTED as MUTED, DASHBOARD_SURFACE as SURFACE,
                       DASHBOARD_METRIC, FONT_FAMILY, dashboard_card)


class DailySummary(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BACKGROUND)
        card, content = dashboard_card(self, inset=12)
        card.pack(fill="both", expand=True)
        header = tk.Frame(content, bg=SURFACE)
        header.pack(fill="x", pady=(0, 8))
        tk.Label(header, text="날짜별 요약", bg=SURFACE, fg=FOREGROUND,
                 font=(FONT_FAMILY, 12, "bold")).pack(side="left")
        self.day = tk.StringVar(master=self)
        self.date_picker = ttk.Combobox(header, width=11, state="readonly", textvariable=self.day,
                                        font=(FONT_FAMILY, 8))
        self.date_picker.pack(side="right")
        self.values = []
        metrics = tk.Frame(content, bg=SURFACE)
        metrics.pack(fill="x")
        for column in range(2):
            metrics.columnconfigure(column, weight=1, uniform="metric")
        for index, name in enumerate(("측정 시간", "깜빡임 총횟수", "분당 깜빡임", "표시된 알림")):
            row, column = divmod(index, 2)
            tile, metric = dashboard_card(metrics, color=DASHBOARD_METRIC, radius=8, inset=6)
            tile.grid(row=row, column=column, sticky="nsew",
                      padx=(0, 6 if column == 0 else 0), pady=(0, 6 if row == 0 else 0))
            tk.Label(metric, text=name, bg=DASHBOARD_METRIC, fg=MUTED,
                     font=(FONT_FAMILY, 8)).pack()
            value = tk.Label(metric, text="—", bg=DASHBOARD_METRIC, fg=ACCENT,
                             font=(FONT_FAMILY, 11, "bold"))
            value.pack()
            self.values.append(value)
        self.message = tk.Label(content, bg=SURFACE, fg=MUTED, font=(FONT_FAMILY, 8), anchor="w")

    def show(self, statistics):
        if statistics is None or not statistics.valid_seconds:
            values = ("—",) * len(self.values)
            message = "통계 기록을 읽지 못했습니다." if statistics is None else "측정 기록 없음"
            self.message.configure(text=message)
            self.message.pack(fill="x", pady=(4, 0))
        else:
            self.message.pack_forget()
            values = (f"{int(statistics.valid_seconds):,}초", f"{statistics.blinks:,}회",
                      f"{statistics.blinks_per_minute:,.2f}회/분", f"{statistics.alerts:,}회")
        for label, value in zip(self.values, values):
            label.configure(text=value)


class StatisticsPanel(tk.Frame):
    def __init__(self, parent, directory, summary):
        super().__init__(parent, bg=BACKGROUND)
        self.directory = directory
        self.summary = summary
        self.window = self.winfo_toplevel()
        card, content = dashboard_card(self, inset=16)
        card.pack(fill="both", expand=True)

        tk.Label(content, text="일일 통계", bg=SURFACE, fg=FOREGROUND,
                 font=(FONT_FAMILY, 15, "bold"), anchor="w").pack(fill="x")
        header = tk.Frame(content, bg=SURFACE)
        header.pack(fill="x", pady=(12, 8))
        tk.Label(header, text="날짜", bg=SURFACE, fg=FOREGROUND,
                 font=(FONT_FAMILY, 9)).pack(side="left")
        self.day = summary.day
        self.picker = ttk.Combobox(header, width=12, state="readonly", textvariable=self.day,
                                   font=(FONT_FAMILY, 9))
        self.picker.pack(side="left", padx=8)
        self.picker.bind("<<ComboboxSelected>>", self.refresh)
        summary.date_picker.bind("<<ComboboxSelected>>", self.refresh)
        self.export_button = tk.Button(header, text="CSV 내보내기", command=self.export_csv,
            font=(FONT_FAMILY, 9, "bold"), bg=ACCENT, fg=SURFACE, activebackground=FOREGROUND,
            activeforeground=SURFACE, disabledforeground=BORDER, relief="flat", bd=0,
            highlightthickness=1, highlightbackground=SURFACE, highlightcolor=ACCENT, padx=12, pady=4)
        self.export_button.pack(side="right")
        self.export_status = tk.Label(header, bg=SURFACE, fg=MUTED, font=(FONT_FAMILY, 9))
        self.export_status.pack(side="right", padx=8)

        self.chart = tk.Canvas(content, bg=SURFACE, highlightthickness=0, width=1, height=1)
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
        following_today = self.today is not None and self.day.get() == self.today.isoformat()
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
            self.summary.date_picker.configure(values=choices)
            if following_today or self.day.get() not in choices:
                self.day.set(today.isoformat())
            selected = date.fromisoformat(self.day.get())
            if csv_path(self.directory, selected).is_file():
                self.export_button.configure(state="normal", bg=ACCENT)
            statistics = daily_statistics(self.directory, selected)
            self.rates = statistics.rates
        except (OSError, ValueError, TypeError, OverflowError):
            self.message = "통계 기록을 읽지 못했습니다."
        if selected != self.plotted_day:
            self.plotted_day = selected
            self.selected_index = None
        self.summary.show(statistics)
        self.draw()

    def _check_date(self):
        if self.window.state() != "withdrawn" and date.today() != self.today:
            self.refresh()
        self.date_check = self.after(1000, self._check_date)

    def _cancel_date_check(self, event):
        if event.widget == self:
            self.after_cancel(self.date_check)

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
        left, top, right, bottom = 42, 36, width - 28, height - 32
        chart.create_text(1, 14, text="분당 깜빡임 (회/분)", anchor="w", fill=FOREGROUND,
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
