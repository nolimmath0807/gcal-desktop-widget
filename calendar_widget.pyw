# 구글 캘린더 비공개 iCal 주소를 읽어 7일 일정을 보여주는 바탕화면 위젯 (읽기 전용)
import argparse
import ctypes
import threading
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox
import urllib.request
import webbrowser
import winreg
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
FONT = "맑은 고딕"  # Tk를 띄운 뒤 pick_font()가 Pretendard로 바꾼다
# 토스풍 색 토큰 (ui-guide-toss-shadcn.md 4장). hover는 카드 호버 면, press는 버튼 호버 면, faint는 다른 달 날짜.
LIGHT = dict(bg="#F2F4F6", card="#FFFFFF", fg="#191F28", muted="#8B95A1", faint="#C5CCD3",
             sec="#F2F4F6", sec_fg="#4E5968", hover="#F9FAFB", press="#E5E8EB", line="#E5E8EB",
             primary="#3182F6", tint="#E8F3FF", tint_fg="#3182F6", red="#F04452", green="#03B26C")
DARK = dict(bg="#17171C", card="#202027", fg="#E4E4E5", muted="#9E9EA4", faint="#55555C",
            sec="#2C2C35", sec_fg="#C3C3C6", hover="#27272F", press="#3A3A45", line="#2C2C35",
            primary="#3182F6", tint="#1E2A3D", tint_fg="#64A8FF", red="#F04452", green="#03B26C")


def system_theme():
    """Windows 앱 테마(AppsUseLightTheme)에 맞는 색 토큰."""
    path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
        return LIGHT if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else DARK


T = system_theme()


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


def root_hwnd(root):
    """overrideredirect 창이라 Tk 내부 창의 최상위 창을 찾는다."""
    return ctypes.windll.user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()  # GA_ROOT


