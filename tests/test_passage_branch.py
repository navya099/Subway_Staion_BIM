"""출구통로 T자 분기: 부모 측벽 자동 접합·개구부·여러 단계·검증 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataclasses

import ifcopenshell
import pytest

from engine.cad_engine import StationCADEngine
from entrances.entrance_spec import EntranceSpec
from gui.passage_draft import PassageDraft, VertexDraft, preview
from passages.passage_check import layout_passages
from passages.passage_spec import PassageSpec, station_path
from signs.sign_layout import EXIT, layout_signs
from signs.sign_spec import SignSettings
from test_curved import NO_COLS
from test_finishes import ifc_world_volume
from test_patch import make_cfg
from helper import prism_member as PM

# make_cfg: 3개 층 각 6m, 내공 198 × 18, 외벽 1.0 → 외벽 바깥면 t = ±10, 통로 기본 내공 4 × 3, 벽 0.6 (외곽 반폭 2.6)


def A():
    return PassageSpec(floor=3, path=station_path([(50, None, None), (50, 30, 0), (80, 30, 0)]), name="A")


def cfg_b(*children, parent=None):
    cfg = make_cfg(NO_COLS())
    cfg.passages = [parent or A(), *children]
    return cfg


def lays(cfg):
    return {l.name: l for l in layout_passages(cfg)}


def wall_volume(lay, code):
    return sum(p.volume for e in lay.elements if e.code == code for p in e.pieces)


# ===================================================== 접합
def test_branch_attaches_perpendicular_to_parent_wall():
    b = PassageSpec(floor=1, path=station_path([(50, 20, None), (40, 20, 0), (40, 5, 0)]), name="B", parent="A")
    L = lays(cfg_b(b))
    a, c = L["A"], L["B"]
    assert c.parent == "A" and c.floor == 3 and c.wall_opening is None             # 층은 부모를 따름 (입력 1 무시)
    v0 = c.vertices[0]
    assert (v0.s, v0.t) == pytest.approx((50 - 2.6, 20.0)) and v0.z == pytest.approx(a.vertices[1].z)
    assert (c.branch_seg, c.branch_a, c.side) == (0, pytest.approx(10.0), 1)       # A 1구간(+t 방향)의 왼쪽 = −s
    assert c.vertices[1].z == pytest.approx(a.z_floor)                              # 높이 기준 = 분기점 부모 바닥
    # 첫 꼭짓점 t 를 비우면 두 번째 꼭짓점으로 부모 구간을 찾음
    b2 = dataclasses.replace(b, path=station_path([(0, None, None), (40, 20, 0)]))
    assert lays(cfg_b(b2))["B"].vertices[0].t == pytest.approx(20.0)


@pytest.mark.parametrize("child_h, lintel", [(3.0, False), (2.4, True)])
def test_parent_wall_opening_volume(child_h, lintel):
    base = lays(cfg_b())["A"]
    b = PassageSpec(path=station_path([(65, 30, None), (65, 45, 0)]), name="B", parent="A", inner_height=child_h,
                    inner_width=3.0)
    L = lays(cfg_b(b))
    a = L["A"]
    assert L["B"].side == 1 and L["B"].branch_seg == 1
    cut = 3.0 * child_h * 0.6                                                      # 내공 폭 × 높이 × 부모 벽 두께
    assert wall_volume(a, "S2_WALL_L") == pytest.approx(wall_volume(base, "S2_WALL_L") - cut)
    assert wall_volume(a, "S2_WALL_R") == pytest.approx(wall_volume(base, "S2_WALL_R"))
    assert any("lintel" in p.local for e in a.elements for p in e.pieces) is lintel


def test_multi_level_branch_and_volumes(tmp_path):
    c = PassageSpec(path=station_path([(65, 30, None), (65, 45, 0)]), name="C", parent="A")
    d = PassageSpec(path=station_path([(65, 40, None), (75, 40, 0)]), name="D", parent="C", inner_width=3.0)
    cfg = cfg_b(d, c)                                                                # 자식이 부모보다 먼저 입력돼도 됨
    L = lays(cfg)
    assert [l.name for l in layout_passages(cfg)] == ["A", "D", "C"]                # 결과는 입력 순서
    assert L["D"].parent == "C" and L["D"].side == -1 and L["D"].vertices[0].s == pytest.approx(65 + 2.6)
    eng = StationCADEngine(cfg)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "b.ifc"))
    by = {e.Name: e for e in f.by_type("IfcElement") if e.Name}
    for ps in eng.passages.all_passages():
        for e in ps.elements:
            assert PM.mesh_volume([fc for p in e.pieces for fc in p.faces()]) == pytest.approx(e.volume, rel=1e-9)
            assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=1e-6), e.name
    assert [o[0] for o in cfg.wall_openings() if o[-1] == "PASSAGE"] == ["A"]      # 본체 측벽 개구부는 뿌리 통로만


def test_entrance_on_branch_and_exit_sign_only_for_root():
    cfg = cfg_b(PassageSpec(path=station_path([(65, 30, None), (65, 45, 0)]), name="C", parent="A"))
    cfg.station.ground_el = cfg.lv(65) - cfg.station.offset + cfg.station.floor_level(3) + 15.0
    cfg.entrances = [EntranceSpec(passage="C")]
    eng = StationCADEngine(cfg)
    assert [e.name for e in eng.entrances.entrances]
    cfg.sign_settings = SignSettings(enabled=True)
    assert [p.name for p in layout_signs(cfg) if p.kind == EXIT] == ["EX_A"]


# ===================================================== 검증
@pytest.mark.parametrize("children, msg", [
    ([PassageSpec(path=station_path([(60, 30, None), (60, 45, 0)]), name="B", parent="X")], "없습니다"),
    ([PassageSpec(path=station_path([(60, 30, None), (60, 45, 0)]), name="B", parent="B")], "자기 자신"),
    ([PassageSpec(path=station_path([(60, 30, None), (60, 45, 0)]), name="B", parent="C"),
      PassageSpec(path=station_path([(60, 40, None), (70, 40, 0)]), name="C", parent="B")], "순환"),
    ([PassageSpec(path=station_path([(60, 30, None), (60, 31, 0)]), name="B", parent="A")], "바깥에"),
    ([PassageSpec(path=station_path([(78, 30, None), (78, 45, 0)]), name="B", parent="A")], "측벽 범위"),
    ([PassageSpec(path=station_path([(85, 30, None), (95, 30, 0)]), name="B", parent="A")], "구간 밖"),     # 부모 끝 너머
    ([PassageSpec(path=station_path([(65, 30, None), (65, 45, 0)]), name="B", parent="A", inner_height=3.5)], "내공 높이"),
    ([PassageSpec(path=station_path([(65, 30, None), (65, 45, None)]), name="B", parent="A")], "바닥 높이"),
    ([PassageSpec(path=station_path([(65, 30, 0.5), (65, 45, 0)]), name="B", parent="A")], "부모 바닥"),
])
def test_invalid_branch(children, msg):
    with pytest.raises(ValueError, match=msg):
        cfg_b(*children).validate()


def test_sloped_parent_segment_rejected():
    parent = PassageSpec(floor=3, path=station_path([(50, None, None), (50, 30, 0), (50, 40, 1.0)]), name="A")
    with pytest.raises(ValueError, match="수평이 아닙니다"):
        cfg_b(PassageSpec(path=station_path([(50, 35, None), (60, 35, 0.5)]), name="B", parent="A"),
              parent=parent).validate()


def test_branch_overlapping_another_passage_rejected():
    c = PassageSpec(path=station_path([(65, 30, None), (65, 45, 0)]), name="C", parent="A")
    e = PassageSpec(floor=3, path=station_path([(70, None, None), (70, 40, 0), (60, 40, 0)]), name="E")
    with pytest.raises(ValueError, match="겹칩니다"):
        cfg_b(c, e).validate()


# ===================================================== 입력 초안
def test_draft_parent():
    d = PassageDraft(name="B", parent="A", vertices=[VertexDraft("150", "", ""), VertexDraft("140", "20", "0")])
    sp = d.to_spec("출구통로 2", 100.0)
    assert sp.parent == "A" and sp.path[0].y is None
    assert "A 에서 분기" in preview(d, 100.0)



# ===================================================== 끝 폐합 옵션 (통로마다 체크)
def closed_set(end_t=25.5):
    return [PassageSpec(floor=3, path=station_path([(30, None, None), (30, end_t, 0)]), name="EX1", close_end=True),
            PassageSpec(path=station_path([(32.6, 22.9, None), (50.9, 22.9, 0)]), name="EX2", parent="EX1", close_end=True),
            PassageSpec(path=station_path([(44, 25.5, None), (44, 35, 0)]), name="EX3", parent="EX2")]


def test_close_end_option_end_wall_and_volumes(tmp_path):
    cfg = make_cfg(NO_COLS())
    cfg.passages = closed_set()
    L = lays(cfg)
    for name, closed in (("EX1", True), ("EX2", True), ("EX3", False)):
        codes = [e.code for e in L[name].elements]
        assert ("S1_END" in codes) is closed
    end = next(e for e in L["EX2"].elements if e.code == "S1_END")
    (pc,) = end.pieces
    assert (pc.a0, pc.a1) == pytest.approx((18.3 - 0.6, 18.3)) and pc.volume == pytest.approx(4.0 * 3.0 * 0.6)
    haunch = [p for e in L["EX2"].elements for p in e.pieces if len(p.sect) == 3]
    assert haunch and all(p.a1 == pytest.approx(18.3 - 0.6) for p in haunch)       # 헌치는 끝 벽 앞까지 (겹침 없음)
    eng = StationCADEngine(cfg)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "c.ifc"))
    by = {x.Name: x for x in f.by_type("IfcElement") if x.Name}
    for ps in eng.passages.all_passages():
        for x in ps.elements:
            assert PM.mesh_volume([fc for p in x.pieces for fc in p.faces()]) == pytest.approx(x.volume, rel=1e-9)
            assert ifc_world_volume(by[x.name]) == pytest.approx(x.volume, rel=1e-6), x.name
    # 끄면 끝단 개방 (예전과 같음)
    cfg.passages = [dataclasses.replace(sp, close_end=False) for sp in closed_set()]
    assert not any(e.code.endswith("END") for l in layout_passages(cfg) for e in l.elements)


@pytest.mark.parametrize("passages, entrance, msg", [
    (closed_set(25.0), None, "끝 벽과 겹칩니다"),                                   # 분기 개구부(끝 14.9)가 끝 벽(14.4~15)에 걸림
    (closed_set(), "EX1", "출입구가 붙은 통로는 끝을 막을 수 없습니다"),
    ([PassageSpec(floor=3, path=station_path([(30, None, None), (30, 10.5, 0)]), name="EX1", close_end=True)], None, "너무 짧습니다"),
])
def test_close_end_errors(passages, entrance, msg):
    cfg = make_cfg(NO_COLS())
    cfg.passages = passages
    if entrance:
        cfg.entrances = [EntranceSpec(passage=entrance, ground_el=200.0)]
    with pytest.raises(ValueError, match=msg):
        cfg.validate()


def test_draft_close_end():
    d = PassageDraft(name="EX1", close_end=True, vertices=[VertexDraft("130", "", ""), VertexDraft("130", "25", "0")])
    assert d.to_spec("출구통로 1", 100.0).close_end is True and "끝 폐합" in preview(d, 100.0)
