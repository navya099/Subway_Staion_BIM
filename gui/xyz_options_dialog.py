import tkinter as tk
from tkinter import ttk

from config.alignment_text import ORDER_PRESETS, XYZOptions, preview_lines

FONT = ("Malgun Gothic", 9)


class XYZOptionsDialog:
    """좌표 목록 파일을 읽기 전에 열 순서 / 시작 측점 / 평활 구간을 정하는 대화상자. 확인하면 result 에 XYZOptions"""

    def __init__(self, parent, path, modal=True):
        self.result: XYZOptions | None = None
        self.top = tk.Toplevel(parent)
        self.top.title("좌표 목록 선형 읽기 옵션")
        self.top.transient(parent)
        self.top.resizable(False, False)
        name = str(path).replace("\\", "/").rsplit("/", 1)[-1]

        tk.Label(self.top, text=f"파일: {name}", font=("Malgun Gothic", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(self.top, text="앞부분 미리보기 (길이 단위는 m 로 읽습니다)", font=("Malgun Gothic", 8), fg="#555555").pack(anchor="w", padx=12)
        box = tk.Text(self.top, width=62, height=8, font=("Consolas", 9), bg="#F5F5F5")
        box.insert("1.0", "\n".join(preview_lines(path)))
        box.configure(state="disabled")
        box.pack(padx=12, pady=(2, 8))

        form = tk.Frame(self.top)
        form.pack(fill="x", padx=12)
        tk.Label(form, text="열 순서", font=FONT).grid(row=0, column=0, sticky="w", pady=2)
        self.order_var = tk.StringVar(value=ORDER_PRESETS[0][0])
        self.combo = ttk.Combobox(form, textvariable=self.order_var, state="readonly", width=34, font=FONT,
                                  values=[label for label, _ in ORDER_PRESETS])
        self.combo.grid(row=0, column=1, sticky="w", padx=6)
        tk.Label(form, text="시작 측점 (m)", font=FONT).grid(row=1, column=0, sticky="w", pady=2)
        self.start_var = tk.StringVar(value="0.0")
        tk.Entry(form, textvariable=self.start_var, width=12, font=FONT).grid(row=1, column=1, sticky="w", padx=6)
        tk.Label(form, text="평활 반폭 (m)", font=FONT).grid(row=2, column=0, sticky="w", pady=2)
        self.smooth_var = tk.StringVar(value="5.0")
        tk.Entry(form, textvariable=self.smooth_var, width=12, font=FONT).grid(row=2, column=1, sticky="w", padx=6)
        tk.Label(self.top, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=470,
                 text="• 측점 열이 있는 형식이면 그 첫 값이 시작 측점이 됩니다 (입력한 시작 측점은 무시).\n"
                      "• Civil 3D 의 N,E,Z 순서 파일은 'Y X Z' 를 고르세요.\n"
                      "• 좌표 소수점이 cm 단위로 거칠면 평활 반폭을 8~12 로 늘리면 방향·곡률이 매끈해집니다."
                 ).pack(anchor="w", padx=12, pady=(6, 0))
        self.error_var = tk.StringVar(value="")
        tk.Label(self.top, textvariable=self.error_var, fg="#C62828", font=FONT).pack(anchor="w", padx=12)

        btns = tk.Frame(self.top)
        btns.pack(pady=10)
        tk.Button(btns, text="확인", width=10, font=FONT, command=self.ok).pack(side="left", padx=6)
        tk.Button(btns, text="취소", width=10, font=FONT, command=self.cancel).pack(side="left", padx=6)
        self.top.protocol("WM_DELETE_WINDOW", self.cancel)
        if modal:
            self.top.grab_set()
            self.top.wait_window()

    def ok(self):
        try:
            start = float(self.start_var.get().replace(",", "."))
            smooth = float(self.smooth_var.get().replace(",", "."))
        except ValueError:
            self.error_var.set("시작 측점과 평활 반폭은 숫자로 입력하세요")
            return
        if smooth < 0:
            self.error_var.set("평활 반폭은 0 이상이어야 합니다")
            return
        order = dict(ORDER_PRESETS)[self.order_var.get()]
        self.result = XYZOptions(order=order, start_station=start, smooth_m=smooth)
        self.top.destroy()

    def cancel(self):
        self.result = None
        self.top.destroy()
