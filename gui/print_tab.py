import tkinter as tk
from tkinter import ttk


class PrintTab:
    def __init__(self, parent, entries_dict):
        self.parent = parent
        self.entries = entries_dict  # 메인 앱의 entries 공유받기

    def build(self):
        """탭 4: 출력옵션 제원 입력"""
        pad_opts = {'padx': 15, 'pady': 8}
        tk.Label(self.parent, text="[ 출력옵션 제원 입력 ]", font=("Malgun Gothic", 10, "bold"), fg="#2E7D32").pack(
            anchor="w", padx=15, pady=(15, 5))