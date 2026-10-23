"""열별 기둥 입력 UI 테스트 (tkinter + 디스플레이 필요. Linux CI 에서는 xvfb-run -a pytest 로 실행, 없으면 건너뜀)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ifcopenshell
import pytest

tk = pytest.importorskip("tkinter")

from columns.column_shape_type import ColumnShapeType as T
from engine.bim_engine import BIMEngine
from gui.column_draft import CIRCLE, RECT, estimate_count
from gui.gui_app import StationBIMApp
from gui.tk_adapter import TkAdapter


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("디스플레이가 없어 GUI 테스트를 건너뜀")
    a = StationBIMApp(root)
    root.update()
    yield a
    root.destroy()


def set_entry(app, key, text):
    e = app.entries[key]
    e.delete(0, "end"); e.insert(0, text)


def set_floors(app, n):
    set_entry(app, "floors", str(n))
    app._on_floors_changed()
    app.root.update()


def test_initial_state_has_one_default_row_per_floor(app):
    ct = app.column_tab
    n = int(app.entries["floors"].get())
    assert ct.floor_count == n and all(len(f.rows) == 1 for f in ct.drafts.floors.values())
    cfg = TkAdapter.collect_entries(app.entries)             # 기본값 그대로 변환 가능
    assert cfg.column.target_floors == list(range(1, n + 1))


def test_floor_change_keeps_existing_input_and_ignores_partial_typing(app):
    ct = app.column_tab
    set_floors(app, 2)
    ct._vars[(1, 0, "interval")].set("7.5")
    set_floors(app, 3)
    assert ct.floor_count == 3 and ct.drafts.floors[1].rows[0].interval == "7.5"
    assert ct._vars[(1, 0, "interval")].get() == "7.5"        # 다시 그려도 입력값 유지
    set_entry(app, "floors", ""); app._on_floors_changed()    # 입력 도중 빈칸 → 상태 유지
    assert ct.floor_count == 3
    set_floors(app, 1)
    assert list(ct.drafts.floors) == [1] and len(ct._vars) == 5


def test_editing_entries_updates_draft_and_count_label(app):
    ct = app.column_tab; set_floors(app, 2)
    ct._vars[(1, 0, "t_offset")].set("2.5")
    ct._vars[(1, 0, "interval")].set("20")
    row = ct.drafts.floors[1].rows[0]
    assert (row.t_offset, row.interval) == ("2.5", "20")
    expected = estimate_count(row, float(app.entries["length"].get()), float(app.entries["wall_t"].get()))
    assert ct._count_vars[0][0].get() == f"→ 약 {expected}개"
    ct._vars[(1, 0, "interval")].set("abc")
    assert "확인" in ct._count_vars[0][0].get()


def test_row_and_pattern_buttons(app):
    ct = app.column_tab; set_floors(app, 2)
    ct.add_row(1); ct.add_row(1)
    assert len(ct.drafts.floors[1].rows) == 3
    ct.remove_row(1, 1)
    assert len(ct.drafts.floors[1].rows) == 2
    ct.add_pattern(2, 0)
    assert len(ct.drafts.floors[2].rows[0].patterns) == 2
    ct.set_shape(2, 0, 1, CIRCLE)
    assert ct.drafts.floors[2].rows[0].patterns[1].shape == CIRCLE
    assert (2, 0, 1, "diameter") in ct._vars and (2, 0, 1, "width") not in ct._vars   # 형태에 맞는 입력칸만 표시
    ct.remove_pattern(2, 0, 0)
    assert len(ct.drafts.floors[2].rows[0].patterns) == 1
    for r in range(len(ct.drafts.floors[1].rows)):             # 모든 열 삭제 → 기둥 없음
        ct.remove_row(1, 0)
    assert TkAdapter.collect_entries(app.entries).column.target_floors == [2]


def test_buttons_are_really_clickable(app):
    """위젯의 버튼을 직접 invoke 해서 콜백 연결을 확인"""
    ct = app.column_tab; set_floors(app, 1)

    def find(widget, text):
        for w in widget.winfo_children():
            if isinstance(w, tk.Button) and w.cget("text") == text:
                return w
            r = find(w, text)
            if r:
                return r
    find(ct.body, "+ 열 추가").invoke(); app.root.update()
    assert len(ct.drafts.floors[1].rows) == 2
    find(ct.body, "+ 패턴 추가").invoke(); app.root.update()
    assert len(ct.drafts.floors[1].rows[0].patterns) == 2
    find(ct.body, "열 삭제").invoke(); app.root.update()
    assert len(ct.drafts.floors[1].rows) == 1


def test_user_example_end_to_end_from_ui_to_ifc(app, tmp_path):
    ct = app.column_tab
    set_entry(app, "height", "18"); set_entry(app, "slab_t", "0.4"); set_entry(app, "floor_t", "1.2")
    set_floors(app, 3)
    d = ct.drafts.floors
    ct._vars[(1, 0, 0, "width")].set("0.4"); ct._vars[(1, 0, 0, "depth")].set("1.0")      # B3F 사각 0.4x1.0, 1열
    ct.add_row(2)
    ct.set_shape(2, 0, 0, CIRCLE); ct.set_shape(2, 1, 0, CIRCLE)                          # B2F 원기둥 φ1.0, 2열
    ct._vars[(2, 0, "t_offset")].set("-3.0"); ct._vars[(2, 1, "t_offset")].set("3.0")
    ct.set_shape(3, 0, 0, CIRCLE); ct.add_pattern(3, 0); ct.set_shape(3, 0, 1, RECT)      # B1F 원+사각 혼합, 1열
    ct._vars[(3, 0, "interval")].set("8.0")

    cfg = TkAdapter.collect_entries(app.entries)
    assert cfg.column.floors[2].rows[1].pattern[0].radius == pytest.approx(0.5)
    kinds = [s.shape_type for s in cfg.column.floors[3].rows[0].pattern]
    assert kinds == [T.CIRCLE, T.RECTANGLE]

    paths = BIMEngine.build(cfg, tmp_path)                    # 파일 선택창 없이 엔진만 실행
    f = ifcopenshell.open(paths[-1])
    per = {}
    for rel in f.by_type("IfcRelContainedInSpatialStructure"):
        n = len([e for e in rel.RelatedElements if e.is_a("IfcColumn")])
        per[rel.RelatingStructure.Name] = per.get(rel.RelatingStructure.Name, 0) + n
    assert per == {"B3F": 20, "B2F": 40, "B1F": 25}


def test_bad_input_reports_floor_and_row(app):
    ct = app.column_tab; set_floors(app, 2)
    ct._vars[(2, 0, "interval")].set("-5")
    with pytest.raises(ValueError, match="B1F 1열"):
        TkAdapter.collect_entries(app.entries)


def test_gui_initial_values_come_from_dataclass_defaults(app):
    from config.alignment_config import AlignmentConfig
    from config.station_config import StationParameters
    from platforms.platform_params import PlatformParameters
    for obj, keys in ((StationParameters(), ("length", "width", "start_station", "offset", "height", "floors", "wall_t",
                                              "floor_t", "slab_t")),
                      (AlignmentConfig(), ("bp_x", "bp_y", "bp_z", "ep_x", "ep_y", "ep_z", "bp_station")),
                      (PlatformParameters(), ("track_spacing", "plat_offset", "plat_thick", "plat_height", "support_t"))):
        for k in keys:
            assert app.entries[k].get() == str(getattr(obj, k)), k


class _Recorder:
    """messagebox / filedialog 대체: 호출 내용을 기록"""
    def __init__(self, directory=""):
        self.calls, self.directory = [], directory

    def showerror(self, title, msg): self.calls.append(("error", msg))
    def showinfo(self, title, msg): self.calls.append(("info", msg))
    def askdirectory(self, **kw): return self.directory


def test_generate_button_shows_error_for_bad_input(app, monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr("gui.gui_app.messagebox", rec)
    monkeypatch.setattr("gui.gui_app.filedialog", rec)
    set_entry(app, "length", "abc")
    app.on_generate()
    assert rec.calls and rec.calls[0][0] == "error" and "정거장 전체 길이" in rec.calls[0][1]


def test_generate_button_reports_engine_errors_with_location(app, monkeypatch, tmp_path):
    rec = _Recorder(str(tmp_path))
    monkeypatch.setattr("gui.gui_app.messagebox", rec)
    monkeypatch.setattr("gui.gui_app.filedialog", rec)
    app.column_tab.add_row(1)
    app.column_tab._vars[(1, 1, "t_offset")].set("0.2")         # 같은 층 두 열이 겹침
    app.on_generate()
    kind, msg = rec.calls[0]
    assert kind == "error" and "겹칩니다" in msg and "B2F" in msg
    assert list(tmp_path.iterdir()) == []                       # 실패 시 반쯤 만든 파일을 남기지 않음


def test_generate_button_success_writes_all_files(app, monkeypatch, tmp_path):
    rec = _Recorder(str(tmp_path))
    monkeypatch.setattr("gui.gui_app.messagebox", rec)
    monkeypatch.setattr("gui.gui_app.filedialog", rec)
    app.on_generate()
    kind, msg = rec.calls[0]
    assert kind == "info" and len(msg.strip().splitlines()) == 6        # 제목 줄 + 파일 5개
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".dxf"] * 4 + [".ifc"]


def test_generate_cancelled_dialog_does_nothing(app, monkeypatch, tmp_path):
    rec = _Recorder("")                                          # 폴더 선택 취소
    monkeypatch.setattr("gui.gui_app.messagebox", rec)
    monkeypatch.setattr("gui.gui_app.filedialog", rec)
    app.on_generate()
    assert rec.calls == []


# ---------------- 곡선 선형 파일 불러오기 ----------------
import shutil

from config.alignment_config import AlignmentConfig
from config.curved_alignment import CurvedAlignment

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "curve_alignment.json")
SAMPLE_EL = os.path.join(ROOT, "samples", "curve_alignment_elements.json")


class _Dialogs:
    def __init__(self, open_path="", directory=""):
        self.calls, self.open_path, self.directory = [], open_path, directory

    def showerror(self, title, msg): self.calls.append(("error", title, msg))
    def showinfo(self, title, msg): self.calls.append(("info", title, msg))
    def askopenfilename(self, **kw): return self.open_path
    def askdirectory(self, **kw): return self.directory


def patch_dialogs(monkeypatch, **kw):
    d = _Dialogs(**kw)
    for mod in ("gui.station_tab", "gui.gui_app"):
        monkeypatch.setattr(f"{mod}.messagebox", d)
    monkeypatch.setattr("gui.station_tab.filedialog", d)
    monkeypatch.setattr("gui.gui_app.filedialog", d)
    return d


def test_loading_curve_file_replaces_bp_ep_inputs(app, monkeypatch):
    d = patch_dialogs(monkeypatch, open_path=SAMPLE)
    tab = app.station_tab
    tab.load_alignment_file()
    assert isinstance(app.entries["alignment_source"].alignment, CurvedAlignment)
    assert all(str(app.entries[k].cget("state")) == "disabled" for k in ("bp_x", "bp_y", "bp_z", "ep_x", "ep_y", "ep_z", "bp_station"))
    assert str(tab.reset_btn.cget("state")) == "normal" and "곡선" in tab.align_status.get() and "curve_alignment.json" in tab.align_status.get()
    cfg = TkAdapter.collect_entries(app.entries)
    assert cfg.align is app.entries["alignment_source"].alignment and not cfg.align.is_straight
    assert d.calls == []                                           # 정상 파일은 오류창 없음


def test_loading_adjusts_start_station_when_outside_alignment(app, monkeypatch):
    patch_dialogs(monkeypatch, open_path=SAMPLE_EL)               # 선형 STA 1000 ~ 1820, 기본 시작 측점 0.0 은 범위 밖
    app.station_tab.load_alignment_file()
    assert float(app.entries["start_station"].get()) == 1000.0
    assert "시작 측점을 선형 시작" in app.station_tab.align_status.get()
    TkAdapter.collect_entries(app.entries)                         # 이제 검증 통과


def test_reset_returns_to_bp_ep_line(app, monkeypatch):
    patch_dialogs(monkeypatch, open_path=SAMPLE)
    app.station_tab.load_alignment_file()
    app.station_tab.reset_alignment()
    assert app.entries["alignment_source"].alignment is None
    assert str(app.entries["bp_x"].cget("state")) == "normal" and str(app.station_tab.reset_btn.cget("state")) == "disabled"
    assert isinstance(TkAdapter.collect_entries(app.entries).align, AlignmentConfig)


def test_bad_alignment_file_shows_error_and_keeps_state(app, monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"; bad.write_text('{"type": "heading", "bp_x": 1}', encoding="utf-8")
    d = patch_dialogs(monkeypatch, open_path=str(bad))
    app.station_tab.load_alignment_file()
    assert d.calls and d.calls[0][0] == "error" and "bad.json" in d.calls[0][2] and "필요한 항목이 없습니다" in d.calls[0][2]
    assert app.entries["alignment_source"].alignment is None and str(app.entries["bp_x"].cget("state")) == "normal"


def test_cancelled_file_dialog_changes_nothing(app, monkeypatch):
    d = patch_dialogs(monkeypatch, open_path="")
    app.station_tab.load_alignment_file()
    assert d.calls == [] and app.entries["alignment_source"].alignment is None


def test_station_outside_loaded_alignment_is_reported(app, monkeypatch, tmp_path):
    d = patch_dialogs(monkeypatch, open_path=SAMPLE, directory=str(tmp_path))
    app.station_tab.load_alignment_file()
    set_entry(app, "start_station", "900")                          # 정거장 끝 1100 > 선형 끝 1000
    app.on_generate()
    kind, _, msg = d.calls[-1]
    assert kind == "error" and "선형 범위" in msg and list(tmp_path.iterdir()) == []


def test_generate_with_curve_file_writes_curved_outputs(app, monkeypatch, tmp_path):
    d = patch_dialogs(monkeypatch, open_path=SAMPLE, directory=str(tmp_path))
    app.station_tab.load_alignment_file()
    set_entry(app, "start_station", "330")                          # 직선 → 완화곡선 → 원곡선을 지나는 구간
    set_floors(app, 3)
    set_entry(app, "height", "18")
    app.on_generate()
    kind, _, msg = d.calls[-1]
    assert kind == "info", msg
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".dxf"] * 4 + [".ifc"]
    import ezdxf
    plan = ezdxf.readfile(str(next(p for p in tmp_path.iterdir() if "평면도" in p.name)))
    assert any("[WCS]" in t.dxf.text for t in plan.modelspace().query("TEXT"))
    f = ifcopenshell.open(str(next(p for p in tmp_path.iterdir() if p.suffix == ".ifc")))
    assert {e.Representation.Representations[0].RepresentationType for e in f.by_type("IfcWall")} == {"Tessellation"}


def test_all_entries_fit_inside_the_window(app):
    """창 너비(480px)를 넘어 입력칸이 잘리는 일이 없어야 함 (BP Z / EP Z 가 가려졌던 문제)"""
    app.root.update()
    right_edge = app.root.winfo_rootx() + app.root.winfo_width()
    for k in ("bp_x", "bp_y", "bp_z", "ep_x", "ep_y", "ep_z", "bp_station", "length", "start_station"):
        e = app.entries[k]
        assert e.winfo_rootx() + e.winfo_width() <= right_edge, k
