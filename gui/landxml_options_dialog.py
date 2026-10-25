import tkinter as tk
from tkinter import ttk

from config.alignment_landxml import LandXMLOptions

FONT = ("Malgun Gothic", 9)
AXIS_PRESETS = [("자동 판단 (표준 '북 동' 먼저)", "auto"), ("북 동  (LandXML 표준)", "NE"), ("동 북", "EN")]


class LandXMLOptionsDialog:
    """LandXML 파일에서 읽을 선형 / 종단 / 좌표 순서를 고르는 대화상자. 확인하면 result 에 LandXMLOptions"""

    def __init__(self, parent, path, infos, modal=True):
        self.result: LandXMLOptions | None = None
        self.infos = {i.name: i for i in infos}
        self.top = tk.Toplevel(parent)
        self.top.title("LandXML 선형 선택")
        self.top.transient(parent)
        self.top.resizable(False, False)
        name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
        tk.Label(self.top, text=f"파일: {name}  (선형 {len(infos)}개)", font=("Malgun Gothic", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 4))

        form = tk.Frame(self.top)
        form.pack(fill="x", padx=12)
        tk.Label(form, text="선형", font=FONT).grid(row=0, column=0, sticky="w", pady=2)
        self.align_var = tk.StringVar(value=infos[0].name)
        self.align_combo = ttk.Combobox(form, textvariable=self.align_var, state="readonly", width=38, font=FONT,
                                        values=[i.name for i in infos])
        self.align_combo.grid(row=0, column=1, sticky="w", padx=6)
        tk.Label(form, text="종단", font=FONT).grid(row=1, column=0, sticky="w", pady=2)
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(form, textvariable=self.profile_var, state="readonly", width=38, font=FONT)
        self.profile_combo.grid(row=1, column=1, sticky="w", padx=6)
        tk.Label(form, text="좌표 순서", font=FONT).grid(row=2, column=0, sticky="w", pady=2)
        self.axis_var = tk.StringVar(value=AXIS_PRESETS[0][0])
        self.axis_combo = ttk.Combobox(form, textvariable=self.axis_var, state="readonly", width=38, font=FONT,
                                       values=[label for label, _ in AXIS_PRESETS])
        self.axis_combo.grid(row=2, column=1, sticky="w", padx=6)

        self.info_var = tk.StringVar()
        tk.Label(self.top, textvariable=self.info_var, justify="left", fg="#555555", font=("Malgun Gothic", 8),
                 wraplength=470).pack(anchor="w", padx=12, pady=(8, 0))
        tk.Label(self.top, justify="left", fg="#555555", font=("Malgun Gothic", 8), wraplength=470,
                 text="• 요소 끝점을 파일 좌표와 대조해서 좌표 순서가 틀리면 자동으로 알려줍니다.\n"
                      "• 길이 단위는 파일의 <Units> 로 m 로 환산합니다."
                 ).pack(anchor="w", padx=12, pady=(4, 0))
        self.error_var = tk.StringVar(value="")
        tk.Label(self.top, textvariable=self.error_var, fg="#C62828", font=FONT, wraplength=470, justify="left").pack(anchor="w", padx=12)

        btns = tk.Frame(self.top)
        btns.pack(pady=10)
        tk.Button(btns, text="확인", width=10, font=FONT, command=self.ok).pack(side="left", padx=6)
        tk.Button(btns, text="취소", width=10, font=FONT, command=self.cancel).pack(side="left", padx=6)
        self.align_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        self.top.protocol("WM_DELETE_WINDOW", self.cancel)
        self._refresh()
        if modal:
            self.top.grab_set()
            self.top.wait_window()

    def _refresh(self):
        info = self.infos[self.align_var.get()]
        self.profile_combo.configure(values=info.profiles)
        self.profile_var.set(info.profiles[0] if info.profiles else "")
        self.info_var.set(f"연장 {info.length:,.1f}m, 시작 측점 {info.sta_start:,.2f}, 종단 {len(info.profiles)}개"
                          + ("" if info.profiles else "  ⚠ 이 선형에는 종단이 없어 읽을 수 없습니다 (표고 필요)"))

    def ok(self):
        info = self.infos[self.align_var.get()]
        if not info.profiles:
            self.error_var.set("이 선형에는 종단(Profile)이 없습니다. 종단이 있는 선형을 고르세요")
            return
        axis = dict(AXIS_PRESETS)[self.axis_var.get()]
        self.result = LandXMLOptions(alignment=info.name, profile=self.profile_var.get(), axis=axis)
        self.top.destroy()

    def cancel(self):
        self.result = None
        self.top.destroy()
