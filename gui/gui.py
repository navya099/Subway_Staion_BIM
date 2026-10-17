import tkinter as tk
from tkinter import messagebox, ttk
from config.cadconfig import StationParameters
from engine.cad_engine import StationCADEngine
from platforms.platform_params import PlatformParameters


class StationBIMApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("지하철 개착정거장 자동 설계 (BIM Engine)")
        self.root.geometry("440x1024")
        self.root.resizable(False, False)

        self._build_ui()

    def _build_ui(self):
        pad_opts = {'padx': 10, 'pady': 3}

        # 1. 파라미터 입력부
        tk.Label(self.root, text="[ 1. 선형 및 3D 골조 파라미터 ]", font=("Malgun Gothic", 10, "bold"), fg="#1565C0").pack(anchor="w", padx=10, pady=(10, 2))

        self.entries = {}
        fields = [
            ("length", "정거장 총 길이 (L, m):", "200"),
            ("width", "정거장 전체 폭 (W, m) [CL 기준]:", "20"),
            ("base_level", "시점(STA. 0+000) 기준선 표고 (Base Level):", "134.45"),
            ("slope_permil", "종단구배 (퍼밀, ‰):", "10"),
            ("offset", "선형 기준선 ~ 바닥 상단 오프셋 (m):", "5.0"),
            ("height", "정거장 총 높이 (내부공간 H, m):", "12"),
            ("floors", "층수 (예: 2):", "2")
        ]

        for key, label_text, default_val in fields:
            tk.Label(self.root, text=label_text, font=("Malgun Gothic", 9)).pack(anchor="w", **pad_opts)
            entry = tk.Entry(self.root, font=("Malgun Gothic", 9), width=35)
            entry.pack(anchor="w", **pad_opts)
            entry.insert(0, default_val)
            self.entries[key] = entry

        # --- [신규 승강장 입력 섹션] ---
        tk.Label(self.root, text="[ 2. 상대식 승강장 제원 파라미터 ]", font=("Malgun Gothic", 10, "bold"), fg="#D32F2F").pack(
            anchor="w", padx=10, pady=(8, 2))
        plat_fields = [
            ("track_spacing", "선로 간격 D (m):", "4.0"),
            ("plat_offset", "선로중심~승강장 끝단 거리 (m):", "1.5"),
            ("plat_thick", "승강장 두께 (m, 표준 0.2):", "0.2"),
            ("plat_height", "바닥 기준 승강장 높이 (m):", "1.2")
        ]
        for key, lbl, val in plat_fields:
            tk.Label(self.root, text=lbl, font=("Malgun Gothic", 9)).pack(anchor="w", **pad_opts)
            e = tk.Entry(self.root, width=35, font=("Malgun Gothic", 9));
            e.pack(anchor="w", **pad_opts);
            e.insert(0, val)
            self.entries[key] = e

        # 두께 입력부 (한 줄 배열)
        tk.Label(self.root, text="두께 (외벽 / 바닥 / 슬래브, m):", font=("Malgun Gothic", 9)).pack(anchor="w", **pad_opts)
        t_frame = tk.Frame(self.root)
        t_frame.pack(anchor="w", **pad_opts)
        for key, default_val in [("wall_t", "0.8"), ("floor_t", "1.0"), ("slab_t", "0.6")]:
            entry = tk.Entry(t_frame, font=("Malgun Gothic", 9), width=10)
            entry.pack(side="left", padx=2)
            entry.insert(0, default_val)
            self.entries[key] = entry

        # 3D 생성 버튼
        btn_3d = tk.Button(self.root, text="종단구배 반영 3D 개착박스 DXF 생성", font=("Malgun Gothic", 10, "bold"), bg="#3F51B5", fg="white", command=self.on_generate_3d)
        btn_3d.pack(pady=8, fill="x", padx=10)

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10, pady=6)

        # 2. 도면 추출 옵션부
        tk.Label(self.root, text="[ 2. 도면 추출 및 도면화 (STA) ]", font=("Malgun Gothic", 10, "bold"), fg="#D32F2F").pack(anchor="w", padx=10, pady=(2, 2))

        self.section_mode = tk.StringVar(value="range")
        mode_frame = tk.Frame(self.root)
        mode_frame.pack(anchor="w", padx=10, pady=2)
        tk.Radiobutton(mode_frame, text="범위 측점 추출 (일괄)", variable=self.section_mode, value="range", command=self._toggle_mode).pack(side="left", padx=5)
        tk.Radiobutton(mode_frame, text="단일 측점 추출", variable=self.section_mode, value="single", command=self._toggle_mode).pack(side="left", padx=5)

        self.range_frame = tk.Frame(self.root)
        self.range_frame.pack(anchor="w", padx=10, pady=2)
        tk.Label(self.range_frame, text="추출 간격 (m):", font=("Malgun Gothic", 9)).grid(row=0, column=0, sticky="w", padx=2)
        self.entry_interval = tk.Entry(self.range_frame, font=("Malgun Gothic", 9), width=15)
        self.entry_interval.grid(row=0, column=1, padx=2)
        self.entry_interval.insert(0, "50")

        self.single_frame = tk.Frame(self.root)
        tk.Label(self.single_frame, text="추출할 특정 STA (m):", font=("Malgun Gothic", 9)).grid(row=0, column=0, sticky="w", padx=2)
        self.entry_single_sta = tk.Entry(self.single_frame, font=("Malgun Gothic", 9), width=15)
        self.entry_single_sta.grid(row=0, column=1, padx=2)
        self.entry_single_sta.insert(0, "100")

        # 2D 생성 버튼들
        btn_section = tk.Button(self.root, text="구배 반영 2D 횡단면도 DXF 일괄 생성", font=("Malgun Gothic", 11, "bold"), bg="#E65100", fg="white", command=self.on_generate_section)
        btn_section.pack(pady=5, fill="x", padx=10)

        btn_plan_profile = tk.Button(self.root, text="2D 평면도 & 종단면도 DXF 생성", font=("Malgun Gothic", 10, "bold"), bg="#2E7D32", fg="white", command=self.on_generate_plan_profile)
        btn_plan_profile.pack(pady=5, fill="x", padx=10)

    def _toggle_mode(self):
        if self.section_mode.get() == "range":
            self.single_frame.pack_forget()
            self.range_frame.pack(anchor="w", padx=10, pady=2)
        else:
            self.range_frame.pack_forget()
            self.single_frame.pack(anchor="w", padx=10, pady=2)

    def get_params(self) -> StationParameters:
        return StationParameters(
            length=float(self.entries["length"].get()),
            width=float(self.entries["width"].get()),
            base_level=float(self.entries["base_level"].get()),
            slope_permil=float(self.entries["slope_permil"].get()),
            offset=float(self.entries["offset"].get()),
            height=float(self.entries["height"].get()),
            floors=int(self.entries["floors"].get()),
            wall_t=float(self.entries["wall_t"].get()),
            floor_t=float(self.entries["floor_t"].get()),
            slab_t=float(self.entries["slab_t"].get()),
            interval=float(self.entry_interval.get())
        )


    def get_plat_params(self) -> PlatformParameters:
        return PlatformParameters(
            track_spacing=float(self.entries["track_spacing"].get()),
            plat_offset=float(self.entries["plat_offset"].get()),
            plat_thick=float(self.entries["plat_thick"].get()),
            plat_height=float(self.entries["plat_height"].get()),
        )

    def on_generate_3d(self):
        try:
            params = self.get_params()
            plat_params = self.get_plat_params()
            engine = StationCADEngine(params, plat_params)
            path = engine.generate_3d_dxf()
            messagebox.showinfo("성공", f"3D 모델 DXF 생성 완료!\n저장 경로: {path}")
        except Exception as e:
            messagebox.showerror("오류", f"3D 생성 실패:\n{e}")

    def on_generate_section(self):
        try:
            params = self.get_params()
            pf_params = self.get_plat_params()
            engine = StationCADEngine(params, pf_params)

            stations = []
            if self.section_mode.get() == "range":
                interval = float(self.entry_interval.get())
                if interval <= 0: raise ValueError("간격은 0보다 커야 합니다.")
                cur = 0.0
                while cur <= params.length:
                    stations.append(cur)
                    cur += interval
                if cur - interval < params.length: stations.append(params.length)
            else:
                s_val = float(self.entry_single_sta.get())
                if not (0 <= s_val <= params.length): raise ValueError("측점 범위를 벗어났습니다.")
                stations.append(s_val)

            path = engine.generate_section_dxf(stations)
            messagebox.showinfo("성공", f"2D 횡단면도 DXF 생성 완료 ({len(stations)}개소)!\n저장 경로: {path}")
        except Exception as e:
            messagebox.showerror("오류", f"횡단면도 생성 실패:\n{e}")

    def on_generate_plan_profile(self):
        try:
            params = self.get_params()
            engine = StationCADEngine(params)
            p_plan = engine.generate_plan_dxf()
            p_prof = engine.generate_profile_dxf()
            messagebox.showinfo("성공", f"2D 평면도 및 종단면도 DXF 생성 완료!\n\n- 평면도: {p_plan}\n- 종단면도: {p_prof}")
        except Exception as e:
            messagebox.showerror("오류", f"평면/종단도 생성 실패:\n{e}")