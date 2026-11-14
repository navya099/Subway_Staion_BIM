import copy
import os
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

from engine.bim_engine import BIMEngine
from gui.column_tab import ColumnTab
from gui.entrance_tab import EntranceTab
from gui.escalator_tab import EscalatorTab
from gui.opening_tab import OpeningTab
from gui.passage_tab import PassageTab
from gui.platform_tab import PlatformTab
from gui.print_tab import PrintTab
from gui.project_file import FILETYPES, LIST_DRAFTS, SUFFIX, ProjectState, RecentProjects, open_project, save_project
from gui.stair_tab import StairTab
from gui.station_tab import StationTab
from gui.tk_adapter import TkAdapter


APP_TITLE = "지하철 개착정거장 자동 설계 (BIM Engine)"
FLOOR_KEYS = ("floor_height_", "wall_t_")       # 층수에 따라 다시 만들어지는 입력칸
DRAFT_TABS = ("column_tab", "opening_tab", "stair_tab", "escalator_tab", "passage_tab", "entrance_tab")


class StationBIMApp:
    def __init__(self, root: tk.Tk, recent_file=None, watch=True):
        """recent_file: 최근 프로젝트 목록 파일 (기본: 사용자 설정 폴더). watch: 제목 표시줄의 변경 표시(*)를 주기적으로 갱신"""
        self.floor_col_frame = None
        self.entries = {}
        self.root = root
        self.root.geometry("480x1024")
        self.root.resizable(False, True)
        self.project_path = None
        self.recent = RecentProjects(recent_file)

        self._build_ui()
        self._build_menu()
        self.root.update_idletasks()
        self._default_state = self.collect_state()   # 새 프로젝트 = 처음 화면
        self._saved_key = self._default_state.key()
        self.refresh_title()
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)
        self._watch_job = None
        if watch:
            self._watch()

    def _build_ui(self):
        # 전체 메인 탭 노트북 생성
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # 탭 1: 선형 및 본체 제원
        tab_station = ttk.Frame(notebook)
        notebook.add(tab_station, text=" 1. 선형·본체 ")
        self.station_tab = StationTab(tab_station, self.entries, self._on_floors_changed)
        self.station_tab.build_station_tab()

        # 탭 2: 승강장 제원
        tab_platform = ttk.Frame(notebook)
        notebook.add(tab_platform, text=" 2. 승강장 ")
        self.platform_tab = PlatformTab(tab_platform, self.entries)
        self.platform_tab.build()

        # 탭 3: 중앙 기둥 제원
        tab_column = ttk.Frame(notebook)
        notebook.add(tab_column, text=" 3. 기둥 ")
        self.column_tab = ColumnTab(tab_column, self.entries)
        self.column_tab.build()
        # 1번 탭에서 길이/외벽 두께를 바꾼 뒤 기둥 탭으로 오면 예상 기둥 개수를 다시 계산
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # 탭 4: 슬래브 오프닝
        tab_opening = ttk.Frame(notebook)
        notebook.add(tab_opening, text=" 4. 오프닝 ")
        self.opening_tab = OpeningTab(tab_opening, self.entries)
        self.opening_tab.build()

        # 탭 5: 계단
        tab_stair = ttk.Frame(notebook)
        notebook.add(tab_stair, text=" 5. 계단 ")
        self.stair_tab = StairTab(tab_stair, self.entries)
        self.stair_tab.build()

        # 탭 6: 에스컬레이터
        tab_esc = ttk.Frame(notebook)
        notebook.add(tab_esc, text=" 6. ESC ")
        self.escalator_tab = EscalatorTab(tab_esc, self.entries)
        self.escalator_tab.build()

        # 탭 7: 출구통로
        tab_passage = ttk.Frame(notebook)
        notebook.add(tab_passage, text=" 7. 통로 ")
        self.passage_tab = PassageTab(tab_passage, self.entries)
        self.passage_tab.build()

        # 탭 8: 출입구
        tab_entrance = ttk.Frame(notebook)
        notebook.add(tab_entrance, text=" 8. 출입구 ")
        self.entrance_tab = EntranceTab(tab_entrance, self.entries)
        self.entrance_tab.build()

        # 탭 9: 출력 설정
        tab_print = ttk.Frame(notebook)
        notebook.add(tab_print, text=" 9. 출력 ")
        self.print_tab = PrintTab(tab_print, self.entries)
        self.print_tab.build()

        # 하단 공통 실행 버튼 패널 (어떤 탭에 있든 항상 실행 가능)
        btn_frame = tk.Frame(self.root, bg="#ECEFF1", relief="groove", bd=1)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btn_frame, text="성과물 출력", font=("Malgun Gothic", 9, "bold"), bg="#3F51B5", fg="white", width=22,
                  command=self.on_generate).pack(side="left", padx=8, pady=8)
        tk.Button(btn_frame, text="종료", font=("Malgun Gothic", 9, "bold"), bg="#00897B", fg="white", width=22,
                  command=self.on_exit).pack(side="right", padx=8, pady=8)

    def _on_tab_changed(self, event=None):
        """1번 탭에서 바꾼 값(내공 길이, 층수, 시작 측점, 층 높이)을 기둥·오프닝·계단·에스컬레이터·통로 탭에 반영"""
        if hasattr(self, 'column_tab'):
            self.column_tab.refresh_counts()
        if hasattr(self, 'opening_tab'):
            self.opening_tab.update_floor_ui()
            self.opening_tab.refresh_ranges()
        if hasattr(self, 'stair_tab'):
            self.stair_tab.update_floor_ui()
            self.stair_tab.refresh_info()
        if hasattr(self, 'escalator_tab'):
            self.escalator_tab.update_floor_ui()
            self.escalator_tab.refresh_info()
        if hasattr(self, 'passage_tab'):
            self.passage_tab.update_floor_ui()
            self.passage_tab.refresh_info()
        if hasattr(self, 'print_tab'):
            self.print_tab.update_floor_ui()
            self.print_tab.refresh_info()

    def _on_floors_changed(self, event=None):
        """🌟 층수가 변경될 때 메인 앱을 통해 ColumnTab의 UI 갱신을 트리거"""
        if hasattr(self, 'station_tab'):
            self.station_tab.update_floor_heights()
        if hasattr(self, 'column_tab'):
            self.column_tab.update_column_floor_ui()
        if hasattr(self, 'opening_tab'):
            self.opening_tab.update_floor_ui()
        if hasattr(self, 'stair_tab'):
            self.stair_tab.update_floor_ui()
        if hasattr(self, 'escalator_tab'):
            self.escalator_tab.update_floor_ui()
        if hasattr(self, 'passage_tab'):
            self.passage_tab.update_floor_ui()
        if hasattr(self, 'print_tab'):
            self.print_tab.update_floor_ui()

    def on_generate(self):
        try:
            cfg = TkAdapter.collect_entries(self.entries)
            opt = TkAdapter.collect_output(self.entries, cfg)       # 폴더를 고르기 전에 출력 옵션도 검사
            out_dir = filedialog.askdirectory(title="성과물 저장 폴더 선택")
            if not out_dir:
                return
            paths = BIMEngine.build(cfg, out_dir, opt)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror('에러', f"{type(e).__name__}: {e}")
            return
        messagebox.showinfo('완료', "생성된 파일:\n" + "\n".join(paths))


    # ================================================================== 프로젝트 파일
    def _build_menu(self):
        bar = tk.Menu(self.root)
        m = tk.Menu(bar, tearoff=0)
        m.add_command(label="새 프로젝트", accelerator="Ctrl+N", command=self.on_new)
        m.add_command(label="열기…", accelerator="Ctrl+O", command=self.on_open)
        self.recent_menu = tk.Menu(m, tearoff=0)
        m.add_cascade(label="최근 프로젝트", menu=self.recent_menu)
        m.add_separator()
        m.add_command(label="저장", accelerator="Ctrl+S", command=self.on_save)
        m.add_command(label="다른 이름으로 저장…", accelerator="Ctrl+Shift+S", command=self.on_save_as)
        m.add_separator()
        m.add_command(label="종료", command=self.on_exit)
        bar.add_cascade(label="파일", menu=m)
        self.root.config(menu=bar)
        self.file_menu = m
        # Ctrl+Shift+S 는 Shift 때문에 keysym 이 대문자 S 로 옴
        for seq, fn in (("<Control-n>", self.on_new), ("<Control-o>", self.on_open), ("<Control-s>", self.on_save),
                        ("<Control-S>", self.on_save_as)):
            self.root.bind_all(seq, lambda e, f=fn: self._shortcut(f))
        self._refresh_recent_menu()

    @staticmethod
    def _shortcut(fn):
        fn()
        return "break"

    def _refresh_recent_menu(self):
        self.recent_menu.delete(0, "end")
        if not self.recent.items:
            self.recent_menu.add_command(label="(없음)", state="disabled")
        for k, path in enumerate(self.recent.items, start=1):
            self.recent_menu.add_command(label=f"{k}. {os.path.basename(path)}  —  {os.path.dirname(path)}",
                                         command=lambda p=path: self.on_open(p))

    # ------------------------------------------------------------------ 화면 ↔ 상태
    def collect_state(self) -> ProjectState:
        """현재 화면 입력 전체 (입력칸 텍스트 + 탭별 초안 + 포함된 선형)"""
        st = ProjectState()
        st.fields = {k: e.get() for k, e in self.entries.items() if isinstance(e, tk.Entry)}
        st.platform_type = int(self.entries["platform_type"].get())
        st.sync_all = bool(self.entries["sync_all"].get())
        st.column_floors = copy.deepcopy(self.column_tab.drafts.floors)      # 화면이 초안을 계속 고치므로 복사본
        for name in LIST_DRAFTS:
            setattr(st, name, copy.deepcopy(self.entries[name].items))
        st.print_draft = copy.deepcopy(self.print_tab.draft)
        source = self.station_tab.source
        st.alignment = source.embedded if source.alignment is not None else None
        return st

    @staticmethod
    def _set_entry(e: tk.Entry, text: str):
        state = e.cget("state")
        e.configure(state="normal")              # 비활성 칸(선형 파일 사용 중 BP/EP, 1개 층의 중간 슬래브)도 채움
        e.delete(0, "end")
        e.insert(0, text)
        e.configure(state=state)

    def apply_state(self, st: ProjectState) -> list:
        """상태를 화면에 복원. 경고 목록 반환 (포함된 선형을 읽지 못하면 BP/EP 직선으로 열고 경고)"""
        warnings = []
        self.station_tab.reset_alignment()
        for k, v in st.fields.items():
            if not k.startswith(FLOOR_KEYS) and isinstance(self.entries.get(k), tk.Entry):
                self._set_entry(self.entries[k], v)
        self._on_floors_changed()                # 층수에 맞게 층별 입력칸·탭을 다시 구성
        for k, v in st.fields.items():
            if k.startswith(FLOOR_KEYS) and isinstance(self.entries.get(k), tk.Entry):
                self._set_entry(self.entries[k], v)
        self.station_tab.refresh_heights()
        if st.platform_type is not None:
            self.entries["platform_type"].set(st.platform_type)
        self.entries["sync_all"].set(st.sync_all)
        floors = self.column_tab.drafts.floors
        floors.clear()
        floors.update(copy.deepcopy(st.column_floors))                      # 상태(예: 새 프로젝트 기본값)는 그대로 두고 복사본을 편집
        for name in LIST_DRAFTS:
            self.entries[name].items[:] = copy.deepcopy(getattr(st, name))
        for name in DRAFT_TABS:
            tab = getattr(self, name)
            n = getattr(tab, "floor_count", 0)
            if n and hasattr(tab.drafts, "ensure_floors"):
                tab.drafts.ensure_floors(n)
            tab.render()
        pd = self.print_tab.draft                               # 초안 객체는 그대로 두고 내용만 교체 (entries 가 참조)
        pd.__dict__.update(copy.deepcopy(st.print_draft).__dict__)
        pd.ensure_floors(self.print_tab._read_floor_count() or 1, 0)
        self.print_tab.render()
        if st.alignment is not None:
            try:
                a = st.alignment.load()
            except ValueError as e:
                warnings.append(f"포함된 선형 파일({st.alignment.main})을 읽지 못해 BP/EP 직선으로 열었습니다: {e}")
            else:
                self.station_tab.set_alignment(a, st.alignment.source_path or st.alignment.main, st.alignment,
                                               note="\n(프로젝트에 포함된 선형)")
        self._on_tab_changed()
        self.root.update_idletasks()
        return warnings

    # ------------------------------------------------------------------ 변경 여부 · 제목
    def is_dirty(self) -> bool:
        return self.collect_state().key() != self._saved_key

    def refresh_title(self):
        name = os.path.basename(self.project_path) if self.project_path else "새 프로젝트"
        title = f"{name}{' *' if self.is_dirty() else ''} — {APP_TITLE}"
        if self.root.title() != title:
            self.root.title(title)

    def _watch(self):
        try:
            self.refresh_title()
        except (tk.TclError, ValueError, KeyError):
            pass
        self._watch_job = self.root.after(700, self._watch)

    def _mark_saved(self, path):
        self.project_path = path
        self._saved_key = self.collect_state().key()
        self.recent.add(path)
        self._refresh_recent_menu()
        self.refresh_title()

    # ------------------------------------------------------------------ 메뉴 동작
    def ask_save_changes(self):
        """저장하지 않은 변경이 있을 때 물음: True(저장) / False(저장 안 함) / None(취소)"""
        name = os.path.basename(self.project_path) if self.project_path else "새 프로젝트"
        return messagebox.askyesnocancel("저장 확인", f"'{name}' 의 변경 사항을 저장할까요?", parent=self.root)

    def ask_open_path(self):
        return filedialog.askopenfilename(title="프로젝트 열기", filetypes=FILETYPES, parent=self.root)

    def ask_save_path(self):
        init = os.path.basename(self.project_path) if self.project_path else "정거장" + SUFFIX
        return filedialog.asksaveasfilename(title="프로젝트 저장", defaultextension=SUFFIX, filetypes=FILETYPES,
                                            initialfile=init, parent=self.root)

    def confirm_discard(self) -> bool:
        """계속 진행해도 되면 True (변경 없음 / 저장함 / 저장 안 함 선택)"""
        if not self.is_dirty():
            return True
        ans = self.ask_save_changes()
        if ans is None:
            return False
        return self.on_save() if ans else True

    def on_new(self):
        if not self.confirm_discard():
            return False
        self.apply_state(self._default_state)
        self.project_path = None
        self._saved_key = self.collect_state().key()
        self.refresh_title()
        return True

    def on_open(self, path=None):
        if not self.confirm_discard():
            return False
        path = path or self.ask_open_path()
        if not path:
            return False
        try:
            st = open_project(path)              # 화면을 바꾸기 전에 모두 읽고 검사
        except ValueError as e:
            messagebox.showerror("프로젝트 열기 오류", f"{path}\n{e}", parent=self.root)
            if not os.path.exists(path):
                self.recent.remove(path)
                self._refresh_recent_menu()
            return False
        warnings = self.apply_state(st)
        self._mark_saved(path)
        if warnings:
            messagebox.showwarning("프로젝트 열기", "\n".join(warnings), parent=self.root)
        return True

    def on_save(self):
        if not self.project_path:
            return self.on_save_as()
        return self._save_to(self.project_path)

    def on_save_as(self):
        path = self.ask_save_path()
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += SUFFIX
        return self._save_to(path)

    def _save_to(self, path) -> bool:
        try:
            save_project(path, self.collect_state())
        except OSError as e:
            messagebox.showerror("프로젝트 저장 오류", f"{path}\n{e.strerror or e}", parent=self.root)
            return False
        self._mark_saved(path)
        return True

    def on_exit(self):
        if not self.confirm_discard():
            return False
        if self._watch_job is not None:
            self.root.after_cancel(self._watch_job)
            self._watch_job = None
        self.root.destroy()
        return True
