import tkinter as tk


class PlatformTab:
    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict  # 메인 앱의 entries 공유받기

    def build(self):
        """탭 2: 상대식 승강장 상세 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 8}
        tk.Label(self.parent, text="[ 승강장(Side Platform) 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#D32F2F").pack(
            anchor="w", padx=15, pady=(15, 5))

        plat_fields = [
            ("track_spacing", "선로 간격 D (m):", "4.4"),
            ("plat_offset", "선로중심~승강장 끝단 거리 (m):", "1.7"),
            ("plat_thick", "승강장 슬래브 두께 (m):", "0.2"),
            ("plat_height", "바닥 기준 승강장 높이 (m):", "1.1")
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
        self.station_type_var = tk.IntVar(value=0)

        chk_f = tk.Frame(self.parent)
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

        self.entries['platform_type'] = self.station_type_var