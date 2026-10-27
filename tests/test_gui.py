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


def set_heights(app, *values):
    """층별 높이 입력칸(최하층부터)에 값을 넣음. 층수를 바꾼 뒤에 호출해야 입력칸이 맞게 만들어져 있음"""
    for n, v in enumerate(values, start=1):
        set_entry(app, f"floor_height_{n}", str(v))


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
    set_floors(app, 3)
    set_heights(app, 6, 6, 6); set_entry(app, "mid_t", "0.4"); set_entry(app, "roof_t", "0.4"); set_entry(app, "floor_t", "1.2")
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
    for obj, keys in ((StationParameters(), ("length", "width", "start_station", "offset", "floors", "wall_t",
                                              "floor_t", "mid_t", "roof_t")),
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
    set_heights(app, 6, 6, 6)
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


# ---------------- 좌표 목록(txt) 선형 불러오기 ----------------
from config.alignment_text import XYZOptions
from config.sampled_alignment import SampledAlignment
from gui.xyz_options_dialog import XYZOptionsDialog

SAMPLE_TXT = os.path.join(ROOT, "samples", "alignment_xyz_example.txt")


def test_txt_alignment_goes_through_options_dialog(app, monkeypatch):
    patch_dialogs(monkeypatch, open_path=SAMPLE_TXT)
    asked = []
    monkeypatch.setattr(app.station_tab, "_ask_xyz_options", lambda p: asked.append(p) or XYZOptions(start_station=300.0))
    app.station_tab.load_alignment_file()
    a = app.entries["alignment_source"].alignment
    assert asked == [SAMPLE_TXT] and isinstance(a, SampledAlignment) and a.start_station == 300.0
    assert "좌표 목록 501점" in app.station_tab.align_status.get()
    assert str(app.entries["bp_x"].cget("state")) == "disabled"
    assert float(app.entries["start_station"].get()) == 300.0       # 기본 0 은 선형(300~) 밖이라 자동으로 맞춤


def test_json_alignment_does_not_open_the_options_dialog(app, monkeypatch):
    patch_dialogs(monkeypatch, open_path=SAMPLE)
    monkeypatch.setattr(app.station_tab, "_ask_xyz_options", lambda p: pytest.fail("JSON 에는 열 순서를 묻지 않음"))
    app.station_tab.load_alignment_file()
    assert isinstance(app.entries["alignment_source"].alignment, CurvedAlignment)


def test_cancelling_the_options_dialog_loads_nothing(app, monkeypatch):
    d = patch_dialogs(monkeypatch, open_path=SAMPLE_TXT)
    monkeypatch.setattr(app.station_tab, "_ask_xyz_options", lambda p: None)
    app.station_tab.load_alignment_file()
    assert app.entries["alignment_source"].alignment is None and d.calls == []


def test_bad_txt_reports_file_and_line(app, monkeypatch, tmp_path):
    bad = tmp_path / "bad.txt"; bad.write_text("X,Y,Z\n1,2,3\n2,3,4\n3,abc,5\n", encoding="utf-8")
    d = patch_dialogs(monkeypatch, open_path=str(bad))
    monkeypatch.setattr(app.station_tab, "_ask_xyz_options", lambda p: XYZOptions())
    app.station_tab.load_alignment_file()
    assert d.calls[0][0] == "error" and "bad.txt: 4번째 줄: 숫자로 읽을 수 없는 값이 있습니다" in d.calls[0][2]
    assert app.entries["alignment_source"].alignment is None


def test_loading_shows_warnings_in_status(app, monkeypatch, tmp_path):
    rows = [f"{300 + i * 25.0:.3f},{0:.3f},{100 + i * 0.05:.3f}" for i in range(12)]      # 25m 간격: 성김
    f = tmp_path / "sparse.csv"; f.write_text("X,Y,Z\n" + "\n".join(rows), encoding="utf-8")
    patch_dialogs(monkeypatch, open_path=str(f))
    monkeypatch.setattr(app.station_tab, "_ask_xyz_options", lambda p: XYZOptions(start_station=300.0))
    app.station_tab.load_alignment_file()
    assert "⚠" in app.station_tab.align_status.get() and "25.0m" in app.station_tab.align_status.get()
    assert app.entries["alignment_source"].warnings


def test_generate_from_txt_alignment(app, monkeypatch, tmp_path):
    d = patch_dialogs(monkeypatch, open_path=SAMPLE_TXT, directory=str(tmp_path))
    monkeypatch.setattr(app.station_tab, "_ask_xyz_options", lambda p: XYZOptions(start_station=300.0))
    app.station_tab.load_alignment_file()
    set_entry(app, "start_station", "330")
    set_floors(app, 3); set_heights(app, 6, 6, 6)
    app.on_generate()
    assert d.calls[-1][0] == "info", d.calls[-1]
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".dxf"] * 4 + [".ifc"]


