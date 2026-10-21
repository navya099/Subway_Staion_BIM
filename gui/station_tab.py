import tkinter as tk

from config.alignment_config import AlignmentConfig
from config.station_config import StationParameters


class StationTab:
    def __init__(self, parent, entries_dict, on_floors_changed_callback):
        self.parent = parent
        self.entries = entries_dict  # 메인 앱의 entries 공유받기
        self.on_floors_changed = on_floors_changed_callback  # 콜백 연결

    def build_station_tab(self):
        """탭 1: 선형 및 정거장 박스 기본 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 4}
        AL, SP = AlignmentConfig(), StationParameters()   # 초기값은 dataclass 기본값이 단일 출처
        tk.Label(self.parent, text="[ WCS 절대 좌표계 선형 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#1565C0").pack(
            anchor="w", padx=15, pady=(10, 5))

        coord_frame = tk.Frame(self.parent)
        coord_frame.pack(anchor="w", padx=15, pady=2)

        tk.Label(coord_frame, text="BP X:", font=("Malgun Gothic", 9)).grid(row=0, column=0, sticky="w")
        self.entries["bp_x"] = tk.Entry(coord_frame, width=12)
        self.entries["bp_x"].grid(row=0, column=1, padx=4)
        self.entries["bp_x"].insert(0, str(AL.bp_x))

        tk.Label(coord_frame, text="BP Y:", font=("Malgun Gothic", 9)).grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.entries["bp_y"] = tk.Entry(coord_frame, width=12)
        self.entries["bp_y"].grid(row=0, column=3, padx=4)
        self.entries["bp_y"].insert(0, str(AL.bp_y))

        tk.Label(coord_frame, text="BP Z:", font=("Malgun Gothic", 9)).grid(row=0, column=4, sticky="w", padx=(10, 0))
        self.entries["bp_z"] = tk.Entry(coord_frame, width=12)
        self.entries["bp_z"].grid(row=0, column=5, padx=4)
        self.entries["bp_z"].insert(0, str(AL.bp_z))

        tk.Label(coord_frame, text="EP X:", font=("Malgun Gothic", 9)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.entries["ep_x"] = tk.Entry(coord_frame, width=12)
        self.entries["ep_x"].grid(row=1, column=1, padx=4, pady=(4, 0))
        self.entries["ep_x"].insert(0, str(AL.ep_x))

        tk.Label(coord_frame, text="EP Y:", font=("Malgun Gothic", 9)).grid(row=1, column=2, sticky="w", padx=(10, 0),
                                                                            pady=(4, 0))
        self.entries["ep_y"] = tk.Entry(coord_frame, width=12)
        self.entries["ep_y"].grid(row=1, column=3, padx=4, pady=(4, 0))
        self.entries["ep_y"].insert(0, str(AL.ep_y))

        tk.Label(coord_frame, text="EP Z:", font=("Malgun Gothic", 9)).grid(row=1, column=4, sticky="w", padx=(10, 0))
        self.entries["ep_z"] = tk.Entry(coord_frame, width=12)
        self.entries["ep_z"].grid(row=1, column=5, padx=4)
        self.entries["ep_z"].insert(0, str(AL.ep_z))

        tk.Label(coord_frame, text="선형 시작 측점:", font=("Malgun Gothic", 9)).grid(row=2, column=0, sticky="w")
        self.entries["bp_station"] = tk.Entry(coord_frame, width=12)
        self.entries["bp_station"].grid(row=2, column=1, padx=4)
        self.entries["bp_station"].insert(0, str(AL.bp_station))

        tk.Label(self.parent, text="[ 정거장 횡단 및 구배 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#1565C0").pack(
            anchor="w", padx=15, pady=(15, 5))

        fields = [
            ("length", "정거장 전체 길이 (L, m):", str(SP.length)),
            ("width", "정거장 전체 폭 (W, m):", str(SP.width)),
            ("start_station", "정거장 시작 측점 STA(m):", str(SP.start_station)),
            ("offset", "기준선 ~ 바닥 상단 오프셋 (m):", str(SP.offset)),
            ("height", "정거장 총 높이 (H, m):", str(SP.height)),
            ("floors", "층수:", str(SP.floors)),
            ("wall_t", "외벽 두께:", str(SP.wall_t)),
            ("floor_t", "바닥슬래브 두께:", str(SP.floor_t)),
            ("slab_t", "천장 및 중간슬래브 두께:", str(SP.slab_t)),
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