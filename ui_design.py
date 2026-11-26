"""화면의 색상과 크기, 스위치와 알림 그림을 정한다."""

from PIL import Image, ImageDraw


BACKGROUND = "#ffffff"
FOREGROUND = "#202927"
MUTED = "#69736e"
BORDER = "#e5e9e6"
ACCENT = "#27714b"
ERROR_COLOR = "#a33030"
SWITCH_OFF = "#737d77"
TRANSPARENT = "#010203"
FONT_FAMILY = "Malgun Gothic"
PANEL_WIDTH = 360
CONTENT_PAD_X, CONTENT_PAD_Y = 28, 26
DESCRIPTION_WIDTH = 304
DASHBOARD_BACKGROUND = "#f2f0eb"
DASHBOARD_SURFACE = "#fffdfa"
DASHBOARD_METRIC = "#e9e7df"
DASHBOARD_FOREGROUND = "#1e3932"
DASHBOARD_MUTED = "#53665d"
DASHBOARD_BORDER = "#d9ded7"
DASHBOARD_ACCENT = "#006241"
SURFACE_SIZES = {"pill": (330, 78), "blink": (96, 60)}
DESCRIPTIONS = {
    "pill": "화면 오른쪽 위에 짧은 문장이 나타납니다.",
    "edge": "화면 가장자리에 옅은 빛이 천천히 나타납니다.",
    "blink": "화면 오른쪽 위에서 두 눈이 세 번 깜빡입니다.",
}


def dashboard_card(parent, *, color=DASHBOARD_SURFACE, radius=12, inset=12):
    import tkinter as tk

    scale = parent.winfo_fpixels("1i") / 96
    padding = round(inset * scale)
    frame = tk.Frame(parent, bg=parent.cget("bg"))
    backdrop = tk.Canvas(frame, bg=frame.cget("bg"), highlightthickness=0, bd=0)
    backdrop.place(relwidth=1, relheight=1)
    content = tk.Frame(frame, bg=color)
    content.pack(fill="both", expand=True, padx=padding, pady=padding)

    def draw(event):
        width, height = event.width, event.height
        r = min(round(radius * scale), width / 2, height / 2)
        backdrop.delete("all")
        backdrop.create_polygon(
            0, r, 0, 0, r, 0, width - r, 0, width, 0, width, r,
            width, height - r, width, height, width - r, height,
            r, height, 0, height, 0, height - r, smooth=True, fill=color)

    backdrop.bind("<Configure>", draw)
    return frame, content


def switch_image(px, enabled, *, accent=ACCENT):
    width, height = px(34), px(20)
    factor = 3
    image = Image.new("RGBA", (width * factor, height * factor), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, width * factor - 1, height * factor - 1),
        radius=height * factor // 2, fill=accent if enabled else SWITCH_OFF)
    margin = px(3) * factor
    diameter = height * factor - 2 * margin
    left = width * factor - margin - diameter if enabled else margin
    draw.ellipse((left, margin, left + diameter, margin + diameter), fill=BACKGROUND)
    return image.resize((width, height), Image.Resampling.LANCZOS)


def paint_popup(canvas, px, *, dark):
    canvas.delete("all")
    # 글자 가장자리가 번져 보이지 않도록 뒤 화면 밝기에 맞춘다.
    canvas.configure(bg=FOREGROUND if dark else BACKGROUND)
    canvas.create_text(px(8), px(13), text="눈 깜빡임 알림",
        font=(FONT_FAMILY, 9), fill="#a4d7b5" if dark else ACCENT, anchor="w")
    canvas.create_text(px(8), px(43), text="천천히 눈을 깜빡여 주세요",
        font=(FONT_FAMILY, 14, "bold"), fill=BACKGROUND if dark else FOREGROUND, anchor="w")


def draw_eye(canvas, px, opening):
    canvas.delete("eye")
    # 두 눈이 같은 시점에 감기도록 한 값을 함께 사용한다.
    y = px(30)
    half_width = px(18)
    half_height = px(19) * opening
    for center in (27, 69):
        x = px(center)
        if opening < .06:
            for color, width in ((BACKGROUND, 5), (FOREGROUND, 2.5)):
                canvas.create_line(x-half_width, y, x+half_width, y,
                    fill=color, width=px(width), capstyle="round", tags="eye")
            continue
        canvas.create_oval(x-half_width, y-half_height, x+half_width, y+half_height,
            fill=BACKGROUND, outline=FOREGROUND, width=px(2.5), tags="eye")
        if opening > .18:
            radius = min(px(10), half_height * .65)
            pupil_x, pupil_y = x + px(3), y - px(3) * opening
            canvas.create_oval(pupil_x-radius, pupil_y-radius, pupil_x+radius, pupil_y+radius,
                fill=FOREGROUND, outline="", tags="eye")
            if opening > .6:
                glint = px(2)
                gx, gy = pupil_x-px(3), pupil_y-px(3)
                canvas.create_oval(gx-glint, gy-glint, gx+glint, gy+glint,
                    fill=BACKGROUND, outline="", tags="eye")
