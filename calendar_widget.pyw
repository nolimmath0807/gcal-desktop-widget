# 구글 캘린더 비공개 iCal 주소를 읽어 7일 일정을 보여주는 바탕화면 위젯 (읽기 전용)
import argparse
import ctypes
import threading
import tkinter as tk
import tkinter.messagebox
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

KST = ZoneInfo("Asia/Seoul")
HERE = Path(__file__).resolve().parent
URL_FILE = HERE / "ics_url.txt"
POS_FILE = HERE / "widget_pos.txt"
PIN_FILE = HERE / "widget_pin.txt"
DAYS = 7
REFRESH_MS = 5 * 60 * 1000
WEEKDAYS = "월화수목금토일"
FONT = "맑은 고딕"
BG = "#1e1e1e"


def to_local(value):
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def group_events(ics_texts, now, first=None, days=DAYS):
    """ICS 텍스트 목록 -> [(날짜, [{"time","title","past"}, ...]), ...] (first부터 days일, 일정 있는 날만, 날짜순)."""
    today = first or now.date()
    last = today + timedelta(days=days)
    days = {}
    for text in ics_texts:
        cal = icalendar.Calendar.from_ical(text)
        for ev in recurring_ical_events.of(cal).between(today, last):
            start, end = to_local(ev.start), to_local(ev.end)
            title = str(ev.get("SUMMARY", "(제목 없음)"))
            if isinstance(start, datetime):
                if today <= start.date() < last:
                    days.setdefault(start.date(), []).append(
                        {"time": start.strftime("%H:%M"), "title": title, "past": end <= now}
                    )
                continue
            d = max(start, today)
            while d < min(end, last):
                days.setdefault(d, []).append({"time": "종일", "title": title, "past": False})
                d += timedelta(days=1)
    for items in days.values():
        items.sort(key=lambda e: ("" if e["time"] == "종일" else e["time"], e["title"]))
    return sorted(days.items())


def day_label(d, today):
    label = f"{d.month}/{d.day} ({WEEKDAYS[d.weekday()]})"
    return label + " 오늘" if d == today else label


