import tkinter as tk
from tkinter import ttk
from gui import pick_buttons as PB

from gui.column_draft import level_name
from gui import ext_ev_draft as X
from gui.elevator_draft import DOOR_LABELS, GLASS_FIELDS, NUM_FIELDS, SHAFT_LABELS, ElevatorDraft, ElevatorDrafts, preview
from preview.pick import POINT

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 8


class ElevatorTab:
    """탭 8: 엘리베이터 (승강로 + 피트 + 오버헤드 + 카, 정지층 출입구·슬래브 오프닝 자동)

    - 위치: 승강로 내공 중심의 STA 와 t (t 는 기둥·오프닝과 같은 좌표, 왼쪽 +)
    - 정지층: 최하 ~ 최상 정지층 사이 모든 층. 카는 고른 층에 정지한 위치로 모델링
    - 최하층에서 승강장 안에 놓이면 승강장 상면에 정지 (승강장 슬래브에 승강로 구멍)
    - 외부 엘리베이터(지상 노출)는 아래쪽 따로 — 출구통로·출입구와 별개 객체 (entries['ext_ev_drafts'])
    """

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict
        self.drafts = ElevatorDrafts()
        self.entries['elevator_drafts'] = self.drafts
        self.ext = X.ExtEvDrafts()
        self.entries['ext_ev_drafts'] = self.ext
        self.floor_count = 0
        self._vars = {}            # (번호, 필드) → StringVar / BooleanVar
        self._info_vars = []       # (StringVar, ElevatorDraft) 미리보기
        self._ext_infos = []       # (StringVar, ExtEvDraft) 미리보기
        self._combos = {}          # (번호, 'lower'|'upper'|'car'|'door') → Combobox

    # ------------------------------------------------------------------ 구성
    def build(self):
        tk.Label(self.parent, text="[ 엘리베이터 ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#6A1B9A").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=430,
                 text="• 승강로(콘크리트) + 피트(바닥 아래로 내림) + 오버헤드 + 카(바닥·벽·천장·문)\n"
                      "• 위치는 승강로 내공 중심의 절대 STA 와 t. 최하~최상 정지층의 모든 층에 정지\n"
                      "• 카는 '카 정지층' 에 서 있는 위치. 문 방향 쪽 벽에 층마다 출입구\n"
                      "• 승강로가 지나는 슬래브·승강장 슬래브에는 승강로 외곽 크기 오프닝 자동").pack(anchor="w", padx=15)

        bar = tk.Frame(self.parent)
        bar.pack(fill="x", padx=15, pady=(6, 2))
        tk.Button(bar, text="+ 엘리베이터 추가", font=FONT, command=self.add_elevator).pack(side="left")
        tk.Button(bar, text="+ 외부 엘리베이터 추가", font=FONT, command=self.add_ext_ev).pack(side="left", padx=(6, 0))
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
        self.ext.ensure_floors(n)
        self.floor_count = n
        self.render()

    def _start_station(self) -> float:
        try:
            return float(self.entries['start_station'].get())
        except (KeyError, ValueError):
            return 0.0

    def floor_names(self) -> list[str]:
        n = max(2, self.floor_count)
        return [level_name(n, k) for k in range(1, n + 1)]

    # ------------------------------------------------------------------ 편집 동작
    def add_elevator(self):
        n = max(2, self.floor_count)
        self.drafts.items.append(ElevatorDraft(upper_floor=n, sta_center=f"{self._start_station() + 40.0:g}"))
        self.render()

    def remove_elevator(self, idx):
        del self.drafts.items[idx]
        self.render()

    def set_floor(self, idx, key: str, floor_n: int):
        """정지층·카 층 선택. 최하 < 최상, 카는 그 사이로 맞춤"""
        it = self.drafts.items[idx]
        setattr(it, {"lower": "lower_floor", "upper": "upper_floor", "car": "car_floor"}[key], floor_n)
        self.drafts.ensure_floors(max(2, self.floor_count))
        for k, attr in (("lower", "lower_floor"), ("upper", "upper_floor"), ("car", "car_floor")):
            c = self._combos.get((idx, k))
            if c is not None:
                c.current(getattr(it, attr) - 1)
        self.refresh_info()

    def set_shaft(self, idx, label: str):
        self.drafts.items[idx].shaft = label
        self.refresh_info()

    def set_door(self, idx, label: str):
        self.drafts.items[idx].door = label
        self.refresh_info()

    # ------------------------------------------------------------------ 그리기
    def render(self):
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        self._vars.clear()
        self._info_vars.clear()
        self._ext_infos.clear()
        self._combos.clear()
        if not self.drafts.items:
            tk.Label(self.body, text="엘리베이터 없음", fg="#888888", font=FONT).pack(anchor="w", padx=8, pady=6)
        for i, it in enumerate(self.drafts.items):
            self._build_elevator(i, it)
        for i, it in enumerate(self.ext.items):
            self._build_ext_ev(i, it)
        counts = [f"{label} {n}대" for label, n in (("내부", len(self.drafts.items)), ("외부", len(self.ext.items))) if n]
        self.count_var.set(", ".join(counts))
        self.refresh_info()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(pos)

    def _combo(self, parent, i, key, values, index, on_select, width):
        c = ttk.Combobox(parent, values=values, state="readonly", width=width, font=FONT)
        c.current(index)
        c.bind("<<ComboboxSelected>>", lambda e: on_select(c))
        self._combos[(i, key)] = c
        return c

    def _build_elevator(self, i, it: ElevatorDraft):
        box = tk.LabelFrame(self.body, text=f" 엘리베이터 {i + 1} ", font=FONT_B, fg="#4A148C", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=5)
        top = tk.Frame(box)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT).pack(side="left")
        self._entry(top, it, "name", (i, "name"), 6).pack(side="left", padx=(2, 6))
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_elevator(i)).pack(side="right")

        row = tk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        names = self.floor_names()
        for key, label, attr in (("lower", "최하", "lower_floor"), ("upper", "최상", "upper_floor"), ("car", "카", "car_floor")):
            tk.Label(row, text=label, font=FONT).pack(side="left", padx=(0, 2))
            self._combo(row, i, key, names, min(getattr(it, attr), len(names)) - 1,
                        lambda c, k=i, kk=key: self.set_floor(k, kk, c.current() + 1), 5).pack(side="left", padx=(0, 8))

        row = tk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="중심 STA", font=FONT).pack(side="left")
        self._entry(row, it, "sta_center", (i, "sta_center"), 9).pack(side="left", padx=(2, 8))
        tk.Label(row, text="t", font=FONT).pack(side="left")
        self._entry(row, it, "t_center", (i, "t_center"), 6).pack(side="left", padx=(2, 8))
        PB.button(row, "위치 선택", lambda k=i, d=it: PB.pick_point(self, k, f"엘리베이터 {k + 1} 승강로 중심", d.lower_floor,
                                                                 "sta_center")).pack(side="left")

        row = tk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="문 방향", font=FONT).pack(side="left")
        door = DOOR_LABELS.index(it.door) if it.door in DOOR_LABELS else 0
        self._combo(row, i, "door", DOOR_LABELS, door, lambda c, k=i: self.set_door(k, c.get()), 13).pack(side="left", padx=(2, 8))
        var = tk.BooleanVar(value=it.through)
        self._vars[(i, "through")] = var

        def on_through(*_, obj=it, v=var):
            obj.through = bool(v.get())
            self.refresh_info()
        var.trace_add("write", on_through)
        tk.Checkbutton(row, text="관통형 (반대쪽에도 문)", variable=var, font=FONT).pack(side="left")

        row = tk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="승강로", font=FONT).pack(side="left")
        sh = SHAFT_LABELS.index(it.shaft) if it.shaft in SHAFT_LABELS else 0
        self._combo(row, i, "shaft", SHAFT_LABELS, sh, lambda c, k=i: self.set_shaft(k, c.get()), 15).pack(side="left", padx=(2, 8))
        tk.Label(row, text="층별 문(최하층부터, 예 -s, +t)", font=FONT).pack(side="left")
        self._entry(row, it, "door_floors", (i, "door_floors"), 12).pack(side="left", padx=(2, 0))

        row = tk.Frame(box)                              # 애니메이션 대비: 카 위치·문 열림, 투시형 카·사다리
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="카 오프셋(m)", font=FONT).pack(side="left")
        self._entry(row, it, "car_offset", (i, "car_offset"), 5).pack(side="left", padx=(2, 8))
        tk.Label(row, text="문 열림(0~1)", font=FONT).pack(side="left")
        self._entry(row, it, "door_open", (i, "door_open"), 4).pack(side="left", padx=(2, 8))
        for attr, label in (("car_glass", "투시형 카"), ("ladder", "피트 사다리"), ("fixtures", "호출 버튼·층 표시")):
            bv = tk.BooleanVar(value=getattr(it, attr, True))
            self._vars[(i, attr)] = bv

            def on_b(*_, obj=it, v=bv, a=attr):
                setattr(obj, a, bool(v.get()))
                self.refresh_info()
            bv.trace_add("write", on_b)
            tk.Checkbutton(row, text=label, variable=bv, font=FONT).pack(side="left", padx=(0, 6))

        grid = tk.Frame(box)
        grid.pack(fill="x", pady=(4, 0))
        for n, (attr, label) in enumerate(NUM_FIELDS + GLASS_FIELDS + [("glass_rows", "유리 줄 높이(쉼표)")]):
            r, col = divmod(n, 2)
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
        start = self._start_station()
        n = max(2, self.floor_count)
        for var, it in self._info_vars:
            var.set(preview(it, start, n))
        for var, it in self._ext_infos:
            var.set(X.preview(it, start))

    # ------------------------------------------------------------------ 외부 엘리베이터
    def _host_names(self, host: str) -> list:
        """고를 수 있는 출구통로·출입구 이름 (이름을 비운 것은 기본 이름)"""
        key, prefix = ("passage_drafts", "EX") if host == X.HOST_PASSAGE else ("entrance_drafts", "EN")
        items = getattr(self.entries.get(key), "items", [])
        return [it.name.strip() or f"{prefix}{k}" for k, it in enumerate(items, start=1)]

    def add_ext_ev(self):
        names = self._host_names(X.HOST_PASSAGE)
        self.ext.items.append(X.ExtEvDraft(host=X.HOST_PASSAGE if names else X.HOST_STATION, host_name=names[0] if names else "",
                                           sta=f"{self._start_station() + 40.0:g}"))
        self.render()

    def remove_ext_ev(self, idx):
        del self.ext.items[idx]
        self.render()

    def set_host(self, idx, label: str):
        """위치 기준을 바꾸면 입력칸이 달라짐. 이름이 새 기준 목록에 없으면 첫 이름으로"""
        it = self.ext.items[idx]
        it.host = label
        names = self._host_names(label) if label in (X.HOST_PASSAGE, X.HOST_ENTRANCE) else []
        if it.host_name.strip() not in names:
            it.host_name = names[0] if names else ""
        self.render()

    def pick_ext(self, idx):
        def done(pts):
            s, t = pts[0]
            self._vars[("ext", idx, "sta")].set(f"{self._start_station() + s:.3f}")
            if self.ext.items[idx].host == X.HOST_WALL:             # 측벽 쪽 = 고른 점의 t 부호
                label = X.SIDE_LABELS[0 if t >= 0 else 1]
                self.ext.items[idx].side = label
                self._combos[("ext", idx, "side")].set(label)
                self.refresh_info()
            else:
                self._vars[("ext", idx, "t")].set(f"{t:.3f}")
        floor = self.ext.items[idx].floor if self.ext.items[idx].host == X.HOST_WALL else 1
        PB.request(self, POINT, floor, f"외부 엘리베이터 {idx + 1} 중심", done)

    def _build_ext_ev(self, i, it):
        box = tk.LabelFrame(self.body, text=f" 외부 엘리베이터 {i + 1} (지상 노출) ", font=FONT_B, fg="#00695C", padx=6, pady=4)
        box.pack(fill="x", padx=(5, 8), pady=5)

        def line():
            row = tk.Frame(box)
            row.pack(fill="x", pady=(0, 4))
            return row

        def entry(row, attr, text, width):
            tk.Label(row, text=text, font=FONT).pack(side="left", padx=(0, 2))
            self._entry(row, it, attr, ("ext", i, attr), width).pack(side="left", padx=(0, 8))

        def combo(row, attr, text, values, width, fn=None):
            tk.Label(row, text=text, font=FONT).pack(side="left", padx=(0, 2))
            c = ttk.Combobox(row, values=values, state="readonly", width=width, font=FONT)
            c.set(getattr(it, attr))

            def on(_e):
                if fn is not None:
                    fn(c.get())
                else:
                    setattr(it, attr, c.get())
                    self.refresh_info()
            c.bind("<<ComboboxSelected>>", on)
            c.pack(side="left", padx=(0, 8))
            self._combos[("ext", i, attr)] = c

        row = line()
        entry(row, "name", "이름", 10)
        combo(row, "host", "위치 기준", X.HOST_LABELS, 11, lambda v: self.set_host(i, v))
        tk.Button(row, text="삭제", font=FONT, command=lambda: self.remove_ext_ev(i)).pack(side="right")

        row = line()
        if it.host in (X.HOST_PASSAGE, X.HOST_ENTRANCE):           # 붙는 통로·출입구 (이름 직접 입력도 가능)
            tk.Label(row, text="통로" if it.host == X.HOST_PASSAGE else "출입구", font=FONT).pack(side="left", padx=(0, 2))
            var = tk.StringVar(value=it.host_name)
            self._vars[("ext", i, "host_name")] = var

            def on_name(*_):
                it.host_name = var.get()
                self.refresh_info()
            var.trace_add("write", on_name)
            c = ttk.Combobox(row, textvariable=var, width=9, font=FONT)
            c.configure(postcommand=lambda: c.configure(values=self._host_names(it.host)))
            c.pack(side="left", padx=(0, 8))
            self._combos[("ext", i, "host_name")] = c
        if it.host == X.HOST_WALL:
            names = self.floor_names()
            tk.Label(row, text="층", font=FONT).pack(side="left", padx=(0, 2))
            fc = ttk.Combobox(row, values=names, state="readonly", width=5, font=FONT)
            fc.current(min(max(it.floor, 1), len(names)) - 1)

            def on_floor(_e):
                it.floor = fc.current() + 1
                self.refresh_info()
            fc.bind("<<ComboboxSelected>>", on_floor)
            fc.pack(side="left", padx=(0, 8))
            self._combos[("ext", i, "floor")] = fc
        for attr, text in X.PLACE_FIELDS.get(it.host, []):
            entry(row, attr, text, 8)
        if it.host in (X.HOST_PASSAGE, X.HOST_WALL):
            combo(row, "side", "쪽", X.SIDE_LABELS, 9)
        if it.host in (X.HOST_WALL, X.HOST_STATION):
            PB.button(row, "위치 선택", lambda: self.pick_ext(i)).pack(side="left")

        row = line()
        combo(row, "face", "지상 문", X.FACES, 4)
        if it.host not in (X.HOST_PASSAGE, X.HOST_WALL):           # 벽에 붙으면 지하 문 = 그 벽 쪽
            combo(row, "low_face", "지하 문", [X.SAME_FACE] + X.FACES, 12)
        combo(row, "car_at", "카", X.CAR_LABELS, 5)
        entry(row, "car_offset", "카 오프셋(m)", 5)
        entry(row, "door_open", "문 열림(0~1)", 4)

        row = line()
        combo(row, "low_finish", "지하 마감", X.LOW_LABELS, 16)
        entry(row, "ground_el", "지표 EL(비우면 자동)", 8)
        row = line()
        entry(row, "line_name", "사인 노선명", 8)
        entry(row, "sign_bg", "사인 배경색", 8)
        bv = tk.BooleanVar(value=it.fixtures)
        self._vars[("ext", i, "fixtures")] = bv
        bv.trace_add("write", lambda *_: setattr(it, "fixtures", bool(bv.get())))
        tk.Checkbutton(row, text="호출 버튼·층 표시", variable=bv, font=FONT).pack(side="left")
        info = tk.StringVar(value="")
        self._ext_infos.append((info, it))
        tk.Label(box, textvariable=info, font=FONT, fg="#1565C0", anchor="w", justify="left", wraplength=560).pack(fill="x")
