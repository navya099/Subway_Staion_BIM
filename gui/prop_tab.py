import copy
import tkinter as tk
from tkinter import ttk

from gui import pick_buttons as PB
from gui.passage_draft import floor_label
from gui.prop_draft import ANGLES, KIND_CODES, KIND_LABELS, PropDrafts, new_draft, preview, titles
from preview.pick import POINT
from props.prop_kinds import KINDS, TEXT

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")


class PropTab:
    """탭 16: 비품 (의자·쓰레기통·소화기·발매기·게이트·옥내소화전·점검구·매달림 안내사인)

    - 종류를 골라 추가하고 [위치 선택] 으로 미리보기 평면에서 놓을 점을 고름 (앞면 방향은 따로)
    - 벽에 붙는 종류는 고른 점에서 0.5m 안의 가장 가까운 벽 마감 표면에 붙음 (방향 자동)
    - 벽·기둥·문·다른 비품과 겹치면 모델을 만들 때 오류
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = PropDrafts()
        self.entries['prop_drafts'] = self.drafts
        self.floor_count = 0
        self._vars = {}            # (번호, 속성) / (번호, 'v', 치수 키) → StringVar
        self._combos = {}          # (번호, 'kind'|'floor'|'angle')
        self._titles = []          # 제목 LabelFrame
        self._open = set()         # 치수를 펼친 초안 id

    # ------------------------------------------------------------------ 구성
    def build(self):
        tk.Label(self.parent, text="[ 비품 ]", font=("Malgun Gothic", 10, "bold"), fg="#4E342E").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=620,
                 text="• 종류를 골라 추가하고 [위치 선택]으로 미리보기 평면에서 놓을 점을 고름 (STA·t = 비품 중심)\n"
                      "• 옥내소화전·벽 점검구는 고른 점에서 0.5m 안의 가장 가까운 벽 마감 표면에 붙음 (방향 자동)\n"
                      "• 높이는 그 자리 바닥 마감면(천장 점검구는 천장판) 기준 자동. 벽·기둥·문·다른 비품과 겹치면 오류").pack(anchor="w", padx=15)
        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        tk.Label(bar, text="종류", font=FONT).pack(side="left")
        self.new_kind = ttk.Combobox(bar, values=KIND_LABELS, state="readonly", width=16, font=FONT)
        self.new_kind.current(0)
        self.new_kind.pack(side="left", padx=(2, 8))
        tk.Label(bar, text="층", font=FONT).pack(side="left")
        self.new_floor = ttk.Combobox(bar, values=[], state="readonly", width=6, font=FONT)
        self.new_floor.pack(side="left", padx=(2, 8))
        tk.Button(bar, text="+ 추가", font=FONT, command=self.add_prop).pack(side="left")
        PB.button(bar, "추가할 위치 선택", self.pick_new).pack(side="left", padx=(6, 0))
        self.info_var = tk.StringVar(value="")
        tk.Label(self.parent, textvariable=self.info_var, font=FONT, fg="#1565C0", anchor="w", justify="left", wraplength=640).pack(
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
        n = self._read_floor_count() or self.floor_count or 1
        if n == self.floor_count:
            return
        self.drafts.ensure_floors(n)
        self.floor_count = n
        floors = self.floor_choices()
        cur = self.new_floor.current()
        self.new_floor.configure(values=floors)
        self.new_floor.current(min(max(cur, 0), len(floors) - 1))
        self.render()

    def floor_choices(self) -> list:
        return [floor_label(self.floor_count, n) for n in range(1, self.floor_count + 1)]

    # ------------------------------------------------------------------ 편집 동작
    def _add(self, sta, t=0.0):
        self.drafts.items.append(new_draft(KIND_CODES[self.new_kind.current()], self.new_floor.current() + 1, sta, t))
        self.render()
        self.canvas.yview_moveto(1.0)

    def add_prop(self):
        self._add(PB.base_station(self.entries) + 20.0)

    def pick_new(self):
        """미리보기에서 점을 고르면 그 자리에 새 비품"""
        label = KIND_LABELS[self.new_kind.current()]
        PB.request(self, POINT, self.new_floor.current() + 1, f"{label} 놓을 위치",
                   lambda pts: self._add(PB.base_station(self.entries) + pts[0][0], pts[0][1]))

    def remove_prop(self, i):
        del self.drafts.items[i]
        self.render()

    def copy_prop(self, i):
        """바로 아래에 복제 (이름은 자동 — 위치는 다시 골라야 겹치지 않음)"""
        it = copy.deepcopy(self.drafts.items[i])
        it.name = ""
        self.drafts.items.insert(i + 1, it)
        self.render()

    def set_kind(self, i, kind):
        self.drafts.items[i].set_kind(kind)
        self.render()

    def set_floor(self, i, n):
        self.drafts.items[i].floor = n
        self.refresh_info()

    def toggle(self, i):
        self._open ^= {id(self.drafts.items[i])}
        self.render()

    def pick_position(self, i):
        PB.pick_point(self, i, f"비품 {titles(self.drafts)[i]} 위치", self.drafts.items[i].floor, "sta", "t")

    # ------------------------------------------------------------------ 그리기
    def render(self):
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        self._vars.clear()
        self._combos.clear()
        self._titles = []
        self._open &= {id(it) for it in self.drafts.items}
        if not self.drafts.items:
            tk.Label(self.body, text="비품 없음", fg="#888888", font=FONT).pack(anchor="w", padx=8, pady=6)
        for i, it in enumerate(self.drafts.items):
            self._build_item(i, it)
        self.refresh_info()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _build_item(self, i, it):
        box = tk.LabelFrame(self.body, text="", font=FONT_B, fg="#4E342E", padx=6, pady=3)
        box.pack(fill="x", padx=(5, 8), pady=4)
        self._titles.append(box)
        row = tk.Frame(box)
        row.pack(fill="x")
        c = ttk.Combobox(row, values=KIND_LABELS, state="readonly", width=15, font=FONT)
        if it.kind in KIND_CODES:
            c.current(KIND_CODES.index(it.kind))
        c.bind("<<ComboboxSelected>>", lambda e: self.set_kind(i, KIND_CODES[c.current()]))
        c.pack(side="left")
        self._combos[(i, "kind")] = c
        tk.Label(row, text="이름", font=FONT).pack(side="left", padx=(6, 2))
        self._entry(row, i, it, "name", 12).pack(side="left")
        tk.Label(row, text="층", font=FONT).pack(side="left", padx=(6, 2))
        floors = self.floor_choices()
        f = ttk.Combobox(row, values=floors, state="readonly", width=5, font=FONT)
        f.current(min(it.floor, len(floors)) - 1)
        f.bind("<<ComboboxSelected>>", lambda e: self.set_floor(i, f.current() + 1))
        f.pack(side="left")
        self._combos[(i, "floor")] = f
        tk.Button(row, text="삭제", font=FONT, command=lambda: self.remove_prop(i)).pack(side="right")
        tk.Button(row, text="복제", font=FONT, command=lambda: self.copy_prop(i)).pack(side="right", padx=3)

        row = tk.Frame(box)
        row.pack(fill="x", pady=(3, 0))
        tk.Label(row, text="STA", font=FONT).pack(side="left")
        self._entry(row, i, it, "sta", 9).pack(side="left", padx=(2, 6))
        tk.Label(row, text="t", font=FONT).pack(side="left")
        self._entry(row, i, it, "t", 7).pack(side="left", padx=(2, 6))
        if it.is_wall:
            tk.Label(row, text="방향 자동 (벽)", font=FONT, fg="#777777").pack(side="left")
        else:
            tk.Label(row, text="앞면 방향", font=FONT).pack(side="left")
            a = ttk.Combobox(row, values=ANGLES, textvariable=self._var((i, "angle"), it.angle, lambda v: setattr(it, "angle", v)),
                             width=14, font=FONT)
            a.pack(side="left", padx=(2, 0))
            self._combos[(i, "angle")] = a
        PB.button(row, "위치 선택", lambda: self.pick_position(i)).pack(side="left", padx=(8, 0))
        opened = id(it) in self._open
        tk.Button(row, text="치수 ▲" if opened else "치수 ▼", font=FONT, command=lambda: self.toggle(i)).pack(side="right")
        if opened and it.kind in KINDS:
            self._build_values(tk.Frame(box), i, it)

    def _build_values(self, grid, i, it):
        grid.pack(fill="x", pady=(3, 0))
        r = col = 0
        for fl in KINDS[it.kind].fields:
            wide = fl.type == TEXT
            if col and (wide or col >= 6):
                r, col = r + 1, 0
            tk.Label(grid, text=fl.label, font=FONT).grid(row=r, column=col, sticky="w", padx=(0 if col == 0 else 8, 2), pady=1)
            var = self._var((i, "v", fl.key), it.values.get(fl.key, ""), lambda v, k=fl.key: it.values.__setitem__(k, v))
            tk.Entry(grid, textvariable=var, width=34 if wide else 7, font=FONT).grid(row=r, column=col + 1, sticky="w", columnspan=5 if wide else 1)
            col += 6 if wide else 2

    def _var(self, key, value, setter):
        var = tk.StringVar(value=value)
        self._vars[key] = var

        def on_write(*_):
            setter(var.get())
            self.refresh_info()
        var.trace_add("write", on_write)
        return var

    def _entry(self, parent, i, it, attr, width):
        return tk.Entry(parent, textvariable=self._var((i, attr), getattr(it, attr), lambda v: setattr(it, attr, v)), width=width, font=FONT)

    def refresh_info(self):
        if not hasattr(self, "info_var"):
            return
        self.info_var.set(preview(self.drafts, PB.base_station(self.entries)))
        for box, name in zip(self._titles, titles(self.drafts)):
            box.configure(text=f" {name} ")
