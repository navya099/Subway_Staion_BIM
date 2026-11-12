import tkinter as tk
from tkinter import ttk

from gui.stair_draft import DIRECTIONS, StairDraft, StairDrafts, floor_choice_label, preview

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 8

# (라벨, 속성) 2열 배치
_FIELDS = [("시작 STA", "sta_start", "t 위치", "t_center"),
           ("폭", "width", "단높이 상한", "riser_max"),
           ("단너비", "tread", "런 높이 상한", "flight_rise_max"),
           ("계단참 길이", "landing_len", "슬래브 두께", "waist_t"),
           ("머리 높이", "headroom", None, None)]


class StairTab:
    """탭 5: 직선 계단 (런 + 중간 계단참, 위층 슬래브 오프닝 자동 생성)

    - 위치: 첫 단이 시작되는 STA + 오르는 방향, t 위치 + 폭 (t 는 기둥·오프닝과 같은 좌표)
    - 단수는 단높이 상한으로 자동(올림), 한 런 높이가 런 높이 상한을 넘지 않도록 계단참을 자동으로 넣는다
    - 위층 슬래브는 머리 높이가 부족한 구간부터 계단 상단까지 자동으로 뚫린다
    - 입력값은 StairDrafts(화면 비의존 초안)에 저장되고, 성과물 출력 시 TkAdapter 가 StairSpec 으로 변환한다.
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = StairDrafts()
        self.entries['stair_drafts'] = self.drafts
        self.floor_count = 0
        self._vars = {}            # 테스트/갱신용: (번호, 필드) → StringVar
        self._info_vars = []       # (StringVar, StairDraft) 미리보기
        self._combos = {}          # (번호, 'floor'|'direction') → Combobox

    # ------------------------------------------------------------------ 구성
    def build(self):
        tk.Label(self.parent, text="[ 계단 ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#6A1B9A").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=430,
                 text="• 길이 단위는 모두 m.  직선 계단 (런 + 중간 계단참)\n"
                      "• 시작 STA: 첫 단의 절대 STA.  오르는 방향으로 계단이 이어짐\n"
                      "• 단수는 단높이 상한으로 자동, 계단참은 런 높이 상한으로 자동\n"
                      "• 최하층에서 승강장 안에 놓이면 승강장 상면에서 시작\n"
                      "• 위층 슬래브는 머리 높이가 부족한 구간부터 자동으로 뚫림").pack(anchor="w", padx=15)

        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        tk.Button(bar, text="+ 계단 추가", font=FONT, command=self.add_stair).pack(side="left")
        self.count_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.count_var, font=FONT, fg="#1565C0").pack(side="left", padx=10)

        wrap = tk.Frame(self.parent)
        wrap.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 6))
        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas)
        win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.bind("<Enter>", lambda e: self._bind_wheel(True))
        self.canvas.bind("<Leave>", lambda e: self._bind_wheel(False))

        self.update_floor_ui()

    def _bind_wheel(self, on: bool):
        if on:
            self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
        else:
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.canvas.unbind_all(ev)

    # ------------------------------------------------------------------ 층수 / 정거장 제원 변경
    def _read_floor_count(self):
        try:
            n = int(self.entries['floors'].get().strip())
        except (KeyError, ValueError):
            return None
        return n if 1 <= n <= 20 else None

    def update_floor_ui(self):
        """층수가 바뀌면 호출. 시작 층 선택 목록을 새 층수에 맞게 다시 그림 (입력 도중의 빈칸/0 은 무시)"""
        if not hasattr(self, 'body'):
            return
        n = self._read_floor_count()
        if n is None:
            n = self.floor_count or 1
        if n == self.floor_count:
            return
        self.drafts.ensure_floors(n)
        self.floor_count = n
        self.render()

    def _start_station(self) -> float:
        try:
            return float(self.entries['start_station'].get())
        except (KeyError, ValueError):
            return 0.0

    def _floor_height(self, floor_n: int):
        try:
            return float(self.entries[f'floor_height_{floor_n}'].get())
        except (KeyError, ValueError):
            return None

    def floor_choices(self) -> list[str]:
        return [floor_choice_label(self.floor_count, n) for n in range(1, max(2, self.floor_count))]

    # ------------------------------------------------------------------ 편집 동작
    def add_stair(self):
        self.drafts.items.append(StairDraft(sta_start=f"{self._start_station() + 10.0:g}"))
        self.render()

    def remove_stair(self, idx):
        del self.drafts.items[idx]
        self.render()

    def set_floor(self, idx, floor_n: int):
        self.drafts.items[idx].lower_floor = floor_n
        self.refresh_info()

    def set_direction(self, idx, label: str):
        self.drafts.items[idx].direction = label
        self.refresh_info()

    # ------------------------------------------------------------------ 그리기
    def render(self):
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        self._vars.clear()
        self._info_vars.clear()
        self._combos.clear()
        if not self.drafts.items:
            tk.Label(self.body, text="계단 없음", fg="#888888", font=FONT).pack(anchor="w", padx=8, pady=6)
        for i, it in enumerate(self.drafts.items):
            self._build_stair(i, it)
        self.count_var.set(f"계단 {len(self.drafts.items)}개" if self.drafts.items else "")
        self.refresh_info()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _build_stair(self, i, it: StairDraft):
        box = tk.LabelFrame(self.body, text=f" 계단 {i + 1} ", font=FONT_B, fg="#4A148C", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=5)

        top = tk.Frame(box)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT).pack(side="left")
        self._entry(top, it, "name", (i, "name"), width=6).pack(side="left", padx=(2, 6))
        tk.Label(top, text="층", font=FONT).pack(side="left")
        floors = self.floor_choices()
        fc = ttk.Combobox(top, values=floors, state="readonly", width=11, font=FONT)
        fc.set(floors[min(it.lower_floor, len(floors)) - 1])
        fc.pack(side="left", padx=(2, 0))
        fc.bind("<<ComboboxSelected>>", lambda e, c=fc, k=i: self.set_floor(k, c.current() + 1))
        self._combos[(i, "floor")] = fc
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_stair(i)).pack(side="right")

        row = tk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="오르는 방향", font=FONT).pack(side="left")
        dc = ttk.Combobox(row, values=DIRECTIONS, state="readonly", width=13, font=FONT)
        dc.set(it.direction if it.direction in DIRECTIONS else DIRECTIONS[0])
        dc.pack(side="left", padx=(2, 0))
        dc.bind("<<ComboboxSelected>>", lambda e, c=dc, k=i: self.set_direction(k, c.get()))
        self._combos[(i, "direction")] = dc

        grid = tk.Frame(box)
        grid.pack(fill="x", pady=(4, 0))
        for r, (l1, a1, l2, a2) in enumerate(_FIELDS):
            tk.Label(grid, text=l1, font=FONT).grid(row=r, column=0, sticky="w")
            self._entry(grid, it, a1, (i, a1), width=ENTRY_W).grid(row=r, column=1, padx=(2, 12), pady=1)
            if l2:
                tk.Label(grid, text=l2, font=FONT).grid(row=r, column=2, sticky="w")
                self._entry(grid, it, a2, (i, a2), width=ENTRY_W).grid(row=r, column=3, padx=(2, 0), pady=1)

        info = tk.StringVar(value="")
        self._info_vars.append((info, it))
        tk.Label(box, textvariable=info, font=FONT, fg="#1565C0", anchor="w", justify="left").pack(fill="x", pady=(2, 0))

    def _entry(self, parent, obj, attr, key, width):
        var = tk.StringVar(value=getattr(obj, attr))
        self._vars[key] = var

        def on_write(*_):
            setattr(obj, attr, var.get())
            self.refresh_info()
        var.trace_add("write", on_write)
        return tk.Entry(parent, textvariable=var, width=width, font=FONT)

    def refresh_info(self):
        """계단별 미리보기: 단수·단높이·계단참·길이·STA 범위 (FL 기준, 구배 무시 추정)"""
        start = self._start_station()
        for var, it in self._info_vars:
            h = self._floor_height(it.lower_floor)
            var.set("→ 층 높이를 확인하세요" if h is None or h <= 0 else preview(it, h, start))
