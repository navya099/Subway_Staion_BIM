"""점자블록 (자동 점형 경고블록 + 유도블록 경로, 바닥 마감 대체) 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataclasses

import ifcopenshell
import pytest

from elevators.elevator_spec import ElevatorSpec
from engine.cad_engine import StationCADEngine
from escalators.escalator_spec import EscalatorSpec
from finishes.finish_spec import FinishSettings
from gui.project_file import ProjectState
from gui.tactile_draft import TactileDrafts, TactilePathDraft, TactilePointDraft, preview
from helper import prism_member as PM
from helper.strip_member import _fan
from rooms.room_spec import RoomSettings, RoomSpec
from stairs.stair_spec import StairSpec
from tactiles.tactile_layout import layout_tactile
from tactiles.tactile_spec import GUIDE, WARNING, TactilePathSpec, TactileSettings
from test_curved import NO_COLS, curved_cfg
from test_finishes import ifc_world_volume
from test_patch import make_cfg, user_example

# user_example: 3개 층 각 6m, 내공 198 x 18, 승강장 t ±3.9 ~ ±9 (상면 1.3), 기둥 B3 t=0 / B2 t=±3 원 / B1 t=0 원+사각 0.8


def cfg_t(*paths, finishes=False, curved=False, columns=None, **ts):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(columns or NO_COLS())
    cfg.rooms, cfg.room_settings = [], RoomSettings()
    cfg.finish_settings = FinishSettings(enabled=finishes)
    cfg.tactile_settings = TactileSettings(enabled=True, paths=list(paths), **ts)
    return cfg


def area(rects):
    return sum((r[1] - r[0]) * (r[3] - r[2]) for r in rects)


def blocks(cfg, floor=None, kind=None, source=None):
    return [b for b in layout_tactile(cfg) if (floor is None or b.floor == floor) and (kind is None or b.kind == kind)
            and (source is None or b.source == source)]


def no_overlap(bs):
    for i, a in enumerate(bs):
        for b in bs[i + 1:]:
            if a.floor != b.floor:
                continue
            ds = min(a.rect[1], b.rect[1]) - max(a.rect[0], b.rect[0])
            dt = min(a.rect[3], b.rect[3]) - max(a.rect[2], b.rect[2])
            assert not (ds > 1e-9 and dt > 1e-9), (a, b)


# ===================================================== 배치
def test_disabled_by_default():
    cfg = make_cfg(NO_COLS())
    assert cfg.tactile_settings.enabled is False and layout_tactile(cfg) == []
    assert StationCADEngine(cfg).tactiles.elements == []


def test_platform_edge_bands():
    cfg = cfg_t()
    edge = blocks(cfg, source="EDGE")
    assert {b.floor for b in edge} == {1} and {b.kind for b in edge} == {WARNING}
    assert sorted(b.rect for b in edge) == [(0.0, 198.0, -5.1, -4.5), (0.0, 198.0, 4.5, 5.1)]   # 끝단 3.9 + 0.6, 폭 0.6
    assert all(b.base == pytest.approx(1.3) for b in edge)                                       # 승강장 상면
    cfg = cfg_t(edge_offset=0.3, edge_width=0.9)
    assert sorted(b.rect for b in blocks(cfg, source="EDGE"))[1] == pytest.approx((0.0, 198.0, 4.2, 5.1))
    assert blocks(cfg_t(edge=False), source="EDGE") == []


@pytest.mark.parametrize("direction", [1, -1])
def test_stair_front_and_arrival_bands(direction):
    cfg = cfg_t()
    cfg.stairs = [StairSpec(lower_floor=2, s_start=100.0, direction=direction, t_center=3.0, width=2.0, name="ST")]
    lay = cfg.stair_layouts()[0]
    low, top = blocks(cfg, floor=2, source="ST"), blocks(cfg, floor=3, source="ST")
    assert len(low) == 1 and len(top) == 1
    s_low = sorted((100.0 - direction * 0.3, 100.0 - direction * 0.9))
    s_top = sorted((lay.s_at(lay.length + 0.3), lay.s_at(lay.length + 0.9)))
    assert low[0].rect == pytest.approx((*s_low, 2.0, 4.0)) and top[0].rect == pytest.approx((*s_top, 2.0, 4.0))
    assert top[0].base == pytest.approx(cfg.station.floor_level(3))
    assert blocks(cfg_t(stair=False), source="ST") == []


def test_escalator_bands_beyond_truss_ends():
    cfg = cfg_t()
    cfg.escalators = [EscalatorSpec(lower_floor=1, s_wp=80.0, direction=1, t_center=-6.5, name="ES")]   # 승강장 위
    lay = cfg.escalator_layouts()[0]
    u0, u1 = lay.u_range
    low, top = blocks(cfg, floor=1, source="ES"), blocks(cfg, floor=2, source="ES")
    assert low[0].rect == pytest.approx((80.0 + u0 - 0.9, 80.0 + u0 - 0.3, -7.3, -5.7))
    assert low[0].base == pytest.approx(1.3)
    assert top[0].rect == pytest.approx((80.0 + u1 + 0.3, 80.0 + u1 + 0.9, -7.3, -5.7))


@pytest.mark.parametrize("side, through", [("+t", False), ("-s", True)])
def test_elevator_door_bands_on_every_stop(side, through):
    cfg = cfg_t()
    cfg.elevators = [ElevatorSpec(lower_floor=2, upper_floor=3, s_center=150.0, t_center=-3.0, door_side=side,
                                  through=through, name="EV")]
    s0, s1, t0, t1 = cfg.elevators[0].outer_rect()
    half = 0.9 / 2 + 0.3
    for n in (2, 3):
        got = sorted(b.rect for b in blocks(cfg, floor=n, source="EV"))
        if side == "+t":
            assert got == [pytest.approx((150.0 - half, 150.0 + half, t1 + 0.3, t1 + 0.9))]
        else:
            assert got == [pytest.approx((s0 - 0.9, s0 - 0.3, -3.0 - half, -3.0 + half)),
                           pytest.approx((s1 + 0.3, s1 + 0.9, -3.0 - half, -3.0 + half))]
    assert blocks(cfg, floor=1, source="EV") == []


def test_path_points_warning_segments_guide_and_priority():
    p = TactilePathSpec(floor=2, points=[(20.0, 0.0), (60.0, 0.0), (60.0, 5.0)], name="P")
    cfg = cfg_t(p)
    warn, guide = blocks(cfg, floor=2, kind=WARNING), blocks(cfg, floor=2, kind=GUIDE)
    assert area(b.rect for b in warn) == pytest.approx(3 * 0.09)
    assert area(b.rect for b in guide) == pytest.approx(39.7 * 0.3 + 4.7 * 0.3)
    # 폭 지정 + 다른 경로와 교차: 점형 우선, 서로 겹치지 않음, 합 = 합집합 넓이
    q = TactilePathSpec(floor=2, points=[(40.0, -3.0), (40.0, 3.0)], width=0.6, name="Q")
    cfg = cfg_t(p, q)
    bs = blocks(cfg, floor=2)
    no_overlap(bs)
    union = 3 * 0.09 + 0.36 * 2 + (39.7 * 0.3 + 4.7 * 0.3) + 5.4 * 0.6 - 0.6 * 0.3     # 교차 0.6×0.3 한 번만
    assert area(b.rect for b in bs) == pytest.approx(union)
    assert all(b.kind == GUIDE for b in bs if b.rect[0] < 40.0 < b.rect[1] and b.rect[2] < 0 < b.rect[3])


def test_obstacles_columns_partitions_stairs_removed():
    p = TactilePathSpec(floor=3, points=[(0.15, 0.0), (197.85, 0.0)], name="P")
    cfg = cfg_t(p, columns=user_example())
    cols = [c for c in StationCADEngine(cfg).columns.column_packages if c.level == "B1F"][0].columns
    n_rect = sum(1 for c in cols if getattr(c.shape, "radius", None) is None)
    from finishes.finish_engine import column_footprints
    eng = StationCADEngine(cfg)
    bs = [b for b in layout_tactile(cfg, column_footprints(cfg, eng.columns)) if b.floor == 3]
    full = 198.0 * 0.3                                               # 끝 점 정사각형 2개 + 선형 = 내공 길이 전체
    assert area(b.rect for b in bs) == pytest.approx(full - n_rect * 0.8 * 0.3)    # 사각 기둥 0.8 폭만큼 빠짐 (원기둥은 남김)
    # 칸막이벽·계단 평면도 빠짐
    cfg2 = cfg_t(TactilePathSpec(floor=2, points=[(10.0, 6.0), (60.0, 6.0)], name="P"))
    cfg2.rooms = [RoomSpec(2, "역무실", 30, 40, 2, 9, name="OFF")]
    cfg2.stairs = [StairSpec(lower_floor=2, s_start=50.0, direction=1, t_center=6.0, width=2.0, name="ST")]
    got = blocks(cfg2, floor=2, source="P")
    for b in got:
        assert not (b.rect[0] < 30.1 and b.rect[1] > 29.9) and not (b.rect[0] < 40.1 and b.rect[1] > 39.9)   # 칸막이벽 자리
        assert b.rect[1] <= 50.0 + 1e-9                                                              # 계단 평면 앞에서 끝
    no_overlap(blocks(cfg2))


# ===================================================== 마감 대체 · 높이 · 체적
def floor_finish_area(eng):
    return sum(p.shape.length * p.shape.width for r in eng.finishes.rooms for e in r.elements if e.code == "FLOOR"
               for p in e.pieces)


def test_blocks_replace_floor_finish_at_same_level():
    p = TactilePathSpec(floor=3, points=[(20.0, 4.0), (60.0, 4.0)], name="P")
    on = StationCADEngine(cfg_t(p, finishes=True))
    off_cfg = cfg_t(p, finishes=True)
    off_cfg.tactile_settings = TactileSettings(enabled=False)
    off = StationCADEngine(off_cfg)
    tactile_area = sum(e.area for e in on.tactiles.elements)
    assert floor_finish_area(on) + tactile_area == pytest.approx(floor_finish_area(off))
    ft = on.finishes.rooms[0].finish
    for e in on.tactiles.elements:
        for pc in e.pieces:
            n = e.floor
            base = on.cfg.platform.top_level if n == 1 else on.cfg.station.floor_level(n)
            assert PM.z_off(on.cfg, pc) == pytest.approx(base + ft.ffl - ft.floor_t)        # 마감재 하면
            assert pc.shape.height == pytest.approx(ft.floor_t)
    # 마감 끔: 기준 바닥 위 블록 두께
    eng = StationCADEngine(cfg_t(p, block_t=0.04))
    for e in eng.tactiles.elements:
        for pc in e.pieces:
            base = eng.cfg.platform.top_level if e.floor == 1 else eng.cfg.station.floor_level(e.floor)
            assert PM.z_off(eng.cfg, pc) == pytest.approx(base) and pc.shape.height == pytest.approx(0.04)


def test_room_without_floor_finish_gets_block_on_structure():
    p = TactilePathSpec(floor=2, points=[(32.0, 5.0), (38.0, 5.0)], name="P")
    cfg = cfg_t(p, finishes=True)
    cfg.rooms = [RoomSpec(2, "기계실", 30, 40, 2, 9, name="MEC")]          # 콘크리트 면처리: 바닥 마감 없음
    eng = StationCADEngine(cfg)
    pcs = [pc for e in eng.tactiles.elements if e.floor == 2 for pc in e.pieces]
    assert pcs and all(PM.z_off(eng.cfg, pc) == pytest.approx(cfg.station.floor_level(2)) for pc in pcs)
    assert all(pc.shape.height == pytest.approx(0.03) for pc in pcs)


@pytest.mark.parametrize("curved", [False, True])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, curved):
    p = TactilePathSpec(floor=2, points=[(20.0, 4.0), (60.0, 4.0), (60.0, -4.0)], name="P")
    cfg = cfg_t(p, finishes=True, curved=curved)
    cfg.stairs = [StairSpec(lower_floor=2, s_start=100.0, direction=1, t_center=3.0, width=2.0, name="ST")]
    eng = StationCADEngine(cfg)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "t.ifc"))
    by = {e.Name: e for e in f.by_type("IfcCovering")}
    tol = 1e-4 if curved else 1e-7
    assert {e.name for e in eng.tactiles.elements} == {"TB_B3F_WARN", "TB_B2F_WARN", "TB_B2F_GUIDE", "TB_B1F_WARN"}
    for e in eng.tactiles.elements:
        quads = [q for pc in e.pieces for q in PM.sweep_quads(PM.rings(eng.cfg, pc))]
        if curved:
            quads = [t for q in quads for t in _fan(q)]
        assert PM.mesh_volume(quads) == pytest.approx(e.volume, rel=tol), e.name
        el = by[e.name]
        assert ifc_world_volume(el) == pytest.approx(e.volume, rel=tol), e.name
        assert el.PredefinedType == "FLOORING" and el.ObjectType == e.material
        assert el.ContainedInStructure[0].RelatingStructure.Name == e.level
        assert ifcopenshell.util.element.get_material(el).Name == e.material


def test_drawings_and_dae_texture(tmp_path):
    p = TactilePathSpec(floor=1, points=[(20.0, 6.0), (60.0, 6.0)], name="P")
    eng = StationCADEngine(cfg_t(p, finishes=True))
    doc = eng.build_3d_doc()
    assert len(doc.modelspace().query('3DFACE[layer=="FIN_TACTILE"]')) == sum(6 * len(e.pieces) for e in eng.tactiles.elements)
    sec = [it for it in eng.tactiles.section_items(40.0)]
    assert sorted(round(it.u0, 3) for it in sec) == [-5.1, 4.5, 5.85]          # 연단 띠 2 + 경로 선형
    assert len(eng.tactiles.plan_items(2.0, floor=1)) == sum(len(e.pieces) for e in eng.tactiles.elements if e.floor == 1)
    assert eng.tactiles.plan_items(2.0, floor=2) == []
    assert [it for it in eng.tactiles.profile_items(4.8)]                       # 연단 띠를 지나는 종단
    plan = eng.build_plan_doc(floors=[1], cut_h=2.0)
    assert len(plan.modelspace().query('*[layer=="PLAN_TACTILE"]')) > 0
    # DAE: 점형·선형 재질에 텍스처
    from PIL import Image
    d = tmp_path / "tile"
    d.mkdir()
    for n in ("tactile_warning", "tactile_guide"):
        Image.new("RGB", (8, 8), (240, 200, 20)).save(d / f"{n}.png")
    eng.generate_dae(tmp_path / "m.dae", texture_dir=d)
    assert {"점자블록 점형", "점자블록 선형"} <= set(eng.dae_result.textured)


# ===================================================== 검증
@pytest.mark.parametrize("path, msg", [
    (TactilePathSpec(floor=2, points=[(20.0, 0.0), (30.0, 2.0)]), "선형 방향"),
    (TactilePathSpec(floor=2, points=[(20.0, 0.0)]), "2개 이상"),
    (TactilePathSpec(floor=2, points=[(20.0, 0.0), (20.0, 0.0)]), "같은 위치"),
    (TactilePathSpec(floor=4, points=[(20.0, 0.0), (30.0, 0.0)]), "층 번호"),
    (TactilePathSpec(floor=1, points=[(20.0, 0.0), (30.0, 0.0)]), "승강장 위"),
    (TactilePathSpec(floor=1, points=[(20.0, 6.0), (20.0, -6.0)]), "승강장 위"),
    (TactilePathSpec(floor=2, points=[(20.0, 8.95), (30.0, 8.95)]), "내공 폭"),
    (TactilePathSpec(floor=2, points=[(-1.0, 0.0), (30.0, 0.0)]), "내공 길이"),
    (TactilePathSpec(floor=2, points=[(20.0, 0.0), (30.0, 0.0)], width=0.0), "폭"),
])
def test_invalid_paths(path, msg):
    with pytest.raises(ValueError, match=msg):
        cfg_t(path).validate()


def test_invalid_settings_and_duplicate_names():
    with pytest.raises(ValueError, match="블록 크기"):
        cfg_t(size=0.0).validate()
    with pytest.raises(ValueError, match="연단 이격"):
        cfg_t(edge_offset=-0.1).validate()
    a = TactilePathSpec(floor=2, points=[(20.0, 0.0), (30.0, 0.0)], name="A")
    with pytest.raises(ValueError, match="중복"):
        cfg_t(a, dataclasses.replace(a)).validate()


# ===================================================== 입력 초안 · 프로젝트 파일
def test_draft_to_settings_and_preview():
    d = TactileDrafts()
    assert d.settings.enabled is True                                         # GUI 기본 켬
    d.settings.edge_offset, d.settings.stair = "0.5", False
    d.items.append(TactilePathDraft(name="P", floor=2, vertices=[TactilePointDraft("120", "1.5"),
                                                                 TactilePointDraft("130", "1.5")]))
    ts = d.to_settings(100.0)
    assert ts.enabled and ts.edge_offset == 0.5 and ts.stair is False and ts.size == 0.3
    assert ts.paths[0].points == [(20.0, 1.5), (30.0, 1.5)] and ts.paths[0].width is None and ts.paths[0].floor == 2
    assert "유도 경로 1개" in preview(d, 100.0) and "계단 앞" not in preview(d, 100.0)
    d.items[0].width = "x"
    with pytest.raises(ValueError, match="유도블록 경로 1\\(P\\)"):
        d.to_settings(100.0)
    d.settings.enabled = False
    assert d.to_settings(0.0).enabled is False and "만들지 않음" in preview(d, 0.0)


def test_project_state_roundtrip():
    st = ProjectState()
    st.tactile_settings.edge_width = "0.9"
    st.tactile_settings.elevator = False
    st.tactile_drafts = [TactilePathDraft(name="P", floor=3, width="0.6",
                                          vertices=[TactilePointDraft("1", "2"), TactilePointDraft("1", "5")])]
    back = ProjectState.from_dict(st.to_dict())
    assert back.tactile_settings == st.tactile_settings and back.tactile_drafts == st.tactile_drafts
    old = st.to_dict()
    del old["tactile_settings"], old["tactile_drafts"]                         # 옛 파일
    back = ProjectState.from_dict(old)
    assert back.tactile_settings.enabled is True and back.tactile_drafts == []
