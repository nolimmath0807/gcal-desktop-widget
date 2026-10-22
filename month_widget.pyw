# 구글 캘린더 일정을 한 달 달력 격자로 보여주는 바탕화면 위젯 (calendar_widget 재사용, 읽기 전용)
import argparse
import calendar
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime

import calendar_widget as cw

MONTH_DAYS = "일월화수목금토"


def month_grid(year, month):
    """그 달 달력에 보일 주 목록 (일요일 시작, 주마다 날짜 7개)."""
    return calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)


def month_events(ics_texts, now, weeks):
    """격자 전체 기간의 {날짜: [일정, ...]}."""
    return dict(cw.group_events(ics_texts, now, first=weeks[0][0], days=len(weeks) * 7))


def short(item, max_px, measure):
    """일정 한 줄을 max_px 폭(measure로 잰 값)에 맞게 자른다."""
    text = item["title"] if item["time"] == "종일" else f"{item['time']} {item['title']}"
    if measure(text) <= max_px:
        return text
    while text and measure(text + "…") > max_px:
        text = text[:-1]
    return text + "…"


def visible_items(cell_h, total, top, line_h):
    """칸 높이(px), 일정 수, 날짜 줄 높이, 일정 줄 높이 -> 보여줄 일정 수. 넘치면 "+N" 줄 자리를 남기고, 최소 1개."""
    slots = max((cell_h - top) // line_h, 1)
    return total if total <= slots else max(slots - 1, 1)


class MonthWidget(cw.Widget):
    pos_file = cw.HERE / "month_pos.txt"
    pin_file = cw.HERE / "month_pin.txt"
    size = "700x520"
    min_size = (420, 320)

    def default_pos(self):
        return 40, 40

    def __init__(self):
        super().__init__()
        today = datetime.now(cw.KST).date()
        self.year, self.month = today.year, today.month
        self.popup = None

    def in_dialog(self, e):
        return super().in_dialog(e) or (self.popup is not None and str(e.widget).startswith(str(self.popup)))

    def drag_end(self, e):
        super().drag_end(e)
        if self.in_dialog(e):
            return
        moved = abs(e.x_root - self.press[0]) + abs(e.y_root - self.press[1])
        on_click = getattr(e.widget, "on_click", None)
        if moved < 5 and on_click:
            on_click()

    def clickable(self, widget, action):
        widget.on_click = action
        return widget

    def shift(self, step):
        index = self.year * 12 + self.month - 1 + step
        self.year, self.month = divmod(index, 12)
        self.month += 1
        self.render()

    def go_today(self):
        today = datetime.now(cw.KST).date()
        self.year, self.month = today.year, today.month
        self.render()

    def show_day(self, d, items):
        if self.popup is not None:
            self.popup.destroy()
        T = cw.T
        self.popup = tk.Toplevel(self.root, bg=T["card"], padx=18, pady=16)
        self.popup.title(cw.day_label(d, None))
        self.popup.attributes("-topmost", True)
        self.popup.protocol("WM_DELETE_WINDOW", self.close_day)
        self.popup.columnconfigure(0, minsize=tkfont.Font(font=(cw.FONT, 9)).measure("00:00") + 12)
        tk.Label(self.popup, text=cw.day_label(d, None), bg=T["card"], fg=T["fg"], font=(cw.FONT, 13, "bold"),
                 bd=0, anchor="w").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        if not items:
            tk.Label(self.popup, text="일정 없음", bg=T["card"], fg=T["muted"], font=(cw.FONT, 10),
                     bd=0).grid(row=1, column=0, columnspan=2, sticky="w")
        for row, item in enumerate(items, start=1):
            tk.Label(self.popup, text=item["time"], bg=T["card"], fg=T["muted"], font=(cw.FONT, 9),
                     bd=0).grid(row=row, column=0, sticky="nw", pady=2)
            tk.Label(self.popup, text=item["title"], bg=T["card"], fg=T["muted"] if item["past"] else T["fg"],
                     font=(cw.FONT, 10), bd=0, anchor="w", justify="left",
                     wraplength=320).grid(row=row, column=1, sticky="w", pady=2)
        self.popup.geometry(f"+{self.root.winfo_pointerx() + 10}+{self.root.winfo_pointery() + 10}")

    def close_day(self):
        self.popup.destroy()
        self.popup = None

    def nav_button(self, parent, text, action):
        T = cw.T
        widget = self.clickable(tk.Label(parent, text=text, bg=T["card"], fg=T["sec_fg"], font=(cw.FONT, 9),
                                         bd=0, padx=9, pady=3, cursor="hand2"), action)
        widget.pack(side="right", padx=(4, 0))
        cw.round_corners(widget, 6, T["bg"])
        cw.hoverable(widget, T["card"], T["press"])

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        T = cw.T
        now = datetime.now(cw.KST)
        today = now.date()
        if not cw.read_urls():
            self.hint = self.label("캘린더 주소가 없어요. 여기를 눌러 넣어 주세요", color=T["primary"], bold=True)
            return
        weeks = month_grid(self.year, self.month)
        events = month_events(self.texts, now, weeks)

        head = tk.Frame(self.body, bg=T["bg"])
        head.pack(fill="x", padx=2)
        title = self.clickable(tk.Label(head, text=f"{self.year}년 {self.month}월", bg=T["bg"], fg=T["fg"],
                                        font=(cw.FONT, 17, "bold"), bd=0, cursor="hand2"), self.go_today)
        title.pack(side="left")
        self.nav_button(head, "▶", lambda: self.shift(1))
        self.nav_button(head, "◀", lambda: self.shift(-1))
        tk.Label(head, text=self.status, bg=T["bg"], fg=self.status_color(), font=(cw.FONT, 8),
                 bd=0).pack(side="right", padx=(0, 8))

        grid = tk.Frame(self.body, bg=T["bg"])
        grid.pack(fill="both", expand=True, pady=(8, 0))
        colors = [T["red"]] + [T["fg"]] * 5 + [T["primary"]]
        for col, name in enumerate(MONTH_DAYS):
            grid.columnconfigure(col, weight=1, uniform="col")
            day_head = tk.Label(grid, text=name, bg=T["bg"], fg=T["muted"] if col % 6 else colors[col],
                                font=(cw.FONT, 9), bd=0)
            day_head.grid(row=0, column=col, pady=(0, 4))
        # 칸 크기는 창 크기에서 계산한다 (body 여백 24x24, 칸 간격 4x4, 칸 안 여백 12x10)
        width, height = map(int, self.size.split("x"))
        self.cell_w = (width - 24) // 7 - 4 - 12
        self.cell_h = (height - 24 - title.winfo_reqheight() - 8 - day_head.winfo_reqheight() - 4) // len(weeks) - 4 - 10
        self.item_font = tkfont.Font(font=(cw.FONT, 8))
        self.top_h = max(tkfont.Font(font=(cw.FONT, 9, "bold")).metrics("linespace"), 20) + 2
        for row, week in enumerate(weeks, start=1):
            grid.rowconfigure(row, weight=1, uniform="row")
            for col, d in enumerate(week):
                self.cell(grid, row, col, d, events.get(d, []), today, colors[col])

    def cell(self, grid, row, col, d, items, today, color):
        T = cw.T
        line_h = self.item_font.metrics("linespace") + 3
        shown = visible_items(self.cell_h, len(items), self.top_h, line_h)
        dim = d.month != self.month
        frame = tk.Frame(grid, bg=T["card"], padx=6, pady=5)
        frame.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
        frame.pack_propagate(False)
        if d == today:
            dot = tk.Canvas(frame, width=20, height=20, bg=T["card"], highlightthickness=0, bd=0)
            dot.create_oval(0, 0, 19, 19, fill=T["primary"], outline=T["primary"])
            dot.create_text(10, 10, text=str(d.day), fill="#FFFFFF", font=(cw.FONT, 8, "bold"))
            dot.pack(anchor="w", pady=(0, 2))
        else:
            tk.Label(frame, text=str(d.day), bg=T["card"], fg=T["faint"] if dim else color,
                     font=(cw.FONT, 9, "bold"), bd=0, padx=3, anchor="w").pack(fill="x", pady=(2, 4))
        dot_w = self.item_font.measure("● ")
        for item in items[:shown]:
            faded = dim or item["past"]
            if item["time"] == "종일":
                chip = tk.Label(frame, text=short(item, self.cell_w - 10, self.item_font.measure), bg=T["tint"],
                                fg=T["muted"] if faded else T["tint_fg"], font=self.item_font, bd=0,
                                padx=5, pady=1, anchor="w")
                chip.pack(fill="x", pady=(1, 0))
                cw.round_corners(chip, 4, T["card"])
                continue
            line = tk.Frame(frame, bg=T["card"])
            line.pack(fill="x", pady=(1, 0))
            tk.Label(line, text="●", bg=T["card"], fg=T["faint"] if faded else T["primary"], font=(cw.FONT, 5),
                     bd=0).pack(side="left", padx=(2, 3))
            tk.Label(line, text=short(item, self.cell_w - dot_w, self.item_font.measure), bg=T["card"],
                     fg=T["muted"] if faded else T["fg"], font=self.item_font, bd=0, pady=1,
                     anchor="w").pack(side="left", fill="x")
        if len(items) > shown:
            tk.Label(frame, text=f"+{len(items) - shown}", bg=T["card"], fg=T["muted"], font=self.item_font,
                     bd=0, padx=3, anchor="w").pack(fill="x", pady=(1, 0))
        cw.round_corners(frame, 8, T["bg"])
        open_day = lambda: self.show_day(d, items)
        for w in cw.walk(frame):
            self.clickable(w, open_day)
        cw.hoverable(frame, T["card"], T["hover"])


def selftest():
    oct_weeks = month_grid(2026, 10)
    assert oct_weeks[0][0] == date(2026, 9, 27) and oct_weeks[0][0].weekday() == 6
    assert len(oct_weeks) == 5 and oct_weeks[-1][-1] == date(2026, 10, 31)
    assert len(month_grid(2026, 8)) == 6  # 8/1이 토요일
    now = datetime(2026, 10, 22, 16, 0, tzinfo=cw.KST)
    events = month_events([cw.SAMPLE_ICS], now, oct_weeks)
    standup = [d for d, items in events.items() if any(i["title"] == "스탠드업" for i in items)]
    assert standup == [date(2026, 10, n) for n in (1, 8, 15, 22, 29)], standup
    assert events[date(2026, 10, 30)] == [{"time": "종일", "title": "범위 밖", "past": False}]
    assert events[date(2026, 10, 1)][0]["past"] is True
    assert short({"time": "14:00", "title": "아주 긴 회의 제목입니다"}, 11, len) == "14:00 아주 긴…"
    assert short({"time": "종일", "title": "휴가"}, 11, len) == "휴가"
    assert short({"time": "종일", "title": "아주 긴 회의 제목입니다"}, 30, len) == "아주 긴 회의 제목입니다"
    assert visible_items(80, 2, 17, 15) == 2  # 4줄 자리, 다 들어감
    assert visible_items(80, 6, 17, 15) == 3  # 4줄 자리 중 1줄은 "+3"
    assert visible_items(20, 5, 17, 15) == 1  # 너무 작아도 1개는 보인다
    assert visible_items(20, 1, 17, 15) == 1
    print("OK")


def main(selftest_mode):
    if selftest_mode:
        selftest()
        return
    MonthWidget().run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    main(parser.parse_args().selftest)
