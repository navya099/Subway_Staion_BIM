"""구조물 확폭 2단계: 넓어진 내공의 실·마감·점자블록·사인, 계단 등 범위 검사, 통로·환기구 접합 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math

import ifcopenshell
import pytest

from config.widening import WidenSpec, clear_traps, outer_at
from engine.cad_engine import StationCADEngine
from helper import prism_member as PM
from helper import trap_region as T
from rooms.room_spec import RoomSpec
from test_finishes import ifc_world_volume
from test_widening import cfg_w

# make_cfg: 3개 층 각 6m, 내공 198 × 18 (내공면 |t| = 9), 외벽 1.0, 승강장 끝단 3.9
POCKET = WidenSpec(side=1, floors=[2], s_start=50, s_end=80, amount=2.0)          # B2F +t, 45° 전이 (48 ~ 82)


def floor_rooms(cfg, n):
    return next(fl for fl in cfg.room_layouts() if fl.floor == n)


def inset_area(d):
    """B2F 내공 다각형(POCKET)을 d 만큼 안으로 띄운(연귀) 다각형 면적 — A − P d + d² Σ cot(α/2) (독립 공식)"""
    A = 198 * 18 + 2 * 30 + 2 * 2
    P = 2 * 198 + 2 * 18 - 34 + 30 + 2 * math.sqrt(8)
    cots = 4 * 1.0 + 2 / math.tan(math.radians(225 / 2)) + 2 / math.tan(math.radians(135 / 2))
    return A - P * d + d * d * cots


# ===================================================== 도우미
def test_trap_region_ops():
    a = [T.rect(0, 10, 0, 5)]
    tri = [(0.0, 10.0, 0.0, 0.0, 0.0, 10.0)]
    assert T.area(T.subtract(a, [T.rect(2, 4, 1, 2)])) == pytest.approx(48.0)
    assert T.area(T.intersect(tri, a)) == pytest.approx(37.5)
    assert T.area(T.union(a, tri)) == pytest.approx(50 + 12.5)
    assert len(T.groups(T.subtract(a, [T.rect(4, 6, -1, 6)]))) == 2
    assert T.contains(tri, 9, 8) and not T.contains(tri, 2, 8)


def test_clear_traps_area():
    cfg = cfg_w(POCKET)
    assert T.area(clear_traps(cfg, 2)) == pytest.approx(inset_area(0.0))
    assert T.area(clear_traps(cfg, 1)) == pytest.approx(198 * 18)


# ===================================================== 실
def test_rooms_merge_pocket_into_adjacent_room():
    """내공면에 닿은 실이 포켓까지 넓어지고(맞닿은 실에 합침), 포켓 안 입력 실도 가능, 실 면적 합 = 넓어진 내공"""
    cfg = cfg_w(POCKET)
    cfg.rooms = [RoomSpec(2, "역무실", 40, 60, 0, 9.0), RoomSpec(2, "창고", 62, 70, 9.5, 10.95)]
    cfg.validate()
    fl = floor_rooms(cfg, 2)
    rooms = {r.use: r for r in fl.rooms}
    assert rooms["역무실"].area == pytest.approx(20 * 9 + 2 + 10 * 2)          # + 포켓 (사선 48~50 삼각형 + 50~60)
    assert rooms["창고"].area == pytest.approx(8 * 1.5)                         # t1 10.95 → 넓어진 내공면 11 에 붙음
    assert sum(r.area for r in fl.rooms) == pytest.approx(inset_area(0.0))
    walls = {pw.name: pw for pw in fl.partitions}
    t_at_60 = [p for pw in walls.values() for p in pw.pieces if abs((p[0] + p[1]) / 2 - 60) < 1e-6]
    assert max(p[3] for p in t_at_60) == pytest.approx(11.0)                    # s = 60 벽이 넓어진 내공면까지
    StationCADEngine(cfg)


def test_room_outside_widened_clear_rejected():
    cfg = cfg_w(POCKET)
    cfg.rooms = [RoomSpec(2, "창고", 40, 60, 9.5, 10.5)]                         # s 40 ~ 48 은 포켓 밖
    with pytest.raises(ValueError, match="확폭 포함"):
        cfg.validate()


# ===================================================== 마감
def _finish_cfg(curved=False):
    cfg = cfg_w(POCKET, WidenSpec(side=-1, floors=[2], s_start=20, s_end=40, amount=1.0, taper_in=0.0), curved=curved) \
        if curved else cfg_w(POCKET)
    cfg.finish_settings.enabled = True
    return cfg


def test_finish_areas_follow_slanted_face():
    """기본 실(포켓 포함): 바닥 = 넓어진 내공, 천장 = 벽 마감 표면까지(내공을 face 만큼 띄운 다각형), 벽 마감재 = 띠 (공식)"""
    cfg = _finish_cfg()
    eng = StationCADEngine(cfg)
    (room,) = [r for r in eng.finishes.rooms if r.floor == 2]
    ft = room.finish
    face, gap = ft.face, ft.wall_gap
    vol = lambda code: room.element(code).volume
    assert vol("FLOOR") == pytest.approx(inset_area(0.0) * ft.floor_t, rel=1e-9)
    assert vol("CEILING") == pytest.approx(inset_area(face) * ft.board_t, rel=1e-9)
    h = room.ceiling_rel - room.ffl_rel
    assert vol("WALL") == pytest.approx((inset_area(gap) - inset_area(face)) * h, rel=1e-9)


@pytest.mark.parametrize("curved", [False, True])
def test_finish_volumes_mesh_and_ifc_agree(tmp_path, curved):
    cfg = _finish_cfg(curved)
    cfg.rooms = [RoomSpec(2, "역무실", 40, 60, 0, 9.0)]
    eng = StationCADEngine(cfg)
    eng.build_3d_doc()
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "w.ifc"))
    by = {e.Name: e for e in f.by_type("IfcProduct") if e.Name}
    tol = 1e-4 if curved else 1e-7
    els = [e for r in eng.finishes.rooms if r.floor == 2 for e in r.elements if e.code != "FRAME"]
    assert any(p.trap for e in els for p in e.pieces)
    for e in els:
        mesh = sum(PM.mesh_volume(PM.sweep_quads(PM.rings(eng.cfg, p))) for p in e.pieces)
        assert mesh == pytest.approx(e.volume, rel=tol), e.name
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=tol), e.name
    for r in eng.rooms.rooms:
        if r.floor == 2:
            assert ifc_world_volume(by[r.name]) == pytest.approx(sum(p.shape.volume for p in r.pieces), rel=tol), r.name


def test_plan_draws_slanted_finish():
    cfg = _finish_cfg()
    eng = StationCADEngine(cfg)
    items = eng.finishes.plan_items(eng.cfg.station.floor_level(2) + 2.0, floor=2)
    assert any(abs(it.vb1 - it.vb0) > 1.0 for it in items)                     # 사선 벽 마감 조각
    eng.build_plan_doc(floors=[2], cut_h=2.0)


def test_world_plan_follows_slanted_finish():
    """곡선(WCS) 평면도: 사다리꼴 조각은 아래·위 변을 측점마다 보간 (예전엔 시작 높이로 사각형 — 사선 마감이 직선으로 그려짐)"""
    eng = StationCADEngine(_finish_cfg(curved=True))
    items = [it for it in eng.finishes.plan_items(eng.cfg.station.floor_level(2) + 2.0, floor=2) if abs(it.vb1 - it.vb0) > 1.0]
    assert items
    for it, w in zip(items, eng._plan_items_world(items)):
        n = len(w.pts) // 2
        assert w.pts[0] == pytest.approx(eng.cfg.to_world(it.u0, it.vb0))
        assert w.pts[n - 1] == pytest.approx(eng.cfg.to_world(it.u1, it.vb1))
        assert w.pts[n] == pytest.approx(eng.cfg.to_world(it.u1, it.vt1))


# ===================================================== 범위 검사
def test_stair_tactile_opening_in_pocket():
    from openings.opening_kind import OpeningKind
    from openings.opening_spec import OpeningSpec
    from stairs.stair_spec import StairSpec
    from tactiles.tactile_spec import TactilePathSpec
    cfg = cfg_w(POCKET)
    cfg.stairs = [StairSpec(lower_floor=2, s_start=55.0, direction=1, t_center=10.0, width=1.6)]
    cfg.openings = [OpeningSpec(kind=OpeningKind.VENT, slabs={2}, s_start=70.0, length=3.0, t_center=10.0, width=1.0)]
    cfg.tactile_settings.enabled = True
    cfg.tactile_settings.paths = [TactilePathSpec(floor=2, points=[(52.0, 10.5), (78.0, 10.5)])]
    cfg.validate()
    eng = StationCADEngine(cfg)
    assert eng.stairs.stair_packages
    bad = cfg_w(POCKET)
    bad.stairs = [StairSpec(lower_floor=2, s_start=20.0, direction=1, t_center=10.0, width=1.6)]
    with pytest.raises(ValueError, match="확폭 포함"):
        bad.validate()
    bad = cfg_w(POCKET)
    bad.tactile_settings.enabled = True
    bad.tactile_settings.paths = [TactilePathSpec(floor=2, points=[(30.0, 10.5), (52.0, 10.5)])]
    with pytest.raises(ValueError, match="확폭 포함"):
        bad.validate()


# ===================================================== 통로 접합 · 역명판
def test_passage_attaches_to_widened_outer_face():
    from passages.passage_spec import PassageSpec, PathVertex
    cfg = cfg_w(WidenSpec(side=1, floors=[1], s_start=50, s_end=80, amount=2.0))
    cfg.passages = [PassageSpec(floor=1, path=[PathVertex("station", 65.0, None, None), PathVertex("station", 65.0, 30.0, 0.0)])]
    cfg.validate()
    (lay,) = cfg.passage_layouts()
    assert lay.vertices[0].t == pytest.approx(outer_at(cfg, 1, 1, 65.0)) == pytest.approx(12.0)
    eng = StationCADEngine(cfg)
    wall = next(w for pk in eng.walls.wall_packages for w in pk.walls if w.name == "WALL_B3F_R")
    assert wall.openings
    cfg.passages = [PassageSpec(floor=1, path=[PathVertex("station", 65.0, 10.0, None), PathVertex("station", 65.0, 30.0, 0.0)])]
    with pytest.raises(ValueError, match="바깥면"):
        cfg.validate()


def test_nameplates_follow_widened_wall_and_skip_taper():
    from signs.sign_layout import layout_signs
    cfg = cfg_w(WidenSpec(side=1, floors=[1], s_start=59 + 3, s_end=150, amount=1.0, taper_in=4.0))   # 전이 58 ~ 62 (역명판 s 59)
    cfg.sign_settings.enabled = True
    plates = {round(p.s, 3): p for p in layout_signs(cfg) if p.name.startswith("NP_L")}
    assert 59.0 not in plates                                              # 사선 전이부 건너뜀
    assert plates[99.0].t == pytest.approx(10.0)                           # 넓어진 내공면 (마감 끔)
    assert plates[19.0].t == pytest.approx(9.0)
