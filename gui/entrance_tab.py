import tkinter as tk
from tkinter import ttk

from gui.entrance_draft import EV_CAR_AT, EV_FACES, EV_SAME, NUM_FIELDS, OUTDOORS, SIDES, EntranceDraft, EntranceDrafts, preview, zones_summary

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
ENTRY_W = 8


class EntranceTab:
    """탭 10: 출입구 (출구통로 끝에 이어 지표까지 오르는 경사 박스 + 계단 + 에스컬레이터)

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
        self._zone_labels = {}      # 번호 → 두께 구간 요약 Label

    def build(self):
        tk.Label(self.parent, text="[ 출입구 ]", font=("Malgun Gothic", 10, "bold"),
                 fg="#6A1B9A").pack(anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=430,
                 text="• 출구통로 끝(마지막 꼭짓점)에 이어 통로 방향으로 지표까지 오름\n"
                      "• 지표 EL 만 주면 계단·에스컬레이터·박스 길이·천장 높이 자동 (비우면 정거장 공통 지표 EL)\n"
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

    def set_outdoor(self, idx, label: str):
        self.drafts.items[idx].outdoor = label
        self.refresh_info()

    def render(self):
        pos = self.canvas.yview()[0]
        for w in self.body.winfo_children():
            w.destroy()
        self._vars.clear()
        self._info_vars.clear()
        self._combos.clear()
        self._zone_labels.clear()
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
        tk.Label(top, text="마감", font=FONT).pack(side="left", padx=(8, 0))
        fd = self.entries.get("finish_drafts")
        fnames = ["(통로 기준)"] + (fd.names() if fd is not None else [])
        fc = ttk.Combobox(top, values=fnames, state="readonly", width=10, font=FONT)
        fc.set(it.finish if it.finish in fnames else fnames[0])
        fc.bind("<<ComboboxSelected>>", lambda e, cc=fc, k=i: setattr(self.drafts.items[k], "finish", cc.get()))
        fc.pack(side="left", padx=(2, 0))
        self._combos[(i, "finish")] = fc
        tk.Button(top, text="삭제", font=FONT, command=lambda: self.remove_entrance(i)).pack(side="right")

        row = tk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        var = tk.BooleanVar(value=it.escalator)
        self._vars[(i, "escalator")] = var

        def on_esc(*_, obj=it, v=var):
            obj.escalator = v.get()
            self.refresh_info()
        var.trace_add("write", on_esc)
        svar = tk.BooleanVar(value=getattr(it, "stair", True))
        self._vars[(i, "stair")] = svar

        def on_stair(*_, obj=it, v=svar):
            obj.stair = v.get()
            self.refresh_info()
        svar.trace_add("write", on_stair)
        tk.Checkbutton(row, text="계단", variable=svar, font=FONT).pack(side="left")
        tk.Checkbutton(row, text="에스컬레이터", variable=var, font=FONT).pack(side="left", padx=(6, 0))
        self._entry(row, it, "escalator_count", (i, "escalator_count"), 3).pack(side="left", padx=(2, 0))
        tk.Label(row, text="대", font=FONT).pack(side="left")
        tk.Label(row, text="쪽", font=FONT).pack(side="left", padx=(8, 0))
        c = ttk.Combobox(row, values=SIDES, state="readonly", width=10, font=FONT)
        c.set(it.side if it.side in SIDES else SIDES[0])
        c.bind("<<ComboboxSelected>>", lambda e, cc=c, k=i: self.set_side(k, cc.get()))
        c.pack(side="left", padx=(2, 0))
        self._combos[(i, "side")] = c
        tk.Label(row, text="바깥", font=FONT).pack(side="left", padx=(8, 0))
        oc = ttk.Combobox(row, values=OUTDOORS, state="readonly", width=11, font=FONT)
        oc.set(it.outdoor if it.outdoor in OUTDOORS else OUTDOORS[0])
        oc.bind("<<ComboboxSelected>>", lambda e, cc=oc, k=i: self.set_outdoor(k, cc.get()))
        oc.pack(side="left", padx=(2, 0))
        self._combos[(i, "outdoor")] = oc
        tk.Button(row, text="두께 구간…", font=FONT, command=lambda k=i: self.open_zones(k)).pack(side="left", padx=(12, 0))
        zl = tk.Label(row, text=zones_summary(it), font=FONT, fg="#455A64")
        zl.pack(side="left", padx=(4, 0))
        self._zone_labels[i] = zl

        row2 = tk.Frame(box)                              # 캐노피 · 출구 사인
        row2.pack(fill="x", pady=(4, 0))
        cvar = tk.BooleanVar(value=getattr(it, "canopy", True))
        self._vars[(i, "canopy")] = cvar

        def on_canopy(*_, obj=it, v=cvar):
            obj.canopy = v.get()
            self.refresh_info()
        cvar.trace_add("write", on_canopy)
        tk.Checkbutton(row2, text="캐노피 (출구 사인)", variable=cvar, font=FONT).pack(side="left")
        wvar = tk.BooleanVar(value=getattr(it, "cp_wall", True))
        self._vars[(i, "cp_wall")] = wvar

        def on_wall(*_, obj=it, v=wvar):
            obj.cp_wall = v.get()
            self.refresh_info()
        wvar.trace_add("write", on_wall)
        tk.Checkbutton(row2, text="유리벽", variable=wvar, font=FONT).pack(side="left", padx=(4, 0))
        tk.Label(row2, text="출구 번호", font=FONT).pack(side="left", padx=(8, 0))
        self._entry(row2, it, "exit_number", (i, "exit_number"), 4).pack(side="left", padx=(2, 0))
        tk.Label(row2, text="노선명", font=FONT).pack(side="left", padx=(8, 0))
        self._entry(row2, it, "line_name", (i, "line_name"), 7).pack(side="left", padx=(2, 0))
        tk.Label(row2, text="사인 배경색", font=FONT).pack(side="left", padx=(8, 0))
        self._entry(row2, it, "sign_bg", (i, "sign_bg"), 8).pack(side="left", padx=(2, 0))
        avar = tk.BooleanVar(value=getattr(it, "arch_wall", True))
        self._vars[(i, "arch_wall")] = avar

        def on_arch(*_, obj=it, v=avar):
            obj.arch_wall = v.get()
            self.refresh_info()
        avar.trace_add("write", on_arch)
        tk.Checkbutton(row2, text="건축 벽체", variable=avar, font=FONT).pack(side="left", padx=(8, 0))

        row3 = tk.Frame(box)                              # 외부 엘리베이터 (출입구 좌표)
        row3.pack(fill="x", pady=(4, 0))
        evar = tk.BooleanVar(value=getattr(it, "ev_on", False))
        self._vars[(i, "ev_on")] = evar

        def on_ev(*_, obj=it, v=evar):
            obj.ev_on = v.get()
            self.refresh_info()
        evar.trace_add("write", on_ev)
        tk.Checkbutton(row3, text="외부 EV", variable=evar, font=FONT).pack(side="left")
        for attr, label, w_ in (("ev_u", "u", 5), ("ev_t", "t", 5), ("ev_low_z", "지하 EL", 7), ("ev_door_open", "문 열림", 3)):
            tk.Label(row3, text=label, font=FONT).pack(side="left", padx=(6, 0))
            self._entry(row3, it, attr, (i, attr), w_).pack(side="left", padx=(2, 0))
        row4 = tk.Frame(box)
        row4.pack(fill="x", pady=(2, 0))
        for attr, label, values in (("ev_face", "지상 문", EV_FACES), ("ev_low_face", "지하 문", [EV_SAME] + EV_FACES),
                                    ("ev_car_at", "카", list(EV_CAR_AT))):
            tk.Label(row4, text=label, font=FONT).pack(side="left", padx=(6, 0))
            cb = ttk.Combobox(row4, values=values, state="readonly", width=12 if attr == "ev_low_face" else 5, font=FONT)
            cur = getattr(it, attr)
            cb.set(cur if cur in values else values[0])
            cb.bind("<<ComboboxSelected>>", lambda e, cc=cb, k=i, a=attr: (setattr(self.drafts.items[k], a, cc.get()),
                                                                          self.refresh_info()))
            cb.pack(side="left", padx=(2, 0))
            self._combos[(i, attr)] = cb

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

    # ------------------------------------------------------------ 두께 구간 창
    def open_zones(self, i):
        """두께 구간 입력 창: 줄마다 (u 시작, 두께). u = 통로 끝 이음면에서 출입구 진행 거리 (m). 비우면 벽·슬래브 두께 일정"""
        it = self.drafts.items[i]
        win = tk.Toplevel(self.canvas)
        win.title(f"출입구 {i + 1} 두께 구간")
        self.zone_win = win
        tk.Label(win, text="u 시작 = 통로 끝(이음면)에서 출입구 진행 거리 (m). 그 u 부터 다음 구간 앞까지 측벽·천장·바닥 두께.\n"
                           "첫 구간 앞(u < 첫 시작)은 '벽·슬래브 두께'. 줄이 없으면 두께 일정.",
                 font=FONT, justify="left", fg="#455A64").pack(anchor="w", padx=8, pady=(6, 4))
        body = tk.Frame(win)
        body.pack(fill="x", padx=8)
        self._zone_vars = []

        def draw():
            for w in body.winfo_children():
                w.destroy()
            self._zone_vars = []
            tk.Label(body, text="u 시작 (m)", font=FONT).grid(row=0, column=0)
            tk.Label(body, text="두께 (m)", font=FONT).grid(row=0, column=1)
            for r, row in enumerate(it.thick_zones, start=1):
                pair = []
                for col in (0, 1):
                    var = tk.StringVar(value=str(row[col]))

                    def on_write(*_, rr=row, cc=col, v=var):
                        rr[cc] = v.get()
                        self._update_zone_label(i)
                    var.trace_add("write", on_write)
                    tk.Entry(body, textvariable=var, width=10, font=FONT).grid(row=r, column=col, padx=2, pady=1)
                    pair.append(var)
                self._zone_vars.append(pair)
                tk.Button(body, text="삭제", font=FONT, command=lambda rr=r - 1: (it.thick_zones.pop(rr), draw(),
                                                                              self._update_zone_label(i))).grid(row=r, column=2, padx=4)

        def add():
            last = it.thick_zones[-1][0] if it.thick_zones else "0"
            try:
                nxt = f"{float(last) + 10:g}" if it.thick_zones else "0"
            except ValueError:
                nxt = ""
            it.thick_zones.append([nxt, str(it.wall_t)])
            draw()
            self._update_zone_label(i)
        bar = tk.Frame(win)
        bar.pack(fill="x", padx=8, pady=6)
        tk.Button(bar, text="+ 구간 추가", font=FONT, command=add).pack(side="left")
        tk.Button(bar, text="닫기", font=FONT, command=win.destroy).pack(side="right")
        draw()
        return win

    def _update_zone_label(self, i):
        zl = self._zone_labels.get(i)
        if zl is not None:
            zl.config(text=zones_summary(self.drafts.items[i]))
        self.refresh_info()

    def refresh_info(self):
        for var, it in self._info_vars:
            var.set(preview(it))
