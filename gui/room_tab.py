import tkinter as tk
from tkinter import ttk

from gui.column_draft import level_name
from gui.room_draft import RoomDraft, RoomDrafts, preview
from rooms.room_spec import ROOM_USES, RoomSettings

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 8


class RoomTab:
    """탭 4: 실(구획). 층별로 사각형 실을 입력하면 나머지는 그 층 기본 실, 실 경계에는 칸막이벽이 자동으로 선다.

    - 실 범위 = 칸막이벽 중심선 (STA 범위 × t 범위, t 는 왼쪽 +). 본체 벽 위 변에는 칸막이벽이 생기지 않음
    - 용도는 목록에서 고르거나 직접 입력 (나중에 용도별 마감을 연결)
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = RoomDrafts()
        self.entries['room_drafts'] = self.drafts
        self.floor_count = 0
        self._vars = {}            # (번호, 필드) → StringVar,  ('default', 층) → StringVar,  'partition_t' → StringVar
        self._info_vars = []
        self._combos = {}          # (번호, 'floor'|'use') / ('default', 층) → Combobox

    # ------------------------------------------------------------------ 구성
    def build(self):
        tk.Label(self.parent, text="[ 실 (구획) ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#2E7D32").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=470,
                 text="• 실 = 층별 사각형 (STA 범위 × t 범위, 칸막이벽 중심선 기준, t 는 왼쪽 +)\n"
                      "• 입력하지 않은 나머지 영역은 그 층의 기본 실. 실 경계에는 칸막이벽 자동 (본체 벽 위 변은 제외)\n"
                      "• 용도는 목록에서 고르거나 직접 입력 (마감은 용도별로 다음 단계에서 연결)").pack(anchor="w", padx=15)

        top = tk.LabelFrame(self.parent, text=" 공통 설정 ", font=FONT_B, fg="#2E7D32", padx=8, pady=4)
        top.pack(fill="x", padx=15, pady=(6, 0))
        row = tk.Frame(top)
        row.pack(fill="x")
        tk.Label(row, text="칸막이벽 두께 (m)", font=FONT).pack(side="left")
        var = tk.StringVar(value=self.drafts.settings.partition_t)
        self._vars["partition_t"] = var

        def on_pt(*_):
            self.drafts.settings.partition_t = var.get()
            self.refresh_info()
        var.trace_add("write", on_pt)
        tk.Entry(row, textvariable=var, width=ENTRY_W, font=FONT).pack(side="left", padx=4)
        self.default_frame = tk.Frame(top)
        self.default_frame.pack(fill="x", pady=(4, 0))

        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        tk.Button(bar, text="+ 실 추가", font=FONT, command=self.add_room).pack(side="left")
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

    def floor_names(self) -> list[str]:
        return [level_name(self.floor_count, k) for k in range(1, self.floor_count + 1)]

    # ------------------------------------------------------------------ 편집 동작
    def add_room(self):
        top = max(1, self.floor_count)
        sta = self._start_station() + 10.0
        self.drafts.items.append(RoomDraft(floor=top, sta0=f"{sta:g}", sta1=f"{sta + 15.0:g}"))
        self.render()

    def remove_room(self, idx):
        del self.drafts.items[idx]
        self.render()

    def set_floor(self, idx, floor_n: int):
        self.drafts.items[idx].floor = floor_n
        self.refresh_info()

    def set_use(self, idx, use: str):
        self.drafts.items[idx].use = use
        self.refresh_info()

    def set_default_use(self, floor_n: int, use: str):
        self.drafts.settings.default_uses[str(floor_n)] = use

    # ------------------------------------------------------------------ 그리기
    def render(self):
        self._render_defaults()
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        for k in [k for k in self._vars if k != "partition_t" and not (isinstance(k, tuple) and k[0] == "default")]:
            del self._vars[k]
        self._info_vars.clear()
        for k in [k for k in self._combos if k[0] != "default"]:
            del self._combos[k]
        if "partition_t" in self._vars and self._vars["partition_t"].get() != self.drafts.settings.partition_t:
            self._vars["partition_t"].set(self.drafts.settings.partition_t)
        if not self.drafts.items:
            tk.Label(self.body, text="입력한 실 없음 (층마다 기본 실 하나)", fg="#888888", font=FONT).pack(anchor="w", padx=8, pady=6)
        for i, it in enumerate(self.drafts.items):
            self._build_room(i, it)
        self.count_var.set(f"실 {len(self.drafts.items)}개" if self.drafts.items else "")
        self.refresh_info()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _render_defaults(self):
        """층별 기본 실 용도 (위층부터). 비우면 자동: 최하층 = 승강장층, 그 위 = 대합실"""
        if not hasattr(self, "default_frame"):
            return
        for w in self.default_frame.winfo_children():
            w.destroy()
        for k in [k for k in self._combos if k[0] == "default"]:
            del self._combos[k]
        for k in [k for k in self._vars if isinstance(k, tuple) and k[0] == "default"]:
            del self._vars[k]
        tk.Label(self.default_frame, text="층별 기본 실", font=FONT).grid(row=0, column=0, sticky="w", padx=(0, 6))
        auto = RoomSettings()
        for col, n in enumerate(range(self.floor_count, 0, -1)):
            tk.Label(self.default_frame, text=level_name(self.floor_count, n), font=FONT).grid(row=0, column=1 + 2 * col, sticky="e")
            var = tk.StringVar(value=self.drafts.settings.default_uses.get(str(n)) or auto.default_use(n))
            self._vars[("default", n)] = var                         # 목록 선택·직접 입력 모두 변수 변경으로 반영
            var.trace_add("write", lambda *_, v=var, k=n: self.set_default_use(k, v.get()))
            c = ttk.Combobox(self.default_frame, values=ROOM_USES, width=7, font=FONT, textvariable=var)
            c.grid(row=0, column=2 + 2 * col, padx=(2, 6))
            self._combos[("default", n)] = c

    def _build_room(self, i, it: RoomDraft):
        box = tk.LabelFrame(self.body, text=f" 실 {i + 1} ", font=FONT_B, fg="#1B5E20", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=4)
        top = tk.Frame(box)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT).pack(side="left")
        self._entry(top, it, "name", (i, "name"), 8).pack(side="left", padx=(2, 6))
        tk.Label(top, text="층", font=FONT).pack(side="left")
        floors = self.floor_names()
        fc = ttk.Combobox(top, values=floors, state="readonly", width=5, font=FONT)
        fc.current(min(it.floor, len(floors)) - 1)
        fc.bind("<<ComboboxSelected>>", lambda e, c=fc, k=i: self.set_floor(k, c.current() + 1))
        fc.pack(side="left", padx=(2, 6))
        self._combos[(i, "floor")] = fc
        tk.Label(top, text="용도", font=FONT).pack(side="left")
        uvar = tk.StringVar(value=it.use)
        self._vars[(i, "use")] = uvar
        uvar.trace_add("write", lambda *_, v=uvar, k=i: self.set_use(k, v.get()))
        uc = ttk.Combobox(top, values=ROOM_USES, width=8, font=FONT, textvariable=uvar)   # 목록 선택 또는 직접 입력
        uc.pack(side="left", padx=(2, 0))
        self._combos[(i, "use")] = uc
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_room(i)).pack(side="right")

        grid = tk.Frame(box)
        grid.pack(fill="x", pady=(4, 0))
        for r, (l1, a1, l2, a2) in enumerate((("시작 STA", "sta0", "끝 STA", "sta1"), ("t 시작 (−)", "t0", "t 끝 (+)", "t1"))):
            tk.Label(grid, text=l1, font=FONT).grid(row=r, column=0, sticky="w")
            self._entry(grid, it, a1, (i, a1), ENTRY_W + 2).grid(row=r, column=1, padx=(2, 12), pady=1)
            tk.Label(grid, text=l2, font=FONT).grid(row=r, column=2, sticky="w")
            self._entry(grid, it, a2, (i, a2), ENTRY_W + 2).grid(row=r, column=3, padx=(2, 0), pady=1)
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
        start = self._start_station()
        n = max(1, self.floor_count)
        for var, it in self._info_vars:
            var.set(preview(it, start, n))
