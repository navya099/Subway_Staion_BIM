import tkinter as tk


class StationTab:
    def __init__(self, parent, entries_dict, on_floors_changed_callback):
        self.parent = parent
        self.entries = entries_dict  # 메인 앱의 entries 공유받기
        self.on_floors_changed = on_floors_changed_callback  # 콜백 연결

    def build_station_tab(self):
        """탭 1: 선형 및 정거장 박스 기본 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 4}
        tk.Label(self.parent, text="[ WCS 절대 좌표계 선형 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#1565C0").pack(
            anchor="w", padx=15, pady=(10, 5))

        coord_frame = tk.Frame(self.parent)
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

        tk.Label(self.parent, text="[ 정거장 횡단 및 구배 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#1565C0").pack(
            anchor="w", padx=15, pady=(15, 5))

        fields = [
            ("width", "정거장 전체 폭 (W, m):", "20.0"),
            ("base_level", "시점(BP) 기준선 표고 (m):", "134.45"),
            ("slope_permil", "종단구배 (‰):", "10.0"),
            ("offset", "기준선 ~ 바닥 상단 오프셋 (m):", "0.0"),
            ("height", "정거장 총 높이 (H, m):", "12.0"),
            ("floors", "층수:", "2")
        ]

        for key, lbl, val in fields:
            row_f = tk.Frame(self.parent)
            row_f.pack(fill="x", **pad_opts)
            tk.Label(row_f, text=lbl, font=("Malgun Gothic", 9), width=25, anchor="w").pack(side="left")
            e = tk.Entry(row_f, width=15, font=("Malgun Gothic", 9))
            e.pack(side="right")
            e.insert(0, val)
            self.entries[key] = e

            # 🌟 층수 입력 필드인 경우 전달받은 콜백 함수 바인딩
            if key == "floors" and self.on_floors_changed:
                e.bind("<KeyRelease>", self.on_floors_changed)