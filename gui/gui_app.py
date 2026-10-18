import tkinter as tk
from tkinter import messagebox, ttk

from engine.bim_engine import BIMEngine
from gui.column_tab import ColumnTab
from gui.platform_tab import PlatformTab
from gui.print_tab import PrintTab
from gui.station_tab import StationTab
from gui.tk_adapter import TkAdapter


class StationBIMApp:
    def __init__(self, root: tk.Tk):
        self.floor_col_frame = None
        self.entries = {}
        self.root = root
        self.root.title("지하철 개착정거장 자동 설계 (BIM Engine)")
        self.root.geometry("480x1024")
        self.root.resizable(False, True)

        self._build_ui()

    def _build_ui(self):
        # 전체 메인 탭 노트북 생성
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # 탭 1: 선형 및 본체 제원
        tab_station = ttk.Frame(notebook)
        notebook.add(tab_station, text="  1. 선형 및 본체  ")
        self.station_tab = StationTab(tab_station, self.entries, self._on_floors_changed)
        self.station_tab.build_station_tab()

        # 탭 2: 승강장 제원
        tab_platform = ttk.Frame(notebook)
        notebook.add(tab_platform, text="  2. 상대식 승강장  ")
        self.platform_tab = PlatformTab(tab_platform, self.entries)
        self.platform_tab.build()

        # 탭 3: 중앙 기둥 제원
        tab_column = ttk.Frame(notebook)
        notebook.add(tab_column, text="  3. 중앙 기둥  ")
        self.column_tab = ColumnTab(tab_column, self.entries)
        self.column_tab.build()

        # 탭 4: 출력 설정
        tab_print = ttk.Frame(notebook)
        notebook.add(tab_print, text="  4. 출력 설정  ")
        self.print_tab = PrintTab(tab_print, self.entries)
        self.print_tab.build()

        # 하단 공통 실행 버튼 패널 (어떤 탭에 있든 항상 실행 가능)
        btn_frame = tk.Frame(self.root, bg="#ECEFF1", relief="groove", bd=1)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btn_frame, text="성과물 출력", font=("Malgun Gothic", 9, "bold"), bg="#3F51B5", fg="white", width=22,
                  command=self.on_generate).pack(side="left", padx=8, pady=8)
        tk.Button(btn_frame, text="종료", font=("Malgun Gothic", 9, "bold"), bg="#00897B", fg="white", width=22,
                  command=self.root.destroy).pack(side="right", padx=8, pady=8)

    def _on_floors_changed(self, event=None):
        """🌟 층수가 변경될 때 메인 앱을 통해 ColumnTab의 UI 갱신을 트리거"""
        if hasattr(self, 'column_tab'):
            self.column_tab.update_column_floor_ui()

    def on_generate(self):
        try:
            spg = TkAdapter.collect_entries(self.entries)
            bim = BIMEngine.build(spg)
        except Exception as e:
            messagebox.showerror('에러', str(e))
            return

