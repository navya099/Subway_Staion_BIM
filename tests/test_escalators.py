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


def test_parts_and_their_vertical_rules():
    """트러스 하면 = 스텝 코 선 − 트러스 높이, 스텝 층 하면 = 코 선 − (단높이 + 판 두께),
    난간 패널 = 코 선 ~ 핸드레일 아래, 핸드레일 상면 = 코 선 + 핸드레일 높이. 경사 스텝 디딤판은 수평이고 앞 코가 코 선 위"""
    eng = eng_with(esc(1, name="A"), esc(2, s=120.0, d=-1, name="B"))
    cfg = eng.cfg
    for e, lay in zip(eng.escalators.all_escalators(), cfg.escalator_layouts()):
        sp, nose = lay.spec, nose_fn(cfg, lay)
        assert [p.name for p in e.parts] == [f"{e.name}_TRUSS", f"{e.name}_STEPS", f"{e.name}_BALUSTRADE_L",
                                             f"{e.name}_HANDRAIL_L", f"{e.name}_BALUSTRADE_R", f"{e.name}_HANDRAIL_R"]
        for st in e.part(K.TRUSS).shape.strips:
            assert st.zb0 == pytest.approx(nose(st.s0) - sp.truss_depth, abs=1e-9)
            assert st.zb1 == pytest.approx(nose(st.s1) - sp.truss_depth, abs=1e-9)
        steps = e.part(K.STEPS).shape.strips
        s_lo, s_hi = sorted((lay.s_at(-sp.lower_flat_steps * sp.step_depth), lay.s_at(lay.run + sp.upper_flat_steps * sp.step_depth)))
        assert (steps[0].s0, steps[-1].s1) == pytest.approx((s_lo, s_hi))
        for st in steps:
            assert st.zb0 == pytest.approx(nose(st.s0) - sp.riser - STEP_PLATE_T, abs=1e-9)
            u_mid = ((st.s0 + st.s1) / 2.0 - sp.s_wp) * sp.direction
            if 0 < u_mid < lay.run:                                   # 경사 스텝: 수평 디딤판, 앞 코(아래쪽 끝)가 코 선 위
                assert st.zt == pytest.approx(st.zt_end)
                front = st.s0 if sp.direction > 0 else st.s1
                assert st.zt == pytest.approx(nose(front), abs=1e-9)
            else:                                                     # 평탄 스텝: 바닥면을 따름
                assert st.zt == pytest.approx(nose(st.s0), abs=1e-9) and st.zt_end == pytest.approx(nose(st.s1), abs=1e-9)
        for side in (1, -1):
            for st in e.part(K.BALUSTRADE, side).shape.strips:
                assert st.zb0 == pytest.approx(nose(st.s0), abs=1e-9)
                assert st.zt == pytest.approx(nose(st.s0) + sp.handrail_height - HANDRAIL_H, abs=1e-9)
            for st in e.part(K.HANDRAIL, side).shape.strips:
                assert st.zt_end == pytest.approx(nose(st.s1) + sp.handrail_height, abs=1e-9)
        # 평면: 스텝 폭, 난간·핸드레일은 스텝 밖, 모두 트러스 폭 안
        t0, t1 = e.t_range
        assert e.part(K.STEPS).t_range == pytest.approx((sp.t_center - 0.5, sp.t_center + 0.5))
        for p in e.parts:
            assert t0 - 1e-9 <= p.t_range[0] < p.t_range[1] <= t1 + 1e-9
        assert e.part(K.BALUSTRADE, 1).t_range[0] > sp.t_center + 0.5 and e.part(K.BALUSTRADE, -1).t_range[1] < sp.t_center - 0.5


def test_truss_ends_flush_with_floors_and_strips_contiguous():
    eng = eng_with(esc(1), esc(2, s=120.0, d=-1))
    cfg = eng.cfg
    for e, lay in zip(eng.escalators.all_escalators(), cfg.escalator_layouts()):
        for p in e.parts:
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
        assert z_lo == pytest.approx(elev(cfg, s_lo_end, lay.base_level), abs=1e-9)        # 하부 덮개판 = 시작면
        assert z_hi == pytest.approx(elev(cfg, s_hi_end, z_top), abs=1e-9)                # 상부 덮개판 = 위층 바닥


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
    els = {e.Name: e for e in f.by_type("IfcBuildingElementPart") + f.by_type("IfcRailing")}
    for e in eng.escalators.all_escalators():
        for p in e.parts:
            mesh = sum(PM.mesh_volume(q) for q in part_faces(cfg, p))
            assert mesh == pytest.approx(p.shape.volume, rel=1e-4 if curved else 1e-7)
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
        assert set(parts) == {p.name for p in by_name(eng, name).parts}
        assert parts[f"{name}_TRUSS"].is_a("IfcBuildingElementPart") and parts[f"{name}_TRUSS"].ObjectType == "TRUSS"
        assert parts[f"{name}_STEPS"].is_a("IfcBuildingElementPart")
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
    faces = list(ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace().query('3DFACE[layer=="STRUCT_ESCALATOR"]'))
    strips = sum(len(p.shape.strips) for e in eng.escalators.all_escalators() for p in e.parts)
    assert len(faces) == 6 * strips


def test_section_profile_plan(tmp_path):
    eng = eng_with(esc(1, s=40.0, name="A"))
    e = by_name(eng, "A")
    sta = 44.0                                                    # 경사부
    path = eng.generate_section_dxf([sta], tmp_path / "s.dxf")
    sec = _q(path, "SEC_ESCALATOR")
    assert len(sec) == 6                                          # 트러스·스텝·난간 2·핸드레일 2
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert texts.count("A") == 1
    plat_sec = _q(path, "SEC_PLATFORM")
    base_sec = _q(StationCADEngine(make_cfg(user_example())).generate_section_dxf([sta], tmp_path / "b.dxf"), "SEC_PLATFORM")
    assert len(plat_sec) == len(base_sec)                         # s=44 는 피트(≈37.6~42.1) 밖
    pit_sec = _q(eng.generate_section_dxf([39.0], tmp_path / "p.dxf"), "SEC_PLATFORM")
    assert len(pit_sec) == len(base_sec) + 1                      # 피트 구간: 승강장 슬래브가 구멍으로 둘로 나뉨

    prof = eng.generate_profile_dxf(tmp_path / "f.dxf")
    base = StationCADEngine(make_cfg(user_example())).generate_profile_dxf(tmp_path / "g.dxf")
    assert len(_q(prof, "PROF_BEYOND")) == len(_q(base, "PROF_BEYOND")) + 4      # 트러스·스텝·한쪽 난간·핸드레일

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
