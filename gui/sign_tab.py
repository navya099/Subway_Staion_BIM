import tkinter as tk
from tkinter import ttk

from gui.sign_draft import (HANG_FIELDS, ExitDraft, NEIGHBOR_FIELDS, PLATE_FIELDS, STATION_FIELDS, STYLE_NAMES, SignDraft,
                            preview)

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
SMALL = ("Malgun Gothic", 8)


class SignTab:
    """탭 15: 사인 (역명판 + 승강장 타는 곳·대합실 출구 안내사인)

    - 역 정보(역명·역번호·노선색·양쪽 이웃 역)로 역명판 이미지를 그려 승강장 뒤 측벽에 일정 간격으로 붙임
    - 타는 곳: 승강장으로 내려가는 계단·에스컬레이터 입구 위, 출구: 출구통로 입구 앞 (천장 매달림, 자동 배치)
    - 이미지는 텍스처 DAE 에만 붙음 (도면·IFC 는 문구)
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.draft = SignDraft()
        self.entries['sign_draft'] = self.draft
        self._vars = {}                 # 속성 → 변수, ('exit', 통로, 'number'|'destinations') → 변수
        self._combo = None

    def build(self):
        tk.Label(self.parent, text="[ 사인 ]", font=("Malgun Gothic", 10, "bold"), fg="#0D47A1").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=SMALL, wraplength=520,
                 text="• 역명판: 승강장 뒤 측벽(마감 표면)에 간격마다, 이미지는 텍스처 DAE 에 붙음\n"
                      "• 타는 곳: 승강장으로 내려가는 계단·에스컬레이터 입구 위, 출구: 출구통로 입구 앞 (천장 매달림)\n"
                      "• 이웃 역 +s = 종점 방향, −s = 시점 방향 (역명판의 좌우는 보는 방향에 맞춰 자동)").pack(anchor="w", padx=15)
        wrap = tk.Frame(self.parent)
        wrap.pack(fill="both", expand=True, padx=(10, 0), pady=(4, 6))
        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas)
        win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.parent.bind("<Map>", lambda e: self.render_exits())       # 탭을 열 때 출구통로 목록 다시 읽음
        self._build_static()

    def _frame(self, title):
        box = tk.LabelFrame(self.body, text=f" {title} ", font=FONT_B, padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=4)
        return box

    def _check(self, parent, attr, label):
        var = tk.BooleanVar(value=bool(getattr(self.draft, attr)))
        self._vars[attr] = var
        var.trace_add("write", lambda *_: self._set(attr, var.get()))
        return tk.Checkbutton(parent, text=label, variable=var, font=FONT)

    def _entry(self, parent, attr, width):
        var = tk.StringVar(value=getattr(self.draft, attr))
        self._vars[attr] = var
        var.trace_add("write", lambda *_: self._set(attr, var.get()))
        return tk.Entry(parent, textvariable=var, width=width, font=FONT)

    def _grid(self, parent, fields, cols, width, prefix=""):
        g = tk.Frame(parent)
        g.pack(fill="x")
        for k, (attr, label, *_) in enumerate(fields):
            r, c = divmod(k, cols)
            tk.Label(g, text=label, font=FONT).grid(row=r, column=c * 2, sticky="w")
            self._entry(g, prefix + attr, width).grid(row=r, column=c * 2 + 1, padx=(2, 10), pady=1)
        return g

    def _set(self, attr, value):
        setattr(self.draft, attr, value)
        self.refresh_info()

    def _build_static(self):
        top = tk.Frame(self.body)
        top.pack(fill="x", padx=5)
        self._check(top, "enabled", "사인 만들기").pack(side="left")
        self.info = tk.StringVar(value="")
        tk.Label(top, textvariable=self.info, font=FONT, fg="#1565C0").pack(side="left", padx=10)

        self._grid(self._frame("역 정보"), STATION_FIELDS, 3, 12)
        box = self._frame("이웃 역")
        for prefix, label in (("plus_", "+s (종점 방향)"), ("minus_", "−s (시점 방향)")):
            tk.Label(box, text=label, font=FONT_B).pack(anchor="w")
            self._grid(box, NEIGHBOR_FIELDS, 4, 9, prefix)

        box = self._frame("역명판 (승강장 측벽)")
        row = tk.Frame(box)
        row.pack(fill="x")
        tk.Label(row, text="스타일", font=FONT).pack(side="left")
        self._combo = ttk.Combobox(row, values=STYLE_NAMES, state="readonly", width=14, font=FONT)
        self._combo.set(self.draft.style)
        self._combo.bind("<<ComboboxSelected>>", lambda e: self._set("style", self._combo.get()))
        self._combo.pack(side="left", padx=4)
        self._grid(box, PLATE_FIELDS, 4, 6)

        box = self._frame("타는 곳 (대합실, 승강장으로 내려가는 계단·에스컬레이터 위)")
        self._check(box, "boarding", "타는 곳 사인").pack(anchor="w")
        row = tk.Frame(box)
        row.pack(fill="x")
        for attr, label in (("dest_l", "왼쪽 선로(+t) 방면"), ("dest_r", "오른쪽 선로(−t) 방면")):
            tk.Label(row, text=label, font=FONT).pack(side="left")
            self._entry(row, attr, 14).pack(side="left", padx=(2, 10))

        box = self._frame("출구 (출구통로 입구 앞)")
        self._check(box, "exits_on", "출구 사인").pack(anchor="w")
        tk.Label(box, text="목적지는 ' / ' 로 줄을 나눔 (최대 3줄), 번호를 비우면 통로 순번", font=SMALL, fg="#555555").pack(anchor="w")
        self.exit_frame = tk.Frame(box)
        self.exit_frame.pack(fill="x")

        self._grid(self._frame("매달림 사인 치수 (m, 하단 = 바닥 마감면 기준, 거리 = 계단 끝·측벽에서)"), HANG_FIELDS, 3, 6)
        self.render_exits()

    def passage_names(self) -> list:
        drafts = self.entries.get('passage_drafts')
        if drafts is None:
            return []
        return [it.name.strip() or f"EX{i + 1}" for i, it in enumerate(drafts.items)]

    def render_exits(self):
        if not hasattr(self, "exit_frame"):
            return
        for w in self.exit_frame.winfo_children():
            w.destroy()
        for k in [k for k in self._vars if isinstance(k, tuple)]:
            del self._vars[k]
        names = self.passage_names()
        if not names:
            tk.Label(self.exit_frame, text="출구통로 없음 (10.통로 탭)", font=FONT, fg="#888888").grid(row=0, column=0, sticky="w")
        for r, name in enumerate(names):
            e = next((x for x in self.draft.exits if x.passage == name), None) or ExitDraft(name)   # 입력할 때만 초안에 붙임
            tk.Label(self.exit_frame, text=name, font=FONT, width=10, anchor="w").grid(row=r, column=0, sticky="w")
            for c, (attr, w) in enumerate((("number", 4), ("destinations", 34)), start=1):
                var = tk.StringVar(value=getattr(e, attr))
                self._vars[("exit", name, attr)] = var
                var.trace_add("write", lambda *_, ee=e, a=attr, v=var: self._set_exit(ee, a, v.get()))
                tk.Entry(self.exit_frame, textvariable=var, width=w, font=FONT).grid(row=r, column=c, padx=2, pady=1)
        self.refresh_info()

    def _set_exit(self, e, attr, value):
        setattr(e, attr, value)
        if e not in self.draft.exits:
            self.draft.exits.append(e)
        self.refresh_info()

    def render(self):
        """프로젝트를 열어 초안이 바뀌면 화면 값을 맞춤"""
        for attr, var in self._vars.items():
            if isinstance(attr, str):
                v = getattr(self.draft, attr)
                if var.get() != v:
                    var.set(v)
        if self._combo is not None:
            self._combo.set(self.draft.style)
        self.render_exits()

    def refresh_info(self):
        if hasattr(self, "info"):
            self.info.set(preview(self.draft))
