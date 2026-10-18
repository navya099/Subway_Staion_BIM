import tkinter as tk
from tkinter import messagebox, ttk
from config.cadconfig import StationParameters
from config.master_config import StationProjectConfig
from engine.cad_engine import StationCADEngine
from platforms.platform_params import PlatformParameters


class StationBIMApp:
    def __init__(self, root: tk.Tk):
        self.floor_col_frame = None
        self.entries = {}
        self.root = root
        self.root.title("지하철 개착정거장 자동 설계 (BIM Engine)")
        self.root.geometry("440x1024")
        self.root.resizable(False, False)

        self._build_ui()

    def _build_ui(self):
        # 전체 메인 탭 노트북 생성
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # 탭 1: 선형 및 본체 제원
        tab_station = ttk.Frame(notebook)
        notebook.add(tab_station, text="  1. 선형 및 본체  ")
        self._build_station_tab(tab_station)

        # 탭 2: 승강장 제원
        tab_platform = ttk.Frame(notebook)
        notebook.add(tab_platform, text="  2. 상대식 승강장  ")
        self._build_platform_tab(tab_platform)

        # 탭 3: 중앙 기둥 제원
        tab_column = ttk.Frame(notebook)
        notebook.add(tab_column, text="  3. 중앙 기둥  ")
        self._build_column_tab(tab_column)

        # 탭 4: 출력 설정
        tab_print = ttk.Frame(notebook)
        notebook.add(tab_print, text="  4. 출력 설정  ")
        self._build_print_tab(tab_print)

        # 하단 공통 실행 버튼 패널 (어떤 탭에 있든 항상 실행 가능)
        btn_frame = tk.Frame(self.root, bg="#ECEFF1", relief="groove", bd=1)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btn_frame, text="성과물 출력", font=("Malgun Gothic", 9, "bold"), bg="#3F51B5", fg="white", width=22,
                  command=self.on_generate_3d).pack(side="left", padx=8, pady=8)
        tk.Button(btn_frame, text="종료", font=("Malgun Gothic", 9, "bold"), bg="#00897B", fg="white", width=22,
                  command=self.root.destroy).pack(side="right", padx=8, pady=8)

    def _build_station_tab(self, parent):
        """탭 1: 선형 및 정거장 박스 기본 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 4}
        tk.Label(parent, text="[ WCS 절대 좌표계 선형 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#1565C0").pack(anchor="w",
                                                                                                             padx=15,
                                                                                                             pady=(
                                                                                                             10, 5))

        coord_frame = tk.Frame(parent)
        coord_frame.pack(anchor="w", padx=15, pady=2)

        tk.Label(coord_frame, text="BP X:", font=("Malgun Gothic", 9)).grid(row=0, column=0, sticky="w")
        self.entries["bp_x"] = tk.Entry(coord_frame, width=12)
        self.entries["bp_x"].grid(row=0, column=1, padx=4)
        self.entries["bp_x"].insert(0, "286.4826")
        tk.Label(coord_frame, text="BP Y:", font=("Malgun Gothic", 9)).grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.entries["bp_y"] = tk.Entry(coord_frame, width=12)
        self.entries["bp_y"].grid(row=0, column=3, padx=4)
        self.entries["bp_y"].insert(0, "-85.3896")

        tk.Label(coord_frame, text="EP X:", font=("Malgun Gothic", 9)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.entries["ep_x"] = tk.Entry(coord_frame, width=12)
        self.entries["ep_x"].grid(row=1, column=1, padx=4, pady=(4, 0))
        self.entries["ep_x"].insert(0, "575.9987")
        tk.Label(coord_frame, text="EP Y:", font=("Malgun Gothic", 9)).grid(row=1, column=2, sticky="w", padx=(10, 0),
                                                                            pady=(4, 0))
        self.entries["ep_y"] = tk.Entry(coord_frame, width=12)
        self.entries["ep_y"].grid(row=1, column=3, padx=4, pady=(4, 0))
        self.entries["ep_y"].insert(0, "437.4075")

        tk.Label(parent, text="[ 정거장 횡단 및 구배 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#1565C0").pack(anchor="w",
                                                                                                           padx=15,
                                                                                                           pady=(15, 5))

        fields = [
            ("width", "정거장 전체 폭 (W, m):", "20.0"),
            ("base_level", "시점(BP) 기준선 표고 (m):", "134.45"),
            ("slope_permil", "종단구배 (‰):", "10.0"),
            ("offset", "기준선 ~ 바닥 상단 오프셋 (m):", "0.0"),
            ("height", "정거장 총 높이 (H, m):", "12.0"),
            ("floors", "층수:", "2")
        ]
        for key, lbl, val in fields:
            row_f = tk.Frame(parent)
            row_f.pack(fill="x", **pad_opts)
            tk.Label(row_f, text=lbl, font=("Malgun Gothic", 9), width=25, anchor="w").pack(side="left")
            e = tk.Entry(row_f, width=15, font=("Malgun Gothic", 9))
            e.pack(side="right")
            e.insert(0, val)
            self.entries[key] = e
            # 🌟 층수(floors) 입력 필드에 키 입력 감지 이벤트 연결
            if key == "floors":
                e.bind("<KeyRelease>", self._on_floors_changed)

    def _build_platform_tab(self, parent):
        """탭 2: 상대식 승강장 상세 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 8}
        tk.Label(parent, text="[ 승강장(Side Platform) 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#D32F2F").pack(
            anchor="w", padx=15, pady=(15, 5))

        plat_fields = [
            ("track_spacing", "선로 간격 D (m):", "4.4"),
            ("plat_offset", "선로중심~승강장 끝단 거리 (m):", "1.7"),
            ("plat_thick", "승강장 슬래브 두께 (m):", "0.2"),
            ("plat_height", "바닥 기준 승강장 높이 (m):", "1.1")
        ]
        for key, lbl, val in plat_fields:
            row_f = tk.Frame(parent)
            row_f.pack(fill="x", **pad_opts)
            tk.Label(row_f, text=lbl, font=("Malgun Gothic", 9), width=28, anchor="w").pack(side="left")
            e = tk.Entry(row_f, width=12, font=("Malgun Gothic", 9))
            e.pack(side="right")
            e.insert(0, val)
            self.entries[key] = e

        # 선택 옵션 (두 라디오버튼이 하나의 변수를 공유하도록 수정)
        # 0: 상대식 승강장, 1: 섬식 승강장
        self.station_type_var = tk.IntVar(value=0)

        chk_f = tk.Frame(parent)
        chk_f.pack(fill="x", padx=15, pady=10)

        tk.Radiobutton(
            chk_f,
            text="상대식 승강장",
            variable=self.station_type_var,
            value=0,  # 선택 시 변수 값이 0이 됨
            font=("Malgun Gothic", 9)
        ).pack(anchor="w")

        tk.Radiobutton(
            chk_f,
            text="섬식 승강장",
            variable=self.station_type_var,
            value=1,  # 선택 시 변수 값이 1이 되는 섬식
            font=("Malgun Gothic", 9),
            state="disabled"  # 비활성화 옵션 수정
        ).pack(anchor="w")

    def _build_column_tab(self, parent):
        """탭 3: 중앙 기둥 상세 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 8}

        # 1. 공통 기둥 제원
        tk.Label(parent, text="[ 중앙 기둥(Central Column) 기본 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#2E7D32").pack(
            anchor="w", padx=15, pady=(15, 5))

        col_fields = [
            ("col_interval", "기둥 종방향 배치 간격 (m):", "10.0"),
            ("col_width", "기둥 폭 (진행방향, m):", "0.8"),
            ("col_depth", "기둥 두께 (직교방향, m):", "0.8")
        ]
        for key, lbl, val in col_fields:
            row_f = tk.Frame(parent)
            row_f.pack(fill="x", **pad_opts)
            tk.Label(row_f, text=lbl, font=("Malgun Gothic", 9), width=28, anchor="w").pack(side="left")
            e = tk.Entry(row_f, width=12, font=("Malgun Gothic", 9))
            e.pack(side="right")
            e.insert(0, val)
            self.entries[key] = e

        # 체크박스 옵션 (승강장층 동기화)
        self.sync_var = tk.BooleanVar(value=True)
        chk_f = tk.Frame(parent)
        chk_f.pack(fill="x", padx=15, pady=10)
        tk.Checkbutton(chk_f, text=" 최하층 승강장과 기둥 배치 동기화", variable=self.sync_var, font=("Malgun Gothic", 9)).pack(
            anchor="w")

        # 🌟 층별 기둥 제원이 들어갈 동적 컨테이너 프레임 생성
        self.floor_col_frame = tk.Frame(parent)
        self.floor_col_frame.pack(fill="x", expand=True)

        # 초기 화면 구성
        self.update_column_floor_ui()



    def _build_print_tab(self, parent):
        """탭 4: 출력옵션 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 8}
        tk.Label(parent, text="[ 출력옵션 제원 입력 ]", font=("Malgun Gothic", 10, "bold"), fg="#2E7D32").pack(
            anchor="w", padx=15, pady=(15, 5))

        col_fields = [
            ("col_interval", "기둥 종방향 배치 간격 (m):", "10.0"),
            ("col_width", "기둥 폭 (진행방향, m):", "0.8"),
            ("col_depth", "기둥 두께 (직교방향, m):", "0.8")
        ]
        for key, lbl, val in col_fields:
            row_f = tk.Frame(parent)
            row_f.pack(fill="x", **pad_opts)
            tk.Label(row_f, text=lbl, font=("Malgun Gothic", 9), width=28, anchor="w").pack(side="left")
            e = tk.Entry(row_f, width=12, font=("Malgun Gothic", 9))
            e.pack(side="right")
            e.insert(0, val)
            self.entries[key] = e

        # 체크박스 옵션 (승강장층 동기화)
        self.sync_var = tk.BooleanVar(value=True)
        chk_f = tk.Frame(parent)
        chk_f.pack(fill="x", padx=15, pady=10)
        tk.Checkbutton(chk_f, text=" 최하층 승강장과 기둥 높이 동기화", variable=self.sync_var, font=("Malgun Gothic", 9)).pack(
            anchor="w")

    def get_project_config(self) -> StationProjectConfig:
        """모든 탭의 데이터를 수집하여 Master Config 객체로 포장"""
        station_p = StationParameters(
            bp_x=float(self.entries["bp_x"].get()), bp_y=float(self.entries["bp_y"].get()),
            ep_x=float(self.entries["ep_x"].get()), ep_y=float(self.entries["ep_y"].get()),
            width=float(self.entries["width"].get()), base_level=float(self.entries["base_level"].get()),
            slope_permil=float(self.entries["slope_permil"].get()), offset=float(self.entries["offset"].get()),
            height=float(self.entries["height"].get()), floors=int(self.entries["floors"].get())
        )
        platform_p = PlatformParameters(
            track_spacing=float(self.entries["track_spacing"].get()),
            plat_offset=float(self.entries["plat_offset"].get()),
            plat_thick=float(self.entries["plat_thick"].get()),
            plat_height=float(self.entries["plat_height"].get())
        )
        column_p = ColumnParameters(
            interval=float(self.entries["col_interval"].get()),
            width=float(self.entries["col_width"].get()),
            depth=float(self.entries["col_depth"].get()),
            sync_with_platform=self.sync_var.get(),
            target_floors=[1, 2]  # 필요시 확장 가능
        )
        return StationProjectConfig(station=station_p, platform=platform_p, column=column_p)

    def on_generate_3d(self):
        try:
            config = self.get_project_config()  # 1. 마스터 컨피그 수집
            engine = StationCADEngine(config) # 2. 엔진 인자 단 1개 전송!
            path = engine.generate_3d_dxf()
            messagebox.showinfo("성공", f"3D 모델 DXF 생성 완료!\n저장 경로: {path}")
        except Exception as e:
            messagebox.showerror("오류", f"3D 생성 실패:\n{e}")

    def on_generate_section(self):
        try:
            config = self.get_project_config()  # 1. 마스터 컨피그 수집
            engine = StationCADEngine(config)  # 2. 엔진 인자 단 1개 전송!

            stations = []
            if self.section_mode.get() == "range":
                interval = float(self.entry_interval.get())
                if interval <= 0: raise ValueError("간격은 0보다 커야 합니다.")
                cur = 0.0
                while cur <= config.station.length:
                    stations.append(cur)
                    cur += interval
                if cur - interval < config.station.length: stations.append(config.station.length)
            else:
                s_val = float(self.entry_single_sta.get())
                if not (0 <= s_val <= config.station.length): raise ValueError("측점 범위를 벗어났습니다.")
                stations.append(s_val)

            path = engine.generate_section_dxf(stations)
            messagebox.showinfo("성공", f"2D 횡단면도 DXF 생성 완료 ({len(stations)}개소)!\n저장 경로: {path}")
        except Exception as e:
            messagebox.showerror("오류", f"횡단면도 생성 실패:\n{e}")

    def on_generate_plan_profile(self):
        try:
            config = self.get_project_config()  # 1. 마스터 컨피그 수집
            engine = StationCADEngine(config)  # 2. 엔진 인자 단 1개 전송!
            p_plan = engine.generate_plan_dxf()
            p_prof = engine.generate_profile_dxf()
            messagebox.showinfo("성공", f"2D 평면도 및 종단면도 DXF 생성 완료!\n\n- 평면도: {p_plan}\n- 종단면도: {p_prof}")
        except Exception as e:
            messagebox.showerror("오류", f"평면/종단도 생성 실패:\n{e}")

    def on_export_ifc(self):
        try:
            config = self.get_project_config()  # 1. 마스터 컨피그 수집
            engine = StationCADEngine(config)  # 2. 엔진 인자 단 1개 전송!
            path = engine.generate_ifc()
            messagebox.showinfo("성공", f"BIM IFC 생성 완료!\n\n- {path}")
        except Exception as e:
            messagebox.showerror("오류", f"BIM IFC 생성 실패:\n{e}")

    def _on_floors_changed(self, event=None):
        """층수 입력값이 바뀔 때 호출되는 콜백 함수"""
        self.update_column_floor_ui()

    def update_column_floor_ui(self):
        """층수에 따라 기둥 탭의 층별 입력 필드를 실시간 재구성"""
        if not hasattr(self, 'floor_col_frame'):
            return

        # 1. 기존 프레임 내부 위젯 전면 제거
        for widget in self.floor_col_frame.winfo_children():
            widget.destroy()

        # 2. 현재 입력된 층수 파싱
        try:
            floors_str = self.entries['floors'].get().strip()
            target_floors = int(floors_str) if floors_str else 1
        except (KeyError, ValueError):
            target_floors = 1

        target_floors = max(1, target_floors)  # 최소 1층 보장

        # 3. 이전 층별 entries 키 정리 (지워진 층의 old key 제거)
        keys_to_remove = [k for k in self.entries if k.startswith("floor_") and k.endswith(("_width", "_depth"))]
        for k in keys_to_remove:
            del self.entries[k]

        # 4. 층별 UI 동적 생성
        pad_opts = {'padx': 15, 'pady': 4}
        tk.Label(self.floor_col_frame, text="[ 층별 기둥 제원 설정 ]", font=("Malgun Gothic", 10, "bold"), fg="#2E7D32").pack(
            anchor="w", padx=15, pady=(10, 5))

        for floor_idx in range(target_floors):
            floor_num = target_floors - floor_idx
            level_name = f"B{floor_num}F"

            tk.Label(self.floor_col_frame, text=f" - {level_name} 기둥 제원", font=("Malgun Gothic", 9, "italic"),
                     fg="#555555").pack(
                anchor="w", padx=20, pady=(5, 2))

            # 층별 입력창들을 담을 개별 서브 프레임 생성 (나중에 갱신하기 위함)
            floor_item_frame = tk.Frame(self.floor_col_frame)
            floor_item_frame.pack(fill="x", padx=10)

            # 1. 기둥 형태 선택 콤보박스 추가
            type_key = f"floor_{floor_idx}_type"
            row_f = tk.Frame(floor_item_frame)
            row_f.pack(fill="x", **pad_opts)
            tk.Label(row_f, text="   • 기둥 형태:", font=("Malgun Gothic", 9), width=28, anchor="w").pack(side="left")

            combo = ttk.Combobox(row_f, values=['사각기둥', '원기둥'], state="readonly", width=10, font=("Malgun Gothic", 9))
            combo.pack(side="right")
            combo.set('사각기둥')  # 기본값 설정
            self.entries[type_key] = combo  # 콤보박스 객체 저장

            # 입력 필드들이 동적으로 그려질 컨테이너
            fields_container = tk.Frame(floor_item_frame)
            fields_container.pack(fill="x")

            # 콤보박스 변경 시 필드를 다시 그려주는 함수 정의
            def refresh_fields(event=None, f_idx=floor_idx, cb=combo, container=fields_container):
                # 기존 입력 필드 삭제
                for widget in container.winfo_children():
                    widget.destroy()

                # 기존 entry 키들도 정리가 필요하다면 여기서 처리
                selected_type = cb.get()
                if selected_type == '사각기둥':
                    floor_fields = [
                        (f"floor_{f_idx}_width", "   • 기둥 폭 (m):", "0.8"),
                        (f"floor_{f_idx}_depth", "   • 기둥 두께 (m):", "0.8")
                    ]
                else:  # 원기둥
                    floor_fields = [
                        (f"floor_{f_idx}_radius", "   • 기둥 반지름 (m):", "0.5")
                    ]

                for key, lbl, val in floor_fields:
                    row_f = tk.Frame(container)
                    row_f.pack(fill="x", **pad_opts)
                    tk.Label(row_f, text=lbl, font=("Malgun Gothic", 9), width=28, anchor="w").pack(side="left")
                    e = tk.Entry(row_f, width=12, font=("Malgun Gothic", 9))
                    e.pack(side="right")
                    e.insert(0, val)
                    self.entries[key] = e

            # 콤보박스 선택 이벤트 바인딩
            combo.bind("<<ComboboxSelected>>", refresh_fields)

            # 최초 실행 시 기본 필드(사각기둥 기준) 생성
            refresh_fields()
