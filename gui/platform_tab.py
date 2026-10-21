import tkinter as tk

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