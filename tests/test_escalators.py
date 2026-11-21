"""에스컬레이터 (트러스 외형 + 스텝 + 난간 패널 + 핸드레일, 위층 오프닝·하부 피트 자동) 테스트"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import pytest

from engine.cad_engine import StationCADEngine
from escalators.escalator_spec import HANDRAIL_H, STEP_PLATE_T, EscalatorSpec
from escalators.escalator_type import EscalatorPartKind as K
from helper import prism_member as PM
from helper.strip_member import part_faces
from openings.opening_kind import OpeningKind
from openings.opening_spec import OpeningSpec
from stairs.stair_spec import StairSpec
from test_curved import NO_COLS, curved_cfg
from test_patch import _q, make_cfg, user_example

PLAT = dict(t_center=6.5)            # 우측 승강장(t 3.9 ~ 9.0, 지지벽체 3.9~4.2 / 8.7~9.0) 안, 트러스 5.7 ~ 7.3
MID = dict(t_center=-6.0)            # 2층: 좌측, 원기둥(t=±3) 과 떨어짐


def esc(lower=1, s=40.0, d=1, name="", **kw):
    kw = {**(PLAT if lower == 1 else MID), **kw}
    return EscalatorSpec(lower_floor=lower, s_wp=s, direction=d, name=name, **kw)


def cfg_with(*escs, curved=False, mid_t=1.2, stairs=(), openings=()):
    """2층 시작 에스컬레이터의 피트(1.15m)가 들어가도록 중간 슬래브를 1.2m 로 둔다"""
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(user_example())
    cfg.station.mid_t = mid_t
    cfg.escalators, cfg.stairs, cfg.openings = list(escs), list(stairs), list(openings)
    return cfg


def eng_with(*escs, **kw):
    return StationCADEngine(cfg_with(*escs, **kw))


def by_name(eng, name):
    return next(e for e in eng.escalators.all_escalators() if e.name == name)


def elev(cfg, s, z_rel):
    return cfg.lv(s) - cfg.station.offset + z_rel


def slab(eng, n):
    return next(x for pk in eng.slabs.slab_packages for x in pk.slabs if x.slab_no == n)


def nose_fn(cfg, lay):
    """테스트용 독립 스텝 코 선 (s 기준)"""
    st = cfg.station
    z_top = st.floor_level(lay.lower_floor + 1)
    e0 = elev(cfg, lay.s_at(0.0), lay.base_level)

    def nose(s):
        u = (s - lay.spec.s_wp) * lay.spec.direction
        if u <= 0:
            return elev(cfg, s, lay.base_level)
        if u >= lay.run:
            return elev(cfg, s, z_top)
        return e0 + u * lay.spec.tan
    return nose


# ===================================================== 배치 규약
def test_work_points_follow_angle_and_grade():
    cfg = cfg_with(esc(1, name="A"), esc(2, s=120.0, d=-1, name="B"))
    st = cfg.station
    assert abs(cfg.grade_permil(0.0)) > 10.0
    for lay in cfg.escalator_layouts():
        sp = lay.spec
        e0 = elev(cfg, lay.s_at(0.0), lay.base_level)
        e1 = elev(cfg, lay.s_at(lay.run), st.floor_level(lay.lower_floor + 1))    # 상부 WP = 경사선이 위층 바닥과 만나는 점
        assert lay.rise == pytest.approx(e1 - e0, abs=1e-9)
        assert lay.rise == pytest.approx(lay.run * math.tan(math.radians(sp.angle_deg)), abs=1e-9)
        assert lay.s_wp == pytest.approx((sp.s_wp, sp.s_wp + sp.direction * lay.run))
        assert lay.s_range == pytest.approx(tuple(sorted((lay.s_at(-sp.lower_ext), lay.s_at(lay.run + sp.upper_ext)))))
        assert lay.t_range == pytest.approx((sp.t_center - 0.8, sp.t_center + 0.8))
    a, b = cfg.escalator_layouts()
    assert a.on_platform and a.base_level == pytest.approx(cfg.platform.top_level)
    assert not b.on_platform and b.base_level == pytest.approx(st.floor_level(2))


def lay_nose(lay):
    """배치의 스텝 코 선 (곡선 전이부 포함)을 s 함수로"""
    return lambda s: lay.nose((s - lay.spec.s_wp) * lay.spec.direction)


def test_parts_and_their_vertical_rules():
    """트러스 하면 = 스텝 코 선 − 트러스 높이, 난간 패널 = 코 선 ~ 핸드레일 아래, 핸드레일 상면 = 코 선 + 핸드레일 높이.
    스텝은 개별 객체: 코가 코 선 위·디딤판 수평·코 간격 = 스텝 깊이(수평), 챌판 = 아래 스텝 디딤판 ~ 디딤판 하면"""
    from escalators.escalator_spec import STEP_RISER_T
    eng = eng_with(esc(1, name="A"), esc(2, s=120.0, d=-1, name="B"))
    cfg = eng.cfg
    for e, lay in zip(eng.escalators.all_escalators(), cfg.escalator_layouts()):
        sp, nose = lay.spec, lay_nose(lay)
        side_parts = ["CLAD_SIDE", "OUTER_PLATE", "SKIRT", "INNER_DECK", "BALUSTRADE", "OUTER_DECK", "HANDRAIL", "NEWEL_BASE",
                      "NEWEL_END_IN", "NEWEL_END_OUT"]
        assert {p.name for p in e.parts} == {f"{e.name}_{k}" for k in ("TRUSS", "CLAD_BOTTOM", "FLOOR_PLATE", "COMB")} | \
            {f"{e.name}_{k}_{x}" for x in "LR" for k in side_parts}
        for st in e.part(K.CLAD_BOTTOM).shape.strips:                    # 트러스 하면(아래 외장) = 코 선 − 트러스 높이
            assert st.zb0 == pytest.approx(nose(st.s0) - sp.truss_depth, abs=1e-9)
            assert st.zb1 == pytest.approx(nose(st.s1) - sp.truss_depth, abs=1e-9)
        steps = e.steps
        assert len(steps) > 20 and [x.index for x in steps] == list(range(len(steps)))
        for a_, b_ in zip(steps, steps[1:]):
            assert b_.chain_u - a_.chain_u == pytest.approx(sp.step_depth)
        for x in steps:
            u = x.chain_u
            tread = max(x.shape.strips, key=lambda q: q.s1 - q.s0)
            assert tread.zt == pytest.approx(lay.nose(u)) and tread.zt == pytest.approx(tread.zt_end)   # 수평, 코가 코 선 위
            assert tread.s1 - tread.s0 == pytest.approx(sp.step_depth)
            assert tread.zt - tread.zb0 == pytest.approx(STEP_PLATE_T)
            risers = [q for q in x.shape.strips if q is not tread]
            if x.index > 0 and lay.nose(u) - lay.nose(u - sp.step_depth) > STEP_PLATE_T + 1e-6:
                assert len(risers) == 1 and risers[0].s1 - risers[0].s0 == pytest.approx(STEP_RISER_T)
                assert risers[0].zb0 == pytest.approx(lay.nose(u - sp.step_depth))          # 아래 스텝 디딤판 높이
        # 평면: 스텝 폭, 난간·핸드레일은 스텝 밖, 모두 트러스 폭 안
        t0, t1 = e.t_range
        assert steps[0].t_range == pytest.approx((sp.t_center - 0.5, sp.t_center + 0.5))
        for p in e.parts:
            assert t0 - 1e-9 <= p.t_range[0] < p.t_range[1] <= t1 + 1e-9
        assert e.part(K.BALUSTRADE, 1).t_range[0] > sp.t_center + 0.5 and e.part(K.BALUSTRADE, -1).t_range[1] < sp.t_center - 0.5


def test_nose_line_transition_arcs():
    """곡선 전이부: 원호가 양쪽 직선에 접함(위치·기울기 연속), 반경 일정, 하부 오목·상부 볼록, 반경 0 이면 예전 꺾임"""
    import math
    eng = eng_with(esc(2, s=120.0, d=-1, name="B"))
    lay = eng.cfg.escalator_layouts()[0]
    n = lay.nose
    sp = lay.spec
    assert len(n.arcs) == 2
    for ua, ub, cx, cz, r, sign in n.arcs:
        assert r == pytest.approx(sp.lower_radius if sign < 0 else sp.upper_radius)
        for u in (ua, (ua + ub) / 2, ub):
            assert math.hypot(u - cx, n(u) - cz) == pytest.approx(r, abs=1e-9)
        h = 1e-6
        for u in (ua, ub):                                            # 접점에서 기울기 연속
            left = (n(u) - n(u - h)) / h
            right = (n(u + h) - n(u)) / h
            assert left == pytest.approx(right, abs=1e-3)
    mid = (n.arcs[0][1] + n.arcs[1][0]) / 2
    assert n(mid) == pytest.approx(n.e0 + mid * n.tan)                # 경사부는 직선
    flat = eng_with(esc(2, s=120.0, d=-1, name="B", lower_radius=0.0, upper_radius=0.0)).cfg.escalator_layouts()[0]
    assert flat.nose.arcs == [] and flat.nose(0.5) == pytest.approx(flat.nose.e0 + 0.5 * flat.nose.tan)


def test_steps_do_not_overlap_and_follow_animation_pose():
    """스텝끼리 겹치지 않음, 자세 함수(step_pose)로 u 를 옮겨도 같은 규칙 — 애니메이션용"""
    import itertools
    from escalators.escalator_geom import step_pieces, step_pose
    eng = eng_with(esc(1, name="A"))
    lay = eng.cfg.escalator_layouts()[0]
    boxes = [(x.index, *pc) for x in lay.steps for pc in x.pieces]
    for a_, b_ in itertools.combinations(boxes, 2):
        if a_[0] == b_[0]:
            continue
        assert not (min(a_[2], b_[2]) - max(a_[1], b_[1]) > 1e-9 and min(a_[4], b_[4]) - max(a_[3], b_[3]) > 1e-9)
    dep = lay.spec.step_depth
    shift = 0.13
    moved = []
    for x in lay.steps[1:-1]:
        z, rise = step_pose(lay.nose, x.u + shift, dep)
        assert z == pytest.approx(lay.nose(x.u + shift))
        moved += [(x.index, *pc) for pc in step_pieces(x.u + shift, z, rise, dep)]
    for a_, b_ in itertools.combinations(moved, 2):
        if a_[0] != b_[0]:
            assert not (min(a_[2], b_[2]) - max(a_[1], b_[1]) > 1e-9 and min(a_[4], b_[4]) - max(a_[3], b_[3]) > 1e-9)


def test_truss_ends_flush_with_floors_and_strips_contiguous():
    eng = eng_with(esc(1), esc(2, s=120.0, d=-1))
    cfg = eng.cfg
    for e, lay in zip(eng.escalators.all_escalators(), cfg.escalator_layouts()):
        for p in e.parts:
            if p.kind in (K.HANDRAIL, K.BALUSTRADE, K.FLOOR_PLATE, K.COMB, K.OUTER_PLATE, K.NEWEL_BASE,
                          K.NEWEL_END_IN, K.NEWEL_END_OUT):
                continue                                              # 뉴얼 띠 겹침 / 승강구 부재는 양끝에 따로 (별도 테스트)
            ss = p.shape.strips
            for a, b in zip(ss, ss[1:]):
                assert b.s0 == pytest.approx(a.s1)
        truss = e.part(K.TRUSS).shape.strips
        z_top = cfg.station.floor_level(lay.lower_floor + 1)
        lo_end, hi_end = (truss[0], truss[-1]) if e.direction > 0 else (truss[-1], truss[0])
        s_lo_end = lo_end.s0 if e.direction > 0 else lo_end.s1
        s_hi_end = hi_end.s1 if e.direction > 0 else hi_end.s0
        z_lo = lo_end.zt if e.direction > 0 else lo_end.zt_end
        z_hi = hi_end.zt_end if e.direction > 0 else hi_end.zt
        from escalators.escalator_spec import LANDING_PLATE_T
        assert z_lo == pytest.approx(elev(cfg, s_lo_end, lay.base_level) - LANDING_PLATE_T, abs=1e-9)   # 승강구 바닥판 아래
        assert z_hi == pytest.approx(elev(cfg, s_hi_end, z_top) - LANDING_PLATE_T, abs=1e-9)


# ===================================================== 자동 오프닝 / 피트
def test_upper_opening_covers_truss_through_slab_and_headroom():
    eng = eng_with(esc(1, name="A"), esc(2, s=120.0, d=-1, name="B"))
    cfg = eng.cfg
    st = cfg.station
    for e, lay in zip(eng.escalators.all_escalators(), cfg.escalator_layouts()):
        sl = slab(eng, e.lower_floor)
        (o,) = [o for o in sl.openings if o.name == f"OPEN_{e.name}_{sl.name}"]
        assert o.kind is OpeningKind.ESCALATOR and o.t_range == pytest.approx(e.t_range)
        far = e.s_range[1] if e.direction > 0 else e.s_range[0]
        assert far == pytest.approx(o.s_range[1] if e.direction > 0 else o.s_range[0])   # 트러스 상단 끝까지
        nose = nose_fn(cfg, lay)
        z_sb = st.floor_level(e.lower_floor + 1) - st.mid_t
        start = o.s_range[0] if e.direction > 0 else o.s_range[1]
        before = start - e.direction * 0.05                     # 오프닝 바로 앞: 머리 높이 확보, 트러스가 슬래브에 닿지 않음
        assert elev(cfg, before, z_sb) - nose(before) >= lay.spec.headroom - 1e-6
        tr = next(x for x in e.part(K.TRUSS).shape.strips if x.s0 - 1e-9 <= before <= x.s1 + 1e-9)
        assert tr.zt_at(before) <= elev(cfg, before, z_sb) + 1e-6


def test_lower_pit_in_floor_slab():
    eng = eng_with(esc(2, s=120.0, d=-1, name="B"))
    cfg = eng.cfg
    e, lay = by_name(eng, "B"), cfg.escalator_layouts()[0]
    base = slab(eng, 1)                                         # B2F 가 서 있는 슬래브 = 1번 중간 슬래브
    (pit,) = [o for o in base.openings if o.name == f"OPEN_B_PIT_{base.name}"]
    low_end = e.s_range[1]                                      # 시점 방향으로 오름 → 하단 끝은 s 큰 쪽
    assert pit.s_range[1] == pytest.approx(low_end) and pit.t_range == pytest.approx(e.t_range)
    nose = nose_fn(cfg, lay)
    edge = pit.s_range[0]                                       # 피트 끝: 트러스 하면이 바닥면으로 올라옴
    assert nose(edge) - lay.spec.truss_depth == pytest.approx(elev(cfg, edge, lay.base_level), abs=1e-6)
    for x in e.part(K.TRUSS).shape.strips:                                 # 피트 바닥이 슬래브 하면 위 (트러스 1.15 ≤ 슬래브 1.2)
        assert x.zb0 >= PM.z_at(cfg, base, x.s0) - 1e-6 and x.zb1 >= PM.z_at(cfg, base, x.s1) - 1e-6


def test_pit_deeper_than_slab_rejected():
    with pytest.raises(ValueError, match="피트 깊이"):
        StationCADEngine(cfg_with(esc(2, s=120.0, d=-1), mid_t=0.4))


def test_platform_escalator_cuts_platform_slab():
    base = StationCADEngine(make_cfg(user_example()))
    eng = eng_with(esc(1, name="A"))
    cfg = eng.cfg
    e = by_name(eng, "A")
    plats = [pl for pk in eng.platform.platform_packages for pl in pk.platforms if pl.openings]
    assert len(plats) == 1
    pl = plats[0]
    (hole,) = pl.openings
    assert hole.name == f"OPEN_A_PIT_{pl.name}" and hole.t_range == pytest.approx(e.t_range)
    assert hole.s_range[0] == pytest.approx(e.s_range[0])
    assert len(pl.pieces) == 4
    ref = next(x for pk in base.platform.platform_packages for x in pk.platforms if x.name == pl.name)
    assert pl.net_volume == pytest.approx(ref.net_volume - hole.shape.volume)
    assert all(not s.openings for s in (slab(eng, 0),))                    # 바닥 슬래브는 그대로
    for x in e.part(K.TRUSS).shape.strips:                                 # 피트 바닥이 바닥 슬래브(FL) 위 = 승강장 아래 공간 안
        assert x.zb0 >= elev(cfg, x.s0, 0.0) - 1e-6 and x.zb1 >= elev(cfg, x.s1, 0.0) - 1e-6


def test_platform_pit_on_support_wall_rejected():
    with pytest.raises(ValueError, match="지지벽체"):
        StationCADEngine(cfg_with(esc(1, t_center=4.8)))                   # 트러스 4.0 ~ 5.6 이 선로측 지지벽체(3.9~4.2)와 겹침


# ===================================================== 검증
@pytest.mark.parametrize("sp,msg", [
    (esc(0), "범위"),
    (esc(3), "범위"),
    (esc(1, d=2), "오르는 방향"),
    (esc(1, angle_deg=70.0), "경사각"),
    (esc(1, truss_depth=0.0), "트러스 높이"),
    (esc(1, truss_depth=0.3), "스텝 층"),
    (esc(1, truss_width=1.0), "트러스 외폭"),
    (esc(1, lower_flat_steps=-1), "평탄 스텝"),
    (esc(1, lower_flat_steps=10), "하부 연장"),
    (esc(1, upper_flat_steps=8), "상부 연장"),
    (esc(2, t_center=-8.5), "내공 폭"),
    (esc(2, s=-1.0), "내공 길이"),
    (esc(2, s=190.0), "내공 길이"),
    (esc(1, t_center=4.0), "걸쳐"),
])
def test_invalid_escalator_rejected(sp, msg):
    with pytest.raises(ValueError, match=msg):
        StationCADEngine(cfg_with(sp))


def test_interference_rejected():
    with pytest.raises(ValueError, match="겹칩니다"):                    # 위층 자동 오프닝끼리 먼저 겹침
        StationCADEngine(cfg_with(esc(2, s=120.0, d=-1), esc(2, s=125.0, d=-1)))
    with pytest.raises(ValueError, match="계단 S .* 겹칩니다"):
        StationCADEngine(cfg_with(esc(2, s=120.0, d=-1),
                                  stairs=[StairSpec(lower_floor=2, s_start=112.0, t_center=-6.0, width=2.0, name="S")]))
    with pytest.raises(ValueError, match="이름이 중복"):
        StationCADEngine(cfg_with(esc(1, name="X"), esc(2, s=120.0, d=-1, name="X")))
    man = OpeningSpec(OpeningKind.VENT, 112.0, 1.0, -6.0, 1.0, [1], name="V")        # B2F 에스컬레이터가 서 있는 슬래브
    with pytest.raises(ValueError, match="오프닝 V 위|겹칩니다"):
        StationCADEngine(cfg_with(esc(2, s=120.0, d=-1), openings=[man]))
    # 계단(B2F)이 에스컬레이터(B3F→B2F 가 아닌, B2F 시작) 피트가 뚫린 슬래브 위에 놓임
    with pytest.raises(ValueError, match="피트 오프닝 위|겹칩니다"):
        StationCADEngine(cfg_with(esc(2, s=120.0, d=-1, name="E"),
                                  stairs=[StairSpec(lower_floor=2, s_start=121.0, t_center=-6.0, width=2.0)]))


def test_escalator_on_columns_rejected():
    with pytest.raises(ValueError, match="B2F 기둥"):
        StationCADEngine(cfg_with(esc(2, s=120.0, d=-1, t_center=-3.0)))


# ===================================================== 체적 교차 검증 (공식 ↔ 3D 메쉬 ↔ IFC)
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("curved", [False, True])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, curved):
    eng = eng_with(esc(1, s=40.0), esc(2, s=150.0, d=-1), curved=curved)
    cfg = eng.cfg
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "e.ifc"))
    els = {e.Name: e for e in f.by_type("IfcBuildingElementPart") + f.by_type("IfcRailing") + f.by_type("IfcCovering")}
    for e in eng.escalators.all_escalators():
        for p in e.parts:
            mesh = sum(PM.mesh_volume(q) for q in part_faces(cfg, p))
            assert mesh == pytest.approx(p.shape.volume, rel=1e-4 if curved else 1e-7, abs=1e-8)
            assert ifc_world_volume(els[p.name]) == pytest.approx(p.shape.volume, rel=1e-4)
    # 승강장 슬래브(피트 구멍)도 순 체적으로 내보내짐
    pl = next(x for pk in eng.platform.platform_packages for x in pk.platforms if x.openings)
    ifc_pl = next(x for x in f.by_type("IfcSlab") if x.Name == pl.name)
    assert ifc_world_volume(ifc_pl) == pytest.approx(pl.net_volume, rel=1e-4)


# ===================================================== IFC 구조
def test_ifc_transport_element_aggregates_parts(tmp_path):
    eng = eng_with(esc(1, name="A"), esc(2, s=120.0, d=-1, name="B"))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "e.ifc"))
    escs = {e.Name: e for e in f.by_type("IfcTransportElement")}
    assert set(escs) == {"A", "B"} and all(e.PredefinedType == "ESCALATOR" for e in escs.values())
    for name, level in (("A", "B3F"), ("B", "B2F")):
        el = escs[name]
        assert ifcopenshell.util.element.get_container(el).Name == level
        parts = {p.Name: p for p in ifcopenshell.util.element.get_decomposition(el)}
        e = by_name(eng, name)
        assert set(parts) == {p.name for p in e.parts} | {x.name for x in e.steps}
        assert parts[f"{name}_TRUSS"].is_a("IfcBuildingElementPart") and parts[f"{name}_TRUSS"].ObjectType == "TRUSS"
        step = parts[f"{name}_STEP001"]
        assert step.is_a("IfcBuildingElementPart") and step.ObjectType == "STEP"
        ps = ifcopenshell.util.element.get_psets(parts[f"{name}_STEP010"])["SSBIM_EscalatorStep"]
        assert ps["Index"] == 9 and ps["ChainU"] == pytest.approx(e.steps[9].chain_u)
        assert parts[f"{name}_HANDRAIL_L"].is_a("IfcRailing") and parts[f"{name}_HANDRAIL_L"].PredefinedType == "HANDRAIL"
        assert parts[f"{name}_BALUSTRADE_R"].PredefinedType == "BALUSTRADE"
        assert ifcopenshell.util.element.get_material(parts[f"{name}_TRUSS"]).Name == "Steel_Truss"
    ops = sorted(o.Name for o in f.by_type("IfcOpeningElement"))
    assert ops == ["OPEN_A_PIT_PLAT_B3F_R", "OPEN_A_SLAB_B2F_MID", "OPEN_B_PIT_SLAB_B2F_MID", "OPEN_B_SLAB_B1F_MID"]
    plat_voids = [r for r in f.by_type("IfcRelVoidsElement") if r.RelatingBuildingElement.Name == "PLAT_B3F_R"]
    assert len(plat_voids) == 1


# ===================================================== 도면
def test_3d_dxf_has_six_faces_per_strip(tmp_path):
    eng = eng_with(esc(1), esc(2, s=120.0, d=-1))
    msp = ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace()
    faces = list(msp.query('3DFACE[layer=="STRUCT_ESCALATOR"]')) + list(msp.query('3DFACE[layer=="STRUCT_ESC_GLASS"]'))
    from helper.strip_member import part_faces
    want = sum(len(q) for e in eng.escalators.all_escalators() for p in list(e.parts) + list(e.steps)
               for q in part_faces(eng.cfg, p))
    assert len(faces) == want
    plain = [p for e in eng.escalators.all_escalators() for p in e.parts if p.kind not in (K.HANDRAIL, K.BALUSTRADE, K.NEWEL_BASE,
                                                                                          K.NEWEL_END_IN, K.NEWEL_END_OUT)]
    assert all(len(q) == 6 for p in plain for q in part_faces(eng.cfg, p))     # 직선: 띠마다 6면


def test_section_profile_plan(tmp_path):
    eng = eng_with(esc(1, s=40.0, name="A"))
    e = by_name(eng, "A")
    sta = 44.0                                                    # 경사부
    path = eng.generate_section_dxf([sta], tmp_path / "s.dxf")
    sec = _q(path, "SEC_ESCALATOR")
    assert len(sec) >= 6                                          # 트러스·스텝(디딤판, 챌판)·난간 2·핸드레일 2
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert texts.count("A") == 1
    plat_sec = _q(path, "SEC_PLATFORM")
    base_sec = _q(StationCADEngine(make_cfg(user_example())).generate_section_dxf([sta], tmp_path / "b.dxf"), "SEC_PLATFORM")
    assert len(plat_sec) == len(base_sec)                         # s=44 는 피트(≈37.6~42.1) 밖
    pit_sec = _q(eng.generate_section_dxf([39.0], tmp_path / "p.dxf"), "SEC_PLATFORM")
    assert len(pit_sec) == len(base_sec) + 1                      # 피트 구간: 승강장 슬래브가 구멍으로 둘로 나뉨

    prof = eng.generate_profile_dxf(tmp_path / "f.dxf")
    base = StationCADEngine(make_cfg(user_example())).generate_profile_dxf(tmp_path / "g.dxf")
    step_strips = sum(len(x.shape.strips) for x in e.steps)
    def n_items(p):                                                   # 겹치거나 떨어진 띠(핸드레일·승강구)는 띠마다 윤곽
        ss = p.shape.strips
        gapped = any(abs(b.s0 - a.s1) > 1e-9 for a, b in zip(ss, ss[1:]))
        return len(ss) if (p.kind == K.HANDRAIL or gapped) else 1
    others = sum(n_items(p) for p in e.parts if p.side >= 0)
    assert len(_q(prof, "PROF_BEYOND")) == len(_q(base, "PROF_BEYOND")) + others + step_strips

    plan = eng.generate_plan_dxf(tmp_path / "n.dxf")
    assert len(_q(plan, "PLAN_ESCALATOR")) == 1 + 1 + 2                          # 외곽 + 스텝 + 난간 2
    assert "A ESC UP >" in [t.dxf.text for t in ezdxf.readfile(plan).modelspace().query("TEXT")]
    assert e.on_platform


def test_build_all_outputs_straight_and_curved(tmp_path):
    from engine.bim_engine import BIMEngine
    for curved in (False, True):
        paths = BIMEngine.build(cfg_with(esc(1), esc(2, s=150.0, d=-1), curved=curved), tmp_path / str(curved))
        assert len(paths) == 5 and all(os.path.getsize(p) > 0 for p in paths)


def test_no_escalators_keeps_outputs_unchanged():
    eng = StationCADEngine(make_cfg(user_example()))
    assert eng.escalators.escalator_packages == [] and eng.cfg.platform_holes() == []
    assert all(not pl.pieces for pk in eng.platform.platform_packages for pl in pk.platforms)


# ===================================================== 입력 초안 (화면 비의존)
from gui.escalator_draft import EscalatorDraft, EscalatorDrafts, preview
from gui.stair_draft import UP_MINUS


def test_draft_converts_sta_and_fields():
    d = EscalatorDrafts()
    d.items = [EscalatorDraft(name="E", lower_floor=2, direction=UP_MINUS, sta_wp="254.45", t_center="-6", lower_flat_steps="1")]
    (sp,) = d.to_specs(3, 134.45)
    assert (sp.name, sp.lower_floor, sp.direction, sp.lower_flat_steps) == ("E", 2, -1, 1)
    assert sp.s_wp == pytest.approx(120.0) and sp.t_center == -6.0
    assert (sp.angle_deg, sp.truss_width, sp.truss_depth, sp.headroom) == (30.0, 1.6, 1.15, 2.3)


@pytest.mark.parametrize("field,value,msg", [
    ("sta_wp", "x", r"에스컬레이터 1: 하부 WP 측점"),
    ("truss_depth", "0", "트러스 높이"),
    ("upper_flat_steps", "1.5", "정수"),
    ("lower_flat_steps", "-1", "0 이상"),
    ("direction", "위", "오르는 방향"),
])
def test_draft_errors_name_the_escalator(field, value, msg):
    d = EscalatorDrafts(); d.items = [EscalatorDraft()]
    setattr(d.items[0], field, value)
    with pytest.raises(ValueError, match=msg):
        d.to_specs(3, 0.0)


def test_draft_floor_clamped_and_preview():
    d = EscalatorDrafts(); d.items = [EscalatorDraft(lower_floor=3)]
    assert d.ensure_floors(3) is True and d.items[0].lower_floor == 2
    text = preview(EscalatorDraft(sta_wp="100"), 6.0, 0.0)
    run = 6.0 / math.tan(math.radians(30.0))
    assert f"WP 간 {run:.2f}m" in text and f"STA {100 - 2.4:.2f} ~ {100 + run + 2.8:.2f}" in text
    assert "확인" in preview(EscalatorDraft(angle_deg="abc"), 6.0, 0.0)


@pytest.mark.parametrize("curved", [False, True])
def test_step_volumes_mesh_and_ifc(tmp_path, curved):
    """개별 스텝 체적: 띠 공식 = 3D 메쉬 = IFC (곡선 rel 1e-4)"""
    import numpy as np
    import ifcopenshell.geom
    import ifcopenshell.util.shape
    eng = eng_with(esc(1, name="A"), curved=curved)
    eng.build_3d_doc()
    e = by_name(eng, "A")
    rel = 1e-4 if curved else 1e-9
    for x in e.steps[::5]:
        o = np.array(x.source_element[0].dxf.vtx0, dtype=float)
        v = 0.0
        for f in x.source_element:
            q = [np.array(f.dxf.get(f"vtx{i}"), dtype=float) - o for i in range(4)]
            v += np.dot(q[0], np.cross(q[1], q[2])) / 6.0
            if np.linalg.norm(q[3] - q[2]) > 1e-12:
                v += np.dot(q[0], np.cross(q[2], q[3])) / 6.0
        assert v == pytest.approx(x.volume, rel=rel, abs=1e-8)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "s.ifc"))
    s = ifcopenshell.geom.settings()
    s.set(s.USE_WORLD_COORDS, True)
    by = {el.Name: el for el in f.by_type("IfcBuildingElementPart") if el.ObjectType == "STEP"}
    assert len(by) == len(e.steps)
    for x in e.steps[::7]:
        vol = ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(s, by[x.name]).geometry)
        assert vol == pytest.approx(x.volume, rel=rel, abs=1e-8)


def test_balustrade_detail_cross_section():
    """상세 2단계 단면: 스텝 가장자리 → 틈 → 스커트 → (안쪽 데크) → 유리 → 바깥 데크(트러스 바깥까지), 높이: 트러스 상면 ~ 스커트 ~
    데크 하면(코 선 + 스커트 높이) ~ 데크(두께) ~ 유리 ~ 핸드레일. 띠끼리 겹치지 않음, 유리는 반투명 레이어"""
    import itertools
    from escalators.escalator_spec import DECK_T, SKIRT_GAP, SKIRT_T
    eng = eng_with(esc(1, name="A"))
    lay = eng.cfg.escalator_layouts()[0]
    e = by_name(eng, "A")
    sp, nose = lay.spec, lay_nose(lay)
    c, w = sp.t_center, sp.step_width / 2.0
    L = {k: e.part(getattr(K, k), 1) for k in ("SKIRT", "INNER_DECK", "BALUSTRADE", "OUTER_DECK", "HANDRAIL")}
    assert L["SKIRT"].t_range == pytest.approx((c + w + SKIRT_GAP, c + w + SKIRT_GAP + SKIRT_T))
    assert L["INNER_DECK"].t_range[1] == pytest.approx(L["BALUSTRADE"].t_range[0])
    assert L["OUTER_DECK"].t_range == pytest.approx((L["BALUSTRADE"].t_range[1], c + sp.truss_width / 2.0))
    assert L["BALUSTRADE"].t_range[1] - L["BALUSTRADE"].t_range[0] == pytest.approx(sp.glass_t)
    assert sum(L["HANDRAIL"].t_range) / 2 == pytest.approx(sum(L["BALUSTRADE"].t_range) / 2)          # 유리 위 가운데
    for x in L["INNER_DECK"].shape.strips:
        assert x.zb0 == pytest.approx(nose(x.s0) + sp.skirt_height) and x.zt - x.zb0 == pytest.approx(DECK_T)
    d0, d1 = L["INNER_DECK"].shape.strips[0].s0, L["INNER_DECK"].shape.strips[-1].s1
    for x in L["BALUSTRADE"].shape.strips:
        if d0 - 1e-9 <= x.s0 and x.s1 <= d1 + 1e-9:                    # 데크 위 (뉴얼 반원 유리 제외)
            assert x.zb0 == pytest.approx(nose(x.s0) + sp.skirt_height + DECK_T)
    tops = {round(x.s0, 6): x.zt for x in e.part(K.TRUSS).shape.strips}
    for x in L["SKIRT"].shape.strips:                                  # 스커트 하면 = 그 자리 트러스 상면
        if round(x.s0, 6) in tops:
            assert x.zb0 == pytest.approx(tops[round(x.s0, 6)])
    boxes = []
    for part in e.parts:
        for x in part.shape.strips:
            boxes.append((part.name, x, part.t_range))
    for (na, a, ta), (nb, b, tb) in itertools.combinations(boxes, 2):
        if min(ta[1], tb[1]) - max(ta[0], tb[0]) <= 1e-9 or min(a.s1, b.s1) - max(a.s0, b.s0) <= 1e-9:
            continue
        m = (max(a.s0, b.s0) + min(a.s1, b.s1)) / 2
        assert min(a.zt_at(m), b.zt_at(m)) - max(a.zb_at(m), b.zb_at(m)) <= 1e-9, (na, nb)
    eng.build_3d_doc()
    assert {f.dxf.layer for f in e.part(K.BALUSTRADE, 1).source_element} == {"STRUCT_ESC_GLASS"}
    with pytest.raises(ValueError, match="트러스 외폭"):
        eng_with(esc(1, name="A", truss_width=1.2))


def test_newel_handrail_loop_and_extension():
    """3단계: 난간·데크·스커트·핸드레일이 스텝 구간 양끝 너머 newel_ext, 끝에서 핸드레일이 바깥 반원(뉴얼)으로 돌아 내려감 —
    반원 띠 끝점은 반경 위, 위 띠 윗면 = 반원 바깥, 핸드레일 체적 = 직선 구간 + 반원 고리(근사), 유리와 겹치지 않음"""
    import math
    from escalators.escalator_spec import HANDRAIL_H
    eng = eng_with(esc(1, name="A"))
    lay = eng.cfg.escalator_layouts()[0]
    e = by_name(eng, "A")
    sp = lay.spec
    steps_s = (min(x.s0 for st in e.steps for x in st.shape.strips), max(x.s1 for st in e.steps for x in st.shape.strips))
    deck = e.part(K.INNER_DECK, 1).shape.strips
    assert deck[0].s0 == pytest.approx(steps_s[0] - sp.newel_ext) and deck[-1].s1 == pytest.approx(steps_s[1] + sp.newel_ext)
    rail = e.part(K.HANDRAIL, 1).shape.strips
    lo, hi = min(x.s0 for x in rail), max(x.s1 for x in rail)
    assert lo == pytest.approx(deck[0].s0 - sp.newel_radius) and hi == pytest.approx(deck[-1].s1 + sp.newel_radius)
    glass_all = e.part(K.BALUSTRADE, 1).shape.strips                    # 뉴얼 안쪽 반원 유리까지
    r_in = sp.newel_radius - HANDRAIL_H
    assert min(x.s0 for x in glass_all) == pytest.approx(deck[0].s0 - r_in)
    assert max(x.s1 for x in glass_all) == pytest.approx(deck[-1].s1 + r_in)
    # 위쪽 끝 반원: 띠 끝점이 중심에서 바깥/안쪽 반경 위
    s_end = deck[-1].s1
    z_top = lay.nose((s_end - sp.s_wp) * sp.direction) + sp.handrail_height
    zc, ro, ri = z_top - sp.newel_radius, sp.newel_radius, sp.newel_radius - HANDRAIL_H
    beyond = [x for x in rail if x.s0 >= s_end - 1e-9]
    assert len(beyond) > 12
    for x in beyond:
        for sv, zv in ((x.s0, x.zt), (x.s1, x.zt_end), (x.s0, x.zb0), (x.s1, x.zb1)):
            d = math.hypot(sv - s_end, zv - zc)
            assert ri - 1e-6 <= d <= ro + 1e-6
    # 반원 체적 ≈ 반 고리 넓이 × 폭 (세로 띠 근사, 3% 안)
    width = e.part(K.HANDRAIL, 1).t_range[1] - e.part(K.HANDRAIL, 1).t_range[0]
    ring = sum(x.area for x in beyond) * width
    assert ring == pytest.approx(math.pi / 2 * (ro ** 2 - ri ** 2) * width, rel=0.03)
    # 뉴얼 반원 유리는 핸드레일 고리 안쪽 반경 안 (겹침 없음)
    for x in glass_all:
        if x.s0 >= s_end - 1e-9:
            for sv, zb_, zt_ in ((x.s0, x.zb0, x.zt), (x.s1, x.zb1, x.zt_end)):
                assert math.hypot(sv - s_end, zt_ - zc) <= ri + 1e-6 and math.hypot(sv - s_end, zb_ - zc) <= ri + 1e-6
    big = eng_with(esc(1, name="A", newel_radius=0.47))                 # 반원이 바닥 가까이까지 (데크보다 낮아도 됨)
    assert by_name(big, "A").part(K.HANDRAIL, 1).shape.strips
    with pytest.raises(ValueError, match="뉴얼 반경"):
        eng_with(esc(1, name="A", newel_radius=0.05))
    with pytest.raises(ValueError, match="뉴얼 반경"):
        eng_with(esc(1, name="A", newel_radius=0.495))                 # 반원 아래 끝이 바닥에 닿음


def test_landing_plates_comb_cladding_and_finished_floor():
    """4단계: 스텝 면 = 바닥 마감면 (마감 켬), 승강구 바닥판·콤 윗면 = 마감면, 콤은 첫·끝 스텝 앞 COMB_L, 트러스 외장(옆·아래)은
    트러스 외폭·높이 안, 뉴얼 받침은 고리 아래 ~ 바닥. 피트 깊이 = 트러스 높이 − 마감 높이"""
    import itertools
    from escalators.escalator_spec import CLAD_T, COMB_L, LANDING_PLATE_T
    from finishes.finish_spec import FinishSettings
    cfg = cfg_with(esc(2, s=120.0, d=-1, name="B"))
    cfg.finish_settings = FinishSettings(enabled=True)
    eng = StationCADEngine(cfg)
    lay = eng.cfg.escalator_layouts()[0]
    e = by_name(eng, "B")
    st = eng.cfg.station
    ffl = cfg.finish_settings.for_room(cfg.room_settings.default_use(2)).ffl
    z_lo, z_hi = lay.finish_levels
    assert z_lo == pytest.approx(st.floor_level(2) + ffl) and z_hi == pytest.approx(st.floor_level(3) + ffl)
    nose = lay_nose(lay)
    first = e.steps[0]
    tread = max(first.shape.strips, key=lambda q: q.s1 - q.s0)
    assert tread.zt == pytest.approx(elev(eng.cfg, lay.s_at(first.chain_u), z_lo))       # 첫 스텝 = 아래층 마감면
    for code in (K.FLOOR_PLATE, K.COMB):
        for x in e.part(code).shape.strips:
            assert x.zt == pytest.approx(nose(x.s0)) and x.zt - x.zb0 == pytest.approx(LANDING_PLATE_T)
    combs = e.part(K.COMB).shape.strips
    assert sum(x.s1 - x.s0 for x in combs) == pytest.approx(2 * COMB_L)
    t0, t1 = e.t_range
    for side in (1, -1):
        c = e.part(K.CLAD_SIDE, side)
        assert c.t_range[1] - c.t_range[0] == pytest.approx(CLAD_T) and t0 - 1e-9 <= c.t_range[0] and c.t_range[1] <= t1 + 1e-9
    assert all(x.zt - x.zb0 == pytest.approx(CLAD_T) for x in e.part(K.CLAD_BOTTOM).shape.strips)
    # 모든 부재(스텝 제외)끼리 겹치지 않음
    boxes = [(p.name, x, p.t_range) for p in e.parts for x in p.shape.strips]
    for (na, a, ta), (nb, b, tb) in itertools.combinations(boxes, 2):
        if min(ta[1], tb[1]) - max(ta[0], tb[0]) <= 1e-9 or min(a.s1, b.s1) - max(a.s0, b.s0) <= 1e-9:
            continue
        m = (max(a.s0, b.s0) + min(a.s1, b.s1)) / 2
        assert min(a.zt_at(m), b.zt_at(m)) - max(a.zb_at(m), b.zb_at(m)) <= 1e-9, (na, nb)
    # 데크 끝 마무리: 데크 끝에서 데크 윗면 높이 → 고리 바깥 끝에서 바닥 (1/4 타원), 받침은 고리 아래 끝 이하
    from escalators.escalator_spec import DECK_T
    h_deck = lay.spec.skirt_height + DECK_T
    for side in (1, -1):
        for kind in (K.NEWEL_END_IN, K.NEWEL_END_OUT, K.NEWEL_BASE):
            sts = e.part(kind, side).shape.strips
            assert sts and all(x.zb0 == pytest.approx(nose(x.s0)) and x.zb1 == pytest.approx(nose(x.s1)) for x in sts)
        ends = e.part(K.NEWEL_END_IN, side).shape.strips
        hs = sorted([x.zt - x.zb0 for x in ends] + [x.zt_end - x.zb1 for x in ends])
        assert hs[-1] == pytest.approx(h_deck, abs=1e-9)                # 데크 끝 = 데크 윗면 높이
        assert hs[0] < 0.2 * h_deck                                     # 고리 바깥 끝 쪽은 바닥 가까이
        rail = e.part(K.HANDRAIL, side).shape.strips
        for x in e.part(K.NEWEL_BASE, side).shape.strips:              # 받침 윗면 ≤ 핸드레일 띠 하면 (같은 s)
            m = (x.s0 + x.s1) / 2
            for r in rail:
                if r.s0 - 1e-9 <= m <= r.s1 + 1e-9:
                    assert x.zt_at(m) <= r.zb_at(m) + 1e-9
    # 피트 깊이 = 트러스 높이 − 마감 높이 (마감 높이만큼 얕아짐) — 마감을 끄면 슬래브(1.0)보다 깊은 트러스도 마감이 있으면 됨
    deep = cfg_with(esc(2, s=120.0, d=-1, name="B", truss_depth=1.25), mid_t=1.2)
    with pytest.raises(ValueError, match="피트 깊이"):
        StationCADEngine(deep)
    deep.finish_settings = FinishSettings(enabled=True)
    StationCADEngine(deep)                                              # 1.25 − 0.1 = 1.15 ≤ 1.2
