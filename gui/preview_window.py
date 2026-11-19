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
from preview import pick as P
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
        self.toolbar = tb
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
        self.pick = None           # 진행 중인 위치 선택 (PickSession)
        self.last_error = None     # 마지막 갱신 오류
        self.snapper = None
        self._pick_artists = []
        self.top = tk.Toplevel(master)
        self.top.title("미리보기")
        self.top.geometry("1200x800")
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.bind("<F5>", lambda e: (self.refresh(), "break")[1])   # break: 메인 창의 bind_all F5 와 중복 실행 방지
        self.top.bind("<Escape>", lambda e: self.cancel_pick())
        self.top.bind("<F8>", lambda e: self.toggle_ortho())

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
        tk.Frame(bar, width=16).pack(side="left")
        v = tk.BooleanVar(value=True)
        self._vars["grid_on"] = v
        tk.Checkbutton(bar, text="격자 스냅", variable=v, font=FONT).pack(side="left")
        self.grid_step = tk.Entry(bar, width=5, font=FONT)
        self.grid_step.insert(0, "0.1")
        self.grid_step.pack(side="left")
        self._label(bar, "m")
        v = tk.BooleanVar(value=True)
        self._vars["member_snap"] = v
        tk.Checkbutton(bar, text="부재 스냅", variable=v, font=FONT).pack(side="left", padx=(6, 0))
        v = tk.BooleanVar(value=True)
        self._vars["ortho"] = v
        tk.Checkbutton(bar, text="직교 (F8)", variable=v, font=FONT).pack(side="left", padx=(6, 0))

        # 명령줄 (그림 아래): 선택 중 좌표 직접 입력
        cmd = tk.Frame(self.plan.frame, bg="#ECEFF1")
        cmd.pack(side="bottom", fill="x", before=self.plan.canvas.get_tk_widget())
        tk.Label(cmd, text="명령:", font=FONT, bg="#ECEFF1").pack(side="left", padx=(6, 2))
        self.command = tk.Entry(cmd, width=28, font=FONT)
        self.command.pack(side="left", pady=3)
        self.command.bind("<Return>", lambda e: self.on_command())
        self.cursor_label = tk.Label(cmd, text="", font=FONT, bg="#ECEFF1", fg="#37474F", anchor="w")
        self.cursor_label.pack(side="left", fill="x", expand=True, padx=8)
        tk.Label(cmd, text="STA,offset | @ds,dt | Enter = 경로 끝 | U = 한 점 취소 | F8 = 직교 | Esc = 취소", font=FONT,
                 bg="#ECEFF1", fg="#78909C").pack(side="right", padx=6)
        self.plan.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.plan.canvas.mpl_connect("button_press_event", self._on_click)

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
    def refresh(self, popup=True) -> bool:
        """입력으로 모델을 다시 만들고 지금 탭을 다시 그림. 실패하면 False (이전 모델·그림 유지, last_error 에 오류).
        popup = 오류를 메시지 창으로도 알림"""
        self.last_error = None
        self._say("모델 생성 중…")
        self.top.config(cursor="watch")
        self.top.update_idletasks()
        try:
            cfg = self.get_config()
            engine = StationCADEngine(cfg)
        except Exception as e:
            self.top.config(cursor="")
            self._fail("입력 오류", e)
            self.last_error = e
            if popup:
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
        self._pick_artists = []                         # 다시 그리면 겹쳐 그린 선택 표시도 지워짐
        self.plan.draw_2d(doc, ("plan", n))
        self._say(self.pick.prompt() if self.pick else f"평면 {self.plan_floor.get()} (FL+{h:g}m)")

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

    # ------------------------------------------------------------ 위치 선택 (CAD 명령 방식)
    def start_pick(self, request: P.PickRequest) -> bool:
        """입력 탭의 [선택] 버튼: 평면을 그 층으로 바꾸고 점을 받음. 모델을 만들 수 없으면 False"""
        self.cancel_pick(quiet=True)
        if str(self.nb.select()) != str(self.plan.frame):
            self.nb.select(0)                            # 평면 탭으로 (3D 탭에서 갱신하면 3D 를 다시 만들어 느림)
        stale_note = ""
        if not self.refresh(popup=self.engine is None):  # 입력 탭의 최신 값으로 평면을 그림
            if self.engine is None:
                return False
            # 지금 입력에 오류가 있어도(예: 막 추가한 부재가 기둥과 겹침) 직전 모델 평면에서 위치를 고를 수 있게
            stale_note = f"  ※ 입력 오류로 직전 모델에서 선택: {self.last_error}"
        names = [n for n, k in R.floor_choices(self.cfg) if k == request.floor]
        if names:
            self.plan_floor.set(names[0])
        request.to_world = self.cfg.to_world
        self.pick = P.PickSession(request)
        self.draw_plan()
        self.lift()
        self.plan.canvas.get_tk_widget().focus_set()
        self._say(self.pick.prompt() + stale_note, error=bool(stale_note))
        return True

    def cancel_pick(self, quiet=False):
        if self.pick is None:
            return
        self.pick = None
        self._clear_pick_artists()
        self.plan.canvas.draw_idle()
        if not quiet:
            self._say("선택 취소")

    def _snapper(self) -> P.Snapper:
        floor = dict(R.floor_choices(self.cfg)).get(self.plan_floor.get(), 1)
        key = (id(self.engine), floor)
        if self.snapper is None or self.snapper[0] != key:
            sp = self.cfg.station
            no = {sp.level_name(n): n for n in range(1, sp.floors + 1)}
            cols = [(no[pk.level], c.pos_x, c.pos_y) for pk in self.engine.columns.column_packages for c in pk.columns]
            self.snapper = (key, P.Snapper(P.snap_targets(self.cfg, floor, cols), base=sp.start_station))
        sn = self.snapper[1]
        try:
            g = float(self.grid_step.get())
        except ValueError:
            g = 0.0
        sn.grid = g if (self._vars["grid_on"].get() and g > 0) else None
        sn.members = bool(self._vars["member_snap"].get())
        return sn

    @property
    def _world(self) -> bool:
        return not self.cfg.align.is_straight            # 평면도 auto: 곡선 선형이면 WCS

    def to_st(self, x, y, fast=False) -> tuple:
        """평면도 좌표 → 정거장 로컬 (s, t). fast = 곡선에서 0.5m 중심선 표본 근사 (마우스 이동용, to_station 은 수십 ms)"""
        if not self._world:
            return x, y
        if not fast:
            return self.cfg.to_station(x, y)
        import numpy as np
        if getattr(self, "_fast", None) is None or self._fast[0] is not self.cfg:
            a, p = self.cfg.align, self.cfg.station
            lo = max(a.start_station, p.start_station - 300.0) - p.start_station
            hi = min(a.end_station, p.start_station + p.length + 300.0) - p.start_station
            ss = np.arange(lo, hi + 1e-9, 0.5)
            self._fast = (self.cfg, ss, np.array([self.cfg.to_world(v, 0.0) for v in ss]),
                          np.array([self.cfg.theta_at(v) for v in ss]))
        _, ss, c, th = self._fast
        d = c - np.array([x, y])
        k = int(np.argmin((d ** 2).sum(axis=1)))
        dx, dy = x - c[k, 0], y - c[k, 1]
        ct, st = np.cos(th[k]), np.sin(th[k])
        return float(ss[k] + dx * ct + dy * st), float(-dx * st + dy * ct)

    def to_xy(self, s, t) -> tuple:
        return self.cfg.to_world(s, t) if self._world else (s, t)

    def _tol(self, pixels=10) -> float:
        """화면 pixels 에 해당하는 도면 길이 (부재 스냅 허용 거리)"""
        x0, x1 = self.plan.ax.get_xlim()
        w = max(self.plan.ax.bbox.width, 100.0)          # 그림 영역 폭 (픽셀)
        return abs(x1 - x0) / w * pixels

    def snap_event(self, x, y, fast=False) -> tuple:
        """평면 좌표 → 스냅한 (s, t, 설명). 경로 선택 중 직교 모드면 직전 점에서 s/t 축 방향으로만"""
        s, t = self.to_st(x, y, fast)
        sn = self._snapper()
        if (self._vars["ortho"].get() and self.pick is not None and self.pick.kind in (P.PATH, P.LINE)
                and self.pick.last is not None):                     # 직교는 경로만 (사각형은 대각 두 점)
            return P.ortho_snap(sn, self.pick.last, s, t, self._tol())
        return sn.snap(s, t, self._tol())

    def toggle_ortho(self):
        v = self._vars["ortho"]
        v.set(not v.get())
        self._say(f"직교 모드 {'켬' if v.get() else '끔'} (F8)")

    def _clear_pick_artists(self):
        for a in self._pick_artists:
            try:
                a.remove()
            except (ValueError, AttributeError, NotImplementedError):
                pass
        self._pick_artists = []

    def _line_xy(self, pts):
        """정거장 로컬 꺾은선 → 평면 좌표 (곡선이면 변을 2m 간격으로 나눠 선형을 따라 휨)"""
        if not self._world:
            return [p[0] for p in pts], [p[1] for p in pts]
        xs, ys = [], []
        for (s0, t0), (s1, t1) in zip(pts, pts[1:]):
            n = max(1, int(abs(s1 - s0) / 2.0))
            for k in range(n):
                x, y = self.to_xy(s0 + (s1 - s0) * k / n, t0 + (t1 - t0) * k / n)
                xs.append(x)
                ys.append(y)
        x, y = self.to_xy(*pts[-1])
        return xs + [x], ys + [y]

    def _draw_pick(self, cursor=None, label=""):
        """고른 점·고무줄·커서 표시 (평면 그림 위에 덧그림)"""
        self._clear_pick_artists()
        ax = self.plan.ax
        if self.pick is not None:
            for s, t in self.pick.points:
                x, y = self.to_xy(s, t)
                self._pick_artists += ax.plot([x], [y], "o", color="#FF5252", markersize=6)
            if cursor is not None:
                for line in self.pick.rubber(*cursor):
                    xs, ys = self._line_xy(line)
                    self._pick_artists += ax.plot(xs, ys, "-", color="#FF5252", linewidth=1.2)
        if cursor is not None:
            x, y = self.to_xy(*cursor)
            self._pick_artists += ax.plot([x], [y], "+", color="#FFEB3B", markersize=14, markeredgewidth=1.5)
            if label and label != "격자":
                self._pick_artists.append(ax.annotate(label, (x, y), xytext=(10, 10), textcoords="offset points",
                                                      color="#FFEB3B", fontsize=8, fontname="Malgun Gothic"))
        self.plan.canvas.draw_idle()

    def _cursor_text(self, s, t, label):
        base = self.cfg.station.start_station
        text = f"STA {P.fmt_sta(base + s)}   offset {t:+.3f}"
        if self.pick is not None and self.pick.last is not None:
            ls, lt = self.pick.last
            text += f"   (@{s - ls:.3f}, {t - lt:.3f})"
        return text + (f"   [{label}]" if label else "")

    def _on_motion(self, ev):
        if self.cfg is None or ev.inaxes is not self.plan.ax or ev.xdata is None:
            return
        try:
            s, t, label = self.snap_event(ev.xdata, ev.ydata, fast=True)
        except ValueError:                               # 곡선 선형에서 선형 범위 밖
            return
        self.cursor_label.config(text=self._cursor_text(s, t, label))
        if self.pick is not None:
            self._draw_pick((s, t), label)

    def _on_click(self, ev):
        if self.pick is None or ev.inaxes is not self.plan.ax or ev.xdata is None:
            return
        if self.plan.toolbar.mode:                       # 이동·확대 도구를 쓰는 중이면 선택하지 않음
            return
        if ev.button == 3:
            self.finish_pick()
            return
        if ev.button != 1:
            return
        try:
            s, t, _ = self.snap_event(ev.xdata, ev.ydata)
        except ValueError as e:
            self._say(f"선택: {e}", error=True)
            return
        self.add_pick_point(s, t)

    def add_pick_point(self, s, t):
        """선택에 점 추가 (클릭·명령줄 공통). 필요한 점이 다 모이면 끝냄"""
        if self.pick is None:
            return
        try:
            done = self.pick.add(s, t)
        except ValueError as e:
            self._say(f"선택: {e}", error=True)
            return
        if done:
            self.finish_pick()
        else:
            self._draw_pick((s, t))
            self._say(self.pick.prompt())

    def on_command(self):
        """명령줄 Enter: 좌표 입력 / 빈 줄 = 경로 끝 / U = 한 점 취소"""
        text = self.command.get().strip()
        self.command.delete(0, "end")
        if self.pick is None:
            if text:
                self._say("먼저 입력 탭의 [선택] 버튼으로 선택을 시작하세요", error=True)
            return
        if not text:
            self.finish_pick()
            return
        if text.upper() == "U":
            self.pick.undo()
            self._draw_pick()
            self._say(self.pick.prompt())
            return
        try:
            s, t = P.parse_input(text, self.cfg.station.start_station, self.pick.last)
        except ValueError as e:
            self._say(f"선택: {e}", error=True)
            return
        self.add_pick_point(s, t)

    def finish_pick(self):
        """선택 끝: 입력 탭에 값을 넣고 모델을 다시 만들어 결과를 보여 줌"""
        if self.pick is None:
            return
        if not self.pick.can_finish():
            self._say(f"선택: {self.pick.prompt()} — 점이 더 필요합니다", error=True)
            return
        sess, self.pick = self.pick, None
        self._clear_pick_artists()
        sess.request.floor = dict(R.floor_choices(self.cfg)).get(self.plan_floor.get(), sess.request.floor)   # 고른 평면의 층
        try:
            sess.finish()
        except Exception as e:
            self._fail("선택 반영", e)
            return
        if self.refresh(popup=False):
            self._say(f"[{sess.request.title}] 반영했습니다")
        else:
            self._say(f"[{sess.request.title}] 반영했지만 모델 오류: {self.last_error}", error=True)