# --- 옵션 대화상자 자체 ---
def test_options_dialog_returns_selected_options(app):
    dlg = XYZOptionsDialog(app.root, SAMPLE_TXT, modal=False)
    app.root.update()
    labels = list(dlg.combo.cget("values"))
    assert labels[0].startswith("자동") and any("PENZD" in l for l in labels)
    dlg.order_var.set(next(l for l in labels if "PENZD" in l)); dlg.start_var.set("2000,5"); dlg.smooth_var.set("8")
    dlg.ok()
    assert dlg.result == XYZOptions(order="-yxz", start_station=2000.5, smooth_m=8.0)


def test_options_dialog_default_cancel_and_validation(app):
    dlg = XYZOptionsDialog(app.root, SAMPLE_TXT, modal=False)
    dlg.ok()
    assert dlg.result == XYZOptions(order="auto", start_station=0.0, smooth_m=5.0)

    dlg = XYZOptionsDialog(app.root, SAMPLE_TXT, modal=False)
    dlg.start_var.set("abc"); dlg.ok()
    assert dlg.result is None and "숫자" in dlg.error_var.get() and dlg.top.winfo_exists()
    dlg.smooth_var.set("-3"); dlg.start_var.set("1"); dlg.ok()
    assert dlg.result is None and "0 이상" in dlg.error_var.get()
    dlg.cancel()
    assert dlg.result is None and not dlg.top.winfo_exists()


def test_options_dialog_shows_a_preview(app):
    dlg = XYZOptionsDialog(app.root, SAMPLE_TXT, modal=False)
    text = next(w for w in dlg.top.winfo_children() if isinstance(w, tk.Text))
    assert "X, Y, Z" in text.get("1.0", "end") and "300.000" in text.get("1.0", "end")
    dlg.cancel()


# ---------------- LandXML 선형 불러오기 ----------------
from config.alignment_landxml import LandXMLOptions
from gui.landxml_options_dialog import LandXMLOptionsDialog

SAMPLE_XML = os.path.join(ROOT, "samples", "alignment_landxml_example.xml")


