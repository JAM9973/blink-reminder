"""측정 상태와 설정 버튼을 보여 주는 기본 창이다."""

import tkinter as tk
from PIL import ImageTk
from notification_settings import MODES, MUTE_OPTIONS
from ui_design import (DASHBOARD_BACKGROUND as BACKGROUND, DASHBOARD_FOREGROUND as FOREGROUND,
                       DASHBOARD_MUTED as MUTED, DASHBOARD_BORDER as BORDER,
                       DASHBOARD_ACCENT as ACCENT, DASHBOARD_METRIC, ERROR_COLOR,
                       FONT_FAMILY, CONTENT_PAD_X, CONTENT_PAD_Y,
                       DESCRIPTION_WIDTH, DESCRIPTIONS, switch_image)


class CompactPanel(tk.Frame):
    def __init__(self, window, emit):
        super().__init__(window, bg=BACKGROUND)
        self.emit = emit
        self.scale = window.winfo_fpixels("1i") / 96
        self.power = tk.BooleanVar(value=True)
        self.preview = tk.BooleanVar(value=False)
        self.points = tk.BooleanVar(value=True)
        self._images = []
        self._points_shown = False
        self._notification_warning = ""
        self.content = tk.Frame(self, bg=BACKGROUND)
        self.content.pack(fill="both", expand=True, padx=self.px(CONTENT_PAD_X), pady=self.px(CONTENT_PAD_Y))
        self.content.columnconfigure(0, weight=1)
        self.content.columnconfigure(0, minsize=self.px(254))

        header = self.row(0)
        self.label(header, "측정", 13, weight="bold").pack(side="left")
        self.power_label, self.power_switch = self.switch(
            header, self.power, "측정", lambda: emit("pause_toggle"))

        reading = tk.Frame(self.content, bg=DASHBOARD_METRIC, pady=self.px(10))
        reading.grid(row=1, column=0, sticky="ew", pady=(self.px(16), self.px(12)))
        self.label(reading, "최근 60초 깜빡임", 10, MUTED).pack()
        number = tk.Frame(reading, bg=DASHBOARD_METRIC)
        number.pack()
        self.count_label = self.label(number, "—", 42, ACCENT, weight="bold")
        self.count_label.pack(side="left")
        self.label(number, "회", 12, MUTED).pack(side="left", anchor="s",
            padx=(self.px(7), 0), pady=(0, self.px(14)))
        self.status = self.label(reading, "측정 준비 중", 10, MUTED)
        self.status.pack()
        self.target_summary = self.label(reading, "", 9, MUTED)
        self.target_summary.pack(pady=(self.px(4), 0))

        actions = self.row(2)
        self.preview_button = self.text_button(actions, "카메라 미리보기",
            lambda: emit("preview_toggle"), size=10, color=ACCENT)
        self.preview_button.pack(side="left")
        self.settings_button = self.text_button(actions, "설정 ▾", self.toggle_settings, size=10, color=ACCENT)
        self.settings_button.pack(side="right")

        self.points_row = tk.Frame(self.content, bg=BACKGROUND)
        self.points_check = tk.Checkbutton(self.points_row, text="눈 좌표 표시",
            variable=self.points, command=lambda: emit("points"), font=(FONT_FAMILY, 10),
            bg=BACKGROUND, fg=MUTED, activebackground=BACKGROUND,
            selectcolor=BACKGROUND, relief="flat", bd=0, takefocus=True,
            highlightthickness=1, highlightbackground=BACKGROUND, highlightcolor=ACCENT)
        self.points_check.pack(side="left")

        self.settings = tk.Frame(self.content, bg=BACKGROUND)
        self.settings.columnconfigure(0, weight=1)
        target_row = self.row(0, parent=self.settings)
        self.label(target_row, "분당 알림 기준", 10).pack(side="left")
        stepper = tk.Frame(target_row, bg=BACKGROUND)
        stepper.pack(side="right")
        self.minus_button = self.step_button(stepper, "−", lambda: emit("target_down"))
        self.minus_button.pack(side="left")
        self.target_label = self.label(stepper, "12회", 11)
        self.target_label.configure(width=4, anchor="center")
        self.target_label.pack(side="left", padx=self.px(4))
        self.plus_button = self.step_button(stepper, "+", lambda: emit("target_up"))
        self.plus_button.pack(side="left")

        notification_row = self.row(1, parent=self.settings)
        notification_row.grid_configure(pady=(self.px(5), 0))
        self.label(notification_row, "알림 방식", 11).pack(side="left")
        self.notification_test = self.text_button(notification_row, "알림 확인",
            lambda: emit("notification_test"), size=9, color=ACCENT)
        self.notification_test.pack(side="right")

        choices = self.row(2, parent=self.settings)
        choices.grid_configure(pady=(self.px(4), 0))
        self.notification_value = tk.StringVar(value="pill")
        self.notification_buttons = {}
        self.notification_lines = {}
        for column, (mode, name) in enumerate(MODES.items()):
            choices.columnconfigure(column, weight=1, uniform="notification")
            button = tk.Radiobutton(choices, text=name, value=mode,
                variable=self.notification_value, indicatoron=False,
                command=self._notification_selected, font=(FONT_FAMILY, 10),
                bg=BACKGROUND, fg=MUTED, selectcolor=BACKGROUND,
                activebackground=BACKGROUND, activeforeground=ACCENT,
                relief="flat", offrelief="flat", overrelief="flat", bd=0,
                highlightthickness=1, highlightbackground=BACKGROUND,
                highlightcolor=ACCENT, pady=self.px(7), padx=0, takefocus=True,
                cursor="hand2")
            button.grid(row=0, column=column, sticky="ew")
            line = tk.Frame(choices, height=self.px(2), bg=BORDER)
            line.grid(row=1, column=column, sticky="ew")
            self.notification_buttons[mode] = button
            self.notification_lines[mode] = line
            for key, offset in (("<Left>", -1), ("<Right>", 1)):
                button.bind(key, lambda event, step=offset: self._move_choice(step))
        self.notification_description = self.label(self.settings, "", 9, MUTED)
        self.notification_description.configure(wraplength=self.px(DESCRIPTION_WIDTH), justify="left", height=2, anchor="nw")
        self.notification_description.grid(row=3, column=0, sticky="ew", pady=(self.px(6), 0))
        self._style_notification()

        mute_row = self.row(4, parent=self.settings)
        self.label(mute_row, "자동 알림", 10).pack(side="left")
        self.mute_value = tk.StringVar(value="켜짐  ▾")
        self.mute_button = tk.Menubutton(mute_row, textvariable=self.mute_value,
            font=(FONT_FAMILY, 10), bg=BACKGROUND, fg=ACCENT,
            activebackground=BACKGROUND, activeforeground=ACCENT, takefocus=True)
        self.mute_button.pack(side="right")
        self.mute_menu = tk.Menu(self.mute_button, tearoff=False)
        self.mute_button.configure(menu=self.mute_menu)
        for key, label in MUTE_OPTIONS.items():
            self.mute_menu.add_command(label=label, command=lambda value=key: emit("mute:" + value))

        self.notification_hint = self.label(self.content, "", 9, ERROR_COLOR)
        self.notification_hint.configure(wraplength=self.px(DESCRIPTION_WIDTH), justify="left")

    def toggle_settings(self):
        if self.settings.winfo_manager():
            self.settings.grid_remove()
            self.settings_button.configure(text="설정 ▾")
        else:
            self.settings.grid(row=5, column=0, sticky="ew", pady=(self.px(12), 0))
            self.settings_button.configure(text="설정 ▴")

    def _style_notification(self):
        selected = self.notification_value.get()
        for mode, button in self.notification_buttons.items():
            button.configure(fg=ACCENT if mode == selected else MUTED,
                font=(FONT_FAMILY, 10, "bold" if mode == selected else "normal"))
            self.notification_lines[mode].configure(bg=ACCENT if mode == selected else BORDER)
        self.notification_description.configure(text=DESCRIPTIONS[selected])

    def _notification_selected(self):
        self._style_notification()
        self.emit("notification:" + self.notification_value.get())

    def _move_choice(self, step):
        modes = tuple(MODES)
        selected = modes[(modes.index(self.notification_value.get()) + step) % len(modes)]
        self.notification_buttons[selected].focus_set()
        self.notification_buttons[selected].invoke()
        return "break"

    def px(self, value):
        return max(1, round(value * self.scale))

    def label(self, parent, text, size, color=FOREGROUND, *, weight="normal"):
        return tk.Label(parent, text=text, font=(FONT_FAMILY, size, weight),
                        bg=parent.cget("bg"), fg=color, padx=0, pady=0, anchor="w")

    def row(self, index, *, parent=None):
        frame = tk.Frame(self.content if parent is None else parent, bg=BACKGROUND)
        frame.grid(row=index, column=0, sticky="ew")
        return frame

    def switch_image(self, enabled):
        photo = ImageTk.PhotoImage(switch_image(self.px, enabled, accent=ACCENT), master=self)
        self._images.append(photo)
        return photo

    def switch(self, parent, variable, name, command):
        group = tk.Frame(parent, bg=BACKGROUND)
        group.pack(side="right")
        label = self.label(group, "켜짐" if variable.get() else "꺼짐", 9, MUTED)
        label.pack(side="left", padx=(0, self.px(9)))
        switch = tk.Checkbutton(group, name=name.replace(" ", "_"), variable=variable,
            image=self.switch_image(False), selectimage=self.switch_image(True),
            indicatoron=False, command=command, bd=0, relief="flat",
            offrelief="flat", overrelief="flat", bg=BACKGROUND,
            activebackground=BACKGROUND, selectcolor=BACKGROUND,
            highlightthickness=1, highlightbackground=BACKGROUND, highlightcolor=ACCENT,
            padx=0, pady=0, takefocus=True, cursor="hand2")
        switch.pack(side="left")
        return label, switch

    def text_button(self, parent, text, command, *, size=11, color=FOREGROUND):
        return tk.Button(parent, text=text, command=command, font=(FONT_FAMILY, size),
            fg=color, bg=BACKGROUND, activebackground=BACKGROUND, activeforeground=ACCENT,
            relief="flat", bd=0, padx=self.px(2), pady=self.px(3), takefocus=True,
            highlightthickness=1, highlightbackground=BACKGROUND,
            highlightcolor=ACCENT, cursor="hand2")

    def step_button(self, parent, text, command):
        button = self.text_button(parent, text, command, size=14, color=MUTED)
        button.configure(width=2)
        return button

    def update_values(self, *, paused, result, target, preview_enabled, landmarks_visible,
                      notification_mode="pill", notification_warning="", mute_status="켜짐", face_detected=False):
        self.power.set(not paused)
        self.power_label.configure(text="꺼짐" if paused else "켜짐")
        self.count_label.configure(text=str(result.count_60s) if result is not None else "—")
        if paused:
            status, color = "일시정지 · 카메라 꺼짐", MUTED
        elif result is None:
            status, color = "측정 준비 중", MUTED
        elif not result.face_visible:
            status = "눈 확인 안 됨 · 측정 대기" if face_detected else "얼굴 인식 안 됨"
            color = MUTED
        elif result.state == 0:
            status, color = "눈 상태 확인 중", MUTED
        else:
            status, color = "측정 중", ACCENT
        self.status.configure(text=status, fg=color)
        self.target_summary.configure(text=f"알림 기준 {target}회/분")
        self.target_label.configure(text=f"{target}회")
        self.minus_button.configure(state="disabled" if target <= 0 else "normal")
        if self.preview.get() != preview_enabled:
            self.preview.set(preview_enabled)
            self.preview_button.configure(text="미리보기 닫기" if preview_enabled else "카메라 미리보기")
        self.points.set(landmarks_visible)
        if self.notification_value.get() != notification_mode:
            self.notification_value.set(notification_mode)
            self._style_notification()
        mute_text = f"{mute_status}  ▾"
        if self.mute_value.get() != mute_text:
            self.mute_value.set(mute_text)
        if notification_warning != self._notification_warning:
            self._notification_warning = notification_warning
            self.notification_hint.configure(text=notification_warning)
            if notification_warning:
                self.notification_hint.grid(row=4, column=0, sticky="ew", pady=(self.px(8), 0))
            else:
                self.notification_hint.grid_remove()
        if preview_enabled != self._points_shown:
            self._points_shown = preview_enabled
            if preview_enabled:
                self.points_row.grid(row=3, column=0, sticky="ew", pady=(self.px(6), 0))
            else:
                self.points_row.grid_remove()
