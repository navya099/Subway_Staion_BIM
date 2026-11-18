"""열차(편성·정차) + 승강장 승하차 위치 표시(점자블록) 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ifcopenshell
import ifcopenshell.util.element
import pytest

from engine.cad_engine import StationCADEngine
from gui.project_file import ProjectState
from gui.train_draft import DIRS, TrainDraft, preview
from helper import prism_member as PM
from tactiles.tactile_layout import layout_tactile
from tactiles.tactile_spec import BOARD, WARNING, TactileSettings
from test_finishes import ifc_world_volume
from test_tactile import cfg_t
from trains.train_layout import layout_trains
from trains.train_spec import CarDoor, Train, TrainSettings, TrainStop, default_doors, make_train

# cfg_t: 내공 198 × 18, 선로 간격 4.4 (선로 t = ±2.2), 승강장 끝단 |t| = 3.9, 연단 띠 |t| 4.5 ~ 5.1


def cfg_train(finishes=False, **ts):
    cfg = cfg_t(finishes=finishes)
    cfg.train_settings = TrainSettings(enabled=True, **ts)
    return cfg


# ===================================================== 편성·정차
def test_train_model_defaults():
    tr = make_train()
    assert tr.total_cars == 8 and tr.length == 160.0
    assert [c.is_first for c in tr.cars] == [True] + [False] * 7
    assert [d.offset for d in tr.cars[0].doors] == [2.5, 7.5, 12.5, 17.5] and tr.cars[0].doors[0].width == 1.2
    assert [d.offset for d in default_doors(19.5, 3, 1.3)] == pytest.approx([3.25, 9.75, 16.25])
    first = [CarDoor(4.0), CarDoor(10.0)]
    tr = make_train(3, 20.0, first_doors=first)
    assert [d.offset for d in tr.cars[0].doors] == [4.0, 10.0] and len(tr.cars[1].doors) == 4
    assert tr.cars[0].doors[0] is not first[0]                       # 복사본
    assert TrainSettings().enabled is False and layout_trains(cfg_t()) == []


def test_door_positions_both_directions_and_front():
    cfg = cfg_train()
    r, l = layout_trains(cfg)
    assert (r.track, r.direction, r.t, r.side) == ("R", 1, -2.2, -1) and (l.track, l.direction, l.t, l.side) == ("L", -1, 2.2, 1)
    assert (r.front_s, r.rear_s) == (179.0, 19.0) and (l.front_s, l.rear_s) == (19.0, 179.0)      # 열차 중심 = 내공 중심 99
    assert [(d.label, d.s) for d in r.doors[:5]] == [("1-1", 176.5), ("1-2", 171.5), ("1-3", 166.5), ("1-4", 161.5),
                                                     ("2-1", 156.5)]
    assert [(d.label, d.s) for d in l.doors[:2]] == [("1-1", 21.5), ("1-2", 26.5)]
    assert r.doors[-1].label == "8-4" and r.doors[-1].s == pytest.approx(21.5)
    assert r.cars[0] == (1, 179.0, 159.0)
    (p,) = layout_trains(cfg_train(stops=[TrainStop("R", -1, 30.0)]))       # 선두 STA 지정, −s 방향
    assert (p.front_s, p.rear_s, p.doors[0].s) == (30.0, 190.0, 32.5)


@pytest.mark.parametrize("kw, msg", [
    (dict(train=Train([])), "1량 이상"),
    (dict(train=make_train(2, 20.0, [CarDoor(0.3)])), "차량 길이"),
    (dict(train=make_train(2, 20.0, [CarDoor(5.0), CarDoor(5.5)])), "겹치거나"),
    (dict(train=make_train(2, 20.0, [CarDoor(5.0, 0.0)])), "문 폭"),
    (dict(train=make_train(2, 0.0)), "차량 길이는"),
    (dict(train=make_train(2, 20.0, []), ), "문이 1개 이상"),
    (dict(stops=[TrainStop("R", 1, 150.0)]), "내공"),
    (dict(stops=[TrainStop("R", 1), TrainStop("R", -1)]), "두 번"),
    (dict(stops=[TrainStop("X", 1)]), "L 또는 R"),
    (dict(stops=[TrainStop("R", 0)]), "진행방향"),
    (dict(mark_width=0.0), "표시 폭"),
    (dict(train=make_train(10)), "내공"),
])
def test_invalid_train(kw, msg):
    with pytest.raises(ValueError, match=msg):
        cfg_train(**kw).validate()


# ===================================================== 승하차 위치 표시
def test_boarding_marks_replace_edge_band():
    cfg = cfg_train()
    bs = layout_tactile(cfg)
    board = [b for b in bs if b.kind == BOARD]
    warn = [b for b in bs if b.kind == WARNING and b.source == "EDGE"]
    assert len(board) == 64 and {b.floor for b in board} == {1}
    area = lambda xs: sum((b.rect[1] - b.rect[0]) * (b.rect[3] - b.rect[2]) for b in xs)
    assert area(board) == pytest.approx(64 * 1.8 * 0.6)
    assert area(board) + area(warn) == pytest.approx(2 * 198 * 0.6)                     # 띠 = 승하차 + 나머지 점형
    one = next(b for b in board if b.source == "TRAIN_R" and b.label == "1-1")
    assert one.rect == pytest.approx((175.6, 177.4, -5.1, -4.5)) and one.base == pytest.approx(1.3)
    left = next(b for b in board if b.source == "TRAIN_L" and b.label == "1-1")
    assert left.rect == pytest.approx((20.6, 22.4, 4.5, 5.1))
    # 표시 폭·점자블록 끔·승강장 없음
    assert sum(b.rect[1] - b.rect[0] for b in layout_tactile(cfg_train(mark_width=1.2)) if b.kind == BOARD) == pytest.approx(64 * 1.2)
    cfg = cfg_train()
    cfg.tactile_settings = TactileSettings(enabled=False)
    assert layout_tactile(cfg) == []
    cfg = cfg_train()
    cfg.platform.plat_thick = 0.0
    assert not [b for b in layout_tactile(cfg) if b.kind == BOARD]


def test_boarding_element_drawing_ifc_and_dae(tmp_path):
    eng = StationCADEngine(cfg_train(finishes=True))
    board = next(e for e in eng.tactiles.elements if e.name == "TB_B3F_BOARD")
    assert board.material == "승하차위치표시" and board.area == pytest.approx(64 * 1.8 * 0.6)
    texts = [it.label[0] for it in eng.tactiles.plan_items(2.0, floor=1) if it.label]
    assert len(texts) == 64 and texts.count("1-1") == 2 and "8-4" in texts
    assert not [it for it in eng.tactiles.plan_items(2.0, floor=2) if it.label]
    plan = eng.build_plan_doc(floors=[1], cut_h=2.0)
    assert "3-2" in [t.dxf.text for t in plan.modelspace().query('TEXT[layer=="PLAN_TACTILE"]')]
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "t.ifc"))
    el = next(c for c in f.by_type("IfcCovering") if c.Name == "TB_B3F_BOARD")
    assert ifcopenshell.util.element.get_material(el).Name == "승하차위치표시"
    assert ifc_world_volume(el) == pytest.approx(board.volume, rel=1e-7)
    quads = [q for p in board.pieces for q in PM.sweep_quads(PM.rings(eng.cfg, p))]
    assert PM.mesh_volume(quads) == pytest.approx(board.volume, rel=1e-7)
    from PIL import Image
    d = tmp_path / "tile"
    d.mkdir()
    Image.new("RGB", (8, 8), (220, 100, 190)).save(d / "tactile_boarding.png")
    eng.generate_dae(tmp_path / "m.dae", texture_dir=d)
    assert "승하차위치표시" in eng.dae_result.textured


# ===================================================== 입력 초안 · 프로젝트 파일
def test_draft_to_settings_preview_and_errors():
    d = TrainDraft()
    assert d.enabled is True and d.door_offsets == "2.5, 7.5, 12.5, 17.5" and d.r_dir == DIRS[0] and d.l_dir == DIRS[1]
    d.cars, d.first_doors, d.r_front, d.l_stop = "6", "4, 10", "250", False
    ts = d.to_settings(100.0)
    assert ts.train.total_cars == 6 and [x.offset for x in ts.train.cars[0].doors] == [4.0, 10.0]
    assert ts.stops == [TrainStop("R", 1, 150.0)]
    assert "6량 편성, 길이 120m" in preview(d, 100.0)
    d.door_offsets = ""
    with pytest.raises(ValueError, match="문 위치"):
        d.to_settings(0.0)
    d.door_offsets, d.cars = "5", "x"
    with pytest.raises(ValueError, match="정수"):
        d.to_settings(0.0)
    d.enabled = False
    assert d.to_settings(0.0).enabled is False and "사용 안 함" in preview(d, 0.0)


def test_project_state_roundtrip():
    st = ProjectState()
    st.train_draft.cars, st.train_draft.l_front = "6", "123.4"
    back = ProjectState.from_dict(st.to_dict())
    assert back.train_draft == st.train_draft
    old = st.to_dict()
    del old["train_draft"]
    assert ProjectState.from_dict(old).train_draft == TrainDraft()
