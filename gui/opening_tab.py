import tkinter as tk
from tkinter import ttk

from gui.opening_draft import KIND_LABELS, OpeningDraft, OpeningDrafts, slab_choice_label

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 8
SLAB_COLUMNS = 2


class OpeningTab:
    """탭 4: 슬래브 오프닝 (계단 / 에스컬레이터 / 엘리베이터 / 환기·설비, 항상 직사각형)

    - 위치: 시작 측점(STA) + 길이 = 진행방향 범위, t 위치 + 폭 = 직교방향 범위 (t 는 기둥과 같은 좌표)
    - 뚫을 슬래브: 체크한 슬래브마다 같은 위치로 뚫림 (여러 층을 관통하는 계단·엘리베이터는 여러 개 체크)
    - 입력값은 OpeningDrafts(화면 비의존 초안)에 저장되고, 성과물 출력 시 TkAdapter 가 OpeningSpec 으로 변환한다.
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = OpeningDrafts()
        self.entries['opening_drafts'] = self.drafts
        self.floor_count = 0
        self._vars = {}            # 테스트/갱신용: (번호, 필드) → StringVar,  (번호, 'slab', n) → BooleanVar
        self._range_vars = []      # (StringVar, OpeningDraft) 범위 표시

    # ------------------------------------------------------------------ 구성
    def build(self):
        tk.Label(self.parent, text="[ 슬래브 오프닝 ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#6A1B9A").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=430,
                 text="• 길이 단위는 모두 m, 오프닝은 항상 직사각형\n"
                      "• 시작 측점: 절대 STA (m).  1번 탭의 정거장 시작 측점부터 내공 길이 안에 있어야 함\n"
                      "• t 위치: 선형 중심 0 (기둥 t 위치와 같은 좌표).  기둥과 겹치면 오류\n"
                      "• 뚫을 슬래브를 체크 (여러 층 관통은 여러 개 체크)").pack(anchor="w", padx=15)

        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        tk.Button(bar, text="+ 오프닝 추가", font=FONT, command=self.add_opening).pack(side="left")
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
        """층수가 바뀌면 호출. 슬래브 체크 목록을 새 층수에 맞게 다시 그림 (입력 도중의 빈칸/0 은 무시)"""
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

    def _default_start_sta(self) -> str:
        try:
            return f"{float(self.entries['start_station'].get()):g}"
        except (KeyError, ValueError):
            return "0"

    # ------------------------------------------------------------------ 편집 동작
    def add_opening(self):
        self.drafts.items.append(OpeningDraft(sta_start=self._default_start_sta()))
        self.render()

    def remove_opening(self, idx):
        del self.drafts.items[idx]
        self.render()

    def set_kind(self, idx, kind):
        self.drafts.items[idx].kind = kind
        self.refresh_ranges()

    def toggle_slab(self, idx, slab_no, on):
        slabs = self.drafts.items[idx].slabs
        (slabs.add if on else slabs.discard)(slab_no)

    # ------------------------------------------------------------------ 그리기
    def render(self):
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        self._vars.clear()
        self._range_vars.clear()
        if not self.drafts.items:
            tk.Label(self.body, text="오프닝 없음", fg="#888888", font=FONT).pack(anchor="w", padx=8, pady=6)
        for i, it in enumerate(self.drafts.items):
            self._build_opening(i, it)
        self.count_var.set(f"오프닝 {len(self.drafts.items)}개" if self.drafts.items else "")
        self.refresh_ranges()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _build_opening(self, i, it: OpeningDraft):
        box = tk.LabelFrame(self.body, text=f" 오프닝 {i + 1} ", font=FONT_B, fg="#4A148C", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=5)

        top = tk.Frame(box)
        top.pack(fill="x")
        tk.Label(top, text="용도", font=FONT).pack(side="left")
        combo = ttk.Combobox(top, values=KIND_LABELS, state="readonly", width=10, font=FONT)
        combo.set(it.kind if it.kind in KIND_LABELS else KIND_LABELS[0])
        combo.pack(side="left", padx=(2, 8))
        combo.bind("<<ComboboxSelected>>", lambda e, c=combo, k=i: self.set_kind(k, c.get()))
        tk.Label(top, text="이름", font=FONT).pack(side="left")
        self._entry(top, it, "name", (i, "name"), width=8).pack(side="left", padx=(2, 0))
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_opening(i)).pack(side="right")

        grid = tk.Frame(box)
        grid.pack(fill="x", pady=(4, 0))
        for r, (l1, a1, l2, a2) in enumerate([("시작 STA", "sta_start", "길이", "length"),
                                              ("t 위치", "t_center", "폭", "width")]):
            tk.Label(grid, text=l1, font=FONT).grid(row=r, column=0, sticky="w")
            self._entry(grid, it, a1, (i, a1), width=ENTRY_W).grid(row=r, column=1, padx=(2, 12), pady=1)
            tk.Label(grid, text=l2, font=FONT).grid(row=r, column=2, sticky="w")
            self._entry(grid, it, a2, (i, a2), width=ENTRY_W).grid(row=r, column=3, padx=(2, 0), pady=1)

        rng = tk.StringVar(value="")
        self._range_vars.append((rng, it))
        tk.Label(box, textvariable=rng, font=FONT, fg="#1565C0", anchor="w", justify="left").pack(fill="x", pady=(2, 0))

        tk.Label(box, text="뚫을 슬래브", font=("Malgun Gothic", 8), fg="#555555").pack(anchor="w", pady=(4, 0))
        sf = tk.Frame(box)
        sf.pack(fill="x")
        for n in range(self.floor_count + 1):
            var = tk.BooleanVar(value=n in it.slabs)
            self._vars[(i, "slab", n)] = var
            var.trace_add("write", lambda *_, k=i, nn=n, v=var: self.toggle_slab(k, nn, v.get()))
            tk.Checkbutton(sf, text=slab_choice_label(self.floor_count, n), variable=var, font=FONT, anchor="w").grid(
                row=n // SLAB_COLUMNS, column=n % SLAB_COLUMNS, sticky="w", padx=(0, 10))

    def _entry(self, parent, obj, attr, key, width):
        var = tk.StringVar(value=getattr(obj, attr))
        self._vars[key] = var

        def on_write(*_):
            setattr(obj, attr, var.get())
            self.refresh_ranges()
        var.trace_add("write", on_write)
        return tk.Entry(parent, textvariable=var, width=width, font=FONT)

    def refresh_ranges(self):
        """오프닝별 범위 표시: 진행방향 STA 범위, 직교방향 범위"""
        for var, it in self._range_vars:
            try:
                sta, ln = float(it.sta_start), float(it.length)
                tc, w = float(it.t_center), float(it.width)
                var.set(f"→ STA {sta:g} ~ {sta + ln:g},  t {tc - w / 2:g} ~ {tc + w / 2:g}")
            except ValueError:
                var.set("→ 입력값을 확인하세요")
