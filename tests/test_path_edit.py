"""미리보기 평면 경로 객체(출구통로·환기구·점자 유도 경로) 표시·편집: 화면 비의존 모델(gui.path_edit) + 미리보기 끌기·명령줄"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from gui import path_edit as PE
from gui.passage_draft import MODE_WORLD, PassageDraft, PassageDrafts, VertexDraft
from gui.tactile_draft import TactileDrafts, TactilePathDraft, TactilePointDraft
from gui.vent_draft import VentDraft, VentDrafts
from tactiles.tactile_spec import TactileSettings
from test_curved import NO_COLS
from test_patch import make_cfg

TF = 10.0           # make_cfg 외벽 바깥면 |t|


def _vd(*pts):
    return [VertexDraft(str(x), "" if y is None else str(y), "" if z is None else str(z)) for x, y, z in pts]


def model(passages=(), vents=(), tactile=()):
    """초안 → 설정 (탭이 하는 변환과 같음) + entries"""
    cfg = make_cfg(NO_COLS())
    pd, vd, td = PassageDrafts(), VentDrafts(), TactileDrafts()
    pd.items, vd.items, td.items = list(passages), list(vents), list(tactile)
    cfg.passages = [d.to_spec(f"통로 {i}", 0.0) for i, d in enumerate(pd.items)]
    cfg.vents = [d.to_spec(f"환기구 {i}", 0.0) for i, d in enumerate(vd.items)]
    cfg.tactile_settings = td.to_settings(0.0) if td.items else TactileSettings(enabled=False)
    return cfg, {"passage_drafts": pd, "vent_drafts": vd, "tactile_drafts": td}


def rebuild(cfg, entries):
    cfg.passages = [d.to_spec("통로", 0.0) for d in entries["passage_drafts"].items]
    cfg.vents = [d.to_spec("환기구", 0.0) for d in entries["vent_drafts"].items]
    if entries["tactile_drafts"].items:
        cfg.tactile_settings = entries["tactile_drafts"].to_settings(0.0)
    cfg.validate()
    return PE.collect_paths(cfg, entries)


def passage(name="A", *pts):
    return PassageDraft(name=name, floor=3, vertices=_vd(*(pts or ((50, None, None), (50, 25, 0), (70, 25, 0)))))


def test_collect_paths_and_moves():
    cfg, ent = model([passage(), PassageDraft(name="B", floor=3, parent="A", vertices=_vd((0, None, None), (60, 35, 0)))],
                     tactile=[TactilePathDraft(name="G", floor=2, vertices=[TactilePointDraft("20", "3"), TactilePointDraft("40", "3")])])
    cfg.validate()
    ps = PE.collect_paths(cfg, ent)
    a, b, g = ps
    assert (a.kind, a.name, a.floor) == (PE.PASSAGE, "A", 3)
    assert a.points == [(pytest.approx(50.0), pytest.approx(TF)), (50.0, 25.0), (70.0, 25.0)]
    assert a.moves == [PE.ALONG_S, PE.FREE, PE.FREE] and b.moves[0] == PE.FIXED          # 분기 첫 꼭짓점 = 고정
    assert g.kind == PE.TACTILE and g.points == [(20.0, 3.0), (40.0, 3.0)] and g.moves == [PE.FREE, PE.FREE]
    assert [k for k, _ in a.midpoints()] == [0, 1]
    # 손잡이 찾기: 꼭짓점 우선, 없으면 구간 가운데
    xy = lambda s, t: (s, t)
    assert PE.nearest(ps, xy, 50.05, 25.02, 0.2)[0::2] == ("vertex", 1)
    assert PE.nearest(ps, xy, 60.0, 25.1, 0.2)[0::2] == ("mid", 1)
    assert PE.nearest(ps, xy, 0.0, 0.0, 0.2) is None


def test_move_insert_delete_keep_draft_format():
    cfg, ent = model([passage()])
    cfg.validate()
    (a,) = PE.collect_paths(cfg, ent)
    d = ent["passage_drafts"].items[0]
    PE.move(ent, a, 2, 75.0, 25.0, 0.0, cfg.to_world)
    assert (d.vertices[2].x, d.vertices[2].y, d.vertices[2].z) == ("75", "25", "0")          # 높이 유지
    # 첫 꼭짓점 = 벽을 따라 s 만 (t 는 비운 채 — 자동)
    PE.move(ent, a, 0, 48.0, 99.0, 0.0, cfg.to_world)
    assert (d.vertices[0].x, d.vertices[0].y) == ("48", "")
    PE.move(ent, a, 1, 48.0, 25.0, 0.0, cfg.to_world)                                        # 첫 구간 직각 유지
    (a,) = rebuild(cfg, ent)
    assert a.points[0] == (pytest.approx(48.0), pytest.approx(TF)) and a.points[2] == (75.0, 25.0)
    # 추가: 높이는 이웃 사이 보간 (첫 꼭짓점 높이 비움 = 0)
    d.vertices[2].z = "1.0"
    j = PE.insert(ent, a, 1, 61.5, 25.0, 0.0, cfg.to_world)
    assert j == 2 and (d.vertices[2].x, d.vertices[2].y) == ("61.5", "25") and float(d.vertices[2].z) == pytest.approx(0.5)
    assert len(a.points) == 4 and a.moves[2] == PE.FREE
    # 삭제: 첫 꼭짓점·2개 미만은 오류
    with pytest.raises(ValueError, match="첫 꼭짓점"):
        PE.delete(ent, a, 0)
    PE.delete(ent, a, 2)
    assert len(d.vertices) == 3 and len(a.points) == 3
    PE.delete(ent, a, 2)
    with pytest.raises(ValueError, match="2개 이상"):
        PE.delete(ent, a, 1)


def test_world_mode_branch_fixed_and_vent_shaft_group():
    cfg, _ = model()
    x0, y0 = cfg.to_world(50.0, TF)
    x1, y1 = cfg.to_world(50.0, 25.0)
    w = PassageDraft(name="W", floor=3, mode=MODE_WORLD, vertices=_vd((x0, y0, None), (x1, y1, cfg.lv(50.0) + 12.0)))
    br = PassageDraft(name="C", floor=3, parent="W", vertices=_vd((0, None, None), (40, 20, 0)))
    vent = VentDraft(name="V", floor=3, vertices=_vd((120, None, None), (120, 20, 0), (120, 20, 10)))
    cfg, ent = model([w, br], [vent])
    cfg.validate()
    pw, pc, pv = PE.collect_paths(cfg, ent)
    PE.move(ent, pw, 1, 50.0, 30.0, 0.0, cfg.to_world)                    # 절대 좌표 방식 → X, Y
    wx, wy = cfg.to_world(50.0, 30.0)
    assert (float(w.vertices[1].x), float(w.vertices[1].y)) == pytest.approx((wx, wy), abs=1e-3)
    with pytest.raises(ValueError, match="분기 통로의 첫 꼭짓점"):
        PE.move(ent, pc, 0, 45.0, 25.0, 0.0, cfg.to_world)
    assert pv.group(1) == [1, 2] and pv.group(2) == [1, 2] and [k for k, _ in pv.midpoints()] == [0]   # 수직 구간 = 함께
    PE.move(ent, pv, 2, 125.0, 20.0, 0.0, cfg.to_world)
    assert [(v.x, v.y, v.z) for v in vent.vertices[1:]] == [("125", "20", "0"), ("125", "20", "10")]


def test_tactile_insert_and_move():
    td = TactilePathDraft(name="G", floor=2, vertices=[TactilePointDraft("20", "3"), TactilePointDraft("40", "3")])
    cfg, ent = model(tactile=[td])
    cfg.validate()
    (g,) = PE.collect_paths(cfg, ent)
    PE.insert(ent, g, 0, 30.0, 3.0, 0.0, cfg.to_world)
    PE.move(ent, g, 2, 30.0, 6.0, 0.0, cfg.to_world)
    assert [(v.x, v.y) for v in td.vertices] == [("20", "3"), ("30", "3"), ("30", "6")]
    (g,) = rebuild(cfg, ent)
    assert g.points == [(20.0, 3.0), (30.0, 3.0), (30.0, 6.0)]


# ===================================================== 미리보기 (GUI)
class _Ev:
    def __init__(self, ax, x, y, button=1, px=0, py=0):
        self.inaxes, self.xdata, self.ydata, self.button, self.x, self.y = ax, x, y, button, px, py


@pytest.fixture
def app(tmp_path):
    import tkinter as tk
    from gui.gui_app import StationBIMApp
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("디스플레이가 없어 GUI 테스트를 건너뜀")
    a = StationBIMApp(root, recent_file=str(tmp_path / "recent.json"), watch=False)
    root.update()
    yield a
    root.destroy()


def test_preview_drag_insert_delete_and_command(app, monkeypatch):
    class _Box:
        def __getattr__(self, name):
            return lambda *a, **k: None
    monkeypatch.setattr("gui.preview_window.messagebox", _Box())
    pt = app.passage_tab
    pt.add_passage()
    app.on_preview()
    pv = app.preview
    base = pv.cfg.station.start_station
    it = pt.drafts.items[0]
    names = [n for n, k in __import__("preview.preview_render", fromlist=["x"]).floor_choices(pv.cfg) if k == it.floor]
    pv.plan_floor.set(names[0])
    pv.draw_plan()
    (p,) = pv.paths
    assert pv._visible_paths() == [p] and pv._path_artists                       # 경로 표시
    ax = pv.plan.ax
    s1, t1 = p.points[1]
    # 꼭짓점 2 끌기 → 입력 초안·모델 갱신 (격자 0.1 스냅, 직교 = 직전 꼭짓점에서 t 방향)
    pv._on_click(_Ev(ax, s1, t1, px=100, py=100))
    assert pv.path_sel == ("passage", 0, 1)
    pv._on_motion(_Ev(ax, s1 + 0.03, t1 + 4.04, px=100, py=160))
    pv._on_release(_Ev(ax, s1 + 0.03, t1 + 4.04, px=100, py=160))
    assert float(it.vertices[1].y) == pytest.approx(t1 + 4.0) and float(it.vertices[1].x) == pytest.approx(base + s1)
    assert pv.last_error is None and pv.paths[0].points[1] == (pytest.approx(s1), pytest.approx(t1 + 4.0))
    assert pt._vars.get((0, "v", 1, "y")) is None or pt._vars[(0, "v", 1, "y")].get() == it.vertices[1].y
    # 가운데 손잡이 누르기 = 꼭짓점 추가
    p = pv.paths[0]
    k, (ms, mt) = p.midpoints()[0]
    pv._on_click(_Ev(ax, ms, mt, px=50, py=50))
    pv._on_release(_Ev(ax, ms, mt, px=50, py=50))
    assert len(it.vertices) == 3 and pv.path_sel == ("passage", 0, 1)
    # 명령줄: 고른 꼭짓점 상대 이동 → 직교가 깨지면 모델 오류(초안에는 반영) / 다시 되돌림
    y_before = float(it.vertices[1].y)
    pv.command.insert(0, "@0, 1")
    pv.on_command()
    assert float(it.vertices[1].y) == pytest.approx(y_before + 1.0) and pv.path_sel == ("passage", 0, 1)
    # 오른쪽 클릭 = 삭제, 첫 꼭짓점은 못 지움
    p = pv.paths[0]
    pv._on_click(_Ev(ax, *p.points[1], button=3))
    assert len(it.vertices) == 2
    pv._on_click(_Ev(ax, *pv.paths[0].points[0], button=3))
    assert len(it.vertices) == 2 and "첫 꼭짓점" in pv.status.cget("text")
    # 경로 표시 끄면 손잡이 없음 (누름은 무시)
    pv._vars["paths"].set(False)
    pv._draw_paths()
    assert pv._path_artists == [] and pv._visible_paths() == []
    pv.close()
