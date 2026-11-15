"""미리보기 창: 현재 입력으로 모델을 만들어 평면·종단·횡단·3D 를 바로 본다 (파일 저장 없이).

- 갱신(F5): 입력 → StationProjectConfig → StationCADEngine. 오류면 상태줄·메시지로 알리고 이전 그림은 그대로 둠.
- 그림은 도면 출력과 같은 DXF 문서(StationCADEngine.build_*_doc)를 그대로 그림 (preview.preview_render).
- 같은 보기(같은 층·축·측점)를 다시 그리면 확대/이동 상태를 유지 → 입력을 고치고 F5 로 같은 자리를 계속 확인.
"""
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from config.output_config import PLAN_CUT_H
from engine.cad_engine import StationCADEngine
from preview import preview_render as R

FONT = ("Malgun Gothic", 9)
ALL_FLOORS = "모든 층"


class _View:
    """탭 하나: 위쪽 조작 줄 + matplotlib 그림 + 도구 막대(이동·확대·저장)"""

    def __init__(self, nb, title, three_d=False):
        self.frame = ttk.Frame(nb)
        nb.add(self.frame, text=title)
        self.bar = tk.Frame(self.frame)
        self.bar.pack(fill="x", padx=4, pady=(4, 2))
        self.fig = Figure(figsize=(8, 5), dpi=100, facecolor="#212830" if not three_d else "white")
        self.ax = self.fig.add_axes([0, 0, 1, 1], projection="3d" if three_d else None)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame)
        tb = NavigationToolbar2Tk(self.canvas, self.frame, pack_toolbar=False)
        tb.update()
        tb.pack(side="bottom", fill="x")
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.key = None            # 마지막으로 그린 보기 (같으면 확대 상태 유지)
        self.stale = True          # 모델이 바뀌어 다시 그려야 함
        if not three_d:
            self.canvas.mpl_connect("scroll_event", self._wheel)

    def _wheel(self, ev):
        """마우스 휠: 커서 위치 기준 확대/축소"""
        if ev.inaxes is not self.ax or ev.xdata is None:
            return
        f = 1 / 1.25 if ev.button == "up" else 1.25
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        cx, cy = ev.xdata, ev.ydata
        self.ax.set_xlim(cx + (x0 - cx) * f, cx + (x1 - cx) * f)
        self.ax.set_ylim(cy + (y0 - cy) * f, cy + (y1 - cy) * f)
        self.canvas.draw_idle()

    def draw_2d(self, doc, key):
        keep = key == self.key
        lim = (self.ax.get_xlim(), self.ax.get_ylim()) if keep else None
        R.draw_doc_2d(self.ax, doc)
        if lim:
            self.ax.set_xlim(lim[0])
            self.ax.set_ylim(lim[1])
        self.key, self.stale = key, False
        self.canvas.draw_idle()


