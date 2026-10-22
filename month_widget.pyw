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
        self.popup = tk.Toplevel(self.root, bg=cw.BG, padx=12, pady=10)
        self.popup.title(cw.day_label(d, None))
        self.popup.attributes("-topmost", True)
        self.popup.protocol("WM_DELETE_WINDOW", self.close_day)
        tk.Label(self.popup, text=cw.day_label(d, None), bg=cw.BG, fg="#8ab4f8",
                 font=(cw.FONT, 11, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
        for item in items or [{"time": "", "title": "일정 없음", "past": True}]:
            tk.Label(self.popup, text=f"{item['time']}  {item['title']}".strip(), bg=cw.BG,
                     fg="#666666" if item["past"] else "#e8e8e8", font=(cw.FONT, 10),
                     anchor="w", justify="left", wraplength=320).pack(fill="x")
        self.popup.geometry(f"+{self.root.winfo_pointerx() + 10}+{self.root.winfo_pointery() + 10}")

    def close_day(self):
        self.popup.destroy()
        self.popup = None

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        now = datetime.now(cw.KST)
        today = now.date()
        if not cw.read_urls():
            self.hint = self.label("캘린더 주소가 없어요. 여기를 눌러 넣어 주세요", color="#ffcc66")
            return
        weeks = month_grid(self.year, self.month)
        events = month_events(self.texts, now, weeks)

        head = tk.Frame(self.body, bg=cw.BG)
        head.pack(fill="x")
        nav = dict(bg=cw.BG, fg="#e8e8e8", font=(cw.FONT, 12, "bold"), cursor="hand2")
        self.clickable(tk.Label(head, text="◀", **nav), lambda: self.shift(-1)).pack(side="left")
        title = self.clickable(tk.Label(head, text=f"{self.year}년 {self.month}월", **nav), self.go_today)
        title.pack(side="left", padx=10)
        self.clickable(tk.Label(head, text="▶", **nav), lambda: self.shift(1)).pack(side="left")
        tk.Label(head, text=self.status, bg=cw.BG, fg="#888888", font=(cw.FONT, 8)).pack(side="right")

        grid = tk.Frame(self.body, bg=cw.BG)
        grid.pack(fill="both", expand=True, pady=(6, 0))
        colors = ["#ff7b7b"] + ["#e8e8e8"] * 5 + ["#7bb0ff"]
        for col, name in enumerate(MONTH_DAYS):
            grid.columnconfigure(col, weight=1, uniform="col")
            day_head = tk.Label(grid, text=name, bg=cw.BG, fg=colors[col], font=(cw.FONT, 9, "bold"))
            day_head.grid(row=0, column=col)
        # 칸 크기는 창 크기에서 계산한다 (body 여백 24x20, 칸 테두리·여백 10x6)
        width, height = map(int, self.size.split("x"))
        self.cell_w = (width - 24) // 7 - 10
        self.cell_h = (height - 20 - title.winfo_reqheight() - 6 - day_head.winfo_reqheight()) // len(weeks) - 6
        self.item_font = tkfont.Font(font=(cw.FONT, 8))
        self.top_h = tkfont.Font(font=(cw.FONT, 9, "bold")).metrics("linespace")
        for row, week in enumerate(weeks, start=1):
            grid.rowconfigure(row, weight=1, uniform="row")
            for col, d in enumerate(week):
                self.cell(grid, row, col, d, events.get(d, []), today, colors[col])

    def cell(self, grid, row, col, d, items, today, color):
        shown = visible_items(self.cell_h, len(items), self.top_h, self.item_font.metrics("linespace"))
        bg = "#2f3b52" if d == today else "#262626"
        dim = d.month != self.month
        frame = tk.Frame(grid, bg=bg, padx=4, pady=2)
        frame.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
        frame.pack_propagate(False)
        open_day = lambda: self.show_day(d, items)
        self.clickable(frame, open_day)
        lines = [(str(d.day), "#555555" if dim else color, (cw.FONT, 9, "bold"))]
        for item in items[:shown]:
            text = short(item, self.cell_w, self.item_font.measure)
            lines.append((text, "#555555" if dim or item["past"] else "#d0d0d0", (cw.FONT, 8)))
        if len(items) > shown:
            lines.append((f"+{len(items) - shown}", "#888888", (cw.FONT, 8)))
        for text, fg, font in lines:
            label = tk.Label(frame, text=text, bg=bg, fg=fg, font=font, anchor="w")
            label.pack(fill="x")
            self.clickable(label, open_day)


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
