# 집중 25분·휴식 5분(4번마다 긴 휴식 15분)을 재는 뽀모도로 바탕화면 위젯 (calendar_widget 재사용)
import argparse
import math
import tkinter as tk
import tkinter.font as tkfont
import winsound
from datetime import date
from time import monotonic

import calendar_widget as cw

DURATIONS = {"focus": 25 * 60, "short": 5 * 60, "long": 15 * 60}  # 단계별 길이(초)
LONG_EVERY = 4  # 집중 몇 번마다 긴 휴식
LABELS = {"focus": "집중", "short": "휴식", "long": "긴 휴식"}
GREEN_TINT = "#E5F8EF" if cw.T is cw.LIGHT else "#17322A"
TICK_MS = 250
COUNT_FILE = cw.HERE / "pomodoro_count.txt"


def next_phase(phase, streak):
    """끝난 단계와 이번 세트에서 끝낸 집중 수 -> (다음 단계, 새 집중 수). 4번째 집중 뒤 긴 휴식, 긴 휴식 뒤 세트 초기화."""
    if phase == "focus":
        streak += 1
        return ("long" if streak == LONG_EVERY else "short"), streak
    return "focus", 0 if phase == "long" else streak


def fmt_left(seconds):
    """남은 초 -> "MM:SS". 소수점은 올림이라 59.2초는 "01:00", 0 이하는 "00:00"."""
    return "%02d:%02d" % divmod(max(math.ceil(seconds), 0), 60)


def parse_count(text, today):
    """횟수 파일 "YYYY-MM-DD N" -> 오늘 완료 횟수. 날짜가 오늘이 아니면 0."""
    day, n = text.split()
    return int(n) if day == today.isoformat() else 0