def _two_alignment_xml(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from landxml_maker import make_landxml
    from test_curved import s_curve
    t = s_curve()
    a = make_landxml(t, name="Main")
    b = make_landxml(t, name="Branch", profile_name="Alt", prof_name="Opt").split('<Alignments name="Alignments">')[1].split("</Alignments>")[0]
    p = tmp_path / "two.xml"
    p.write_text(a.replace("</Alignments>", b + "</Alignments>"), encoding="utf-8")
    return str(p)


def test_single_alignment_landxml_loads_without_asking(app, monkeypatch):
    d = patch_dialogs(monkeypatch, open_path=SAMPLE_XML)
    monkeypatch.setattr(app.station_tab, "_ask_landxml_options", lambda *a: pytest.fail("선택지가 없으면 묻지 않음"))
    app.station_tab.load_alignment_file()
    a = app.entries["alignment_source"].alignment
    assert isinstance(a, CurvedAlignment) and a.alignment_name == "Subway-Main" and d.calls == []
    assert "LandXML 선형 'Subway-Main'" in app.station_tab.align_status.get()
    assert str(app.entries["bp_x"].cget("state")) == "disabled"
    TkAdapter.collect_entries(app.entries)                          # 시작 측점 0 은 선형(0~1000) 안이라 통과


def test_multi_alignment_landxml_asks_which_one(app, monkeypatch, tmp_path):
    path = _two_alignment_xml(tmp_path)
    patch_dialogs(monkeypatch, open_path=path)
    seen = []
    monkeypatch.setattr(app.station_tab, "_ask_landxml_options",
                        lambda p, infos: seen.append([i.name for i in infos]) or LandXMLOptions(alignment="Branch", profile="Alt / Opt"))
    app.station_tab.load_alignment_file()
    a = app.entries["alignment_source"].alignment
    assert seen == [["Main", "Branch"]] and (a.alignment_name, a.profile_name) == ("Branch", "Alt / Opt")


def test_cancelled_landxml_dialog_loads_nothing(app, monkeypatch, tmp_path):
    d = patch_dialogs(monkeypatch, open_path=_two_alignment_xml(tmp_path))
    monkeypatch.setattr(app.station_tab, "_ask_landxml_options", lambda p, infos: None)
    app.station_tab.load_alignment_file()
    assert app.entries["alignment_source"].alignment is None and d.calls == []


def test_broken_landxml_shows_error_and_keeps_state(app, monkeypatch, tmp_path):
    bad = tmp_path / "bad.xml"; bad.write_text("<LandXML>\n<Alignments></LandXML>", encoding="utf-8")
    d = patch_dialogs(monkeypatch, open_path=str(bad))
    app.station_tab.load_alignment_file()
    assert d.calls[0][0] == "error" and "bad.xml: XML 형식 오류 (줄 2" in d.calls[0][2]
    assert app.entries["alignment_source"].alignment is None and str(app.entries["bp_x"].cget("state")) == "normal"


def test_landxml_read_error_is_shown(app, monkeypatch, tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from landxml_maker import make_landxml
    from test_curved import s_curve
    p = tmp_path / "unsym.xml"
    p.write_text(make_landxml(s_curve()).replace("<PVI>1000.000000", "<UnsymParaCurve lengthIn='1' lengthOut='2'>450 104</UnsymParaCurve><PVI>1000.000000"), encoding="utf-8")
    d = patch_dialogs(monkeypatch, open_path=str(p))
    app.station_tab.load_alignment_file()
    assert d.calls[0][0] == "error" and "비대칭 포물선 종곡선" in d.calls[0][2]


def test_generate_from_landxml(app, monkeypatch, tmp_path):
    d = patch_dialogs(monkeypatch, open_path=SAMPLE_XML, directory=str(tmp_path))
    app.station_tab.load_alignment_file()
    set_entry(app, "start_station", "330")
    set_floors(app, 3); set_heights(app, 6, 6, 6)
    app.on_generate()
    assert d.calls[-1][0] == "info", d.calls[-1]
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".dxf"] * 4 + [".ifc"]


# --- 대화상자 자체 ---
def _infos(tmp_path):
    from config.alignment_landxml import scan_landxml
    return scan_landxml(_two_alignment_xml(tmp_path))


def test_landxml_dialog_defaults_and_selection(app, tmp_path):
    dlg = LandXMLOptionsDialog(app.root, "two.xml", _infos(tmp_path), modal=False)
    app.root.update()
    assert list(dlg.align_combo.cget("values")) == ["Main", "Branch"] and dlg.profile_var.get() == "Design / FG"
    assert "종단 1개" in dlg.info_var.get() or "종단 2개" in dlg.info_var.get()
    dlg.align_var.set("Branch"); dlg._refresh()
    assert list(dlg.profile_combo.cget("values")) == ["Alt / Opt"] and dlg.profile_var.get() == "Alt / Opt"
    dlg.axis_var.set("동 북"); dlg.ok()
    assert dlg.result == LandXMLOptions(alignment="Branch", profile="Alt / Opt", axis="EN")


def test_landxml_dialog_default_cancel_and_profileless_alignment(app, tmp_path):
    infos = _infos(tmp_path)
    dlg = LandXMLOptionsDialog(app.root, "two.xml", infos, modal=False)
    dlg.ok()
    assert dlg.result == LandXMLOptions(alignment="Main", profile="Design / FG", axis="auto")
    infos[1].profiles = []                                          # 종단이 없는 선형
    dlg = LandXMLOptionsDialog(app.root, "two.xml", infos, modal=False)
    dlg.align_var.set("Branch"); dlg._refresh(); dlg.ok()
    assert dlg.result is None and "종단(Profile)이 없습니다" in dlg.error_var.get() and "⚠" in dlg.info_var.get()
    dlg.cancel()
    assert not dlg.top.winfo_exists()


# ---------------- 실제 Civil 3D 파일 (3차 포물선 완화곡선) ----------------
REAL_XML = os.path.join(ROOT, "samples", "civil3d_korea_cubic_spiral.xml")


def test_real_civil3d_file_loads_through_the_button_without_warnings(app, monkeypatch):
    d = patch_dialogs(monkeypatch, open_path=REAL_XML)
    monkeypatch.setattr(app.station_tab, "_ask_landxml_options", lambda *a: pytest.fail("선형/종단이 하나뿐이면 묻지 않음"))
    app.station_tab.load_alignment_file()
    a = app.entries["alignment_source"].alignment
    assert d.calls == [] and a.alignment_name == "초안1구간" and a.warnings == []
    assert "⚠" not in app.station_tab.align_status.get() and "21120.07" in app.station_tab.align_status.get()


def test_generate_on_the_real_civil3d_alignment(app, monkeypatch, tmp_path):
    d = patch_dialogs(monkeypatch, open_path=REAL_XML, directory=str(tmp_path))
    app.station_tab.load_alignment_file()
    set_entry(app, "start_station", "1560")                        # 3차 포물선 완화곡선(1483.9~1646.2) → 원곡선 구간
    set_floors(app, 3); set_heights(app, 6, 6, 6)
    app.on_generate()
    assert d.calls[-1][0] == "info", d.calls[-1]
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".dxf"] * 4 + [".ifc"]
    set_entry(app, "start_station", "21000")                       # 정거장 끝(21200)이 선형 끝(21120)을 넘음
    app.on_generate()
    assert d.calls[-1][0] == "error" and "선형 범위" in d.calls[-1][2] and "21120.07" in d.calls[-1][2]