def read_urls():
    if not URL_FILE.exists():
        return []
    lines = [line.strip() for line in URL_FILE.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def parse_urls(text):
    """입력 텍스트 -> (주소 목록, http로 시작하지 않는 줄 목록). 줄마다 strip, 빈 줄 제거."""
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return [line for line in lines if line.startswith("http")], [line for line in lines if not line.startswith("http")]


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def restore_geometry(text, size):
    """위치 파일 내용 -> tk geometry 문자열. 새 형식 "WxH+X+Y"는 그대로, 옛 형식 "X Y"는 기본 크기를 붙인다."""
    text = text.strip()
    if "+" in text:
        return text
    x, y = text.split()
    return f"{size}+{x}+{y}"


def pin_to_bottom(root):
    """창을 Z순서 맨 아래(HWND_BOTTOM)로 보낸다. overrideredirect 창이라 Tk 내부 창의 최상위 창을 찾는다."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()  # GA_ROOT
    user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_BOTTOM, SWP_NOSIZE|NOMOVE|NOACTIVATE


class Widget:
    pos_file = POS_FILE
    pin_file = PIN_FILE
    size = ""
    min_size = (220, 150)

    def default_pos(self):
        return self.root.winfo_screenwidth() - 320, self.root.winfo_screenheight() - 520

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.85)
        self.root.configure(bg=BG)
        self.texts = []
        self.status = ""
        self.hint = None
        self.dialog = None
        self.body = tk.Frame(self.root, bg=BG, padx=12, pady=10)
        self.body.pack(fill="both", expand=True)
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="캘린더 주소 설정…", command=self.open_settings)
        self.pinned = tk.BooleanVar(value=self.pin_file.exists() and self.pin_file.read_text().strip() == "1")
        self.menu.add_checkbutton(label="바탕화면에 고정", variable=self.pinned, command=self.toggle_pin)
        self.menu.add_command(label="지금 새로고침", command=self.refresh_now)
        self.menu.add_command(label="구글 캘린더 열기", command=lambda: webbrowser.open("https://calendar.google.com"))
        self.menu.add_command(label="종료", command=self.root.destroy)
        self.root.bind_all("<ButtonPress-1>", self.drag_start)
        self.root.bind_all("<B1-Motion>", self.drag_move)
        self.root.bind_all("<ButtonRelease-1>", self.drag_end)
        self.root.bind_all("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        if self.pos_file.exists():
            geometry = restore_geometry(self.pos_file.read_text(), self.size)
        else:
            x, y = self.default_pos()
            geometry = f"{self.size}+{x}+{y}"
        self.size = geometry.split("+")[0]
        self.root.geometry(geometry)
        self.resizing = None
        self.grip = tk.Label(self.root, text="◢", bg=BG, fg="#888888", font=(FONT, 10), cursor="size_nw_se")
        self.show_grip()
        self.root.bind("<FocusIn>", lambda e: self.keep_pinned())

    def toggle_pin(self):
        self.pin_file.write_text("1" if self.pinned.get() else "0")
        self.show_grip()
        self.keep_pinned()

    def show_grip(self):
        if self.pinned.get():
            self.grip.place_forget()
        else:
            self.grip.place(relx=1, rely=1, anchor="se")
            self.grip.lift()

    def keep_pinned(self):
        if self.pinned.get():
            pin_to_bottom(self.root)

    def pin_loop(self):
        self.keep_pinned()
        self.root.after(1000, self.pin_loop)

    def in_dialog(self, e):
        return self.dialog is not None and str(e.widget).startswith(str(self.dialog))

    def drag_start(self, e):
        if self.in_dialog(e):
            return
        self.press = (e.x_root, e.y_root)
        self.offset = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())
        if e.widget is self.grip:
            self.resizing = (self.root.winfo_width(), self.root.winfo_height())

    def drag_move(self, e):
        if self.in_dialog(e) or self.pinned.get():
            return
        if self.resizing:
            w = max(self.resizing[0] + e.x_root - self.press[0], self.min_size[0])
            h = max(self.resizing[1] + e.y_root - self.press[1], self.min_size[1])
            self.root.geometry(f"{w}x{h}")
            return
        self.root.geometry(f"+{e.x_root - self.offset[0]}+{e.y_root - self.offset[1]}")

    def drag_end(self, e):
        if self.in_dialog(e):
            return
        if self.resizing:
            self.resizing = None
            self.size = f"{self.root.winfo_width()}x{self.root.winfo_height()}"
            self.render()
        self.pos_file.write_text(f"{self.size}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        moved = abs(e.x_root - self.press[0]) + abs(e.y_root - self.press[1])
        if moved < 5 and e.widget is self.hint:
            self.open_settings()

    def open_settings(self):
        if self.dialog is not None:
            self.dialog.deiconify()
            self.dialog.lift()
            self.dialog.focus_force()
            return
        self.dialog = tk.Toplevel(self.root)
        self.dialog.title("캘린더 주소 설정")
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self.close_settings)
        guide = ("구글 캘린더 → 설정 → 왼쪽에서 캘린더 선택 →\n"
                 "\"iCal 형식의 비공개 주소\"를 복사해 붙여 넣어 주세요.\n"
                 "캘린더가 여러 개면 한 줄에 주소 하나씩 넣으면 됩니다.")
        tk.Label(self.dialog, text=guide, font=(FONT, 10), justify="left").pack(anchor="w", padx=12, pady=(12, 6))
        self.url_box = tk.Text(self.dialog, width=70, height=6, font=(FONT, 9))
        self.url_box.pack(fill="both", expand=True, padx=12)
        self.url_box.insert("1.0", "\n".join(read_urls()))
        buttons = tk.Frame(self.dialog)
        buttons.pack(anchor="e", padx=12, pady=12)
        tk.Button(buttons, text="저장", width=8, command=self.save_settings).pack(side="left", padx=(0, 6))
        tk.Button(buttons, text="취소", width=8, command=self.close_settings).pack(side="left")
        self.dialog.focus_force()
        self.url_box.focus_set()

    def save_settings(self):
        urls, bad = parse_urls(self.url_box.get("1.0", "end"))
        if bad:
            tkinter.messagebox.showwarning(
                "주소 확인", "http로 시작하지 않는 줄이 있어요.\n\n" + "\n".join(bad), parent=self.dialog)
            return
        URL_FILE.write_text("".join(u + "\n" for u in urls), encoding="utf-8")
        self.close_settings()
        self.refresh_now()

    def close_settings(self):
        self.dialog.destroy()
        self.dialog = None

    def label(self, text, size=10, color="#e8e8e8", bold=False, pady=0):
        weight = "bold" if bold else "normal"
        widget = tk.Label(self.body, text=text, bg=BG, fg=color, font=(FONT, size, weight),
                          anchor="w", justify="left", wraplength=self.wrap())
        widget.pack(fill="x", pady=(pady, 0))
        return widget

    def wrap(self):
        return max(int(self.size.split("x")[0]) - 40, 100) if self.size else 260

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        now = datetime.now(KST)
        if not read_urls():
            self.hint = self.label("캘린더 주소가 없어요. 여기를 눌러 넣어 주세요", color="#ffcc66")
            return
        groups = group_events(self.texts, now)
        if not groups:
            self.label("7일간 일정 없음", color="#aaaaaa")
        for d, items in groups:
            self.label(day_label(d, now.date()), size=10, color="#8ab4f8", bold=True, pady=6)
            for item in items:
                self.label(f"{item['time']}  {item['title']}", color="#666666" if item["past"] else "#e8e8e8")
        self.label(self.status, size=8, color="#888888", pady=8)

    def refresh_now(self):
        urls = read_urls()
        threading.Thread(target=self.worker, args=(urls,), daemon=True).start()

    def worker(self, urls):
        stamp = datetime.now(KST).strftime("%H:%M")
        try:
            texts = [fetch(u) for u in urls]
        except OSError:
            self.root.after(0, self.apply, None, f"갱신 실패 {stamp}")
            return
        self.root.after(0, self.apply, texts, f"갱신 {stamp}")

    def apply(self, texts, status):
        if texts is not None:
            self.texts = texts
        self.status = status
        self.render()

    def loop(self):
        self.refresh_now()
        self.root.after(REFRESH_MS, self.loop)

    def run(self):
        self.render()
        self.loop()
        self.pin_loop()
        self.root.mainloop()


SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//selftest//KO
BEGIN:VEVENT
UID:single@test
DTSTART;TZID=Asia/Seoul:20261022T140000
DTEND;TZID=Asia/Seoul:20261022T150000
SUMMARY:주간 회의
END:VEVENT
BEGIN:VEVENT
UID:later@test
DTSTART:20261022T090000Z
DTEND:20261022T100000Z
SUMMARY:저녁 약속
END:VEVENT
BEGIN:VEVENT
UID:allday@test
DTSTART;VALUE=DATE:20261023
DTEND;VALUE=DATE:20261024
SUMMARY:휴가
END:VEVENT
BEGIN:VEVENT
UID:weekly@test
DTSTART:20261001T010000Z
DTEND:20261001T013000Z
RRULE:FREQ=WEEKLY
SUMMARY:스탠드업
END:VEVENT
BEGIN:VEVENT
UID:outside@test
DTSTART;VALUE=DATE:20261030
DTEND;VALUE=DATE:20261031
SUMMARY:범위 밖
END:VEVENT
END:VCALENDAR
"""


def selftest():
    now = datetime(2026, 10, 22, 16, 0, tzinfo=KST)
    groups = dict(group_events([SAMPLE_ICS], now))
    assert list(groups) == [date(2026, 10, 22), date(2026, 10, 23)], groups
    assert groups[date(2026, 10, 22)] == [
        {"time": "10:00", "title": "스탠드업", "past": True},
        {"time": "14:00", "title": "주간 회의", "past": True},
        {"time": "18:00", "title": "저녁 약속", "past": False},
    ], groups[date(2026, 10, 22)]
    assert groups[date(2026, 10, 23)] == [{"time": "종일", "title": "휴가", "past": False}]
    # 다음 주 목요일에는 반복 일정만 잡힌다
    later = dict(group_events([SAMPLE_ICS], datetime(2026, 10, 27, 0, 0, tzinfo=KST)))
    assert later[date(2026, 10, 29)] == [{"time": "10:00", "title": "스탠드업", "past": False}]
    assert date(2026, 10, 30) in later and date(2026, 10, 22) not in later
    assert parse_urls("  https://a/basic.ics \n\n\thttp://b.ics\n") == (["https://a/basic.ics", "http://b.ics"], [])
    assert parse_urls("https://a.ics\nwebcal://c.ics\n") == (["https://a.ics"], ["webcal://c.ics"])
    assert parse_urls("\n \n") == ([], [])
    assert day_label(date(2026, 10, 22), date(2026, 10, 22)) == "10/22 (목) 오늘"
    assert restore_geometry("2120 579\n", "") == "+2120+579"
    assert restore_geometry("447 92", "700x520") == "700x520+447+92"
    assert restore_geometry("-1500 -20", "") == "+-1500+-20"
    assert restore_geometry("900x700+-5+10\n", "700x520") == "900x700+-5+10"
    assert restore_geometry("+30+40", "") == "+30+40"
    print("OK")


def main(selftest_mode):
    if selftest_mode:
        selftest()
        return
    Widget().run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    main(parser.parse_args().selftest)
