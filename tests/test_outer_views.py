"""평면도 · 본체 종단면도의 본체 밖 구조물 (출입구 · 외부 엘리베이터 · 환기구 지상부 · 출구통로 투영) 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import numpy as np
import pytest

from config.output_config import OutputOptions
from elevators.ext_ev import ExtEvSpec
from engine import outer_views as OV
from engine.cad_engine import StationCADEngine
from gui.print_draft import OUTER_LABELS, PrintDraft
from helper.strip_member import part_faces
from test_entrances import FORE, cfg_with
from test_patch import make_cfg, user_example


def engine(curved=False, evs=True, **kw):
    cfg = cfg_with({**FORE, "canopy": True, **kw}, curved=curved)
    if evs:
        cfg.ext_evs = [ExtEvSpec(name="A", host="passage", along=6.0, low_finish="glass"),
                       ExtEvSpec(name="W", host="wall", floor=2, u=20.0, host_side=-1, ground_el=cfg.entrances[0].ground_el)]
    return StationCADEngine(cfg)


def names(items):
    return {i.name for i in items}


# ===================================================== 조각 도우미
def box_faces(x0, x1, y0, y1, zb0, zb1, zt0, zt1):
    """u = x 로 아래·위가 기운 상자"""
    p = [(x0, y0, zb0), (x1, y0, zb1), (x1, y1, zb1), (x0, y1, zb0), (x0, y0, zt0), (x1, y0, zt1), (x1, y1, zt1), (x0, y1, zt0)]
    return [(p[3], p[2], p[1], p[0]), tuple(p[4:]), (p[0], p[1], p[5], p[4]), (p[1], p[2], p[6], p[5]), (p[2], p[3], p[7], p[6]), (p[3], p[0], p[4], p[7])]


def test_level_polygon_of_sloped_solid():
    f = box_faces(100000.0, 100010.0, 200000.0, 200002.0, 0.0, 5.0, 1.0, 6.0)           # 1:2 경사, 연직 두께 1
    sec = OV.level_polygon(f, 3.0)                                                      # 하면 3 → x = 6, 상면 3 → x = 4
    assert OV._area(sec) == pytest.approx(2.0 * 2.0, abs=1e-6)
    assert sorted({round(p[0] - 100000.0, 6) for p in sec}) == [4.0, 6.0]
    assert OV.level_polygon(f, 6.5) is None
    band = OV._slab_polygon(f, 2.0, 3.0)                                                # 2 ~ 3 높이 부분을 위에서
    assert sorted({round(p[0] - 100000.0, 6) for p in band})[0] == 2.0 and max(p[0] for p in band) - 100000.0 == pytest.approx(6.0)


def test_touching_pieces_are_merged_but_treads_are_not():
    a = [OV.Solid("W", "L", box_faces(i, i + 1, 0, 1, 0, 0, 2, 2)) for i in range(4)]
    assert len(OV._cut_solids(a, None, 1.0)) == 1                                       # 절단 하나 (아래 윤곽은 같은 모양이라 생략)
    b = [OV.Solid("T", "L", box_faces(i, i + 1, 0, 1, 0, 0, 1, 1), section=False, merge=False) for i in range(4)]
    assert len(OV._cut_solids(b, None, 2.0)) == 4
    gap = [OV.Solid("W", "L", box_faces(i * 2, i * 2 + 1, 0, 1, 0, 0, 2, 2)) for i in range(3)]
    assert len(OV._cut_solids(gap, None, 1.0)) == 3


# ===================================================== 평면도
def test_each_floor_shows_its_own_part():
    eng = engine()
    cfg = eng.cfg
    G = OV.ground_floor(cfg)
    by = {n: OV.plan_outer_items(eng, n, 2.0) for n in range(1, G + 1)}
    assert by[1] == [] or not any(i.name.startswith("EN1") for i in by[1])              # 통로(3층)보다 아래층에는 없음
    assert not any(i.name.startswith(("EN1", "A_")) for i in by[2])
    assert any(i.name.startswith("W_RC_WALL") for i in by[2])                            # 2층 본체 측벽 EV
    assert {"EN1_WALL_L", "EN1_WALL_R"} <= {n for n in names(by[3]) if n.startswith("EN1_WALL")} or \
        any(n.startswith("EN1_WALL_L") for n in names(by[3]))
    assert any(i.layer == "PLAN_STAIR" for i in by[3]) and any(i.layer == "PLAN_ESCALATOR" for i in by[3])
    assert any(n.startswith("A_LGLASS") for n in names(by[3])) and not any(n.startswith("A_GLASS") for n in names(by[3]))
    g = names(by[G])
    assert any(n.startswith("A_GLASS") for n in g) and {"A_RAMP", "A_PODIUM", "W_RAMP"} <= g   # 지상: 유리 박스·기단·경사로
    assert any(n.startswith("EN1_CP_") for n in g) and not any(n.startswith("EN1_CP_") for n in names(by[3]))
    labels = [i.label[0] for i in by[G] if i.label]
    assert sorted(labels) == ["A EV", "EN1 ENTRANCE", "W EV"]


def test_steps_are_split_between_floors_without_loss():
    eng = engine()
    (ent,) = eng.entrances.entrances
    G = OV.ground_floor(eng.cfg)
    seen = {}
    for n in range(1, G + 1):
        for nm in names(OV.plan_outer_items(eng, n, 2.0)):
            seen.setdefault(nm, set()).add(n)
    for s in (s for e in ent.escalators for s in e.steps):
        assert s.name in seen and seen[s.name] <= {3, G}                                  # 모든 스텝이 3층 또는 지상 평면에


def test_shaft_section_area_is_exact():
    """EV RC 승강로 수평 단면 넓이 = 외곽 − 내공 (본체 위 높이: 네 면 모두 자기 벽)"""
    eng = engine()
    x = next(v for v in eng.ext_evs.ext_evs if v.name == "W")
    sp = x.layout.spec
    U0, U1, T0, T1 = x.layout.outer
    z = x.stops[2] - 0.5
    walls = [so for so in OV.ext_ev_solids(x) if "RC_WALL" in so.name]
    area = sum(OV._area(OV.level_polygon(so.faces, z)) for so in walls if so.z0 < z < so.z1)
    w = sp.wall_t
    assert area == pytest.approx((U1 - U0) * (T1 - T0) - (U1 - U0 - 2 * w) * (T1 - T0 - 2 * w), rel=1e-6)


def test_canopy_posts_are_cut_at_ground_level():
    eng = engine()
    (ent,) = eng.entrances.entrances
    posts = [c for c in ent.canopy if c.kind == "CP_POST"]
    its = [i for i in OV.plan_outer_items(eng, OV.ground_floor(eng.cfg), 2.0) if "_CP_POST" in i.name]
    assert len({i.name for i in its}) == len(posts)
    assert OV._area(its[0].pts) == pytest.approx(ent.layout.spec.cp_post ** 2, rel=1e-6)


def test_plan_doc_ground_floor_and_coordinates(tmp_path):
    eng = engine()
    G = OV.ground_floor(eng.cfg)
    doc = eng.build_plan_doc(floors=[3, G], cut_h=2.0)
    txt = [e.dxf.text for e in doc.modelspace().query("TEXT")]
    assert any("GROUND" in t and "GL+2.0" in t for t in txt) and any("B1F" in t for t in txt)
    assert len(doc.modelspace().query('LWPOLYLINE[layer=="PLAN_BEYOND"]')) > 0                  # 본체 외곽·캐노피
    with pytest.raises(ValueError, match="범위"):
        eng.build_plan_doc(floors=[G + 1])
    world = OV.plan_outer_items(eng, G, 2.0)
    local = OV.to_plan_coords(eng.cfg, world, False)                                           # 전개 평면 = (s, t)
    for a, b in zip(world[:40], local[:40]):
        assert eng.cfg.to_world(*b.pts[0]) == pytest.approx(a.pts[0], abs=1e-6)
    assert OV.to_plan_coords(eng.cfg, world, True) is world


def test_no_outer_structures_keeps_previous_plan():
    eng = StationCADEngine(make_cfg(user_example()))
    assert not OV.has_ground(eng.cfg) and OV.plan_outer_items(eng, 1, 2.0) == [] and OV.profile_outer_items(eng) == []
    with pytest.raises(ValueError, match="범위"):
        eng.build_plan_doc(floors=[OV.ground_floor(eng.cfg)])


def test_vent_grill_in_ground_plan():
    from test_vents import ground_cfg
    cfg, _ = ground_cfg([(50, 10, None), (50, 30, 0), (50, 30, None)], protrusion=0.0)
    eng = StationCADEngine(cfg)
    assert OV.has_ground(cfg)
    its = OV.plan_outer_items(eng, OV.ground_floor(cfg), 2.0)
    assert any("GRILL" in i.name for i in its) and all(i.layer == "PLAN_VENT" for i in its)


@pytest.mark.parametrize("curved", [False, True])
def test_body_outline(curved):
    eng = engine(curved=curved, evs=False)
    (it,) = OV.body_outline_items(eng.cfg)
    st = eng.cfg.station
    w = st.wall_t_at(st.floors)
    ss, ts = [p[0] for p in it.pts], [p[1] for p in it.pts]
    assert (min(ss), max(ss)) == pytest.approx((-w, st.length + w)) and (min(ts), max(ts)) == pytest.approx((-st.width / 2 - w, st.width / 2 + w))
    if curved:
        assert len(it.pts) > 20                                                                # 곡선은 표본 측점마다
        eng.build_plan_doc(floors=[OV.ground_floor(eng.cfg)], cut_h=2.0)


# ===================================================== 종단면도
@pytest.mark.parametrize("curved", [False, True])
def test_profile_projection_matches_to_station(curved):
    eng = engine(curved=curved, evs=False)
    (ent,) = eng.entrances.entrances
    its = [i for i in OV.profile_outer_items(eng) if i.name.startswith("EN1_WALL_L")]
    el = next(e for e in ent.elements if e.name == its[0].name)
    pts = [p for fs in part_faces(ent.frame, el) for f in fs for p in f]
    ss = [eng.cfg.to_station(p[0], p[1])[0] for p in pts]
    u = [p[0] for i in its if i.name == el.name for p in i.pts]
    assert (min(u), max(u)) == pytest.approx((min(ss), max(ss)), abs=5e-3)
    z = [p[1] for i in its if i.name == el.name for p in i.pts]
    assert (min(z), max(z)) == pytest.approx((min(p[2] for p in pts), max(p[2] for p in pts)), abs=1e-6)


def test_profile_side_options():
    eng = engine()
    f = lambda s: {i.label[0] for i in OV.profile_outer_items(eng, s) if i.label}
    assert f("both") == {"EX1 EXIT (L)", "EN1 ENTRANCE (L)", "A EV (L)", "W EV (R)"}
    assert f("left") == {"EX1 EXIT (L)", "EN1 ENTRANCE (L)", "A EV (L)"} and f("right") == {"W EV (R)"} and f("none") == set()
    with pytest.raises(ValueError, match="투영"):
        OV.profile_outer_items(eng, "up")


def test_profile_doc_stacks_axes_without_overlap(tmp_path):
    eng = engine()
    base = eng.build_profile_doc([0.0], "none")
    doc = eng.build_profile_doc([0.0, 2.2], "both")
    q = lambda d: [e for e in d.modelspace().query('LWPOLYLINE[layer=="PROF_OUTER"]')]
    assert q(base) == [] and len(q(doc)) == 2 * len(OV.profile_outer_items(eng))
    zs = np.array([[p[1] for p in e.get_points()][0] for e in q(doc)])
    half = len(zs) // 2
    assert zs[:half].min() > zs[half:].max()                                                   # 첫 축 그림 전체가 둘째 축 위
    one = eng.build_profile_doc([0.0], "right")
    assert 0 < len(q(one)) < len(q(doc))


def test_path_profile_is_unchanged():
    from engine.path_profile import passage_profile_items
    eng = engine()
    its = passage_profile_items(eng, "EX1", 0.0)
    assert any(i.name.startswith("EN1") for i in its) and any(i.name.startswith("A_") for i in its)
    assert not any(i.layer == "PROF_OUTER" for i in its)


# ===================================================== 출력 옵션
def test_output_options_ground_and_outer(tmp_path):
    from engine.bim_engine import BIMEngine
    eng = engine(evs=False)
    cfg = eng.cfg
    G = OV.ground_floor(cfg)
    assert OutputOptions().floors(cfg) == [1, 2, 3, G] and OutputOptions(plan_ground=False).floors(cfg) == [1, 2, 3]
    assert OutputOptions(plan_floors=[2]).floors(cfg) == [2, G]
    plain = StationCADEngine(make_cfg(user_example())).cfg
    assert OutputOptions().floors(plain) == [1, 2, 3]
    with pytest.raises(ValueError, match="투영"):
        OutputOptions(profile_outer="x").validate(cfg)
    paths = BIMEngine.build(cfg, tmp_path, OutputOptions(dxf3d=False, ifc=False, section=False, plan_floors=[3], profile_outer="none"))
    plan = next(p for p in paths if "평면도" in p)
    txt = [e.dxf.text for e in ezdxf.readfile(plan).modelspace().query("TEXT")]
    assert any("GROUND" in t for t in txt)
    prof = next(p for p in paths if "종단면도" in p)
    assert len(ezdxf.readfile(prof).modelspace().query('LWPOLYLINE[layer=="PROF_OUTER"]')) == 0


def test_print_draft_options():
    d = PrintDraft(plan_ground=False, profile_outer="오른쪽 (−t)")
    o = d.to_options(4.4)
    assert (o.plan_ground, o.profile_outer) == (False, "right") and PrintDraft().to_options(4.4).profile_outer == "both"
    assert set(OUTER_LABELS.values()) == set(OV.OUTERS)