class PomodoroWidget(cw.Widget):
    pos_file = cw.HERE / "pomodoro_pos.txt"
    pin_file = cw.HERE / "pomodoro_pin.txt"
    style_file = cw.HERE / "pomodoro_style.txt"
    count_file = COUNT_FILE
    size = "280x260"
    min_size = (220, 200)
    calendar = False

    def default_pos(self):
        return self.root.winfo_screenwidth() - 320, 40

    def __init__(self):
        super().__init__()
        self.phase, self.streak = "focus", 0
        self.left, self.end = DURATIONS["focus"], None  # end: 진행 중일 때 끝나는 monotonic 시각
        self.flashing = False
        self.root.after(TICK_MS, self.tick)

    def today_count(self):
        return parse_count(self.count_file.read_text(), date.today()) if self.count_file.exists() else 0

    def remaining(self):
        return self.left if self.end is None else self.end - monotonic()

    def colors(self):
        """(배지 글자, 배지 배경, 막대) 색."""
        T = cw.T
        if self.phase == "focus":
            return T["tint_fg"], T["tint"], T["primary"]
        return T["green"], GREEN_TINT, T["green"]

    def toggle(self):
        if self.end is None:
            self.end = monotonic() + self.left
        else:
            self.left, self.end = self.remaining(), None
        self.render()

    def reset(self):
        self.go(self.phase, self.streak)

    def skip(self):
        # 집중을 건너뛰면 완료로 치지 않고 짧은 휴식으로만 넘어간다
        self.go(*(("short", self.streak) if self.phase == "focus" else next_phase(self.phase, self.streak)))

    def go(self, phase, streak):
        self.phase, self.streak = phase, streak
        self.left, self.end = DURATIONS[phase], None
        self.render()

    def finish(self):
        if self.phase == "focus":
            self.count_file.write_text(f"{date.today().isoformat()} {self.today_count() + 1}")
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        self.go(*next_phase(self.phase, self.streak))
        self.flash(5)

    def flash(self, left):
        """홀수 차례마다 카드 면을 단계 틴트로 바꿔 3번 깜빡인다."""
        self.flashing = bool(left % 2)
        self.render()
        if left:
            self.root.after(300, self.flash, left - 1)

    def tick(self):
        if self.end is not None and self.remaining() <= 0:
            self.finish()
        self.show_time()
        self.root.after(TICK_MS, self.tick)

    def show_time(self):
        for item, ch in zip(self.time_items, fmt_left(self.remaining())):
            self.clock.itemconfigure(item, text=ch)
        done = 1 - max(self.remaining(), 0) / DURATIONS[self.phase]
        self.bar.coords(self.bar_fill, 0, 0, self.bar_w * done, 6)
        self.count_label.configure(text=f"오늘 집중 {self.today_count()}회")

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        T = cw.T
        fg, tint, bar_color = self.colors()
        face = tint if self.flashing else T["card"]
        width, height = map(int, self.size.split("x"))
        box = tk.Frame(self.body, bg=face, padx=14, pady=12)
        box.pack(fill="both", expand=True)

        top = tk.Frame(box, bg=face)
        top.pack(fill="x")
        badge = tk.Label(top, text=LABELS[self.phase], bg=tint, fg=fg, font=self.font(10, "bold"), bd=0, padx=7, pady=1)
        badge.pack(side="left")
        dot = max(tkfont.Font(font=self.font(10)).metrics("linespace") // 2, 6)
        dots = tk.Canvas(top, width=LONG_EVERY * (dot + 5), height=dot, bg=face, highlightthickness=0, bd=0)
        for i in range(LONG_EVERY):
            color = T["primary"] if i < self.streak else T["line"]
            dots.create_oval(i * (dot + 5), 0, i * (dot + 5) + dot - 1, dot - 1, fill=color, outline=color)
        dots.pack(side="right")

        # 아래 줄들을 먼저 깔고, 남은 자리를 시간 글씨가 차지한다
        font = self.font(11, "bold")
        row2 = tk.Frame(box, bg=face)
        row2.pack(side="bottom", fill="x")
        row2.columnconfigure((0, 1), weight=1, uniform="b")
        cw.button(row2, "초기화", self.reset, False, font).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        cw.button(row2, "건너뛰기", self.skip, False, font).grid(row=0, column=1, sticky="ew", padx=(3, 0))
        start = "일시정지" if self.end is not None else "시작"
        cw.button(box, start, self.toggle, True, font).pack(side="bottom", fill="x", pady=(0, 6))
        self.count_label = tk.Label(box, bg=face, fg=T["muted"], font=self.font(10), bd=0)
        self.count_label.pack(side="bottom", anchor="w", pady=(0, 10))
        self.bar_w = width - 24 - 28
        self.bar = tk.Canvas(box, width=self.bar_w, height=6, bg=face, highlightthickness=0, bd=0)
        self.bar.create_rectangle(0, 0, self.bar_w, 6, fill=T["line"], outline="")
        self.bar_fill = self.bar.create_rectangle(0, 0, 0, 6, fill=bar_color, outline="")
        self.bar.pack(side="bottom", pady=(4, 6))

        self.clock = tk.Canvas(box, width=1, height=1, bg=face, highlightthickness=0, bd=0)
        self.clock.pack(fill="both", expand=True)
        box.update_idletasks()
        free_w, free_h = self.bar_w, max(height - 24 - (box.winfo_reqheight() - 1), 10)
        # 크기 100px로 재 보고 남은 자리에 맞게 비례로 키운다. 숫자는 가장 넓은 숫자 폭 칸에 하나씩 놓아 흔들리지 않게 한다.
        probe = tkfont.Font(font=(cw.FONT, -100, "bold"))
        scale = min(free_w / (4 * max(probe.measure(str(d)) for d in range(10)) + probe.measure(":")),
                    free_h / probe.metrics("linespace"))
        big = tkfont.Font(font=(cw.FONT, -max(int(100 * scale), 12), "bold"))
        digit_w, colon_w = max(big.measure(str(d)) for d in range(10)), big.measure(":")
        self.clock.configure(width=free_w, height=free_h)
        x = (free_w - 4 * digit_w - colon_w) / 2
        self.time_items = []
        for ch in "00:00":
            w = colon_w if ch == ":" else digit_w
            self.time_items.append(self.clock.create_text(x + w / 2, free_h / 2, text=ch, fill=T["fg"], font=big))
            x += w

        cw.round_corners(badge, 4, face)
        cw.round_corners(box, 12, T["bg"])
        self.show_time()


def selftest():
    assert next_phase("focus", 0) == ("short", 1)
    assert next_phase("short", 1) == ("focus", 1)
    assert next_phase("focus", 3) == ("long", 4)  # 4번째 집중 뒤 긴 휴식
    assert next_phase("long", 4) == ("focus", 0)
    phase, streak, seen = "focus", 0, []
    for _ in range(16):
        phase, streak = next_phase(phase, streak)
        seen.append(phase)
    assert seen[:8] == ["short", "focus", "short", "focus", "short", "focus", "long", "focus"], seen
    assert seen[8:] == seen[:8]
    assert fmt_left(25 * 60) == "25:00"
    assert fmt_left(59.2) == "01:00"
    assert fmt_left(1499.01) == "25:00"
    assert fmt_left(1498.9) == "24:59"
    assert fmt_left(0.3) == "00:01"
    assert fmt_left(0) == fmt_left(-2.5) == "00:00"
    today = date(2026, 10, 22)
    assert parse_count("2026-10-22 3\n", today) == 3
    assert parse_count("2026-10-21 7", today) == 0  # 날짜 넘어가면 0
    print("OK")


def main(selftest_mode):
    if selftest_mode:
        selftest()
        return
    PomodoroWidget().run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    main(parser.parse_args().selftest)
