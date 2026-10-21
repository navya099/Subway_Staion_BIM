import tkinter as tk
from tkinter import ttk

from gui.column_draft import (CIRCLE, RECT, SHAPES, ColumnDrafts, FloorDraft, PatternDraft, RowDraft,
                              estimate_count, level_name)

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 6


class ColumnTab:
    """탭 3: 층별 · 열별 중앙 기둥 입력

    - 열(row): 선형 직교방향 위치 t 에 놓이는 기둥 줄. 간격 / 시작 여유 / 규격 패턴을 가진다.
    - 패턴: 열을 따라 순서대로 반복되는 기둥 규격. 2개 이상이면 혼합 배치 (예: 원기둥, 사각기둥, 원기둥 ...)
    - 입력값은 ColumnDrafts(화면 비의존 초안)에 저장되고, 성과물 출력 시 TkAdapter 가 ColumnParameters 로 변환한다.
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict  # 메인 앱의 entries 공유받기
        self.drafts = ColumnDrafts()
        self.entries['column_drafts'] = self.drafts
        self.floor_count = 0
        self._vars = {}          # 테스트/갱신용: (층, 열, 필드) 또는 (층, 열, 패턴, 필드) → StringVar
        self._count_vars = []    # (StringVar, RowDraft) 열별 예상 기둥 개수 표시

    # ------------------------------------------------------------------ 구성
    def build(self):
        tk.Label(self.parent, text="[ 중앙 기둥 (층별 · 열별 배치) ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#2E7D32").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=430,
                 text="• 길이 단위는 모두 m\n"
                      "• 열: 선형 직교방향 위치(t)에 놓이는 기둥 줄 (중심선 0, 오른쪽 +)\n"
                      "• 패턴: 열을 따라 순서대로 반복되는 규격 (2개 이상 = 혼합 배치)\n"
                      "• 시작 여유: 마감벽 안쪽 면 ~ 첫 기둥 중심 (종점도 대칭)").pack(anchor="w", padx=15)

        self.sync_var = tk.BooleanVar(value=True)
        tk.Checkbutton(self.parent, text=" 최하층 승강장 위 기둥은 승강장 상면에 맞춤", variable=self.sync_var,
                       font=FONT).pack(anchor="w", padx=15, pady=(6, 4))
        self.entries['sync_all'] = self.sync_var

        # 층/열이 많아지므로 스크롤 영역에 배치
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

        self.update_column_floor_ui()

    def _bind_wheel(self, on: bool):
        if on:
            self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
        else:
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.canvas.unbind_all(ev)

    # ------------------------------------------------------------------ 층수 변경
    def _read_floor_count(self):
        try:
            n = int(self.entries['floors'].get().strip())
        except (KeyError, ValueError):
            return None
        return n if 1 <= n <= 20 else None

    def update_column_floor_ui(self):
        """층수가 바뀌면 호출 (층수 입력창 KeyRelease). 기존 층의 입력은 보존하고 새 층만 기본 1열로 추가"""
        if not hasattr(self, 'body'):
            return
        n = self._read_floor_count()
        if n is None:
            n = self.floor_count or 1      # 입력 도중(빈칸/0 등)에는 현재 상태 유지
        if n == self.floor_count:
            return
        self.drafts.ensure_floors(n)
        self.floor_count = n
        self.render()

    # ------------------------------------------------------------------ 편집 동작
    def add_row(self, floor_n):
        self.drafts.floors[floor_n].rows.append(RowDraft())
        self.render()

    def remove_row(self, floor_n, row_idx):
        del self.drafts.floors[floor_n].rows[row_idx]
        self.render()

    def add_pattern(self, floor_n, row_idx):
        pats = self.drafts.floors[floor_n].rows[row_idx].patterns
        pats.append(PatternDraft(shape=pats[-1].shape) if pats else PatternDraft())
        self.render()

    def remove_pattern(self, floor_n, row_idx, pat_idx):
        del self.drafts.floors[floor_n].rows[row_idx].patterns[pat_idx]
        self.render()

    def set_shape(self, floor_n, row_idx, pat_idx, shape):
        self.drafts.floors[floor_n].rows[row_idx].patterns[pat_idx].shape = shape
        self.render()

    # ------------------------------------------------------------------ 그리기
    def render(self):
        """초안 전체로 화면을 다시 구성 (스크롤 위치 유지)"""
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        self._vars.clear()
        self._count_vars.clear()

        for n in range(1, self.floor_count + 1):          # 최하층(B{n}F)부터 위로
            self._build_floor(n)

        self.refresh_counts()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _build_floor(self, n):
        level = level_name(self.floor_count, n)
        note = "  (최하층)" if n == 1 else ("  (최상층)" if n == self.floor_count else "")
        box = tk.LabelFrame(self.body, text=f" {level}{note} ", font=FONT_B, fg="#1B5E20", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=5)
        floor: FloorDraft = self.drafts.floors[n]

        if not floor.rows:
            tk.Label(box, text="기둥 없음", fg="#888888", font=FONT).pack(anchor="w")
        for r, row in enumerate(floor.rows):
            self._build_row(box, n, r, row)
        tk.Button(box, text="+ 열 추가", font=FONT, command=lambda: self.add_row(n)).pack(anchor="w", pady=(4, 0))

    def _build_row(self, parent, n, r, row: RowDraft):
        rf = tk.LabelFrame(parent, text=f" {r + 1}열 ", font=FONT, padx=6, pady=3)
        rf.pack(fill="x", pady=3)

        head = tk.Frame(rf)
        head.pack(fill="x")
        for col, (label, attr) in enumerate([("t 위치", "t_offset"), ("간격", "interval"),
                                             ("시작 여유", "start_offset")]):
            tk.Label(head, text=label, font=FONT).grid(row=0, column=col * 2, sticky="w", padx=(0, 2))
            self._entry(head, row, attr, (n, r, attr), width=ENTRY_W).grid(row=0, column=col * 2 + 1, padx=(0, 6))
        count = tk.StringVar(value="")
        self._count_vars.append((count, row))
        tk.Label(head, textvariable=count, font=FONT, fg="#1565C0").grid(row=1, column=0, columnspan=4, sticky="w")
        tk.Button(head, text="열 삭제", font=FONT, command=lambda: self.remove_row(n, r)).grid(
            row=1, column=4, columnspan=2, sticky="e", pady=(2, 0))

        tk.Label(rf, text="기둥 패턴 (순서대로 반복)", font=("Malgun Gothic", 8), fg="#555555").pack(anchor="w", pady=(4, 0))
        for k, pat in enumerate(row.patterns):
            self._build_pattern(rf, n, r, k, pat, removable=len(row.patterns) > 1)
        tk.Button(rf, text="+ 패턴 추가", font=("Malgun Gothic", 8),
                  command=lambda: self.add_pattern(n, r)).pack(anchor="w", pady=(2, 0))

    def _build_pattern(self, parent, n, r, k, pat: PatternDraft, removable: bool):
        pf = tk.Frame(parent)
        pf.pack(fill="x", pady=1)
        tk.Label(pf, text=f"{k + 1}.", font=FONT, width=2).pack(side="left")
        combo = ttk.Combobox(pf, values=SHAPES, state="readonly", width=8, font=FONT)
        combo.set(pat.shape if pat.shape in SHAPES else RECT)
        combo.pack(side="left", padx=(0, 6))
        combo.bind("<<ComboboxSelected>>", lambda e, c=combo: self.set_shape(n, r, k, c.get()))

        fields = [("지름", "diameter")] if pat.shape == CIRCLE else [("폭", "width"), ("두께", "depth")]
        for label, attr in fields:
            tk.Label(pf, text=label, font=FONT).pack(side="left")
            self._entry(pf, pat, attr, (n, r, k, attr), width=ENTRY_W).pack(side="left", padx=(2, 6))
        if removable:
            tk.Button(pf, text="−", font=FONT, width=2, command=lambda: self.remove_pattern(n, r, k)).pack(side="right")

    def _entry(self, parent, obj, attr, key, width):
        """초안 객체의 문자열 필드에 묶인 입력창 (입력할 때마다 초안과 예상 개수 갱신)"""
        var = tk.StringVar(value=getattr(obj, attr))
        self._vars[key] = var

        def on_write(*_):
            setattr(obj, attr, var.get())
            self.refresh_counts()
        var.trace_add("write", on_write)
        return tk.Entry(parent, textvariable=var, width=width, font=FONT)

    def refresh_counts(self):
        """열별 예상 기둥 개수 표시 (정거장 길이·외벽 두께는 1번 탭 현재값 사용)"""
        try:
            length = float(self.entries['length'].get())
            wall_t = float(self.entries['wall_t'].get())
        except (KeyError, ValueError):
            length = wall_t = None
        for var, row in self._count_vars:
            n = estimate_count(row, length, wall_t) if length is not None else None
            var.set("→ 약 %d개" % n if n is not None else "→ 입력값을 확인하세요")
