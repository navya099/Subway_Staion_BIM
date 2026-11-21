import tkinter as tk
from tkinter import ttk

from gui.finish_draft import (FACE_FIELD, PFACE_FIELD, FILL_LABELS, FRAME_LABELS, NUM_FIELDS, STAIR_NUM_FIELDS, STAIR_TEXT_FIELDS,
                              STEP_LABELS, TEXT_FIELDS, FinishDrafts, FinishTypeDraft, preview, stair_preview)

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 8


class FinishTab:
    """탭 5: 마감 (용도별 마감표). 실은 용도 이름과 같은 마감 종류를 쓰고, 실 탭에서 실마다 다른 종류로 바꿀 수 있다.

    - 바닥: 마감 높이(구조 바닥 → 마감면) + 마감재 두께 + 그 아래 몰탈 채움 / 빈 공간(액세스 플로어)
    - 벽: 두께(0 = 면처리) + 재질. 천장: 마감면 + 천장 높이, 천장판·천장틀(M/T바, 간격)
    """

    def __init__(self, parent, entries_dict, on_names_changed=None):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = FinishDrafts()
        self.entries['finish_drafts'] = self.drafts
        self.on_names_changed = on_names_changed      # 마감 종류 이름이 바뀌면 실 탭의 덮어쓰기 목록 갱신
        self._vars = {}                               # 'enabled' / (번호, 필드) → tk 변수
        self._info_vars = []
        self._combos = {}

    def build(self):
        tk.Label(self.parent, text="[ 마감 (용도별 마감표) ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#2E7D32").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=510,
                 text="• 실은 용도와 같은 이름의 마감 종류를 씀 (없으면 '기본'). 실 탭에서 실마다 다른 종류로 바꿀 수 있음\n"
                      "• 바닥: 마감 높이(구조 바닥 상면 → 마감면) · 마감재 두께 · 그 아래 몰탈 채움 / 빈 공간(액세스 플로어)\n"
                      "• 벽: 두께 0 = 면처리(형상 없음). 본체 벽·칸막이벽·기둥·승강로 바깥면, 문·통로 자리 비움\n"
                      "• 천장: 바닥 마감면 + 천장 높이 = 천장판 하면. 천장판 + 천장틀(M/T바 간격, 캐링 채널)").pack(anchor="w", padx=15)
        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        var = tk.BooleanVar(value=self.drafts.enabled)
        self._vars["enabled"] = var
        var.trace_add("write", lambda *_: setattr(self.drafts, "enabled", bool(var.get())))
        tk.Checkbutton(bar, text="마감 생성", variable=var, font=FONT_B).pack(side="left")
        tk.Button(bar, text="+ 마감 종류 추가", font=FONT, command=self.add_type).pack(side="left", padx=8)

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

    # ------------------------------------------------------------------ 편집
    def add_type(self):
        k = 1
        while f"마감{k}" in self.drafts.names():
            k += 1
        self.drafts.items.append(FinishTypeDraft(name=f"마감{k}"))
        self.render()
        self._names_changed()

    def remove_type(self, i):
        del self.drafts.items[i]
        self.render()
        self._names_changed()

    def _names_changed(self):
        if self.on_names_changed:
            self.on_names_changed()

    # ------------------------------------------------------------------ 그리기
    def render(self):
        if "enabled" in self._vars and self._vars["enabled"].get() != self.drafts.enabled:
            self._vars["enabled"].set(self.drafts.enabled)
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        for k in [k for k in self._vars if k != "enabled"]:
            del self._vars[k]
        self._info_vars.clear()
        self._combos.clear()
        self._build_stair(self.drafts.stair)
        for i, it in enumerate(self.drafts.items):
            self._build_type(i, it)
        self.refresh_info()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _build_type(self, i, it: FinishTypeDraft):
        box = tk.LabelFrame(self.body, text=f" {it.name} ", font=FONT_B, fg="#1B5E20", padx=6, pady=3)
        box.pack(fill="x", padx=(5, 8), pady=3)
        top = tk.Frame(box)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT).pack(side="left")
        e = self._entry(top, it, "name", (i, "name"), 12)
        e.pack(side="left", padx=(2, 8))
        e.bind("<FocusOut>", lambda ev: self._names_changed())
        tk.Label(top, text="바닥 채움", font=FONT).pack(side="left")
        self._combo(top, i, "fill", list(FILL_LABELS), it.fill, it, 17).pack(side="left", padx=(2, 0))
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_type(i)).pack(side="right")

        grid = tk.Frame(box)
        grid.pack(fill="x", pady=(3, 0))
        cells = ([(a, lb, ENTRY_W) for a, lb, _ in NUM_FIELDS[:3]] + [(FACE_FIELD[0], FACE_FIELD[1], ENTRY_W),
                                                                      (PFACE_FIELD[0], PFACE_FIELD[1], ENTRY_W)]
                 + [(a, lb, 12) for a, lb in TEXT_FIELDS[:2]])
        for n, (attr, label, w) in enumerate(cells):
            r, col = divmod(n, 3)
            tk.Label(grid, text=label, font=FONT).grid(row=r, column=col * 2, sticky="w")
            self._entry(grid, it, attr, (i, attr), w).grid(row=r, column=col * 2 + 1, padx=(2, 8), pady=1, sticky="w")

        row = tk.Frame(box)
        row.pack(fill="x", pady=(3, 0))
        var = tk.BooleanVar(value=it.ceiling)
        self._vars[(i, "ceiling")] = var

        def on_ceil(*_, obj=it, v=var):
            obj.ceiling = bool(v.get())
            self.refresh_info()
        var.trace_add("write", on_ceil)
        tk.Checkbutton(row, text="천장", variable=var, font=FONT).pack(side="left")
        tk.Label(row, text="천장틀", font=FONT).pack(side="left", padx=(6, 0))
        self._combo(row, i, "frame", list(FRAME_LABELS), it.frame, it, 4).pack(side="left", padx=(2, 0))
        grid = tk.Frame(box)
        grid.pack(fill="x", pady=(2, 0))
        cells = [(a, lb, ENTRY_W) for a, lb, _ in NUM_FIELDS[3:]] + [(TEXT_FIELDS[2][0], TEXT_FIELDS[2][1], 14)]
        for n, (attr, label, w) in enumerate(cells):
            r, col = divmod(n, 3)
            tk.Label(grid, text=label, font=FONT).grid(row=r, column=col * 2, sticky="w")
            self._entry(grid, it, attr, (i, attr), w).grid(row=r, column=col * 2 + 1, padx=(2, 8), pady=1, sticky="w")

        info = tk.StringVar(value="")
        self._info_vars.append((info, it))
        tk.Label(box, textvariable=info, font=("Malgun Gothic", 8), fg="#1565C0", anchor="w", justify="left",
                 wraplength=500).pack(fill="x", pady=(2, 0))

    def _build_stair(self, d):
        """계단 마감 (모든 계단 공통): 구조 슬래브 위 계단석 방식·두께·논슬립·옆면"""
        box = tk.LabelFrame(self.body, text=" 계단 마감 (모든 계단) ", font=FONT_B, fg="#4E342E", padx=6, pady=3)
        box.pack(fill="x", padx=(5, 8), pady=3)
        top = tk.Frame(box)
        top.pack(fill="x")
        for attr, text in (("enabled", "계단 마감"), ("nosing", "논슬립")):
            var = tk.BooleanVar(value=getattr(d, attr))
            self._vars[("stair", attr)] = var

            def on_chk(*_, a=attr, v=var):
                setattr(d, a, bool(v.get()))
                self.refresh_info()
            var.trace_add("write", on_chk)
            tk.Checkbutton(top, text=text, variable=var, font=FONT).pack(side="left", padx=(0, 6))
        tk.Label(top, text="방식", font=FONT).pack(side="left")
        self._combo(top, "stair", "method", list(STEP_LABELS), d.method, d, 16).pack(side="left", padx=(2, 0))
        grid = tk.Frame(box)
        grid.pack(fill="x", pady=(3, 0))
        cells = [(a, lb, ENTRY_W) for a, lb in STAIR_NUM_FIELDS] + [(a, lb, 10) for a, lb in STAIR_TEXT_FIELDS]
        for n, (attr, label, w) in enumerate(cells):
            r, col = divmod(n, 3)
            tk.Label(grid, text=label, font=FONT).grid(row=r, column=col * 2, sticky="w")
            self._entry(grid, d, attr, ("stair", attr), w).grid(row=r, column=col * 2 + 1, padx=(2, 8), pady=1, sticky="w")
        info = tk.StringVar(value="")
        self._info_vars.append((info, d))
        tk.Label(box, textvariable=info, font=("Malgun Gothic", 8), fg="#1565C0", anchor="w", justify="left",
                 wraplength=500).pack(fill="x", pady=(2, 0))

    def _combo(self, parent, i, key, values, current, obj, width):
        var = tk.StringVar(value=current if current in values else values[0])
        self._vars[(i, key)] = var

        def on_write(*_):
            setattr(obj, key, var.get())
            self.refresh_info()
        var.trace_add("write", on_write)
        c = ttk.Combobox(parent, values=values, state="readonly", width=width, font=FONT, textvariable=var)
        self._combos[(i, key)] = c
        return c

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
            var.set(preview(it) if isinstance(it, FinishTypeDraft) else stair_preview(it))