# ---------------- 층별 높이 + 슬래브 3종 입력 ----------------
from config.station_config import StationParameters as _SP


def texts(app):
    tab = app.station_tab
    return [tab._clear_labels[i][0].get() for i in sorted(tab._clear_labels)], tab.total_var.get()


def test_station_tab_has_per_floor_heights_and_three_slab_fields(app):
    d = _SP()
    assert "height" not in app.entries and "slab_t" not in app.entries            # 총 높이/통합 슬래브 입력은 없어짐
    assert [app.entries[f"floor_height_{i}"].get() for i in (1, 2)] == [str(h) for h in d.floor_heights]
    assert "floor_height_3" not in app.entries
    assert (app.entries["floor_t"].get(), app.entries["mid_t"].get(), app.entries["roof_t"].get()) == (str(d.floor_t), str(d.mid_t), str(d.roof_t))
    clear, total = texts(app)
    assert total == "총 높이 H = 12.00 m   (2개 층 합계)" and clear == ["→ 내공 5.00 m", "→ 내공 5.00 m"]


def test_floor_count_change_rebuilds_rows_and_keeps_values(app):
    set_floors(app, 3)
    assert app.entries["floor_height_3"].get() == "6.0"                          # 새 층은 바로 아래 층과 같은 높이로 시작
    set_entry(app, "floor_height_1", "7.5"); set_entry(app, "floor_height_3", "4.0")
    set_floors(app, 4)
    assert app.entries["floor_height_4"].get() == "4.0" and app.entries["floor_height_1"].get() == "7.5"
    set_floors(app, 1)
    assert [k for k in app.entries if k.startswith("floor_height_")] == ["floor_height_1"]
    assert str(app.entries["mid_t"].cget("state")) == "disabled"                  # 1개 층이면 중간층 바닥 슬래브 없음
    set_floors(app, 3)
    assert [app.entries[f"floor_height_{i}"].get() for i in (1, 2, 3)] == ["7.5", "6.0", "4.0"]    # 줄였다 늘려도 입력 보존
    assert str(app.entries["mid_t"].cget("state")) == "normal"
    for partial in ("", "0", "99", "x"):                                          # 입력 도중의 값은 무시
        set_entry(app, "floors", partial); app._on_floors_changed()
        assert app.station_tab.floor_count == 3