def pin_to_bottom(root):
    """창을 Z순서 맨 아래(HWND_BOTTOM)로 보낸다."""
    ctypes.windll.user32.SetWindowPos(root_hwnd(root), 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_BOTTOM, SWP_NOSIZE|NOMOVE|NOACTIVATE


def round_window(root):
    """Windows 11 창 모서리를 둥글게 (DWMWA_WINDOW_CORNER_PREFERENCE=33, DWMWCP_ROUND=2)."""
    root.update_idletasks()
    ctypes.windll.dwmapi.DwmSetWindowAttribute(root_hwnd(root), 33, ctypes.byref(ctypes.c_int(2)), 4)


def pick_font():
    return "Pretendard" if "Pretendard" in tkfont.families() else "맑은 고딕"


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def round_corners(widget, r, outer):
    """widget 네 모서리에 바깥 색 조각을 얹어 둥글게 보이게 한다 (안쪽 원은 widget 면 색, 태그 face)."""
    inner = widget.cget("bg")
    # Frame은 padx/pady 안쪽 기준으로 place 되므로 그만큼 밖으로 민다
    px, py = (int(widget.cget("padx")), int(widget.cget("pady"))) if isinstance(widget, tk.Frame) else (0, 0)
    corners = (("nw", 0, 0, (0, 0, 2 * r, 2 * r)), ("ne", 1, 0, (-r, 0, r, 2 * r)),
               ("sw", 0, 1, (0, -r, 2 * r, r)), ("se", 1, 1, (-r, -r, r, r)))
    for anchor, relx, rely, box in corners:
        c = tk.Canvas(widget, width=r, height=r, bg=outer, highlightthickness=0, bd=0)
        c.create_oval(*box, fill=inner, outline=inner, tags="face")
        c.on_click = getattr(widget, "on_click", None)
        c.place(relx=relx, rely=rely, x=px if relx else -px, y=py if rely else -py, anchor=anchor)


def paint(widget, old, new):
    """widget 아래에서 old 색인 면을 new 색으로 바꾼다 (호버용)."""
    for w in walk(widget):
        if w.cget("bg") == old:
            w.configure(bg=new)
        if isinstance(w, tk.Canvas) and w.find_withtag("face") and w.itemcget("face", "fill") == old:
            w.itemconfigure("face", fill=new, outline=new)


def hoverable(widget, normal, hot):
    for w in walk(widget):
        w.bind("<Enter>", lambda e: paint(widget, normal, hot), add="+")
        w.bind("<Leave>", lambda e: paint(widget, hot, normal), add="+")


def card(parent, r=12, padx=14, pady=12):
    """회색 바탕 위 흰 카드 (테두리·그림자 없음). 모서리는 내용을 다 넣은 뒤 round_corners로 얹는다."""
    return tk.Frame(parent, bg=T["card"], padx=padx, pady=pady)


def button(parent, text, command, primary):
    face, fg, hot = (T["primary"], "#FFFFFF", "#1B64DA") if primary else (T["sec"], T["sec_fg"], T["press"])
    widget = tk.Button(parent, text=text, command=command, font=(FONT, 10, "bold"), bg=face, fg=fg,
                       activebackground=hot, activeforeground=fg, relief="flat", bd=0, padx=18, pady=7,
                       cursor="hand2")
    widget.bind("<Enter>", lambda e: widget.configure(bg=hot))
    widget.bind("<Leave>", lambda e: widget.configure(bg=face))
    return widget


class Widget:
    pos_file = POS_FILE
    pin_file = PIN_FILE
    size = ""
    min_size = (220, 150)

    def default_pos(self):
        return self.root.winfo_screenwidth() - 320, self.root.winfo_screenheight() - 520

    def __init__(self):
        global FONT
        self.root = tk.Tk()
        FONT = pick_font()
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.95)
        self.root.configure(bg=T["bg"])
        self.texts = []
        self.status = ""
        self.hint = None
        self.dialog = None
        self.body = tk.Frame(self.root, bg=T["bg"], padx=12, pady=12)
        self.body.pack(fill="both", expand=True)
        self.menu = tk.Menu(self.root, tearoff=0, bg=T["card"], fg=T["fg"], activebackground=T["sec"],
                            activeforeground=T["fg"], selectcolor=T["primary"], font=(FONT, 10), bd=0)
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
        round_window(self.root)
        self.resizing = None
        self.grip = tk.Label(self.root, text="◢", bg=T["bg"], fg=T["muted"], font=(FONT, 10), cursor="size_nw_se")
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
        self.dialog = tk.Toplevel(self.root, bg=T["card"], padx=10, pady=8)
        self.dialog.title("캘린더 주소 설정")
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self.close_settings)
        guide = ("구글 캘린더 → 설정 → 왼쪽에서 캘린더 선택 →\n"
                 "\"iCal 형식의 비공개 주소\"를 복사해 붙여 넣어 주세요.\n"
                 "캘린더가 여러 개면 한 줄에 주소 하나씩 넣으면 됩니다.")
        tk.Label(self.dialog, text="캘린더 주소 설정", bg=T["card"], fg=T["fg"],
                 font=(FONT, 14, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(self.dialog, text=guide, bg=T["card"], fg=T["muted"], font=(FONT, 10),
                 justify="left").pack(anchor="w", padx=12, pady=(0, 10))
        self.url_box = tk.Text(self.dialog, width=70, height=6, font=(FONT, 9), bg=T["sec"], fg=T["fg"],
                               insertbackground=T["fg"], selectbackground=T["primary"], relief="flat", bd=0,
                               highlightthickness=0, padx=10, pady=8)
        self.url_box.pack(fill="both", expand=True, padx=12)
        self.url_box.insert("1.0", "\n".join(read_urls()))
        buttons = tk.Frame(self.dialog, bg=T["card"])
        buttons.pack(anchor="e", padx=12, pady=12)
        button(buttons, "취소", self.close_settings, False).pack(side="left", padx=(0, 6))
        button(buttons, "저장", self.save_settings, True).pack(side="left")
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

    def label(self, text, size=10, color=None, bold=False, pady=0):
        weight = "bold" if bold else "normal"
        widget = tk.Label(self.body, text=text, bg=T["bg"], fg=color or T["fg"], font=(FONT, size, weight),
                          anchor="w", justify="left", wraplength=self.wrap(), bd=0)
        widget.pack(fill="x", pady=(pady, 0))
        return widget

    def status_color(self):
        return T["red"] if self.status.startswith("갱신 실패") else T["muted"]

    def wrap(self):
        return max(int(self.size.split("x")[0]) - 40, 100) if self.size else 260

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        now = datetime.now(KST)
        if not read_urls():
            self.hint = self.label("캘린더 주소가 없어요. 여기를 눌러 넣어 주세요", color=T["primary"], bold=True)
            return
        groups = group_events(self.texts, now)
        if not groups:
            self.label("7일간 일정 없음", color=T["muted"])
        time_font = tkfont.Font(font=(FONT, 9))
        time_w = time_font.measure("00:00") + 12
        title_w = max(self.wrap() - 28 - time_w, 80)
        for d, items in groups:
            box = card(self.body)
            box.pack(fill="x", pady=(0, 8))
            box.columnconfigure(0, minsize=time_w)
            box.columnconfigure(1, weight=1)
            head = tk.Frame(box, bg=T["card"])
            head.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
            tk.Label(head, text=day_label(d, None), bg=T["card"], fg=T["fg"], font=(FONT, 11, "bold"),
                     bd=0).pack(side="left")
            if d == now.date():
                badge = tk.Label(head, text="오늘", bg=T["tint"], fg=T["tint_fg"], font=(FONT, 8, "bold"),
                                 bd=0, padx=7, pady=1)
                badge.pack(side="left", padx=(6, 0))
                round_corners(badge, 4, T["card"])
            for row, item in enumerate(items, start=1):
                color = T["muted"] if item["past"] else T["fg"]
                tk.Label(box, text=item["time"], bg=T["card"], fg=T["muted"], font=time_font,
                         bd=0, anchor="w").grid(row=row, column=0, sticky="nw", pady=2)
                tk.Label(box, text=item["title"], bg=T["card"], fg=color, font=(FONT, 10), bd=0, anchor="w",
                         justify="left", wraplength=title_w).grid(row=row, column=1, sticky="w", pady=2)
            round_corners(box, 12, T["bg"])
        self.label(self.status, size=8, color=self.status_color(), pady=2)

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
