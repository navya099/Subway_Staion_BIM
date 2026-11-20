"""구조물 확폭(1단계: 벽·단부 벽·슬래브·승강장) 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math

import ifcopenshell
import pytest

from config.widening import WidenSpec, side_wall_traps
from engine.cad_engine import StationCADEngine
from gui.project_file import ProjectState
from gui.widen_draft import KINDS, SIDES, WidenDraft, WidenDrafts
from helper import prism_member as PM
from test_curved import NO_COLS, curved_cfg
from test_finishes import ifc_world_volume
from test_patch import make_cfg

# make_cfg: 3개 층 각 6m, 내공 198 × 18 (내공면 |t| = 9), 외벽 1.0, 바닥 1.2·중간 0.4·천장 0.4, 승강장 끝단 3.9 (상면 1.3)


def cfg_w(*ws, curved=False):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(NO_COLS())
    cfg.widenings = list(ws)
    return cfg


def area(traps):
    return sum((s1 - s0) * ((o0 - i0) + (o1 - i1)) / 2.0 for s0, s1, i0, o0, i1, o1 in traps)


def vol(engine_items):
    return sum(x.net_volume for x in engine_items)


def walls(eng, level):
    return {w.name: w for pk in eng.walls.wall_packages if pk.level == level for w in pk.walls}


# ===================================================== 형상
@pytest.mark.parametrize("taper, expect", [
    (None, 198 - 4 + 2 * 2 * math.sqrt(2)),          # 45°: 벽 중심선 길이 × 두께 (사선 벽도 같은 두께)
    (0.0, 202.0),                                    # 직각 계단: 계단 벽 2개(1 × 3)
    (3.0, 198 - 6 + 2 * math.hypot(3, 2)),
])
def test_side_wall_traps_constant_thickness(taper, expect):
    cfg = cfg_w(WidenSpec(side=1, s_start=50, s_end=80, amount=2.0, taper_in=taper, taper_out=taper))
    tr = side_wall_traps(cfg, 1, 1)
    assert area(tr) == pytest.approx(expect, rel=1e-9)
    assert all(i0 <= o0 and i1 <= o1 for _, _, i0, o0, i1, o1 in tr)
    mid = next(t for t in tr if t[0] <= 65 <= t[1])
    assert mid[2:] == pytest.approx((11.0, 12.0, 11.0, 12.0))


@pytest.mark.parametrize("taper, extra", [(None, 2 * 30 + 2 * 2), (0.0, 2 * 30), (3.0, 2 * 30 + 2 * 3)])
def test_wall_thickening_keeps_inner_face(taper, extra):
    """벽체 두께 증가: 내공면 |t| = 9 그대로, 바깥면만 10 → 12 (전이부는 바깥면만 사선)"""
    cfg = cfg_w(WidenSpec(side=1, kind="wall", s_start=50, s_end=80, amount=2.0, taper_in=taper, taper_out=taper))
    tr = side_wall_traps(cfg, 1, 1)
    assert area(tr) == pytest.approx(198 + extra, rel=1e-9)
    assert all(i0 == pytest.approx(9.0) and i1 == pytest.approx(9.0) for _, _, i0, _, i1, _ in tr)
    assert next(t for t in tr if t[0] <= 65 <= t[1])[2:] == pytest.approx((9.0, 12.0, 9.0, 12.0))


def test_wall_thickening_only_changes_outline():
    """벽체 두께 증가(최하층 −t, 종점까지): 바닥 슬래브·단부 벽만 넓어지고 중간 슬래브·승강장은 그대로.
    위층(B2F) +t 두께 증가는 사이 슬래브가 받침"""
    cfg = cfg_w(WidenSpec(side=-1, kind="wall", floors=[1], s_start=150, s_end=None, amount=1.5, taper_in=0.0),
                WidenSpec(side=1, kind="wall", floors=[2], s_start=50, s_end=80, amount=2.0, taper_in=0.0, taper_out=0.0))
    base = StationCADEngine(make_cfg(NO_COLS()))
    eng = StationCADEngine(cfg)
    slabs = {sl.name: sl for pk in eng.slabs.slab_packages for sl in pk.slabs}
    bslabs = {sl.name: sl for pk in base.slabs.slab_packages for sl in pk.slabs}
    assert slabs["SLAB_B3F_FLOOR"].net_volume == pytest.approx(bslabs["SLAB_B3F_FLOOR"].net_volume + 1.5 * (48 + 1.0) * 1.2)
    assert slabs["SLAB_B2F_MID"].net_volume == pytest.approx(bslabs["SLAB_B2F_MID"].net_volume + 2.0 * 30 * 0.4)
    assert slabs["SLAB_B1F_MID"].net_volume == pytest.approx(bslabs["SLAB_B1F_MID"].net_volume)
    plats = {p.name: p.net_volume for pk in eng.platform.platform_packages for p in pk.platforms}
    assert plats == pytest.approx({p.name: p.net_volume for pk in base.platform.platform_packages for p in pk.platforms})
    w, b = walls(eng, "B3F"), walls(base, "B3F")
    assert w["WALL_B3F_L"].net_volume == pytest.approx((198 + 1.5 * 48) * 6.0)
    assert w["WALL_B3F_END"].net_volume == pytest.approx(b["WALL_B3F_END"].net_volume * (20 + 1.5) / 20, rel=1e-6)
    assert walls(eng, "B2F")["WALL_B2F_R"].net_volume == pytest.approx((198 + 60) * 6.0)


def test_walls_floor_selection_and_end_walls():
    cfg = cfg_w(WidenSpec(side=1, floors=[2], s_start=50, s_end=80, amount=2.0),
                WidenSpec(side=-1, s_start=150, s_end=None, amount=1.5, taper_in=3))
    base = StationCADEngine(make_cfg(NO_COLS()))
    eng = StationCADEngine(cfg)
    for level, n, h in (("B3F", 1, 6.0), ("B2F", 2, 6.0), ("B1F", 3, 5.6)):            # 벽 높이 = 층 FL ~ 위층 FL (최상층은 천장 하면)
        w, b = walls(eng, level), walls(base, level)
        r_area = area(side_wall_traps(cfg, n, 1)) if n == 2 else 198.0                       # +t 쪽은 B2F 만
        assert w[f"WALL_{level}_R"].net_volume == pytest.approx(r_area * h, rel=1e-9)
        assert w[f"WALL_{level}_L"].net_volume == pytest.approx(area(side_wall_traps(cfg, n, -1)) * h, rel=1e-9)
        assert w[f"WALL_{level}_START"].net_volume == pytest.approx(b[f"WALL_{level}_START"].net_volume)
        assert w[f"WALL_{level}_END"].net_volume == pytest.approx(b[f"WALL_{level}_END"].net_volume * (20 + 1.5) / 20, rel=1e-6)
    assert walls(eng, "B3F")["WALL_B3F_R"].pieces == [] and len(walls(eng, "B2F")["WALL_B2F_R"].pieces) == 9


def test_slab_and_platform_areas():
    cfg = cfg_w(WidenSpec(side=-1, floors=[1], s_start=150, s_end=None, amount=1.5, taper_in=3.0))
    base = StationCADEngine(make_cfg(NO_COLS()))
    eng = StationCADEngine(cfg)
    slabs = {sl.name: sl for pk in eng.slabs.slab_packages for sl in pk.slabs}
    bslabs = {sl.name: sl for pk in base.slabs.slab_packages for sl in pk.slabs}
    pocket = 1.5 * 48 + 1.5 * 3 / 2                                     # 최하층 −t 포켓 내공 면적
    assert slabs["SLAB_B2F_MID"].net_volume == pytest.approx(bslabs["SLAB_B2F_MID"].net_volume + pocket * 0.4)   # 포켓 천장
    assert slabs["SLAB_B1F_MID"].net_volume == pytest.approx(bslabs["SLAB_B1F_MID"].net_volume)                 # 위층은 그대로
    assert slabs["SLAB_B1F_ROOF"].net_volume == pytest.approx(bslabs["SLAB_B1F_ROOF"].net_volume)
    assert slabs["SLAB_B3F_FLOOR"].net_volume > bslabs["SLAB_B3F_FLOOR"].net_volume
    plats = {p.name: p for pk in eng.platform.platform_packages for p in pk.platforms}
    assert plats["PLAT_B3F_L"].net_volume == pytest.approx(198 * 5.1 * 0.2 + pocket * 0.2)
    assert plats["PLAT_B3F_R"].net_volume == pytest.approx(198 * 5.1 * 0.2)


def test_upper_floor_widening_supported_by_mid_slab():
    """위층만 넓어지면 사이 슬래브가 아래층 바깥면 ~ 위층 바깥면까지 넓어져 위층 확폭 벽을 받침"""
    cfg = cfg_w(WidenSpec(side=1, floors=[2], s_start=50, s_end=80, amount=2.0, taper_in=0.0, taper_out=0.0))
    eng = StationCADEngine(cfg)
    mid = next(sl for pk in eng.slabs.slab_packages for sl in pk.slabs if sl.name == "SLAB_B2F_MID")
    extra = [m for m in mid.pieces if PM.t_range(m)[0] >= 10.0 - 1e-9]
    assert extra and sum(m.shape.length * m.shape.width for m in extra) == pytest.approx(2.0 * 32.0)   # [10, 12] × (49 ~ 81)


@pytest.mark.parametrize("curved, kind", [(False, "clear"), (True, "clear"), (False, "wall"), (True, "wall")])
def test_volumes_mesh_and_ifc_agree(tmp_path, curved, kind):
    a = 60.0
    cfg = cfg_w(WidenSpec(side=1, floors=[1, 2], s_start=a, s_end=a + 30, amount=2.0, kind=kind),
                WidenSpec(side=-1, s_start=150, s_end=None, amount=1.5, taper_in=3.0),
                WidenSpec(side=-1, kind="wall", floors=[2, 3], s_start=20, s_end=40, amount=1.0), curved=curved)
    eng = StationCADEngine(cfg)
    eng.build_3d_doc()
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "w.ifc"))
    by = {e.Name: e for e in f.by_type("IfcElement") if e.Name}
    tol = 1e-4 if curved else 1e-7
    objs = [w for pk in eng.walls.wall_packages for w in pk.walls] + [s for pk in eng.slabs.slab_packages for s in pk.slabs] \
        + [p for pk in eng.platform.platform_packages for p in pk.platforms]
    for o in objs:
        quads = [q for m in o.members for q in PM.sweep_quads(PM.rings(eng.cfg, m))]
        assert PM.mesh_volume(quads) == pytest.approx(o.net_volume, rel=tol), o.name
        fs = [tuple(tuple(p) for p in (e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx2, e.dxf.vtx3)) for e in o.source_element]
        assert PM.mesh_volume([f_[:3] if f_[3] == f_[2] else f_ for f_ in fs]) == pytest.approx(o.net_volume, rel=tol), o.name
        assert ifc_world_volume(by[o.name]) == pytest.approx(o.net_volume, rel=tol), o.name


def test_drawings_follow_widening():
    cfg = cfg_w(WidenSpec(side=1, s_start=50, s_end=80, amount=2.0))
    eng = StationCADEngine(cfg)
    sec = eng.walls.section_items(65.0)
    assert any(it.u0 == pytest.approx(11.0) and it.u1 == pytest.approx(12.0) for it in sec)
    sec_s = eng.slabs.section_items(65.0)
    assert max(it.u1 for it in sec_s) == pytest.approx(12.0)                    # 바닥·천장 슬래브 = 넓어진 바깥면
    plan = eng.walls.plan_items(2.0, floor=1)
    assert any(len(it.pts) == 4 and abs(it.pts[1][1] - it.pts[0][1]) > 0.1 for it in plan)   # 사선 전이 조각
    eng.build_plan_doc(floors=[1], cut_h=2.0)
    eng.build_section_doc([65.0])
    eng.build_profile_doc([0.0, 10.0])


# ===================================================== 검증
@pytest.mark.parametrize("w, msg", [
    (WidenSpec(side=0, s_start=50, s_end=80), "쪽"),
    (WidenSpec(side=1, s_start=50, s_end=80, amount=0.0), "확폭량"),
    (WidenSpec(side=1, s_start=80, s_end=50), "뒤여야"),
    (WidenSpec(side=1, s_start=1, s_end=50, amount=2.0), "시점"),
    (WidenSpec(side=1, s_start=150, s_end=197, amount=2.0), "종점"),
    (WidenSpec(side=1, floors=[4], s_start=50, s_end=80), "층 번호"),
    (WidenSpec(side=1, s_start=50, s_end=80, taper_in=-1.0), "전이 길이"),
    (WidenSpec(side=1, s_start=50, s_end=80, kind="x"), "종류"),
])
def test_invalid(w, msg):
    with pytest.raises(ValueError, match=msg):
        cfg_w(w).validate()


def test_overlap_and_opening_on_taper_rejected():
    with pytest.raises(ValueError, match="겹칩니다"):
        cfg_w(WidenSpec(side=1, s_start=50, s_end=80), WidenSpec(side=1, s_start=81, s_end=100)).validate()
    with pytest.raises(ValueError, match="겹칩니다"):                    # 종류가 달라도 같은 층·쪽은 겹치면 안 됨
        cfg_w(WidenSpec(side=1, s_start=50, s_end=80), WidenSpec(side=1, kind="wall", s_start=70, s_end=100)).validate()
    from openings.opening_kind import OpeningKind
    from openings.opening_spec import OpeningSpec
    cfg = cfg_w(WidenSpec(side=1, floors=[1], s_start=50, s_end=80, amount=2.0))
    cfg.openings = [OpeningSpec(kind=OpeningKind.STAIR, slabs={1}, s_start=47.0, length=3.0, t_center=8.0, width=1.0)]
    with pytest.raises(ValueError, match="사선 전이부"):
        StationCADEngine(cfg)


def test_no_widening_outputs_unchanged():
    base = StationCADEngine(make_cfg(NO_COLS()))
    assert all(w.pieces == [] for pk in base.walls.wall_packages for w in pk.walls)


# ===================================================== 입력 초안 · 프로젝트 파일
def test_draft_and_project():
    d = WidenDraft(side=SIDES[1], floors="B2F, 1", s_start="150", s_end="", amount="1.5", taper_in="3")
    sp = d.to_spec("확폭 1", 100.0, 3)
    assert (sp.side, sp.floors, sp.s_start, sp.s_end, sp.amount, sp.taper_in, sp.taper_out) == (-1, [1, 2], 50.0, None, 1.5, 3.0, None)
    assert sp.kind == "clear" and WidenDraft(kind=KINDS[1]).to_spec("확폭 1", 0.0, 3).kind == "wall"
    with pytest.raises(ValueError, match="종류"):
        WidenDraft(kind="?").to_spec("확폭 1", 0.0, 3)
    with pytest.raises(ValueError, match="B9F"):
        WidenDraft(floors="B9F").to_spec("확폭 1", 0.0, 3)
    ds = WidenDrafts()
    ds.items.append(d)
    assert len(ds.to_specs(100.0, 3)) == 1
    st = ProjectState()
    st.widen_drafts = [d]
    assert ProjectState.from_dict(st.to_dict()).widen_drafts == [d]
