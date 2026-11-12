"""직선 계단 (런 + 중간 계단참, 위층 슬래브 자동 오프닝) 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import pytest

from engine.cad_engine import StationCADEngine
from helper import prism_member as PM
from openings.opening_kind import OpeningKind
from openings.opening_spec import OpeningSpec
from stairs.stair_engine import part_quads
from stairs.stair_layout import plan_risers, riser_count, split_flights
from stairs.stair_spec import StairSpec
from stairs.stair_type import StairPartKind
from test_curved import NO_COLS, curved_cfg
from test_patch import _q, make_cfg, user_example

PLAT = dict(t_center=6.5, width=2.5)            # 우측 승강장(t 3.9 ~ 9.0) 안
MID = dict(t_center=-6.5, width=2.5)            # 2층: 좌측, 기둥(t=±3) 과 떨어짐


def stair(lower=1, s=30.0, d=1, name="", **kw):
    kw = {**(PLAT if lower == 1 else MID), **kw}
    return StairSpec(lower_floor=lower, s_start=s, direction=d, name=name, **kw)


def cfg_with(*stairs, curved=False, openings=()):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(user_example())
    cfg.stairs, cfg.openings = list(stairs), list(openings)
    return cfg


def eng_with(*stairs, **kw):
    return StationCADEngine(cfg_with(*stairs, **kw))


def by_name(eng, name):
    return next(s for s in eng.stairs.all_stairs() if s.name == name)


def elev(cfg, s, z_rel):
    return cfg.lv(s) - cfg.station.offset + z_rel


# ===================================================== 단수 / 런 분할 (순수 계산)
def test_riser_count_rounds_up():
    assert riser_count(6.0, 0.18) == 34 and riser_count(5.4, 0.18) == 30 and riser_count(0.1, 0.18) == 1


def test_split_flights_uses_fewest_even_flights():
    assert split_flights(34, 6.0 / 34, 3.0) == [17, 17]              # 17 x 0.176 = 3.0 (상한과 같음 허용)
    assert split_flights(35, 6.0 / 35, 2.1) == [12, 12, 11]          # 앞쪽 런이 1단 많음 (12 x 0.171 = 2.06)
    assert split_flights(35, 6.0 / 35, 2.0) == [9, 9, 9, 8]          # 상한이 낮으면 런을 하나 더
    assert split_flights(10, 0.17, 3.0) == [10]                       # 계단참 없음
    with pytest.raises(ValueError, match="런 높이 상한"):
        split_flights(10, 0.17, 0.3)


def test_plan_risers_without_slope():
    sp = StairSpec()
    n, r, counts, run = plan_risers(6.0, sp)
    assert n == 34 and r == pytest.approx(6.0 / 34) and counts == [17, 17]
    assert run == pytest.approx(2 * 16 * 0.30 + 1.5)


# ===================================================== 배치 규약
def test_layout_risers_uniform_and_match_real_elevations_with_slope():
    """구배(약 18‰)가 있어도 모든 단높이가 같고, 단높이 x 단수 = 위층 도착점 표고 − 시작점 표고"""
    cfg = cfg_with(stair(1, s=30.0), stair(2, s=120.0, d=-1))
    assert abs(cfg.grade_permil(0.0)) > 10.0
    for lay in cfg.stair_layouts():
        st = cfg.station
        e0 = elev(cfg, lay.s_at(0.0), lay.base_level)
        e1 = elev(cfg, lay.s_at(lay.run), st.floor_level(lay.lower_floor + 1))
        assert lay.n_risers * lay.riser == pytest.approx(e1 - e0, abs=1e-9)
        assert lay.riser <= lay.spec.riser_max + 1e-9
        assert sum(lay.flight_risers) == lay.n_risers
        assert max(lay.flight_risers) * lay.riser <= lay.spec.flight_rise_max + 1e-9
        tops = [zt for p in lay.parts for _, _, zt in p.surfaces]       # 걷는 면 상면: 아래 → 위로 단높이씩 (계단참 포함)
        steps = [b - a for a, b in zip([e0] + tops, tops + [e1])]
        assert all(x == pytest.approx(lay.riser, abs=1e-9) for x in steps)
        assert len(tops) == lay.n_risers - 1                              # 걷는 면 = 디딤판(N − 런 수) + 계단참(런 수 − 1)


def test_platform_stair_starts_on_platform_top_and_needs_fewer_risers():
    eng = eng_with(stair(1, name="P"), stair(1, s=60.0, t_center=-1.5, width=1.0, name="T"))   # T: 선로 사이 (기둥 t=0±0.5 피함)
    p, t = by_name(eng, "P"), by_name(eng, "T")
    plat = eng.cfg.platform
    assert p.on_platform and not t.on_platform
    lp, lt = {lay.name: lay for lay in eng.cfg.stair_layouts()}["P"], {lay.name: lay for lay in eng.cfg.stair_layouts()}["T"]
    assert lp.base_level == pytest.approx(plat.top_level) and lt.base_level == 0.0
    assert p.n_risers < t.n_risers
    assert p.pos_z == pytest.approx(elev(eng.cfg, 30.0, plat.top_level))
    s0 = p.flights[0].shape.strips[0]
    assert s0.zb0 == pytest.approx(elev(eng.cfg, 30.0, plat.top_level))     # 첫 런 하면이 승강장 상면에 놓임


def test_platform_ranges_helper_matches_platform_objects():
    eng = StationCADEngine(make_cfg(user_example()))
    slabs = sorted(PM.t_range(pl) for pk in eng.platform.platform_packages for pl in pk.platforms if pl.part.name == "SLAB")
    ranges = sorted(eng.cfg.platform.slab_t_ranges(eng.cfg.station.width))
    assert len(slabs) == len(ranges) == 2
    for a, b in zip(slabs, ranges):
        assert a == pytest.approx(b)


def test_direction_minus_mirrors_layout():
    cfg = cfg_with(stair(2, s=40.0, name="A"), stair(2, s=160.0, d=-1, name="B"))
    a, b = cfg.stair_layouts()
    assert a.s_range == pytest.approx((40.0, 40.0 + a.run)) and b.s_range == pytest.approx((160.0 - b.run, 160.0))
    assert a.n_risers >= b.n_risers                                       # A 는 구배를 따라 오르막, B 는 내리막 방향
    eng = StationCADEngine(cfg)
    assert by_name(eng, "B").direction == -1
    # 하향 방향 계단의 디딤판은 s 가 줄어들수록 높아짐
    tops = by_name(eng, "B").flights[0].surfaces
    assert tops[0][2] > tops[-1][2]


def test_flights_and_landings_structure():
    eng = eng_with(stair(2, s=40.0))
    s = eng.stairs.all_stairs()[0]
    lay = eng.cfg.stair_layouts()[0]
    n = len(lay.flight_risers)
    assert n >= 2
    kinds = [p.kind for p in s.parts]
    assert kinds == [StairPartKind.FLIGHT, StairPartKind.LANDING] * (n - 1) + [StairPartKind.FLIGHT]   # 런과 계단참이 번갈아
    assert [p.name for p in s.parts][:3] == ["ST1_FLIGHT1", "ST1_LANDING1", "ST1_FLIGHT2"]
    assert [f.n_risers for f in s.flights] == lay.flight_risers
    assert all(f.n_treads == f.n_risers - 1 for f in s.flights)
    land = s.landings[0]
    (sa, sb, _), = land.surfaces
    assert sb - sa == pytest.approx(1.5)
    st = land.shape.strips[0]
    assert st.zt - st.zb0 == pytest.approx(0.2) and st.zb0 == st.zb1
    assert s.level == "B2F" and s.lower_floor == 2


def test_strips_are_contiguous_and_below_tops():
    eng = eng_with(stair(1), stair(2, s=120.0, d=-1))
    for s in eng.stairs.all_stairs():
        strips = sorted((st for p in s.parts for st in p.shape.strips), key=lambda x: x.s0)
        assert strips[0].s0 == pytest.approx(s.s_range[0]) and strips[-1].s1 == pytest.approx(s.s_range[1])
        for a, b in zip(strips, strips[1:]):
            assert b.s0 == pytest.approx(a.s1)
        assert all(st.zb0 < st.zt and st.zb1 < st.zt for st in strips)


# ===================================================== 자동 오프닝
def test_auto_opening_meets_headroom_rule():
    cfg = cfg_with(stair(1), stair(2, s=120.0, d=-1))
    eng = StationCADEngine(cfg)
    st = cfg.station
    for s in eng.stairs.all_stairs():
        slab = next(x for pk in eng.slabs.slab_packages for x in pk.slabs if x.slab_no == s.lower_floor)
        (o,) = [o for o in slab.openings if o.name == f"OPEN_{s.name}_{slab.name}"]
        assert o.kind is OpeningKind.STAIR and s.opening_name == s.name
        assert o.t_range == pytest.approx(s.t_range)
        arrive = s.s_range[1] if s.direction > 0 else s.s_range[0]
        assert arrive == pytest.approx(o.s_range[1] if s.direction > 0 else o.s_range[0])      # 도착 지점까지 뚫림
        bot = st.floor_level(s.lower_floor + 1) - st.mid_t
        hr = 2.1
        inside = outside = 0
        for p in s.parts:
            for sa, sb, zt in p.surfaces:
                clear = min(elev(cfg, sa, bot), elev(cfg, sb, bot)) - zt
                if o.s_range[0] - 1e-9 <= sa and sb <= o.s_range[1] + 1e-9:
                    inside += 1
                else:
                    outside += 1
                    assert clear >= hr - 1e-9                       # 오프닝 밖 걷는 면은 머리 높이 확보
        assert inside > 0 and outside > 0
        first_in = min((sa, zt) for p in s.parts for sa, sb, zt in p.surfaces
                       if o.s_range[0] - 1e-9 <= sa and sb <= o.s_range[1] + 1e-9) if s.direction > 0 else \
            max((sb, zt) for p in s.parts for sa, sb, zt in p.surfaces if o.s_range[0] - 1e-9 <= sa and sb <= o.s_range[1] + 1e-9)
        assert elev(cfg, first_in[0], bot) - first_in[1] < hr + 1e-6   # 오프닝 첫 면은 머리 높이 부족 (필요한 만큼만 뚫음)


def test_auto_opening_reduces_slab_volume():
    base = StationCADEngine(make_cfg(user_example()))
    eng = eng_with(stair(2, s=40.0))
    sl = lambda e: next(x for pk in e.slabs.slab_packages for x in pk.slabs if x.slab_no == 2)
    o = sl(eng).openings[0]
    assert sl(eng).net_volume == pytest.approx(sl(base).net_volume - o.shape.volume)


def test_manual_and_auto_openings_on_same_slab():
    man = OpeningSpec(OpeningKind.ELEVATOR, 100.0, 3.0, 6.0, 3.0, [1])
    eng = eng_with(stair(1), openings=[man])
    slab1 = next(x for pk in eng.slabs.slab_packages for x in pk.slabs if x.slab_no == 1)
    assert sorted(o.name for o in slab1.openings) == ["OPEN_ELEV1_SLAB_B2F_MID", "OPEN_ST1_SLAB_B2F_MID"]


# ===================================================== 검증
@pytest.mark.parametrize("sp,msg", [
    (stair(0), "범위"),
    (stair(3), "범위"),
    (stair(1, d=0), "오르는 방향"),
    (stair(1, width=0.0), "폭"),
    (stair(1, tread=-0.3), "단너비"),
    (stair(1, headroom=0.0), "머리 높이"),
    (stair(1, flight_rise_max=0.3), "2배"),
    (stair(2, t_center=-8.5, width=2.0), "내공 폭"),
    (stair(2, s=-1.0), "내공 길이"),
    (stair(2, s=190.0), "내공 길이"),                       # 오르면서 종점 마감벽을 넘음
    (stair(2, s=5.0, d=-1), "내공 길이"),
    (stair(1, t_center=4.0, width=2.5), "걸쳐"),           # 승강장 끝단(t=3.9)에 걸침
])
def test_invalid_stair_rejected(sp, msg):
    with pytest.raises(ValueError, match=msg):
        StationCADEngine(cfg_with(sp))


def test_single_floor_station_rejects_stair():
    cfg = make_cfg(NO_COLS(), floors=1)
    cfg.stairs = [stair(1)]
    with pytest.raises(ValueError, match="2 이상"):
        StationCADEngine(cfg)


def test_overlapping_stairs_and_duplicate_names_rejected():
    with pytest.raises(ValueError, match="서로 겹칩니다"):
        StationCADEngine(cfg_with(stair(2, s=40.0), stair(2, s=45.0)))
    StationCADEngine(cfg_with(stair(1, s=40.0), stair(2, s=45.0)))          # 층이 다르면 허용 (평면이 겹쳐도)
    with pytest.raises(ValueError, match="이름이 중복"):
        StationCADEngine(cfg_with(stair(1, name="A"), stair(2, s=100.0, name="A")))


def test_auto_opening_overlapping_manual_opening_rejected():
    lay = cfg_with(stair(2, s=40.0)).stair_layouts()[0]
    o = lay.opening
    man = OpeningSpec(OpeningKind.VENT, o.s_start + 0.5, 1.0, o.t_center, 1.0, [2])
    with pytest.raises(ValueError, match="겹칩니다"):
        StationCADEngine(cfg_with(stair(2, s=40.0), openings=[man]))


def test_stair_over_opening_in_its_floor_slab_rejected():
    man = OpeningSpec(OpeningKind.VENT, 41.0, 1.0, -6.5, 1.0, [1], name="V")      # 2층 계단이 서는 슬래브(1번)
    with pytest.raises(ValueError, match="오프닝 V 위"):
        StationCADEngine(cfg_with(stair(2, s=40.0), openings=[man]))


def test_stair_on_columns_rejected():
    with pytest.raises(ValueError, match="B2F 기둥"):                        # 2층 원기둥 t=±3 φ1.0
        StationCADEngine(cfg_with(stair(2, s=40.0, t_center=-3.0, width=2.0)))
    with pytest.raises(ValueError, match="B3F 기둥"):                        # 1층 사각기둥 t=0 (선로 사이 계단)
        StationCADEngine(cfg_with(stair(1, s=40.0, t_center=0.0, width=1.0)))


def test_auto_opening_on_upper_floor_column_rejected():
    # 1층 선로 사이 계단 (t 1.75 ~ 3.25, 1층 기둥 t=0 은 피함): 1번 슬래브 자동 오프닝이 위층(B2F) 원기둥 t=+3 과 겹침
    with pytest.raises(ValueError, match="B2F 기둥"):
        StationCADEngine(cfg_with(stair(1, s=42.0, t_center=2.5, width=1.5)))


# ===================================================== 체적 교차 검증 (공식 ↔ 3D 메쉬 ↔ IFC)
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("curved", [False, True])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, curved):
    eng = eng_with(stair(1, s=30.0), stair(2, s=150.0, d=-1), curved=curved)
    cfg = eng.cfg
    rel = 1e-4 if curved else 1e-9
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "s.ifc"))
    els = {e.Name: e for e in f.by_type("IfcStairFlight") + f.by_type("IfcSlab")}
    for s in eng.stairs.all_stairs():
        for p in s.parts:
            mesh = sum(PM.mesh_volume(q) for q in part_quads(cfg, p))
            assert mesh == pytest.approx(p.shape.volume, rel=rel)
            assert ifc_world_volume(els[p.name]) == pytest.approx(p.shape.volume, rel=1e-4)
            if not curved:                                                  # 직선: 계단 모양 단면적 x 폭 = 체적
                pts = p.shape.profile_points()
                area = 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
                assert area * p.shape.width == pytest.approx(p.shape.volume, rel=1e-9)
        assert s.volume == pytest.approx(sum(p.shape.volume for p in s.parts))
    if curved:
        assert els[eng.stairs.all_stairs()[0].parts[0].name].Representation.Representations[0].RepresentationType == "Tessellation"


# ===================================================== IFC 구조
def test_ifc_stair_aggregates_flights_and_landings(tmp_path):
    eng = eng_with(stair(1, name="A"), stair(2, s=150.0, d=-1, name="B"))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "s.ifc"))
    stairs = {s.Name: s for s in f.by_type("IfcStair")}
    assert set(stairs) == {"A", "B"} and all(s.PredefinedType == "STRAIGHT_RUN_STAIR" for s in stairs.values())
    for name, level in (("A", "B3F"), ("B", "B2F")):
        st = stairs[name]
        parts = ifcopenshell.util.element.get_decomposition(st)
        model = by_name(eng, name)
        assert sorted(p.Name for p in parts) == sorted(p.name for p in model.parts)
        assert ifcopenshell.util.element.get_container(st).Name == level
        for p in parts:
            m = next(x for x in model.parts if x.name == p.Name)
            if p.is_a("IfcStairFlight"):
                assert (p.NumberOfRisers, p.NumberOfTreads) == (m.n_risers, m.n_treads)
                assert p.RiserHeight == pytest.approx(model.riser) and p.TreadLength == pytest.approx(0.3)
                assert p.Representation.Representations[0].RepresentationType == "SweptSolid"
            else:
                assert p.is_a("IfcSlab") and p.PredefinedType == "LANDING"
            assert ifcopenshell.util.element.get_material(p).Name == "Concrete_C24"
    ops = [o for o in f.by_type("IfcOpeningElement") if o.ObjectType == "STAIR"]
    assert sorted(o.Name for o in ops) == ["OPEN_A_SLAB_B2F_MID", "OPEN_B_SLAB_B1F_MID"]


# ===================================================== 도면
def test_3d_dxf_has_six_faces_per_strip(tmp_path):
    eng = eng_with(stair(1), stair(2, s=150.0, d=-1))
    faces = list(ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace().query('3DFACE[layer=="STRUCT_STAIR"]'))
    strips = sum(len(p.shape.strips) for s in eng.stairs.all_stairs() for p in s.parts)
    assert len(faces) == 6 * strips


def test_section_cuts_stair_with_label(tmp_path):
    eng = eng_with(stair(2, s=40.0))
    s = eng.stairs.all_stairs()[0]
    sta = 40.0 + 0.15                                                           # 첫 디딤판
    path = eng.generate_section_dxf([sta], tmp_path / "s.dxf")
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert texts.count("ST1") == 1
    base = StationCADEngine(make_cfg(user_example())).generate_section_dxf([sta], tmp_path / "b.dxf")
    got, ref = _q(path, "SEC_CONCRETE"), _q(base, "SEC_CONCRETE")
    assert len(got) == len(ref) + 1
    st = s.flights[0].shape.strips[0]
    rect = [p for p in got if abs(min(q[0] for q in p.get_points()) + 7.75) < 1e-6]
    assert len(rect) == 1 and max(q[1] for q in rect[0].get_points()) == pytest.approx(st.zt)


def test_profile_shows_stair_beyond_or_cut(tmp_path):
    beyond = eng_with(stair(2, s=40.0))                                        # t -7.75 ~ -5.25: 중심선 밖
    p1 = beyond.generate_profile_dxf(tmp_path / "a.dxf")
    n_parts = len(beyond.stairs.all_stairs()[0].parts)
    base = StationCADEngine(make_cfg(user_example())).generate_profile_dxf(tmp_path / "b.dxf")
    assert len(_q(p1, "PROF_BEYOND")) == len(_q(base, "PROF_BEYOND")) + n_parts
    cfg = make_cfg(NO_COLS()); cfg.stairs = [stair(1, s=40.0, t_center=0.0, width=1.0)]   # 선로 사이, 중심선이 계단을 자름
    cut = StationCADEngine(cfg)
    p2 = cut.generate_profile_dxf(tmp_path / "c.dxf")
    base2 = StationCADEngine(make_cfg(NO_COLS())).generate_profile_dxf(tmp_path / "d.dxf")
    # 계단 부재마다 1개 + 중심선 위 자동 오프닝 때문에 중간 슬래브 종단면이 두 조각으로 나뉨 (+1)
    assert len(_q(p2, "PROF_CONCRETE")) == len(_q(base2, "PROF_CONCRETE")) + len(cut.stairs.all_stairs()[0].parts) + 1
    assert len(list(ezdxf.readfile(p2).modelspace().query('HATCH[layer=="PROF_HATCH"]'))) > \
        len(list(ezdxf.readfile(base2).modelspace().query('HATCH[layer=="PROF_HATCH"]')))


def test_plan_shows_lowest_floor_stairs_only(tmp_path):
    eng = eng_with(stair(1), stair(2, s=150.0, d=-1))
    path = eng.generate_plan_dxf(tmp_path / "p.dxf")
    lower = next(s for s in eng.stairs.all_stairs() if s.lower_floor == 1)
    n_surfaces = sum(len(p.surfaces) for p in lower.parts)
    assert len(_q(path, "PLAN_STAIR")) == n_surfaces + 1                        # 디딤판·계단참 + 전체 윤곽
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert "ST1 UP >" in texts and not any(t.startswith("ST2") for t in texts)


def test_build_all_outputs_with_stairs_straight_and_curved(tmp_path):
    from engine.bim_engine import BIMEngine
    for curved in (False, True):
        paths = BIMEngine.build(cfg_with(stair(1), stair(2, s=150.0, d=-1), curved=curved), tmp_path / str(curved))
        assert len(paths) == 5 and all(os.path.getsize(p) > 0 for p in paths)


def test_no_stairs_keeps_outputs_unchanged():
    eng = StationCADEngine(make_cfg(user_example()))
    assert eng.stairs.stair_packages == [] and eng.cfg.all_openings() == []


# ===================================================== 입력 초안 (화면 비의존)
from gui.stair_draft import UP_MINUS, UP_PLUS, StairDraft, StairDrafts, floor_choice_label, preview


def test_draft_converts_sta_and_direction():
    d = StairDrafts()
    d.items = [StairDraft(name="A", lower_floor=2, direction=UP_MINUS, sta_start="174.45", t_center="-6.5", width="2.5")]
    (sp,) = d.to_specs(3, 134.45)
    assert (sp.name, sp.lower_floor, sp.direction) == ("A", 2, -1)
    assert sp.s_start == pytest.approx(40.0) and (sp.t_lo, sp.t_hi) == (-7.75, -5.25)
    assert (sp.riser_max, sp.tread, sp.flight_rise_max, sp.landing_len, sp.waist_t, sp.headroom) == \
        (0.18, 0.3, 3.0, 1.5, 0.2, 2.1)


@pytest.mark.parametrize("field,value,msg", [
    ("sta_start", "x", r"계단 1: 시작 측점"),
    ("width", "0", "폭은\\(는\\) 0보다"),
    ("riser_max", "-1", "단높이 상한"),
    ("direction", "위로", "오르는 방향"),
])
def test_draft_errors_name_the_stair(field, value, msg):
    d = StairDrafts(); d.items = [StairDraft()]
    setattr(d.items[0], field, value)
    with pytest.raises(ValueError, match=msg):
        d.to_specs(3, 0.0)


def test_draft_floor_clamped_when_floor_count_drops():
    d = StairDrafts(); d.items = [StairDraft(lower_floor=3)]
    assert d.ensure_floors(3) is True and d.items[0].lower_floor == 2
    assert d.ensure_floors(3) is False


def test_floor_choice_labels_and_preview():
    assert [floor_choice_label(3, n) for n in (1, 2)] == ["B3F → B2F", "B2F → B1F"]
    text = preview(StairDraft(sta_start="100", direction=UP_PLUS), 6.0, 0.0)
    assert "34단" in text and "계단참 1개" in text and "STA 100.00 ~ 111.10" in text
    assert "확인" in preview(StairDraft(width="abc"), 6.0, 0.0)
