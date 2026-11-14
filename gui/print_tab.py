import tkinter as tk

from gui.column_draft import level_name
from gui.print_draft import PrintDraft, preview

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
SMALL = ("Malgun Gothic", 8)

# 체크박스: (초안 속성, 라벨)
OUTPUTS = [("dxf3d", "3D DXF"), ("ifc", "IFC"), ("plan", "평면도"), ("profile", "종단면도"), ("section", "단면도")]
PROFILE_AXES = [("profile_center", "선형 중심 (0)"), ("profile_track_l", "왼쪽 선로 중심 (+D/2)"),
                ("profile_track_r", "오른쪽 선로 중심 (−D/2)")]


class PrintTab:
    """탭 9: 출력 옵션. '성과물 출력' 을 누르면 여기서 고른 성과물만 세부 옵션대로 출력"""

    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict  # 메인 앱의 entries 공유받기
        self.draft = PrintDraft()
        self.entries['print_draft'] = self.draft
        self._vars = {}             # 초안 속성 → tk 변수 (보관하지 않으면 회수되면서 trace 가 사라짐)
        self._floor_vars = {}       # 층 번호 → BooleanVar
        self._groups = {}           # 성과물 → 세부 옵션 위젯 목록 (끄면 비활성)
        self.floor_count = 0

    def build(self):
        tk.Label(self.parent, text="[ 출력 옵션 ]", font=("Malgun Gothic", 10, "bold"), fg="#2E7D32").pack(
            anchor="w", padx=15, pady=(12, 2))
        tk.Label(self.parent, justify="left", fg="#555555", font=SMALL, wraplength=430,
                 text="• '성과물 출력' 을 누르면 체크한 성과물만 아래 옵션대로 출력합니다\n"
                      "• 측점은 절대 STA (134.45 또는 0+134.45), 여러 개는 쉼표로 구분\n"
                      "• offset 은 선형 중심에서의 직교 거리 (진행방향 왼쪽 +, m)").pack(anchor="w", padx=15)

        box = self._frame(" 출력할 성과물 ")
        row = tk.Frame(box)
        row.pack(fill="x")
        for attr, label in OUTPUTS:
            self._check(row, attr, label, on_change=self._sync_states).pack(side="left", padx=(0, 8))

        # 평면도
        box = self._frame(" 평면도 ")
        self.floor_frame = tk.Frame(box)
        self.floor_frame.pack(fill="x")
        row = tk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="절단 높이 (각 층 FL +, m)", font=FONT).pack(side="left")
        e = self._entry(row, "plan_cut_h", 8)
        e.pack(side="left", padx=4)
        self._groups["plan"] = [e]

        # 종단면도
        box = self._frame(" 종단면도 (절단 축) ")
        widgets = []
        for attr, label in PROFILE_AXES:
            c = self._check(box, attr, label)
            c.pack(anchor="w")
            widgets.append(c)
        row = tk.Frame(box)
        row.pack(fill="x", pady=(2, 0))
        tk.Label(row, text="직접 지정 offset (쉼표)", font=FONT).pack(side="left")
        e = self._entry(row, "profile_offsets", 22)
        e.pack(side="left", padx=4)
        self._groups["profile"] = widgets + [e]

        # 단면도
        box = self._frame(" 단면도 (횡단) ")
        row = tk.Frame(box)
        row.pack(fill="x")
        tk.Label(row, text="측점 (쉼표)", font=FONT).pack(side="left")
        e_sta = self._entry(row, "section_stations", 30)
        e_sta.pack(side="left", padx=4)
        c = self._check(box, "section_continuous", "연속 단면 (일정 간격)", on_change=self._sync_states)
        c.pack(anchor="w", pady=(4, 0))
        row = tk.Frame(box)
        row.pack(fill="x")
        cont = []
        for attr, label, w in (("section_interval", "간격 m", 6), ("section_from", "시작 STA", 9), ("section_to", "끝 STA", 9)):
            tk.Label(row, text=label, font=FONT).pack(side="left", padx=(0, 2))
            e = self._entry(row, attr, w)
            e.pack(side="left", padx=(0, 8))
            cont.append(e)
        tk.Label(box, text="측점도 연속 단면도 없으면 내공 길이의 1/4 · 1/2 · 3/4 위치. 시작·끝을 비우면 정거장 내공 시점·종점",
                 font=SMALL, fg="#666666", wraplength=420, justify="left").pack(anchor="w")
        self._groups["section"] = [e_sta, c]
        self._cont_entries = cont

        self.info_var = tk.StringVar(value="")
        tk.Label(self.parent, textvariable=self.info_var, font=FONT, fg="#1565C0", justify="left",
                 anchor="w").pack(fill="x", padx=15, pady=(6, 0))
        self.update_floor_ui()
        self.render()

    # ------------------------------------------------------------------ 위젯 도우미
    def _frame(self, title):
        box = tk.LabelFrame(self.parent, text=title, font=FONT_B, fg="#2E7D32", padx=8, pady=4)
        box.pack(fill="x", padx=15, pady=(6, 0))
        return box

    def _check(self, parent, attr, label, on_change=None):
        var = tk.BooleanVar(value=getattr(self.draft, attr))
        self._vars[attr] = var

        def on_write(*_):
            setattr(self.draft, attr, bool(var.get()))
            if on_change:
                on_change()
            self.refresh_info()
        var.trace_add("write", on_write)
        return tk.Checkbutton(parent, text=label, variable=var, font=FONT)

    def _entry(self, parent, attr, width):
        var = tk.StringVar(value=getattr(self.draft, attr))
        self._vars[attr] = var

        def on_write(*_):
            setattr(self.draft, attr, var.get())
            self.refresh_info()
        var.trace_add("write", on_write)
        return tk.Entry(parent, textvariable=var, width=width, font=FONT)

    # ------------------------------------------------------------------ 층수
    def _read_floor_count(self):
        try:
            n = int(self.entries['floors'].get().strip())
        except (KeyError, ValueError):
            return None
        return n if 1 <= n <= 20 else None

    def update_floor_ui(self):
        """층수가 바뀌면 평면도 층 체크박스를 다시 만듦 (입력 도중의 빈칸/0 은 무시)"""
        if not hasattr(self, "floor_frame"):
            return
        n = self._read_floor_count()
        if n is None:
            n = self.floor_count or 1
        if n == self.floor_count:
            return
        self.draft.ensure_floors(n, self.floor_count)
        self.floor_count = n
        self._build_floor_checks()

    def _build_floor_checks(self):
        for w in self.floor_frame.winfo_children():
            w.destroy()
        self._floor_vars.clear()
        tk.Label(self.floor_frame, text="출력할 층", font=FONT).pack(side="left", padx=(0, 4))
        checks = []
        for n in range(self.floor_count, 0, -1):                     # 위층부터 (B1F, B2F …)
            var = tk.BooleanVar(value=n in self.draft.plan_floors)
            self._floor_vars[n] = var
            var.trace_add("write", lambda *_, k=n, v=var: self._set_floor(k, v.get()))
            c = tk.Checkbutton(self.floor_frame, text=level_name(self.floor_count, n), variable=var, font=FONT)
            c.pack(side="left")
            checks.append(c)
        self._floor_checks = checks
        self._sync_states()

    def _set_floor(self, n, on):
        if on:
            self.draft.plan_floors.add(n)
        else:
            self.draft.plan_floors.discard(n)
        self.refresh_info()

    # ------------------------------------------------------------------ 표시
    def render(self):
        """초안 → 화면 (프로젝트 열기·새 프로젝트 후 호출)"""
        for attr, var in self._vars.items():
            if var.get() != getattr(self.draft, attr):
                var.set(getattr(self.draft, attr))
        self.floor_count = 0
        self.update_floor_ui()
        self._sync_states()
        self.refresh_info()

    def _sync_states(self):
        """끈 성과물의 세부 옵션 / 연속 단면을 끄면 그 입력칸을 비활성"""
        if not self._groups:
            return
        groups = dict(self._groups)
        groups["plan"] = groups["plan"] + getattr(self, "_floor_checks", [])
        for key, widgets in groups.items():
            st = "normal" if getattr(self.draft, key) else "disabled"
            for w in widgets:
                w.configure(state=st)
        st = "normal" if self.draft.section and self.draft.section_continuous else "disabled"
        for w in getattr(self, "_cont_entries", []):
            w.configure(state=st)

    def _num_entry(self, key):
        try:
            return float(self.entries[key].get())
        except (KeyError, ValueError):
            return None

    def refresh_info(self):
        if not hasattr(self, "info_var"):
            return
        n = self.floor_count or 1
        self.info_var.set(preview(self.draft, self._num_entry("start_station"), self._num_entry("length"),
                                  self._num_entry("track_spacing"), level_name=lambda k: level_name(n, k)))
