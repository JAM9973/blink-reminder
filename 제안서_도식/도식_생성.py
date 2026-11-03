"""제안서용 16:9 구조도·UI 설계안·개발 일정 도식을 PNG/SVG로 만든다."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Circle, Ellipse


OUT = Path(__file__).resolve().parent
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_BOLD = r"C:\Windows\Fonts\malgunbd.ttf"
REG = FontProperties(fname=FONT)
BOLD = FontProperties(fname=FONT_BOLD)

BG = "#F7FAFE"
INK = "#172339"
SUB = "#45546C"
BLUE = "#175CD3"
BLUE_LIGHT = "#EAF2FF"
LINE = "#CBD5E1"
WHITE = "#FFFFFF"
GREEN = "#0F766E"
GREEN_LIGHT = "#E8F7F4"


def base(title, subtitle, tag):
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.axis("off")
    ax.text(.8, 8.25, title, fontsize=27, color=INK, fontproperties=BOLD, va="center")
    ax.text(.82, 7.72, subtitle, fontsize=15, color=SUB, fontproperties=REG, va="center")
    pill(ax, 13.0, 8.0, 2.15, .5, tag, BLUE_LIGHT, BLUE, 13)
    return fig, ax


def pill(ax, x, y, w, h, label, fill, color, size=14):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.22",
                                linewidth=0, facecolor=fill))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=size, color=color, fontproperties=BOLD)


def card(ax, x, y, w, h, fill=WHITE, edge=LINE, radius=.18, lw=1.4):
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle=f"round,pad=0.02,rounding_size={radius}",
                       linewidth=lw, edgecolor=edge, facecolor=fill)
    ax.add_patch(p)
    return p


def arrow(ax, start, end, color=BLUE, lw=2.5):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=18,
                                 linewidth=lw, color=color, shrinkA=0, shrinkB=0))


def save(fig, stem):
    fig.savefig(OUT / f"{stem}.png", dpi=160, facecolor=BG, bbox_inches=None)
    fig.savefig(OUT / f"{stem}.svg", facecolor=BG, bbox_inches=None)
    plt.close(fig)


def architecture():
    fig, ax = base("프로그램 구조도", "입력 → 눈 상태 파악 → C 언어로 판단 → 필요한 순간에만 아이콘 표시", "구현 방법")
    xs = [.7, 4.55, 8.4, 12.25]
    info = [
        ("01", "노트북 웹캠", "사용자의 눈을\n카메라로 확인", "입력"),
        ("02", "눈 상태 읽기", "Python·MediaPipe가\n눈 위치를 찾음", "Python"),
        ("03", "깜빡임 판단", "C가 횟수와 최근\n60초를 계산", "C 언어"),
        ("04", "아이콘 표시", "기준 미달이 계속되면\n반투명 눈 아이콘", "출력"),
    ]
    for x, (num, title, desc, badge) in zip(xs, info):
        card(ax, x, 3.37, 3.05, 2.72, BLUE_LIGHT if num == "03" else WHITE,
             BLUE if num == "03" else LINE)
        ax.text(x + .28, 5.55, num, fontsize=17, color=BLUE, fontproperties=BOLD)
        ax.text(x + .28, 5.10, title, fontsize=18.5, color=INK, fontproperties=BOLD)
        ax.text(x + .28, 4.51, desc, fontsize=13.7, color=SUB, fontproperties=REG,
                linespacing=1.45, va="top")
        pill(ax, x + .28, 3.53, 1.38, .38, badge, GREEN_LIGHT, GREEN, 11)
    for i in range(3):
        arrow(ax, (xs[i] + 3.13, 4.72), (xs[i + 1] - .16, 4.72))
    card(ax, 5.52, 1.69, 5.12, .85, GREEN_LIGHT, GREEN, .16, 1.4)
    ax.text(8.08, 2.11, "사용자가 알림 기준을 설정", ha="center", va="center",
            fontsize=16, color=GREEN, fontproperties=BOLD)
    arrow(ax, (9.94, 2.58), (9.94, 3.24), GREEN, 2)
    ax.text(8, .83, "카메라 화면은 계속 띄우지 않고, 영상은 저장하지 않는 방향으로 설계",
            ha="center", fontsize=14.5, color=SUB, fontproperties=REG)
    save(fig, "01_프로그램_구조도")


def wireframe():
    fig, ax = base("UI 와이어프레임", "평소에는 백그라운드 실행 · 설정할 때만 창 열기 · 필요할 때만 아이콘 표시", "UI 설계안")
    card(ax, .8, 1.35, 9.4, 5.93, WHITE, LINE)
    ax.text(1.15, 6.77, "눈 깜빡임 알림 · 설정", fontsize=23, color=INK, fontproperties=BOLD)
    pill(ax, 7.62, 6.62, 2.1, .47, "●  측정 중", GREEN_LIGHT, GREEN, 13)
    ax.plot([1.16, 9.82], [6.37, 6.37], color=LINE, lw=1.2)

    labels = [
        (5.72, "알림 기준", "12회 / 60초"),
        (4.67, "기준 미달 지속 시간", "10초"),
        (3.62, "반복 알림 간격", "60초"),
    ]
    for y, label, value in labels:
        ax.text(1.23, y, label, fontsize=17, color=INK, fontproperties=BOLD, va="center")
        card(ax, 6.5, y - .36, 3.1, .72, BG, LINE, .1, 1.1)
        ax.text(6.76, y, value, fontsize=17, color=INK, fontproperties=REG, va="center")
    ax.text(1.23, 2.70, "기준값은 사용자가 바꿀 수 있습니다 · 화면의 수치는 예시값",
            fontsize=13.5, color=SUB, fontproperties=REG)
    card(ax, 1.23, 1.66, 3.0, .72, BLUE_LIGHT, BLUE, .12, 1.5)
    ax.text(2.73, 2.02, "일시정지", ha="center", va="center", fontsize=17, color=BLUE, fontproperties=BOLD)
    card(ax, 4.52, 1.66, 3.0, .72, WHITE, LINE, .12, 1.5)
    ax.text(6.02, 2.02, "종료", ha="center", va="center", fontsize=17, color=INK, fontproperties=BOLD)

    ax.text(10.72, 6.70, "아이콘 표시 예시", fontsize=20, color=INK, fontproperties=BOLD)
    card(ax, 10.65, 3.69, 4.55, 2.61, WHITE, LINE, .18, 1.7)
    ax.text(11.0, 5.85, "노트북 작업 화면", fontsize=15.5, color=SUB, fontproperties=BOLD)
    for line_y, line_w in [(5.45, 2.65), (5.08, 2.35), (4.71, 2.08)]:
        ax.plot([11.0, 11.0 + line_w], [line_y, line_y], color=LINE, lw=3)
    ax.add_patch(Circle((14.17, 4.48), .43, facecolor=BLUE, edgecolor=BLUE, alpha=.22, lw=1.4))
    ax.add_patch(Ellipse((14.17, 4.48), .53, .27, facecolor="none", edgecolor=BLUE, alpha=.75, lw=2))
    ax.add_patch(Circle((14.17, 4.48), .09, facecolor=BLUE, edgecolor="none", alpha=.75))
    ax.text(10.73, 3.17, "기준 미달 시 잠시 표시", fontsize=14, color=SUB, fontproperties=REG)
    ax.text(10.73, 2.67, "크기·투명도 조절 · 글자 안내 선택", fontsize=14, color=SUB, fontproperties=REG)
    card(ax, 10.65, 1.54, 4.55, .67, GREEN_LIGHT, GREEN, .13, 1.2)
    ax.text(12.93, 1.87, "작업 표시줄: 측정 중", ha="center", va="center",
            fontsize=14, color=GREEN, fontproperties=BOLD)
    ax.text(8, .72, "이 그림은 제안 단계의 화면 설계안이며, 실제 실행 화면이 아닙니다.",
            ha="center", fontsize=14, color=SUB, fontproperties=REG)
    save(fig, "02_UI_와이어프레임")


def timeline():
    fig, ax = base("남은 약 8주 개발 일정", "5주차 제안서부터 최종 검증·발표까지 단계별로 진행", "예상 일정")
    phases = [
        ("5~6주차", "설계·기준 정하기", "기능과 UI 설계\n알림 조건 정하기"),
        ("7~8주차", "눈 감지·C 판정", "눈 상태 파악\n깜빡임·60초 집계"),
        ("9~10주차", "백그라운드 UI", "트레이 상태 표시\n설정·일시정지·알림"),
        ("11~12주차", "접근성·안정화", "글자·대비·키보드\n조명·자원 사용 점검"),
        ("13주차 전후", "검증·최종 발표", "수기 기록과 비교\n개선 결과 정리"),
    ]
    x0, gap, w = .63, .15, 2.82
    for i, (week, title, desc) in enumerate(phases):
        x = x0 + i * (w + gap)
        fill = BLUE_LIGHT if i == 0 else WHITE
        edge = BLUE if i == 0 else LINE
        card(ax, x, 3.22, w, 3.42, fill, edge, .16, 1.5)
        pill(ax, x + .24, 5.86, w - .48, .47, week, GREEN_LIGHT if i == 4 else BLUE_LIGHT,
             GREEN if i == 4 else BLUE, 13)
        ax.text(x + .21, 5.28, title, fontsize=16.2, color=INK, fontproperties=BOLD, va="center")
        ax.text(x + .21, 4.49, desc, fontsize=13.3, color=SUB, fontproperties=REG,
                va="top", linespacing=1.8)
        if i < len(phases) - 1:
            arrow(ax, (x + w + .025, 4.81), (x + w + gap - .025, 4.81), BLUE, 1.8)
    card(ax, .72, 1.67, 14.55, .85, GREEN_LIGHT, GREEN, .15, 1.2)
    ax.text(8, 2.10, "이번 제출: 5주차 프로젝트 제안서 PPT + 두 사람의 약 2분 발표 영상",
            ha="center", va="center", fontsize=16, color=GREEN, fontproperties=BOLD)
    ax.text(8, .98, "최종 마감 주차가 공지되면 이후 일정은 수업 일정에 맞춰 조정",
            ha="center", fontsize=14, color=SUB, fontproperties=REG)
    save(fig, "03_개발_일정")


if __name__ == "__main__":
    architecture()
    wireframe()
    timeline()
