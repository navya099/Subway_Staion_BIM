import tkinter as tk
from tkinter import ttk

from gui.passage_draft import COLUMN_LABELS, MODES, VertexDraft, floor_label
from gui.vent_draft import NUM_FIELDS, VentDraft, VentDrafts, default_draft, preview

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 8

# 단면·그릴 입력칸 (2열 배치): 련 수 + 숫자 칸 + 수직구 깊이
_CELLS = [("cells", "련 수")] + [(a, lb) for a, lb, _ in NUM_FIELDS] + [("shaft_depth", "수직구 깊이")]


class VentTab:
    """탭 9: 환기구 (출구통로와 같은 경로 입력 + 연속박스(n련) 단면 + 수직구 + 끝 그릴)

    - 경로 규칙은 출구통로와 같음. 평면 위치가 같고 높이만 다른 연속 두 꼭짓점 = 수직 구간(위로만)
    - 수직구 깊이를 비우면 칸 높이, 그릴은 경로 마지막 끝면(수직구면 상단, 덕트면 끝 단면) 칸마다
    - 본체 측벽에는 칸마다 오프닝이 자동으로 뚫림
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = VentDrafts()
        self.entries['vent_drafts'] = self.drafts
        self.floor_count = 0
        self._vars = {}            # 테스트/갱신용: (번호, 필드) → StringVar,  (번호, 'v', 꼭짓점, 'x'|'y'|'z') → StringVar
        self._info_vars = []       # (StringVar, VentDraft) 미리보기
        self._combos = {}          # (번호, 'floor'|'mode') → Combobox

    # ------------------------------------------------------------------ 구성
    def build(self):
        tk.Label(self.parent, text="[ 환기구 ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#00695C").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=430,
                 text="• 경로는 출구통로와 같음 (첫 꼭짓점 = 측벽 바깥면, 첫 구간 직각, 첫 높이는 비우면 FL)\n"
                      "• 같은 평면 위치에 높이만 다른 꼭짓점을 이어 넣으면 수직구 (위로만, 앞뒤 덕트는 수평)\n"
                      "• 수직구 위로 이어지는 덕트는 아래 덕트와 같은 선(같은/반대 방향)\n"
                      "• 단면 = n련 연속박스, 경로 마지막 끝면에 칸마다 금속 그릴").pack(anchor="w", padx=15)

        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        tk.Button(bar, text="+ 환기구 추가", font=FONT, command=self.add_vent).pack(side="left")
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

    def _float(self, key, default):
        try:
            return float(self.entries[key].get())
        except (KeyError, ValueError):
            return default

    def _t_face(self, floor_n: int) -> float:
        """그 층 외벽 바깥면의 t (내공 폭/2 + 외벽 두께). 입력이 비어 있으면 기본값"""
        return self._float('width', 18.0) / 2.0 + self._float(f'wall_t_{floor_n}', 1.0)

    def floor_choices(self) -> list[str]:
        return [floor_label(self.floor_count, n) for n in range(1, self.floor_count + 1)]

    # ------------------------------------------------------------------ 편집 동작
    def add_vent(self):
        top = max(1, self.floor_count)                       # 환기구는 보통 대합실(최상층) 측벽에 붙음
        sta = self._float('start_station', 0.0) + 60.0
        self.drafts.items.append(default_draft(top, sta, self._t_face(top)))
        self.render()

    def remove_vent(self, idx):
        del self.drafts.items[idx]
        self.render()

    def add_vertex(self, idx):
        vs = self.drafts.items[idx].vertices
        last = vs[-1] if vs else VertexDraft()
        vs.append(VertexDraft(last.x, last.y, last.z or "0"))         # 마지막 꼭짓점을 복사해 이어서 편집
        self.render()

    def remove_vertex(self, idx, j):
        vs = self.drafts.items[idx].vertices
        if len(vs) > 2:                                              # 경로는 꼭짓점 2개 이상
            del vs[j]
            self.render()

    def set_floor(self, idx, floor_n: int):
        self.drafts.items[idx].floor = floor_n
        self.refresh_info()

    def set_mode(self, idx, label: str):
        self.drafts.items[idx].mode = label
        self.render()                                                # 꼭짓점 표 머리글이 바뀜

    # ------------------------------------------------------------------ 그리기
    def render(self):
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        self._vars.clear()
        self._info_vars.clear()
        self._combos.clear()
        if not self.drafts.items:
            tk.Label(self.body, text="환기구 없음", fg="#888888", font=FONT).pack(anchor="w", padx=8, pady=6)
        for i, it in enumerate(self.drafts.items):
            self._build_vent(i, it)
        self.count_var.set(f"환기구 {len(self.drafts.items)}개" if self.drafts.items else "")
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

    def _build_vent(self, i, it: VentDraft):
        box = tk.LabelFrame(self.body, text=f" 환기구 {i + 1} ", font=FONT_B, fg="#004D40", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=5)

        top = tk.Frame(box)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT).pack(side="left")
        self._entry(top, it, "name", (i, "name"), width=6).pack(side="left", padx=(2, 6))
        tk.Label(top, text="층", font=FONT).pack(side="left")
        floors = self.floor_choices()
        self._combo(top, i, "floor", floors, floors[min(it.floor, len(floors)) - 1],
                    lambda c, k=i: self.set_floor(k, c.current() + 1), width=6).pack(side="left", padx=(2, 0))
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_vent(i)).pack(side="right")

        grid = tk.Frame(box)
        grid.pack(fill="x", pady=(4, 0))
        for n, (attr, label) in enumerate(_CELLS):
            r, col = divmod(n, 2)
            tk.Label(grid, text=label, font=FONT).grid(row=r, column=col * 2, sticky="w")
            self._entry(grid, it, attr, (i, attr), width=ENTRY_W).grid(row=r, column=col * 2 + 1, padx=(2, 12), pady=1)

        row = tk.Frame(box)
        row.pack(fill="x", pady=(6, 0))
        tk.Label(row, text="경로 좌표", font=FONT_B).pack(side="left")
        mode = it.mode if it.mode in MODES else MODES[0]
        self._combo(row, i, "mode", MODES, mode, lambda c, k=i: self.set_mode(k, c.get()),
                    width=22).pack(side="left", padx=(4, 0))

        table = tk.Frame(box)
        table.pack(fill="x", pady=(2, 0))
        for c, head in enumerate(("#",) + COLUMN_LABELS[mode]):
            tk.Label(table, text=head, font=("Malgun Gothic", 8), fg="#555555").grid(row=0, column=c, sticky="w")
        for j, v in enumerate(it.vertices):
            tk.Label(table, text=str(j + 1), font=FONT).grid(row=j + 1, column=0, sticky="w")
            for c, attr in enumerate(("x", "y", "z"), start=1):
                self._entry(table, v, attr, (i, "v", j, attr), width=10).grid(row=j + 1, column=c, padx=(2, 4), pady=1)
            tk.Button(table, text="−", font=FONT, width=2, command=lambda k=i, jj=j: self.remove_vertex(k, jj)).grid(
                row=j + 1, column=4)
        tk.Button(box, text="+ 꼭짓점", font=FONT, command=lambda k=i: self.add_vertex(k)).pack(anchor="w", pady=(2, 0))

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
        """환기구별 미리보기: 단면 구성, 꼭짓점·수직 구간 수, 그릴 위치"""
        start = self._float('start_station', 0.0)
        for var, it in self._info_vars:
            var.set(preview(it, start))
