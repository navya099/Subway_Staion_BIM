import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox

from config.alignment import Alignment
from config.alignment_config import AlignmentConfig
from config.alignment_io import describe, file_kind, load_alignment
from config.alignment_landxml import LandXMLOptions, scan_landxml
from gui.column_draft import level_name
from gui.landxml_options_dialog import LandXMLOptionsDialog
from gui.xyz_options_dialog import XYZOptionsDialog
from config.station_config import StationParameters


DEFAULTS = StationParameters()          # 층별 높이 등 초기값의 단일 출처
COORD_KEYS = ("bp_x", "bp_y", "bp_z", "ep_x", "ep_y", "ep_z", "bp_station")


@dataclass
class AlignmentSource:
    """불러온 선형 파일 (없으면 BP/EP 좌표 입력을 사용)"""
    alignment: Alignment | None = None
    path: str = ""
    warnings: tuple = ()


class StationTab:
    def __init__(self, parent, entries_dict, on_floors_changed_callback):
        self.parent = parent
        self.entries = entries_dict  # 메인 앱의 entries 공유받기
        self.on_floors_changed = on_floors_changed_callback  # 콜백 연결
        self._field_vars: dict[str, tk.StringVar] = {}       # tk 변수는 파이썬 객체가 회수되면 trace 도 사라지므로 보관
        self._height_vars: dict[int, tk.StringVar] = {}

    def build_station_tab(self):
        """탭 1: 선형 및 정거장 박스 기본 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 4}
        AL, SP = AlignmentConfig(), StationParameters()   # 초기값은 dataclass 기본값이 단일 출처
        tk.Label(self.parent, text="[ WCS 절대 좌표계 선형 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#1565C0").pack(
            anchor="w", padx=15, pady=(10, 5))

        coord_frame = tk.Frame(self.parent)
        coord_frame.pack(anchor="w", padx=15, pady=2)

        tk.Label(coord_frame, text="BP X:", font=("Malgun Gothic", 9)).grid(row=0, column=0, sticky="w")
        self.entries["bp_x"] = tk.Entry(coord_frame, width=8)
        self.entries["bp_x"].grid(row=0, column=1, padx=4)
        self.entries["bp_x"].insert(0, str(AL.bp_x))

        tk.Label(coord_frame, text="BP Y:", font=("Malgun Gothic", 9)).grid(row=0, column=2, sticky="w", padx=(4, 0))
        self.entries["bp_y"] = tk.Entry(coord_frame, width=8)
        self.entries["bp_y"].grid(row=0, column=3, padx=4)
        self.entries["bp_y"].insert(0, str(AL.bp_y))

        tk.Label(coord_frame, text="BP Z:", font=("Malgun Gothic", 9)).grid(row=0, column=4, sticky="w", padx=(4, 0))
        self.entries["bp_z"] = tk.Entry(coord_frame, width=8)
        self.entries["bp_z"].grid(row=0, column=5, padx=4)
        self.entries["bp_z"].insert(0, str(AL.bp_z))

        tk.Label(coord_frame, text="EP X:", font=("Malgun Gothic", 9)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.entries["ep_x"] = tk.Entry(coord_frame, width=8)
        self.entries["ep_x"].grid(row=1, column=1, padx=4, pady=(4, 0))
        self.entries["ep_x"].insert(0, str(AL.ep_x))

        tk.Label(coord_frame, text="EP Y:", font=("Malgun Gothic", 9)).grid(row=1, column=2, sticky="w", padx=(4, 0),
                                                                            pady=(4, 0))
        self.entries["ep_y"] = tk.Entry(coord_frame, width=8)
        self.entries["ep_y"].grid(row=1, column=3, padx=4, pady=(4, 0))
        self.entries["ep_y"].insert(0, str(AL.ep_y))

        tk.Label(coord_frame, text="EP Z:", font=("Malgun Gothic", 9)).grid(row=1, column=4, sticky="w", padx=(4, 0))
        self.entries["ep_z"] = tk.Entry(coord_frame, width=8)
        self.entries["ep_z"].grid(row=1, column=5, padx=4)
        self.entries["ep_z"].insert(0, str(AL.ep_z))

        tk.Label(coord_frame, text="선형 시작 측점:", font=("Malgun Gothic", 9)).grid(row=2, column=0, sticky="w")
        self.entries["bp_station"] = tk.Entry(coord_frame, width=8)
        self.entries["bp_station"].grid(row=2, column=1, padx=4)
        self.entries["bp_station"].insert(0, str(AL.bp_station))

        self._build_alignment_loader()

        tk.Label(self.parent, text="[ 정거장 횡단 및 구배 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#1565C0").pack(
            anchor="w", padx=15, pady=(15, 5))

        fields = [
            ("length", "정거장 전체 길이 (L, m):", str(SP.length)),
            ("width", "정거장 전체 폭 (W, m):", str(SP.width)),
            ("start_station", "정거장 시작 측점 STA(m):", str(SP.start_station)),
            ("offset", "기준선 ~ 바닥 상단 오프셋 (m):", str(SP.offset)),
            ("floors", "층수:", str(SP.floors)),
            ("wall_t", "외벽 두께:", str(SP.wall_t)),
            ("floor_t", "본체 바닥 슬래브 두께:", str(SP.floor_t)),
            ("mid_t", "중간층 바닥 슬래브 두께:", str(SP.mid_t)),
            ("roof_t", "본체 천장 슬래브 두께:", str(SP.roof_t)),
        ]

        for key, lbl, val in fields:
            row_f = tk.Frame(self.parent)
            row_f.pack(fill="x", **pad_opts)
            tk.Label(row_f, text=lbl, font=("Malgun Gothic", 9), width=25, anchor="w").pack(side="left")
            var = tk.StringVar(value=val)
            self._field_vars[key] = var               # 보관하지 않으면 회수되면서 Tcl 변수와 변경 감지(trace)가 사라짐
            e = tk.Entry(row_f, width=15, font=("Malgun Gothic", 9), textvariable=var)
            e.pack(side="right")
            self.entries[key] = e

            if key == "floors":                       # 층수를 바꾸면 층별 높이 입력칸 / 기둥 탭을 다시 구성
                self._floors_var = var
                if self.on_floors_changed:
                    e.bind("<KeyRelease>", self.on_floors_changed)
                self._build_floor_heights_frame()     # 층수 입력 바로 아래에 층별 높이
            if key in ("mid_t", "roof_t"):            # 슬래브 두께가 바뀌면 내공 높이 표시를 갱신
                var.trace_add("write", lambda *a: self.refresh_heights())
        self.refresh_heights()

    # ------------------------------------------------------------------ 층별 높이
    def _build_floor_heights_frame(self):
        self.heights_frame = tk.LabelFrame(self.parent, text=" 층별 높이 (최하층부터) ", font=("Malgun Gothic", 9, "bold"),
                                           fg="#1565C0", padx=8, pady=4)
        self.heights_frame.pack(fill="x", padx=15, pady=(2, 6))
        self._height_text: dict[int, str] = {}          # 층 번호 → 입력한 문자열 (층수를 바꿔도 보존)
        self._clear_labels: dict[int, tuple] = {}       # 층 번호 → (StringVar, Label)
        self.total_var = tk.StringVar(value="")
        self.floor_count = 0
        self.update_floor_heights()

    def _read_floor_count(self):
        try:
            n = int(self.entries["floors"].get().strip())
        except (KeyError, ValueError):
            return None
        return n if 1 <= n <= 20 else None

    def update_floor_heights(self):
        """층수가 바뀌면 호출. 기존 층의 입력은 보존하고 새 층은 바로 아래 층과 같은 높이로 시작"""
        if not hasattr(self, "heights_frame"):
            return
        n = self._read_floor_count()
        if n is None:
            n = self.floor_count or len(DEFAULTS.floor_heights)      # 입력 도중(빈칸/0 등)에는 현재 상태 유지
        if n == self.floor_count:
            return
        self.floor_count = n
        for w in self.heights_frame.winfo_children():
            w.destroy()
        for key in [k for k in self.entries if k.startswith("floor_height_")]:
            del self.entries[key]
        self._clear_labels.clear()
        self._height_vars.clear()
        last = DEFAULTS.floor_heights[0]
        for i in range(1, n + 1):
            default = str(DEFAULTS.floor_heights[i - 1]) if i <= len(DEFAULTS.floor_heights) else str(last)
            text = self._height_text.setdefault(i, default)
            last = text
            row = tk.Frame(self.heights_frame)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{level_name(n, i)} 층 높이 (m):", font=("Malgun Gothic", 9), width=17, anchor="w").pack(side="left")
            var = tk.StringVar(value=text)
            self._height_vars[i] = var
            e = tk.Entry(row, width=9, font=("Malgun Gothic", 9), textvariable=var)
            e.pack(side="left")
            self.entries[f"floor_height_{i}"] = e
            clear_var = tk.StringVar(value="")
            lbl = tk.Label(row, textvariable=clear_var, font=("Malgun Gothic", 8), fg="#555555")
            lbl.pack(side="left", padx=8)
            self._clear_labels[i] = (clear_var, lbl)
            var.trace_add("write", lambda *a, i=i, v=var: (self._height_text.__setitem__(i, v.get()), self.refresh_heights()))
        tk.Label(self.heights_frame, textvariable=self.total_var, font=("Malgun Gothic", 9, "bold"), fg="#1565C0").pack(anchor="w", pady=(4, 0))
        tk.Label(self.heights_frame, justify="left", fg="#666666", font=("Malgun Gothic", 8), wraplength=410,
                 text="층 높이 = 그 층 바닥 슬래브 상면 ~ 바로 위 슬래브 상면 (최하층은 본체 바닥 슬래브 상면, 최상층은 천장 슬래브 상면까지). "
                      "합계가 정거장 총 높이이고, 내공 높이 = 층 높이 − 위쪽 슬래브 두께입니다.").pack(anchor="w")
        self.refresh_heights()

    def refresh_heights(self):
        """총 높이(합계)와 층별 내공 높이를 다시 계산해 표시"""
        if not hasattr(self, "floor_count") or not self._clear_labels:
            return

        def num(key):
            e = self.entries.get(key)
            try:
                return float(e.get()) if e is not None else None
            except ValueError:
                return None
        n, mid, roof = self.floor_count, num("mid_t"), num("roof_t")
        heights = [num(f"floor_height_{i}") for i in range(1, n + 1)]
        for i, h in enumerate(heights, start=1):
            above = mid if i < n else roof
            var, lbl = self._clear_labels[i]
            if h is None or above is None:
                var.set("→ 입력값을 확인하세요")
                lbl.configure(fg="#C62828")
            else:
                clear = h - above
                var.set(f"→ 내공 {clear:.2f} m")
                lbl.configure(fg="#C62828" if clear <= 0 else "#555555")
        ok = all(h is not None for h in heights)
        self.total_var.set(f"총 높이 H = {sum(heights):.2f} m   ({n}개 층 합계)" if ok else "총 높이: 입력값을 확인하세요")
        if "mid_t" in self.entries:                       # 1개 층이면 중간층 바닥 슬래브가 없음
            self.entries["mid_t"].configure(state="disabled" if n == 1 else "normal")

    # ------------------------------------------------------------------ 곡선 선형 파일
    def _build_alignment_loader(self):
        self.source = AlignmentSource()
        self.entries["alignment_source"] = self.source
        frame = tk.Frame(self.parent)
        frame.pack(anchor="w", padx=15, pady=(6, 0), fill="x")
        tk.Button(frame, text="선형 파일 불러오기…", font=("Malgun Gothic", 9),
                  command=self.load_alignment_file).pack(side="left")
        self.reset_btn = tk.Button(frame, text="BP/EP 직선으로", font=("Malgun Gothic", 9), state="disabled",
                                   command=self.reset_alignment)
        self.reset_btn.pack(side="left", padx=6)
        self.align_status = tk.StringVar(value="선형: 위의 BP/EP 좌표 (직선)")
        tk.Label(self.parent, textvariable=self.align_status, font=("Malgun Gothic", 8), fg="#555555",
                 wraplength=430, justify="left").pack(anchor="w", padx=15)

    def _set_coord_state(self, state):
        for k in COORD_KEYS:
            self.entries[k].configure(state=state)

    def load_alignment_file(self):
        path = filedialog.askopenfilename(
            title="선형 파일 선택",
            filetypes=[("선형 파일", "*.xml *.landxml *.json *.txt *.csv *.dat *.xyz *.asc"), ("LandXML", "*.xml *.landxml"),
                       ("선형 정의 JSON", "*.json"), ("좌표 목록 (txt, csv 등)", "*.txt *.csv *.dat *.xyz *.asc"),
                       ("모든 파일", "*.*")])
        if not path:
            return
        options, kind = None, file_kind(path)
        if kind == "text":                                  # 좌표 목록은 열 순서/시작 측점을 물어봄
            options = self._ask_xyz_options(path)
            if options is None:
                return
        elif kind == "landxml":                             # LandXML 은 고를 것이 있을 때만 물어봄
            try:
                infos = scan_landxml(path)
            except ValueError as e:
                messagebox.showerror("선형 파일 오류", str(e))
                return
            if len(infos) == 1 and len(infos[0].profiles) <= 1:
                options = LandXMLOptions()
            else:
                options = self._ask_landxml_options(path, infos)
                if options is None:
                    return
        try:
            a = load_alignment(path, options)
        except ValueError as e:
            messagebox.showerror("선형 파일 오류", str(e))
            return
        self.source.alignment, self.source.path = a, path
        self.source.warnings = tuple(getattr(a, "warnings", ()))
        self._set_coord_state("disabled")
        self.reset_btn.configure(state="normal")
        note = ""
        try:
            cur, length = float(self.entries["start_station"].get()), float(self.entries["length"].get())
        except ValueError:
            cur = length = None
        if cur is None or cur < a.start_station - 1e-6 or cur + length > a.end_station + 1e-6:
            self.entries["start_station"].delete(0, "end")
            self.entries["start_station"].insert(0, str(a.start_station))
            note = f"\n정거장 시작 측점을 선형 시작({a.start_station:g})에 맞췄습니다."
        for w in self.source.warnings[:3]:
            note += f"\n⚠ {w}"
        self.align_status.set(f"선형: {path.replace(chr(92), '/').rsplit('/', 1)[-1]} ({describe(a)}). BP/EP 입력은 사용하지 않습니다.{note}")

    def _ask_xyz_options(self, path):
        """좌표 목록 파일의 열 순서 / 시작 측점 / 평활 반폭을 묻는 대화상자 (취소하면 None)"""
        return XYZOptionsDialog(self.parent.winfo_toplevel(), path).result

    def _ask_landxml_options(self, path, infos):
        """LandXML 의 선형 / 종단 / 좌표 순서를 고르는 대화상자 (취소하면 None)"""
        return LandXMLOptionsDialog(self.parent.winfo_toplevel(), path, infos).result

    def reset_alignment(self):
        self.source.alignment, self.source.path, self.source.warnings = None, "", ()
        self._set_coord_state("normal")
        self.reset_btn.configure(state="disabled")
        self.align_status.set("선형: 위의 BP/EP 좌표 (직선)")