def test_total_and_clear_heights_update_live(app):
    set_floors(app, 3)
    set_heights(app, 7.0, 5.2, 4.6)
    set_entry(app, "mid_t", "0.9"); set_entry(app, "roof_t", "1.1")             # (회귀) 슬래브 두께를 바꿔도 내공 표시가 갱신돼야 함
    clear, total = texts(app)
    assert total == "총 높이 H = 16.80 m   (3개 층 합계)"
    assert clear == ["→ 내공 6.10 m", "→ 내공 4.30 m", "→ 내공 3.50 m"]            # 아래 두 층은 중간층 슬래브, 최상층은 천장 슬래브
    set_entry(app, "roof_t", "1.6")
    assert texts(app)[0][2] == "→ 내공 3.00 m" and texts(app)[0][:2] == ["→ 내공 6.10 m", "→ 내공 4.30 m"]


def test_bad_or_nonpositive_clear_height_is_flagged(app):
    set_floors(app, 2)
    set_entry(app, "roof_t", "6.0")                                               # 최상층 6.0 - 6.0 = 0
    var, lbl = app.station_tab._clear_labels[2]
    assert var.get() == "→ 내공 0.00 m" and lbl.cget("fg") == "#C62828"
    set_entry(app, "floor_height_1", "abc")
    clear, total = texts(app)
    assert clear[0] == "→ 입력값을 확인하세요" and total == "총 높이: 입력값을 확인하세요"


def test_adapter_sums_floor_heights_and_reads_three_slabs(app):
    set_floors(app, 3)
    set_heights(app, 7.0, 5.2, 4.6)
    set_entry(app, "floor_t", "1.5"); set_entry(app, "mid_t", "0.9"); set_entry(app, "roof_t", "1.1")
    st = TkAdapter.collect_entries(app.entries).station
    assert st.floor_heights == [7.0, 5.2, 4.6] and st.height == pytest.approx(16.8) and st.floors == 3
    assert (st.floor_t, st.mid_t, st.roof_t) == (1.5, 0.9, 1.1)


def test_adapter_errors_name_the_floor_and_slab(app):
    set_floors(app, 3)
    set_entry(app, "floor_height_2", "abc")
    with pytest.raises(ValueError, match=r"B2F 층 높이: 숫자가 아닙니다 \('abc'\)"):
        TkAdapter.collect_entries(app.entries)
    set_entry(app, "floor_height_2", "6")
    set_entry(app, "mid_t", "x")
    with pytest.raises(ValueError, match="중간층 바닥 슬래브 두께: 숫자가 아닙니다"):
        TkAdapter.collect_entries(app.entries)
    set_entry(app, "mid_t", "7.0")                                                # 변환은 되지만 제원 검증에서 걸림
    with pytest.raises(ValueError, match=r"B3F 층 높이\(6m\)가 위쪽 중간층 바닥 슬래브 두께\(7m\) 이하"):
        TkAdapter.collect_entries(app.entries).validate()


def test_generate_with_varied_heights_and_slabs(app, monkeypatch, tmp_path):
    d = patch_dialogs(monkeypatch, directory=str(tmp_path))
    set_floors(app, 3)
    set_heights(app, 7.0, 5.2, 4.6)
    set_entry(app, "floor_t", "1.5"); set_entry(app, "mid_t", "0.9"); set_entry(app, "roof_t", "1.1")
    app.on_generate()
    assert d.calls[-1][0] == "info", d.calls[-1]
    f = ifcopenshell.open(str(next(p for p in tmp_path.iterdir() if p.suffix == ".ifc")))
    elev = {s.Name: s.Elevation for s in f.by_type("IfcBuildingStorey")}
    assert elev["B2F"] - elev["B3F"] == pytest.approx(7.0) and elev["B1F"] - elev["B2F"] == pytest.approx(5.2)   # 층 표고 간격 = 층 높이


def test_floor_height_entries_fit_inside_the_window(app):
    set_floors(app, 6)
    app.root.update()
    right = app.root.winfo_rootx() + app.root.winfo_width()
    bottom = app.station_tab.parent.winfo_rooty() + app.station_tab.parent.winfo_height()
    for k in [f"floor_height_{i}" for i in range(1, 7)] + ["floors", "mid_t", "roof_t"]:
        e = app.entries[k]
        assert e.winfo_rootx() + e.winfo_width() <= right, k
    assert app.entries["roof_t"].winfo_rooty() + app.entries["roof_t"].winfo_height() <= bottom      # 6개 층이어도 아래 입력칸이 잘리지 않음
