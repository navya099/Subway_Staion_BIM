import tkinter as tk
from tkinter import ttk


class ColumnTab:
    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict  # 메인 앱의 entries 공유받기

    def build(self):
        """탭 3: 중앙 기둥 상세 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 8}

        # 1. 공통 기둥 제원
        tk.Label(self.parent, text="[ 중앙 기둥(Central Column) 기본 제원 ]", font=("Malgun Gothic", 10, "bold"), fg="#2E7D32").pack(
            anchor="w", padx=15, pady=(15, 5))

        col_fields = [
            ("col_interval", "기둥 종방향 배치 간격 (m):", "10.0"),
            ("col_width", "기둥 폭 (진행방향, m):", "0.8"),
            ("col_depth", "기둥 두께 (직교방향, m):", "0.8")
        ]
        for key, lbl, val in col_fields:
            row_f = tk.Frame(self.parent)
            row_f.pack(fill="x", **pad_opts)
            tk.Label(row_f, text=lbl, font=("Malgun Gothic", 9), width=28, anchor="w").pack(side="left")
            e = tk.Entry(row_f, width=12, font=("Malgun Gothic", 9))
            e.pack(side="right")
            e.insert(0, val)
            self.entries[key] = e

        # 체크박스 옵션 (승강장층 동기화)
        self.sync_var = tk.BooleanVar(value=True)
        chk_f = tk.Frame(self.parent)
        chk_f.pack(fill="x", padx=15, pady=10)
        tk.Checkbutton(chk_f, text=" 최하층 승강장과 기둥 배치 동기화", variable=self.sync_var, font=("Malgun Gothic", 9)).pack(
            anchor="w")
        self.entries['sync_all'] = self.sync_var
        # 🌟 층별 기둥 제원이 들어갈 동적 컨테이너 프레임 생성
        self.floor_col_frame = tk.Frame(self.parent)
        self.floor_col_frame.pack(fill="x", expand=True)

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
        keys_to_remove = [k for k in self.entries if k.startswith("floor_") and k.endswith(("_width", "_depth", "_radius", "_type"))]
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
                for suffix in ("width", "depth", "radius"):
                    self.entries.pop(f"floor_{f_idx}_{suffix}", None)

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