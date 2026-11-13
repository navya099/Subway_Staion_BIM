import tkinter as tk
from tkinter import ttk

from gui.passage_draft import SIDES, TURNS, PassageDraft, PassageDrafts, floor_label, preview

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 8

# (라벨, 속성) 2열 배치
_FIELDS = [("중심 STA", "sta_center", "구배(‰)", "grade_permil"),
           ("내공 폭", "inner_width", "내공 높이", "inner_height"),
           ("벽 두께", "wall_t", "바닥 두께", "floor_t"),
           ("천장 두께", "roof_t", None, None),
           ("상부 헌치 폭", "top_haunch_w", "상부 헌치 높이", "top_haunch_h"),
           ("하부 헌치 폭", "bottom_haunch_w", "하부 헌치 높이", "bottom_haunch_h"),
           ("첫 구간 길이", "length1", "꺾임 후 길이", "length2")]


class PassageTab:
    """탭 7: 출구통로 (본체 측벽에서 직각으로 나가는 박스, 필요하면 선형 접선 방향으로 한 번 꺾임)

    - 위치: 통로가 붙는 층, 측벽(왼쪽 +t / 오른쪽 −t), 통로 중심 STA
    - 단면: 내공 폭·높이 + 벽·바닥·천장 두께, 상·하부 헌치. 바닥 상면은 그 층 FL 에서 시작해 구배로 오르내림
    - 길이: 통로 중심선 기준 (첫 구간 = 외벽 바깥면 ~ 꺾임점, 꺾임 후 = 꺾임점 ~ 끝). 꺾임 후 길이 0 이면 직선
    - 본체 측벽에는 통로 내공 크기의 오프닝이 자동으로 뚫림
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = PassageDrafts()
        self.entries['passage_drafts'] = self.drafts
        self.floor_count = 0
        self._vars = {}            # 테스트/갱신용: (번호, 필드) → StringVar
        self._info_vars = []       # (StringVar, PassageDraft) 미리보기
        self._combos = {}          # (번호, 'floor'|'side'|'turn') → Combobox

    # ------------------------------------------------------------------ 구성
    def build(self):
        tk.Label(self.parent, text="[ 출구통로 ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#6A1B9A").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=430,
                 text="• 길이 단위는 모두 m.  측벽에서 직각으로 나가는 박스 (꺾임 후 길이 > 0 이면 L자)\n"
                      "• 중심 STA: 통로 중심의 절대 STA.  측벽 오프닝은 자동\n"
                      "• 길이는 통로 중심선 기준 (외벽 바깥면 ~ 꺾임점 ~ 끝), 끝단은 열려 있음\n"
                      "• 바닥은 그 층 FL 에서 시작해 구배(‰)로 오르내림, 꺾임부는 수평").pack(anchor="w", padx=15)

        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        tk.Button(bar, text="+ 출구통로 추가", font=FONT, command=self.add_passage).pack(side="left")
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
        """층수가 바뀌면 호출. 층 선택 목록을 새 층수에 맞게 다시 그림 (입력 도중의 빈칸/0 은 무시)"""
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

    def floor_choices(self) -> list[str]:
        return [floor_label(self.floor_count, n) for n in range(1, self.floor_count + 1)]

    # ------------------------------------------------------------------ 편집 동작
    def add_passage(self):
        top = max(1, self.floor_count)                       # 출구통로는 보통 대합실(최상층)에 붙음
        self.drafts.items.append(PassageDraft(floor=top, sta_center=f"{self._start_station() + 30.0:g}"))
        self.render()

    def remove_passage(self, idx):
        del self.drafts.items[idx]
        self.render()

    def set_floor(self, idx, floor_n: int):
        self.drafts.items[idx].floor = floor_n
        self.refresh_info()

    def set_choice(self, idx, attr: str, label: str):
        setattr(self.drafts.items[idx], attr, label)
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
            tk.Label(self.body, text="출구통로 없음", fg="#888888", font=FONT).pack(anchor="w", padx=8, pady=6)
        for i, it in enumerate(self.drafts.items):
            self._build_passage(i, it)
        self.count_var.set(f"출구통로 {len(self.drafts.items)}개" if self.drafts.items else "")
        self.refresh_info()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _combo(self, parent, i, key, values, current, on_select, width):
        c = ttk.Combobox(parent, values=values, state="readonly", width=width, font=FONT)
        c.set(current)
        c.bind("<<ComboboxSelected>>", lambda e: on_select(c))
        self._combos[(i, key)] = c
        return c

    def _build_passage(self, i, it: PassageDraft):
        box = tk.LabelFrame(self.body, text=f" 출구통로 {i + 1} ", font=FONT_B, fg="#4A148C", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=5)

        top = tk.Frame(box)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT).pack(side="left")
        self._entry(top, it, "name", (i, "name"), width=6).pack(side="left", padx=(2, 6))
        tk.Label(top, text="층", font=FONT).pack(side="left")
        floors = self.floor_choices()
        self._combo(top, i, "floor", floors, floors[min(it.floor, len(floors)) - 1],
                    lambda c, k=i: self.set_floor(k, c.current() + 1), width=6).pack(side="left", padx=(2, 0))
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_passage(i)).pack(side="right")

        row = tk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="측벽", font=FONT).pack(side="left")
        self._combo(row, i, "side", SIDES, it.side if it.side in SIDES else SIDES[0],
                    lambda c, k=i: self.set_choice(k, "side", c.get()), width=10).pack(side="left", padx=(2, 8))
        tk.Label(row, text="꺾임 방향", font=FONT).pack(side="left")
        self._combo(row, i, "turn", TURNS, it.turn if it.turn in TURNS else TURNS[0],
                    lambda c, k=i: self.set_choice(k, "turn", c.get()), width=13).pack(side="left", padx=(2, 0))

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
        """통로별 미리보기: 측벽 오프닝 STA 범위, 길이·끝 위치"""
        start = self._start_station()
        for var, it in self._info_vars:
            var.set(preview(it, start))
