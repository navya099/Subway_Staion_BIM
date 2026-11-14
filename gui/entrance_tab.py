import tkinter as tk
from tkinter import ttk

from gui.entrance_draft import NUM_FIELDS, SIDES, EntranceDraft, EntranceDrafts, preview

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 8


class EntranceTab:
    """탭 9: 출입구 (출구통로 끝에 이어 지표까지 오르는 경사 박스 + 계단 + 에스컬레이터)

    - 통로 이름과 지표 EL 만 주면 계단 단수·계단참, 에스컬레이터 WP, 박스 길이·천장 높이를 모두 자동 계산
    - 계단 시작 위치는 비워 두면 자동 (계단이 바닥 아래로 가면 하부 수평부 쪽으로 앞당김)
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = EntranceDrafts()
        self.entries['entrance_drafts'] = self.drafts
        self._vars = {}            # (번호, 필드) → StringVar / BooleanVar
        self._info_vars = []
        self._combos = {}

    def build(self):
        tk.Label(self.parent, text="[ 출입구 ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#6A1B9A").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=430,
                 text="• 출구통로 끝(마지막 꼭짓점)에 이어 통로 방향으로 지표까지 오름\n"
                      "• 지표 EL 만 주면 계단·에스컬레이터·박스 길이·천장 높이 자동\n"
                      "• 천장은 지표에 닿는 곳에서 끝나고 그 뒤는 개구부 (측벽은 지표 + 파라펫)\n"
                      "• 계단 시작 조정을 비우면 자동 (바닥 아래로 가면 하부 쪽으로 앞당김)").pack(anchor="w", padx=15)
        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        tk.Button(bar, text="+ 출입구 추가", font=FONT, command=self.add_entrance).pack(side="left")
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
        self.render()

    def _bind_wheel(self, on: bool):
        if on:
            self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
        else:
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.canvas.unbind_all(ev)

    # ------------------------------------------------------------------ 편집 동작
    def add_entrance(self):
        passages = self.entries.get('passage_drafts')
        name = "EX1"
        if passages is not None and passages.items:            # 마지막 통로에 붙이는 것을 기본으로
            i = len(passages.items)
            name = passages.items[-1].name.strip() or f"EX{i}"
        self.drafts.items.append(EntranceDraft(passage=name))
        self.render()

    def remove_entrance(self, idx):
        del self.drafts.items[idx]
        self.render()

    def set_side(self, idx, label: str):
        self.drafts.items[idx].side = label
        self.refresh_info()

    def render(self):
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        self._vars.clear()
        self._info_vars.clear()
        self._combos.clear()
        if not self.drafts.items:
            tk.Label(self.body, text="출입구 없음", fg="#888888", font=FONT).pack(anchor="w", padx=8, pady=6)
        for i, it in enumerate(self.drafts.items):
            self._build_entrance(i, it)
        self.count_var.set(f"출입구 {len(self.drafts.items)}개" if self.drafts.items else "")
        self.refresh_info()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _build_entrance(self, i, it: EntranceDraft):
        box = tk.LabelFrame(self.body, text=f" 출입구 {i + 1} ", font=FONT_B, fg="#4A148C", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=5)
        top = tk.Frame(box)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT).pack(side="left")
        self._entry(top, it, "name", (i, "name"), 6).pack(side="left", padx=(2, 6))
        tk.Label(top, text="통로", font=FONT).pack(side="left")
        self._entry(top, it, "passage", (i, "passage"), 6).pack(side="left", padx=(2, 0))
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_entrance(i)).pack(side="right")

        row = tk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        var = tk.BooleanVar(value=it.escalator)
        self._vars[(i, "escalator")] = var

        def on_esc(*_, obj=it, v=var):
            obj.escalator = v.get()
            self.refresh_info()
        var.trace_add("write", on_esc)
        tk.Checkbutton(row, text="에스컬레이터", variable=var, font=FONT).pack(side="left")
        tk.Label(row, text="쪽", font=FONT).pack(side="left", padx=(8, 0))
        c = ttk.Combobox(row, values=SIDES, state="readonly", width=10, font=FONT)
        c.set(it.side if it.side in SIDES else SIDES[0])
        c.bind("<<ComboboxSelected>>", lambda e, cc=c, k=i: self.set_side(k, cc.get()))
        c.pack(side="left", padx=(2, 0))
        self._combos[(i, "side")] = c

        grid = tk.Frame(box)
        grid.pack(fill="x", pady=(4, 0))
        fields = [(attr, label) for attr, label, _ in NUM_FIELDS] + [("stair_offset", "계단 시작 조정")]
        for k, (attr, label) in enumerate(fields):
            r, col = divmod(k, 2)
            tk.Label(grid, text=label, font=FONT).grid(row=r, column=col * 2, sticky="w")
            self._entry(grid, it, attr, (i, attr), ENTRY_W).grid(row=r, column=col * 2 + 1, padx=(2, 12), pady=1)

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
        for var, it in self._info_vars:
            var.set(preview(it))
