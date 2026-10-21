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
