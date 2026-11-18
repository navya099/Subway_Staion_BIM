import tkinter as tk
from tkinter import ttk

from gui.psd_draft import EMERGENCY_LABELS, PsdDraft
from gui.psd_draft import NUM_FIELDS as PSD_FIELDS
from gui.psd_draft import preview as psd_preview
from gui.train_draft import DIRS, TrainDraft
from gui.train_draft import preview as train_preview

from platforms.platform_params import PlatformParameters
from platforms.platform_type import PlatformType


class PlatformTab:
    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict  # 메인 앱의 entries 공유받기

    def build(self):
        """탭 2: 상대식 승강장 상세 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 8}
        tk.Label(self.parent, text="[ 승강장(Side Platform) 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#D32F2F").pack(
            anchor="w", padx=15, pady=(15, 5))

        PP = PlatformParameters()   # 초기값은 dataclass 기본값이 단일 출처
        plat_fields = [
            ("track_spacing", "선로 간격 D (m):", str(PP.track_spacing)),
            ("plat_offset", "선로중심~승강장 끝단 거리 (m):", str(PP.plat_offset)),
            ("plat_thick", "승강장 슬래브 두께 (m):", str(PP.plat_thick)),
            ("plat_height", "바닥 기준 승강장 높이 (m):", str(PP.plat_height)),
            ("support_t", "승강장 지지벽체 두께 (m, 0=없음):", str(PP.support_t)),
        ]
        for key, lbl, val in plat_fields:
            row_f = tk.Frame(self.parent)
            row_f.pack(fill="x", **pad_opts)
            tk.Label(row_f, text=lbl, font=("Malgun Gothic", 9), width=28, anchor="w").pack(side="left")
            e = tk.Entry(row_f, width=12, font=("Malgun Gothic", 9))
            e.pack(side="right")
            e.insert(0, val)
            self.entries[key] = e

        # 선택 옵션 (두 라디오버튼이 하나의 변수를 공유하도록 수정)
        # 0: 상대식 승강장, 1: 섬식 승강장
        self.station_type_var = tk.IntVar(value=PP.plat_type.value)

        chk_f = tk.Frame(self.parent)
        chk_f.pack(fill="x", padx=15, pady=10)

        tk.Radiobutton(
            chk_f,
            text="상대식 승강장",
            variable=self.station_type_var,
            value=PlatformType.NORMAL.value,  # 상대식
            font=("Malgun Gothic", 9)
        ).pack(anchor="w")

        tk.Radiobutton(
            chk_f,
            text="섬식 승강장",
            variable=self.station_type_var,
            value=PlatformType.ISLAND.value,  # 섬식 (미지원)
            font=("Malgun Gothic", 9),
            state="disabled"  # 비활성화 옵션 수정
        ).pack(anchor="w")

        self.entries['platform_type'] = self.station_type_var
        self.build_train()
        self.build_psd()

    # ------------------------------------------------------------------ 열차 (승하차 위치)
    def build_train(self):
        """열차 편성과 선로별 정차: 승강장 연단 점자블록의 승하차 위치 표시(차량-문 번호)를 정함"""
        font, small = ("Malgun Gothic", 9), ("Malgun Gothic", 8)
        self.train_draft = TrainDraft()
        self.entries['train_draft'] = self.train_draft
        self._train_vars = {}             # 속성 → tk 변수 (보관하지 않으면 회수되면서 trace 가 사라짐)
        self._train_combos = {}
        box = tk.LabelFrame(self.parent, text=" 열차 (승하차 위치) ", font=("Malgun Gothic", 9, "bold"), padx=6, pady=4)
        box.pack(fill="x", padx=15, pady=(4, 6))
        tk.Label(box, justify="left", fg="#555555", font=small, wraplength=430,
                 text="• 문 위치 = 차량 앞끝(진행방향)에서 문 중심까지 거리, 쉼표 구분 (선두 차량만 다르면 따로 입력)\n"
                      "• 승하차 위치 = 연단 경고블록 띠 중 문 앞 구간 (점자블록 탭을 켰을 때), 번호 '차량-문'").pack(anchor="w")
        self._train_check(box, "enabled", "열차 사용").pack(anchor="w")
        grid = tk.Frame(box)
        grid.pack(fill="x")
        fields = [("cars", "차량 수"), ("car_length", "차량 길이"), ("door_width", "문 폭"), ("mark_width", "표시 폭")]
        for k, (attr, label) in enumerate(fields):
            r, c = divmod(k, 2)
            tk.Label(grid, text=label, font=font).grid(row=r, column=c * 2, sticky="w")
            self._train_entry(grid, attr, 7).grid(row=r, column=c * 2 + 1, padx=(2, 12), pady=1)
        for attr, label in (("door_offsets", "문 위치"), ("first_doors", "선두 차량 문 위치 (비우면 같음)")):
            row = tk.Frame(box)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, font=font).pack(side="left")
            self._train_entry(row, attr, 26).pack(side="left", padx=4)
        for tr, label in (("r", "오른쪽 선로(−t)"), ("l", "왼쪽 선로(+t)")):
            row = tk.Frame(box)
            row.pack(fill="x", pady=1)
            self._train_check(row, f"{tr}_stop", label).pack(side="left")
            c = ttk.Combobox(row, values=DIRS, state="readonly", width=14, font=font)
            c.set(getattr(self.train_draft, f"{tr}_dir"))
            c.bind("<<ComboboxSelected>>", lambda e, cc=c, a=f"{tr}_dir": self._set_train(a, cc.get()))
            c.pack(side="left", padx=4)
            self._train_combos[f"{tr}_dir"] = c
            tk.Label(row, text="선두 STA", font=font).pack(side="left")
            self._train_entry(row, f"{tr}_front", 10).pack(side="left", padx=4)
        self.train_info = tk.StringVar(value="")
        tk.Label(box, textvariable=self.train_info, font=font, fg="#1565C0", anchor="w", justify="left").pack(fill="x")
        self.refresh_train()

    def _set_train(self, attr, value):
        setattr(self.train_draft, attr, value)
        self.refresh_train()

    def _train_check(self, parent, attr, label):
        var = tk.BooleanVar(value=bool(getattr(self.train_draft, attr)))
        self._train_vars[attr] = var
        var.trace_add("write", lambda *_: self._set_train(attr, var.get()))
        return tk.Checkbutton(parent, text=label, variable=var, font=("Malgun Gothic", 9))

    def _train_entry(self, parent, attr, width):
        var = tk.StringVar(value=getattr(self.train_draft, attr))
        self._train_vars[attr] = var
        var.trace_add("write", lambda *_: self._set_train(attr, var.get()))
        return tk.Entry(parent, textvariable=var, width=width, font=("Malgun Gothic", 9))

    def render_train(self):
        """프로젝트를 열어 초안이 바뀌면 화면 값을 맞춤"""
        for attr, var in self._train_vars.items():
            v = getattr(self.train_draft, attr)
            if var.get() != v:
                var.set(v)
        for attr, c in self._train_combos.items():
            c.set(getattr(self.train_draft, attr))
        self.refresh_train()

    def refresh_train(self):
        try:
            start = float(self.entries['start_station'].get())
        except (KeyError, ValueError, AttributeError):
            start = 0.0
        if hasattr(self, "train_info"):
            self.train_info.set(train_preview(self.train_draft, start))

    # ------------------------------------------------------------------ 스크린도어 (PSD)
    def build_psd(self):
        """스크린도어: 열차 문마다 유닛(고정부 | 가동문 2 | 고정부) + POST + 구동부"""
        font = ("Malgun Gothic", 9)
        self.psd_draft = PsdDraft()
        self.entries['psd_draft'] = self.psd_draft
        self._psd_vars = {}
        box = tk.LabelFrame(self.parent, text=" 스크린도어 (PSD, 열차 문마다 유닛) ", font=("Malgun Gothic", 9, "bold"), padx=6, pady=4)
        box.pack(fill="x", padx=15, pady=(0, 6))
        top = tk.Frame(box)
        top.pack(fill="x")
        var = tk.BooleanVar(value=self.psd_draft.enabled)
        self._psd_vars["enabled"] = var
        var.trace_add("write", lambda *_: self._set_psd("enabled", var.get()))
        tk.Checkbutton(top, text="스크린도어", variable=var, font=font).pack(side="left")
        tk.Label(top, text="비상문 겸용", font=font).pack(side="left", padx=(12, 2))
        c = ttk.Combobox(top, values=EMERGENCY_LABELS, state="readonly", width=6, font=font)
        c.set(self.psd_draft.emergency)
        c.bind("<<ComboboxSelected>>", lambda e: self._set_psd("emergency", c.get()))
        c.pack(side="left")
        self._psd_combo = c
        grid = tk.Frame(box)
        grid.pack(fill="x")
        for k, (attr, label, _) in enumerate(PSD_FIELDS):
            r, col = divmod(k, 3)
            tk.Label(grid, text=label, font=font).grid(row=r, column=col * 2, sticky="w")
            v = tk.StringVar(value=getattr(self.psd_draft, attr))
            self._psd_vars[attr] = v
            v.trace_add("write", lambda *_, a=attr, vv=v: self._set_psd(a, vv.get()))
            tk.Entry(grid, textvariable=v, width=6, font=font).grid(row=r, column=col * 2 + 1, padx=(2, 8), pady=1)
        self.psd_info = tk.StringVar(value=psd_preview(self.psd_draft))
        tk.Label(box, textvariable=self.psd_info, font=font, fg="#1565C0", anchor="w", justify="left").pack(fill="x")

    def _set_psd(self, attr, value):
        setattr(self.psd_draft, attr, value)
        self.psd_info.set(psd_preview(self.psd_draft))

    def render_psd(self):
        for attr, var in self._psd_vars.items():
            v = getattr(self.psd_draft, attr)
            if var.get() != v:
                var.set(v)
        self._psd_combo.set(self.psd_draft.emergency)
        self.psd_info.set(psd_preview(self.psd_draft))
