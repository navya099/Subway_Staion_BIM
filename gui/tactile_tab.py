import tkinter as tk
from tkinter import ttk

from gui import pick_buttons as PB
from gui.pick_fill import num
from gui.passage_draft import floor_label
from gui.tactile_draft import AUTO_GROUPS, SIZE_FIELDS, TactileDrafts, TactilePointDraft, default_path, preview
from preview.pick import PATH

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 7


class TactileTab:
    """탭 13: 점자블록 (자동 점형 경고블록 + 유도블록 경로)

    - 승강장 연단·계단·에스컬레이터·엘리베이터 문 앞 경고블록(점형)은 자동
    - 유도 경로는 (STA, t) 꼭짓점 — 꼭짓점 = 점형, 사이 = 선형. 선분은 선형 방향 또는 직각 방향만
    - 바닥 마감이 있으면 마감재를 대체 (같은 높이), 없으면 바닥 위에 블록 두께
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = TactileDrafts()
        self.entries['tactile_drafts'] = self.drafts
        self.floor_count = 0
        self._vars = {}            # 설정: 속성 → 변수, 경로: (번호, 속성) / (번호, 'v', 꼭짓점, 'x'|'y') → StringVar
        self._combos = {}
        self._set_vars = {}

    # ------------------------------------------------------------------ 구성
    def build(self):
        tk.Label(self.parent, text="[ 점자블록 ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#F9A825").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=430,
                 text="• 경고블록(점형): 승강장 연단·계단·에스컬레이터 시작·끝 앞·엘리베이터 문 앞 자동\n"
                      "• 유도 경로: 꼭짓점 = 점형, 사이 = 선형. 선분은 선형 방향 또는 직각 방향만 (미리보기 선택은 직교 모드)\n"
                      "• 바닥 마감이 있으면 마감재를 대체(같은 높이), 없으면 바닥 위 블록 두께\n"
                      "• 칸막이벽·기둥·승강로·계단·오프닝 자리는 비움").pack(anchor="w", padx=15)
        top = tk.Frame(self.parent)
        top.pack(fill="x", padx=15, pady=(6, 0))
        self._set_check(top, "enabled", "점자블록 만들기").pack(side="left")
        for attr, label, _ in SIZE_FIELDS:
            tk.Label(top, text=label, font=FONT).pack(side="left", padx=(10, 2))
            self._set_entry(top, attr).pack(side="left")

        auto = tk.LabelFrame(self.parent, text=" 자동 경고블록 (m) ", font=FONT_B, padx=6, pady=2)
        auto.pack(fill="x", padx=15, pady=(4, 0))
        for r, (flag, label, fields) in enumerate(AUTO_GROUPS):
            self._set_check(auto, flag, label).grid(row=r, column=0, sticky="w")
            for c, (attr, lb, _) in enumerate(fields):
                tk.Label(auto, text=lb, font=FONT).grid(row=r, column=1 + 2 * c, sticky="e", padx=(8, 2))
                self._set_entry(auto, attr).grid(row=r, column=2 + 2 * c, pady=1)

        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        tk.Button(bar, text="+ 유도 경로 추가", font=FONT, command=self.add_path).pack(side="left")
        self.info_var = tk.StringVar(value="")
        tk.Label(self.parent, textvariable=self.info_var, font=FONT, fg="#1565C0", anchor="w", justify="left").pack(
            fill="x", padx=15)

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

    def _set_check(self, parent, attr, label):
        var = tk.BooleanVar(value=bool(getattr(self.drafts.settings, attr)))
        self._set_vars[attr] = var

        def on_write(*_):
            setattr(self.drafts.settings, attr, var.get())
            self.refresh_info()
        var.trace_add("write", on_write)
        return tk.Checkbutton(parent, text=label, variable=var, font=FONT)

    def _set_entry(self, parent, attr):
        var = tk.StringVar(value=getattr(self.drafts.settings, attr))
        self._set_vars[attr] = var

        def on_write(*_):
            setattr(self.drafts.settings, attr, var.get())
            self.refresh_info()
        var.trace_add("write", on_write)
        return tk.Entry(parent, textvariable=var, width=ENTRY_W, font=FONT)

    # ------------------------------------------------------------------ 층수
    def _read_floor_count(self):
        try:
            n = int(self.entries['floors'].get().strip())
        except (KeyError, ValueError):
            return None
        return n if 1 <= n <= 20 else None

    def update_floor_ui(self):
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

    def floor_choices(self) -> list[str]:
        return [floor_label(self.floor_count, n) for n in range(1, self.floor_count + 1)]

    def _start(self) -> float:
        try:
            return float(self.entries['start_station'].get())
        except (KeyError, ValueError):
            return 0.0

    # ------------------------------------------------------------------ 편집 동작
    def add_path(self):
        self.drafts.items.append(default_path(1, self._start() + 20.0, 6.0))
        self.render()

    def remove_path(self, idx):
        del self.drafts.items[idx]
        self.render()

    def add_vertex(self, idx):
        vs = self.drafts.items[idx].vertices
        last = vs[-1] if vs else TactilePointDraft()
        vs.append(TactilePointDraft(last.x, last.y))
        self.render()

    def remove_vertex(self, idx, j):
        vs = self.drafts.items[idx].vertices
        if len(vs) > 2:
            del vs[j]
            self.render()

    def set_floor(self, idx, floor_n: int):
        self.drafts.items[idx].floor = floor_n
        self.refresh_info()

    def pick_path(self, idx):
        """미리보기 평면에서 경로 꼭짓점 선택 (직교 모드면 선형·직각 방향)"""
        it = self.drafts.items[idx]

        def done(pts):
            base = self._start()
            it.vertices[:] = [TactilePointDraft(num(base + s), num(t)) for s, t in pts]
            self.render()
        PB.request(self, PATH, it.floor, f"유도블록 경로 {idx + 1}", done)

    # ------------------------------------------------------------------ 그리기
    def render(self):
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        self._vars.clear()
        self._combos.clear()
        if not self.drafts.items:
            tk.Label(self.body, text="유도 경로 없음", fg="#888888", font=FONT).pack(anchor="w", padx=8, pady=6)
        for i, it in enumerate(self.drafts.items):
            self._build_path(i, it)
        for attr, var in self._set_vars.items():          # 프로젝트를 열면 설정 초안이 바뀜
            v = getattr(self.drafts.settings, attr)
            if var.get() != v:
                var.set(v)
        self.refresh_info()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _build_path(self, i, it):
        box = tk.LabelFrame(self.body, text=f" 유도 경로 {i + 1} ", font=FONT_B, fg="#F57F17", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=5)
        top = tk.Frame(box)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT).pack(side="left")
        self._entry(top, it, "name", (i, "name"), 6).pack(side="left", padx=(2, 6))
        tk.Label(top, text="층", font=FONT).pack(side="left")
        floors = self.floor_choices()
        c = ttk.Combobox(top, values=floors, state="readonly", width=6, font=FONT)
        c.set(floors[min(it.floor, len(floors)) - 1])
        c.bind("<<ComboboxSelected>>", lambda e, cc=c, k=i: self.set_floor(k, cc.current() + 1))
        c.pack(side="left", padx=(2, 6))
        self._combos[(i, "floor")] = c
        tk.Label(top, text="폭(비우면 블록 크기)", font=FONT).pack(side="left")
        self._entry(top, it, "width", (i, "width"), 5).pack(side="left", padx=(2, 0))
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_path(i)).pack(side="right")

        table = tk.Frame(box)
        table.pack(fill="x", pady=(4, 0))
        for col, head in enumerate(("#", "STA", "t (왼쪽 +)")):
            tk.Label(table, text=head, font=("Malgun Gothic", 8), fg="#555555").grid(row=0, column=col, sticky="w")
        for j, v in enumerate(it.vertices):
            tk.Label(table, text=str(j + 1), font=FONT).grid(row=j + 1, column=0, sticky="w")
            for col, attr in enumerate(("x", "y"), start=1):
                self._entry(table, v, attr, (i, "v", j, attr), 10).grid(row=j + 1, column=col, padx=(2, 4), pady=1)
            tk.Button(table, text="−", font=FONT, width=2, command=lambda k=i, jj=j: self.remove_vertex(k, jj)).grid(
                row=j + 1, column=3)
        brow = tk.Frame(box)
        brow.pack(fill="x", pady=(2, 0))
        tk.Button(brow, text="+ 꼭짓점", font=FONT, command=lambda k=i: self.add_vertex(k)).pack(side="left")
        PB.button(brow, "경로 선택 (미리보기에서 클릭)", lambda k=i: self.pick_path(k)).pack(side="left", padx=(6, 0))

    def _entry(self, parent, obj, attr, key, width):
        var = tk.StringVar(value=getattr(obj, attr))
        self._vars[key] = var

        def on_write(*_):
            setattr(obj, attr, var.get())
            self.refresh_info()
        var.trace_add("write", on_write)
        return tk.Entry(parent, textvariable=var, width=width, font=FONT)

    def refresh_info(self):
        if hasattr(self, "info_var"):
            self.info_var.set(preview(self.drafts, self._start()))