class PreviewWindow:
    """get_config(): 현재 입력 → StationProjectConfig (오류면 예외). print_draft: 출력 탭 초안 (처음 보기 값만 가져옴)"""

    def __init__(self, master, get_config, print_draft=None):
        self.get_config = get_config
        self.cfg = None
        self.engine = None
        self.mesh = None
        self.top = tk.Toplevel(master)
        self.top.title("미리보기")
        self.top.geometry("1200x800")
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.bind("<F5>", lambda e: (self.refresh(), "break")[1])   # break: 메인 창의 bind_all F5 와 중복 실행 방지

        head = tk.Frame(self.top, bg="#ECEFF1")
        head.pack(fill="x")
        tk.Button(head, text="갱신 (F5)", font=("Malgun Gothic", 9, "bold"), bg="#3F51B5", fg="white", width=14,
                  command=self.refresh).pack(side="left", padx=6, pady=4)
        self.status = tk.Label(head, text="", font=FONT, bg="#ECEFF1", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=6)

        self.nb = ttk.Notebook(self.top)
        self.nb.pack(fill="both", expand=True)
        self.plan = _View(self.nb, "평면")
        self.profile = _View(self.nb, "종단")
        self.section = _View(self.nb, "횡단")
        self.view3d = _View(self.nb, "3D", three_d=True)
        self.views = [self.plan, self.profile, self.section, self.view3d]
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.draw_current())

        pd = print_draft
        self._vars = {}
        self._build_plan_bar(pd.plan_cut_h if pd is not None else f"{PLAN_CUT_H:g}")
        self._build_profile_bar()
        self._build_section_bar(next(iter(pd.section_stations.replace(";", ",").split(",")), "").strip() if pd is not None else "")
        self._build_3d_bar()

    # ------------------------------------------------------------ 조작 줄
    @staticmethod
    def _label(bar, text):
        tk.Label(bar, text=text, font=FONT).pack(side="left", padx=(8, 2))

    def _button(self, bar, text, fn, width=8):
        tk.Button(bar, text=text, font=FONT, width=width, command=fn).pack(side="left", padx=2)

    def _build_plan_bar(self, cut_h):
        bar = self.plan.bar
        self._label(bar, "층")
        self.plan_floor = ttk.Combobox(bar, state="readonly", width=8, font=FONT)
        self.plan_floor.pack(side="left")
        self.plan_floor.bind("<<ComboboxSelected>>", lambda e: self.draw_plan())
        self._label(bar, "절단 높이 FL+")
        self.plan_cut = tk.Entry(bar, width=6, font=FONT)
        self.plan_cut.insert(0, cut_h)
        self.plan_cut.pack(side="left")
        self.plan_cut.bind("<Return>", lambda e: self.draw_plan())
        self._label(bar, "m")
        self._button(bar, "그리기", self.draw_plan)

    def _build_profile_bar(self):
        bar = self.profile.bar
        self._label(bar, "절단 축 (선택 또는 offset m, 왼쪽 +)")
        self.profile_axis = ttk.Combobox(bar, width=22, font=FONT)
        self.profile_axis.pack(side="left")
        self.profile_axis.bind("<<ComboboxSelected>>", lambda e: self.draw_profile())
        self.profile_axis.bind("<Return>", lambda e: self.draw_profile())
        self._button(bar, "그리기", self.draw_profile)

    def _build_section_bar(self, sta):
        bar = self.section.bar
        self._label(bar, "측점 STA")
        self.section_sta = tk.Entry(bar, width=12, font=FONT)
        self.section_sta.insert(0, sta)
        self.section_sta.pack(side="left")
        self.section_sta.bind("<Return>", lambda e: self.draw_section())
        self._button(bar, "◀", lambda: self.step_section(-1), width=3)
        self._button(bar, "▶", lambda: self.step_section(1), width=3)
        self._button(bar, "그리기", self.draw_section)
        self.section_scale = tk.Scale(bar, orient="horizontal", showvalue=False, resolution=0.5, from_=0, to=1, length=360)
        self.section_scale.pack(side="left", padx=8, fill="x", expand=True)
        self.section_scale.bind("<ButtonRelease-1>", lambda e: self._scale_released())
        self._label(bar, "간격")
        self.section_step = tk.Entry(bar, width=5, font=FONT)
        self.section_step.insert(0, "5")
        self.section_step.pack(side="left")

    def _build_3d_bar(self):
        bar = self.view3d.bar
        for name in R.group_names():
            v = tk.BooleanVar(value=name in R.default_groups())
            self._vars[("g", name)] = v
            tk.Checkbutton(bar, text=name, variable=v, font=FONT).pack(side="left")
        bar2 = tk.Frame(self.view3d.frame)
        bar2.pack(fill="x", padx=4, pady=(0, 2), before=self.view3d.canvas.get_tk_widget())
        self._label(bar2, "보이는 층")
        self.d3_floor = ttk.Combobox(bar2, state="readonly", width=10, font=FONT)
        self.d3_floor.pack(side="left")
        self._label(bar2, "STA 범위")
        self.d3_from = tk.Entry(bar2, width=10, font=FONT)
        self.d3_from.pack(side="left")
        tk.Label(bar2, text="~", font=FONT).pack(side="left")
        self.d3_to = tk.Entry(bar2, width=10, font=FONT)
        self.d3_to.pack(side="left")
        v = tk.BooleanVar(value=False)
        self._vars["transparent"] = v
        tk.Checkbutton(bar2, text="벽·슬래브 반투명", variable=v, font=FONT).pack(side="left", padx=6)
        self._button(bar2, "그리기", lambda: self.draw_3d(keep_view=True))
        self._button(bar2, "시점 초기화", lambda: self.draw_3d(keep_view=False), width=10)
        tk.Label(bar2, text="(끌기 = 회전, 휠 = 확대)", font=FONT, fg="#607D8B").pack(side="left", padx=6)
        self.view3d.canvas.mpl_connect("scroll_event", self._wheel_3d)

    def _wheel_3d(self, ev):
        R.zoom_3d(self.view3d.ax, 1 / 1.2 if ev.button == "up" else 1.2)
        self.view3d.canvas.draw_idle()

    # ------------------------------------------------------------ 상태
    @property
    def alive(self) -> bool:
        try:
            return bool(self.top.winfo_exists())
        except tk.TclError:
            return False

    def close(self):
        self.top.destroy()

    def lift(self):
        self.top.deiconify()
        self.top.lift()

    def _say(self, text, error=False):
        self.status.config(text=text, fg="#C62828" if error else "#263238")

    def _fail(self, where, e):
        traceback.print_exc()
        self._say(f"{where}: {e}", error=True)

    # ------------------------------------------------------------ 갱신
    def refresh(self) -> bool:
        """입력으로 모델을 다시 만들고 지금 탭을 다시 그림. 실패하면 False (이전 그림 유지)"""
        self._say("모델 생성 중…")
        self.top.config(cursor="watch")
        self.top.update_idletasks()
        try:
            cfg = self.get_config()
            engine = StationCADEngine(cfg)
        except Exception as e:
            self.top.config(cursor="")
            self._fail("입력 오류", e)
            messagebox.showerror("미리보기", f"{type(e).__name__}: {e}", parent=self.top)
            return False
        self.cfg, self.engine, self.mesh = cfg, engine, None
        self._update_choices()
        for v in self.views:
            v.stale = True
        self.top.config(cursor="")
        self._say("모델 생성 완료")
        self.draw_current()
        return True

    def _update_choices(self):
        """층·축·측점 선택지를 새 모델에 맞춤 (고른 값은 가능하면 유지)"""
        cfg, p = self.cfg, self.cfg.station
        names = [n for n, _ in R.floor_choices(cfg)]
        cur = self.plan_floor.get()
        self.plan_floor["values"] = names
        self.plan_floor.set(cur if cur in names else names[0])
        cur = self.d3_floor.get()
        vals = [ALL_FLOORS] + [f"{n}까지" for n in names]
        self.d3_floor["values"] = vals
        self.d3_floor.set(cur if cur in vals else ALL_FLOORS)
        axes = [n for n, _ in R.axis_choices(cfg)]
        cur = self.profile_axis.get()
        self.profile_axis["values"] = axes
        if not cur.strip():
            self.profile_axis.set(axes[0])
        self.section_scale.config(from_=p.start_station, to=p.start_station + p.length)
        if not self.section_sta.get().strip():
            self._set_sta(p.start_station + p.length / 2.0)
        else:
            try:
                self.section_scale.set(p.start_station + R.parse_section_s(self.section_sta.get(), cfg))
            except ValueError:
                pass

    def draw_current(self):
        if self.engine is None:
            return
        idx = self.nb.index(self.nb.select())
        view = self.views[idx]
        if view.stale:
            (self.draw_plan, self.draw_profile, self.draw_section, self.draw_3d)[idx]()

    # ------------------------------------------------------------ 보기별 그리기
    def _ready(self) -> bool:
        if self.engine is None:
            self._say("먼저 갱신(F5)으로 모델을 만드세요", error=True)
            return False
        return True

    def draw_plan(self):
        if not self._ready():
            return
        try:
            names = dict(R.floor_choices(self.cfg))
            n = names[self.plan_floor.get()]
            h = R.parse_cut_h(self.plan_cut.get(), self.cfg, n)
            doc = self.engine.build_plan_doc(floors=[n], cut_h=h)
        except Exception as e:
            self._fail("평면", e)
            return
        self.plan.draw_2d(doc, ("plan", n))
        self._say(f"평면 {self.plan_floor.get()} (FL+{h:g}m)")

    def draw_profile(self):
        if not self._ready():
            return
        try:
            t = R.parse_axis(self.profile_axis.get(), self.cfg)
            doc = self.engine.build_profile_doc([t])
        except Exception as e:
            self._fail("종단", e)
            return
        self.profile.draw_2d(doc, ("profile",))      # 축만 바뀌면 같은 자리에서 비교할 수 있도록 확대 상태 유지
        self._say(f"종단 축 C.L.{t:+g}m" if t else "종단 축 C.L.")

    def _set_sta(self, sta):
        km = int(sta // 1000)
        self.section_sta.delete(0, "end")
        self.section_sta.insert(0, f"{km}+{sta - km * 1000:06.2f}")
        self.section_scale.set(sta)

    def _scale_released(self):
        if self.cfg is None:
            return
        self._set_sta(float(self.section_scale.get()))
        self.draw_section()

    def step_section(self, direction):
        if not self._ready():
            return
        p = self.cfg.station
        try:
            step = float(self.section_step.get())
            s = R.parse_section_s(self.section_sta.get(), self.cfg)
        except ValueError as e:
            self._fail("횡단", e)
            return
        s = min(max(s + direction * step, 0.0), p.length)
        self._set_sta(p.start_station + s)
        self.draw_section()

    def draw_section(self):
        if not self._ready():
            return
        try:
            s = R.parse_section_s(self.section_sta.get(), self.cfg)
            doc = self.engine.build_section_doc([s])
        except Exception as e:
            self._fail("횡단", e)
            return
        self.section_scale.set(self.cfg.station.start_station + s)
        self.section.draw_2d(doc, ("section",))      # 측점만 바뀌면 같은 자리 유지 (단면 비교)
        self._say(f"횡단 STA {self.engine._fmt_sta(s)}")

    def options_3d(self):
        """3D 보기 조작 값 → (레이어 집합, s 구간 | None, FL 기준 높이 상한 | None)"""
        from gui.print_draft import parse_station
        p = self.cfg.station
        groups = {name for name in R.group_names() if self._vars[("g", name)].get()}
        rng = None
        a, b = self.d3_from.get().strip(), self.d3_to.get().strip()
        if a or b:
            s0 = parse_station(a, "3D STA 범위 시작") - p.start_station if a else -1e9
            s1 = parse_station(b, "3D STA 범위 끝") - p.start_station if b else 1e9
            if s0 >= s1:
                raise ValueError("3D: STA 범위의 시작이 끝보다 작아야 합니다")
            rng = (s0, s1)
        h = None
        sel = self.d3_floor.get()
        if sel and sel != ALL_FLOORS:
            n = dict(R.floor_choices(self.cfg))[sel[:-2]]
            h = p.floor_level(n) + p.clear_height(n)
        return R.layers_of(groups), rng, h

    def draw_3d(self, keep_view=True):
        if not self._ready():
            return
        try:
            layers, rng, h = self.options_3d()
            if self.mesh is None:
                self._say("3D 모델 준비 중…")
                self.top.config(cursor="watch")
                self.top.update_idletasks()
                self.mesh = R.mesh_from_doc(self.engine.build_3d_doc(), self.cfg)
            n = R.draw_mesh_3d(self.view3d.ax, self.mesh, layers, s_range=rng, h_max=h,
                               transparent=self._vars["transparent"].get(),
                               keep_view=keep_view and self.view3d.key is not None)
        except Exception as e:
            self.top.config(cursor="")
            self._fail("3D", e)
            return
        self.top.config(cursor="")
        self.view3d.key, self.view3d.stale = ("3d",), False
        self.view3d.canvas.draw_idle()
        self._say(f"3D 면 {n:,}개" + ("" if n else " — 보이는 부재가 없습니다 (표시 묶음·범위 확인)"))
