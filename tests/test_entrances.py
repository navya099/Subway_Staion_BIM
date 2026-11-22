"""출입구 (출구통로 끝 + 경사 박스 + 계단(별도 슬래브·칸막이벽) + 에스컬레이터, 지표 EL 기준 자동 계산) 테스트"""
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
from entrances.entrance_spec import EntranceSpec
from helper import prism_member as PM
from helper.strip_member import part_faces
from passages.passage_spec import PassageSpec, station_path
from test_curved import NO_COLS, curved_cfg
from test_patch import make_cfg, user_example

RISE = 17.287                                         # 실무 도면 예 (EL 92.013 → G.L 109.300)


def straight_passage(name="EX1"):
    return PassageSpec(floor=3, path=station_path([(50, 10, None), (50, 25, 0)]), name=name)


def bent_passage(name="EX1"):
    """선형과 나란히(+s) 꺾여 나가는 통로 → 출입구도 +s 방향 (정거장 횡단면이 출입구를 자름)"""
    return PassageSpec(floor=3, path=station_path([(50, 10, None), (50, 25, 0), (70, 25, 0)]), name=name)


def cfg_with(*entrances, passages=None, curved=False, rise=RISE):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(user_example())
    cfg.passages = list(passages or [straight_passage()])
    zp = cfg.passage_layouts()[-1].vertices[-1].z
    cfg.entrances = [e if isinstance(e, EntranceSpec) else EntranceSpec(passage="EX1", ground_el=zp + rise, **e)
                     for e in (entrances or ({},))]
    return cfg


def lay_of(cfg):
    return cfg.entrance_layouts()[0]


def nose_fn(lay):
    u, tan, zp, G = lay.u, math.tan(math.radians(lay.spec.esc_angle_deg)), lay.z_floor, lay.ground
    return lambda x: zp if x <= u["wp_lo"] else G if x >= u["wp_hi"] else zp + (x - u["wp_lo"]) * tan


# ===================================================== 자동 계산 규약
def test_key_positions_follow_ground_and_escalator():
    cfg = cfg_with()
    lay = lay_of(cfg)
    sp, u = lay.spec, lay.u
    tan = math.tan(math.radians(30.0))
    assert lay.z_floor == pytest.approx(cfg.passage_layouts()[0].vertices[-1].z)
    assert lay.ground - lay.z_floor == pytest.approx(RISE)
    assert u["truss_lo"] == pytest.approx(sp.wall_t + sp.lower_margin)
    assert u["wp_lo"] == pytest.approx(u["truss_lo"] + sp.esc_lower_ext)
    assert u["wp_hi"] - u["wp_lo"] == pytest.approx(RISE / tan)
    assert u["cross"] == pytest.approx(u["wp_lo"] + sp.esc_truss_depth / tan)          # 하부 피트 끝
    assert u["truss_hi"] == pytest.approx(u["wp_hi"] + sp.esc_upper_ext)
    assert u["top"] == pytest.approx(max(u["truss_hi"], u["arrive"]) + sp.top_margin)
    st = lay.stair
    assert st.n_risers * st.riser == pytest.approx(RISE) and st.riser <= sp.riser_max + 1e-9
    assert max(st.flight_risers) * st.riser <= sp.flight_rise_max + 1e-9


def test_frame_continues_last_passage_segment():
    cfg = cfg_with(passages=[bent_passage()])
    lay = lay_of(cfg)
    v = cfg.passage_layouts()[0].vertices
    assert (lay.frame.px, lay.frame.py) == pytest.approx((v[-1].x, v[-1].y))
    d = math.hypot(v[-1].x - v[-2].x, v[-1].y - v[-2].y)
    assert (lay.frame.ux, lay.frame.uy) == pytest.approx(((v[-1].x - v[-2].x) / d, (v[-1].y - v[-2].y) / d))


def test_stair_auto_advances_to_stay_above_floor():
    """기본 계단(평균 약 27°)은 30° 바닥보다 완만 → 하부 수평부 쪽으로 자동으로 앞당겨 바닥 위에 머묾"""
    lay = lay_of(cfg_with())
    assert lay.u["stair0"] < lay.u["cross"] - 1.0
    s_floor = next(p for p in lay.box_parts if p.code == "FLOOR_S").strips
    def floor_top(x):
        st = next(s for s in s_floor if s.s0 - 1e-9 <= x <= s.s1 + 1e-9)
        return st.zt_at(x)
    for p in lay.stair.parts:
        for st in p.strips:
            assert st.zb0 >= floor_top(st.s0) - 1e-6 and st.zb1 >= floor_top(st.s1) - 1e-6
    # 바닥 위 조건을 만족하는 가장 늦은 시작점: 조금 더 늦추면(+0.05m) 바닥 아래로 내려감
    with pytest.raises(ValueError, match="바닥 아래"):
        lay_of(cfg_with({"stair_offset": lay.u["stair0"] - lay.u["cross"] + 0.05}))


def test_steep_stair_starts_at_pit_end_and_impossible_rise_rejected():
    steep = lay_of(cfg_with({"tread": 0.22, "landing_len": 0.8, "riser_max": 0.2}))
    assert steep.u["stair0"] == pytest.approx(steep.u["cross"])                        # 앞당길 필요 없음
    with pytest.raises(ValueError, match="바닥 아래"):
        lay_of(cfg_with(rise=25.0))                                                     # 하부 수평부 끝까지 당겨도 부족


def test_manual_stair_offset_rules():
    with pytest.raises(ValueError, match="0 이하"):
        lay_of(cfg_with({"stair_offset": 0.5}))
    with pytest.raises(ValueError, match="하부 수평부"):
        lay_of(cfg_with({"stair_offset": -20.0}))
    lay = lay_of(cfg_with({"stair_offset": -4.2}))
    assert lay.u["stair0"] == pytest.approx(lay.u["cross"] - 4.2)


def test_roof_clearance_and_end_at_ground():
    lay = lay_of(cfg_with())
    nose = nose_fn(lay)
    roof = next(p for p in lay.box_parts if p.code == "ROOF").strips
    u_re = lay.u["roof_end"]
    assert roof[-1].s1 == pytest.approx(u_re)
    assert roof[-1].zt_end == pytest.approx(lay.ground, abs=1e-6)                       # 천장 상면이 지표에 닿는 점에서 끝
    for st in roof:                                                                     # 천장 하면 ≥ 코 선 + 에스컬레이터 머리 높이
        for x, zb in ((st.s0, st.zb0), (st.s1, st.zb1)):
            assert zb >= nose(x) + lay.spec.esc_headroom - 1e-6
    bottom = lambda x: next(s for s in roof if s.s0 - 1e-9 <= x <= s.s1 + 1e-9).zb_at(x)
    gaps = [bottom(x) - zt for p in lay.stair.parts for ua, ub, zt in p.surfaces for x in (ua + lay.u["stair0"], ub + lay.u["stair0"])
            if x < u_re]
    assert min(gaps) >= lay.spec.stair_headroom - 1e-6                                 # 천장 아래 계단 머리 높이
    assert min(gaps) == pytest.approx(lay.spec.stair_headroom, abs=1e-6) or lay.roof_clear == pytest.approx(2.3)


def test_box_parts_layout():
    lay = lay_of(cfg_with())
    sp, u = lay.spec, lay.u
    codes = {p.code for p in lay.box_parts}
    assert codes == {"FLOOR_S", "FLOOR_E", "ROOF", "WALL_L", "WALL_R", "END_WALL_S", "END_WALL_E",
                     "JOINT_WALL_L", "JOINT_WALL_R", "PARTITION", "PARAPET", "LANDING_E"}
    a, b = sp.inner_width / 2, sp.inner_width / 2 + sp.wall_t
    part = {p.code: p for p in lay.box_parts}
    assert part["WALL_L"].t_range == pytest.approx((a, b)) and part["ROOF"].t_range == pytest.approx((-b, b))
    assert part["JOINT_WALL_L"].t_range == pytest.approx((2.0, a))                      # 통로 내공(±2.0) 바깥만 막음
    open_tops = [st.zt_end for st in part["WALL_L"].strips if st.s0 >= u["roof_end"] - 1e-9]
    assert open_tops and all(z == pytest.approx(lay.ground + sp.parapet) for z in open_tops)
    assert part["END_WALL_S"].strips[0].s0 == pytest.approx(u["top"]) and part["END_WALL_S"].strips[-1].s1 == pytest.approx(u["end"])
    assert part["PARTITION"].t_range == pytest.approx(sp.zones()["partition"])


def test_without_escalator():
    lay = lay_of(cfg_with({"escalator": False, "stair_width": 4.6}))
    assert lay.escalator is None and lay.spec.inner_width == pytest.approx(4.6)
    assert {p.code for p in lay.box_parts} >= {"FLOOR_S", "ROOF"} and "PARTITION" not in {p.code for p in lay.box_parts}


# ===================================================== 검증
@pytest.mark.parametrize("kw,msg", [
    ({"passage": "NOPE"}, "출구통로"),
    ({"escalator_side": 0}, "에스컬레이터 쪽"),
    ({"stair_width": 0.0}, "계단 폭"),
    ({"landing_len": 0.2}, "단너비"),
    ({"haunch_w": 0.3, "haunch_h": 0.0}, "헌치"),
    ({"escalator_zone": 1.0, "stair_width": 3.0}, "트러스 외폭"),
    ({"stair_width": 1.0, "escalator": False}, "통로 내공 폭"),
])
def test_invalid_entrance_rejected(kw, msg):
    cfg = cfg_with()
    base = cfg.entrances[0]
    cfg.entrances = [EntranceSpec(**{**base.__dict__, **kw})]
    with pytest.raises(ValueError, match=msg):
        StationCADEngine(cfg)


def test_shallow_ground_and_duplicate_rejected():
    with pytest.raises(ValueError, match="토피|충분히"):
        StationCADEngine(cfg_with(rise=3.5))
    cfg = cfg_with()
    cfg.entrances = cfg.entrances * 2
    with pytest.raises(ValueError, match="이미 출입구"):
        StationCADEngine(cfg)


# ===================================================== 체적 교차 검증 (공식 ↔ 3D 메쉬 ↔ IFC)
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("curved", [False, True])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, curved):
    eng = StationCADEngine(cfg_with({"escalator_side": -1}, passages=[bent_passage()], curved=curved))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "e.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    ent = eng.entrances.entrances[0]
    for name, m in eng.entrances.strip_members(ent):
        formula = m.shape.volume + sum(p.volume for p in getattr(m, "pieces", []))
        mesh = sum(PM.mesh_volume(q) for q in part_faces(ent.frame, m)) + \
            sum(PM.mesh_volume(p.faces()) for p in getattr(m, "pieces", []))
        assert mesh == pytest.approx(formula, rel=1e-7, abs=1e-8)
        assert ifc_world_volume(by_name[name]) == pytest.approx(formula, rel=1e-6, abs=1e-8)


def test_ifc_structure(tmp_path):
    eng = StationCADEngine(cfg_with())
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "e.ifc"))
    asm = next(a for a in f.by_type("IfcElementAssembly") if a.ObjectType == "ENTRANCE")
    assert asm.Name == "EN1" and ifcopenshell.util.element.get_container(asm).Name == "B1F"
    kids = ifcopenshell.util.element.get_decomposition(asm)
    stair = next(k for k in kids if k.is_a("IfcStair"))
    esc = next(k for k in kids if k.is_a("IfcTransportElement"))
    assert esc.PredefinedType == "ESCALATOR" and stair.PredefinedType == "STRAIGHT_RUN_STAIR"
    flights = [k for k in kids if k.is_a("IfcStairFlight")]
    ent = eng.entrances.entrances[0]
    assert len(flights) == len(ent.layout.stair.flight_risers)
    assert sum(fl.NumberOfRisers for fl in flights) == ent.layout.stair.n_risers
    walls = [k for k in kids if k.is_a("IfcWall") and k.Name.startswith("EN1_")]
    assert {w.Name for w in walls} >= {"EN1_WALL_L", "EN1_WALL_R", "EN1_PARTITION", "EN1_END_WALL_S"}
    roof = next(k for k in kids if k.is_a("IfcSlab") and k.Name == "EN1_ROOF")
    assert roof.PredefinedType == "ROOF" and len(roof.Representation.Representations[0].Items) > len(ent.element("ROOF").shape.strips)


# ===================================================== 도면
def test_3d_dxf_and_section(tmp_path):
    eng = StationCADEngine(cfg_with(passages=[bent_passage()]))
    ent = eng.entrances.entrances[0]
    msp = ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace()
    faces = list(msp.query('3DFACE[layer=="STRUCT_ENTRANCE"]'))
    esc_names = {p.name for p in list(ent.escalator.parts) + list(ent.escalator.steps)}
    members = eng.entrances.strip_members(ent)
    expect = sum(len(fs) for n, m in members if n not in esc_names for fs in part_faces(ent.frame, m)) + \
        sum(len(p.faces()) for p in ent.element("ROOF").pieces)
    assert len(faces) == expect                                                         # 박스·계단 = 콘크리트 레이어
    esc = [m for n, m in members if n in esc_names]                                     # 에스컬레이터 = 에스컬레이터 레이어
    assert {e.dxf.layer for m in esc for e in m.source_element} == {"STRUCT_ESCALATOR", "STRUCT_ESC_GLASS"}
    assert sum(len(m.source_element) for m in esc) == sum(len(fs) for m in esc for fs in part_faces(ent.frame, m))
    sta = 70.0 + ent.layout.u["wp_lo"] + 10.0                                           # 경사부를 가로지르는 횡단면
    items = eng.entrances.section_items(sta)
    names = {it.name for it in items}
    assert {"EN1_ROOF", "EN1_FLOOR_S", "EN1_WALL_L"} <= names and any(n.startswith("EN1_ESC_") for n in names)
    assert [it.label[0] for it in items if it.label] == ["EN1"]
    path = eng.generate_section_dxf([sta], tmp_path / "s.dxf")
    assert "EN1" in [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]


def test_build_all_outputs(tmp_path):
    from engine.bim_engine import BIMEngine
    for curved in (False, True):
        paths = BIMEngine.build(cfg_with(passages=[bent_passage()], curved=curved), tmp_path / str(curved))
        assert len(paths) == 5 and all(os.path.getsize(p) > 0 for p in paths)


def test_no_entrances_keeps_outputs():
    eng = StationCADEngine(make_cfg(user_example()))
    assert eng.entrances.entrances == []


# ===================================================== 정거장 공통 지표 EL
def test_blank_ground_uses_station_ground_el():
    cfg = cfg_with()
    G = cfg.entrances[0].ground_el
    ref = lay_of(cfg)
    cfg.entrances[0].ground_el = None
    with pytest.raises(ValueError, match="지표 EL 을 입력하세요"):
        cfg.entrance_layouts()
    cfg.station.ground_el = G
    lay = lay_of(cfg)
    assert lay.ground == pytest.approx(G) and lay.u == pytest.approx(ref.u)
    cfg.entrances[0].ground_el = G + 1.0                                       # 출입구마다 덮어쓰기
    assert lay_of(cfg).ground == pytest.approx(G + 1.0)


# ===================================================== 입력 초안
from gui.entrance_draft import SIDE_RIGHT, EntranceDraft, EntranceDrafts, preview


def test_draft_converts():
    d = EntranceDrafts()
    d.items = [EntranceDraft(name="A", passage="EX2", side=SIDE_RIGHT, ground_el="109.3", tread="0.28", stair_offset="")]
    (sp,) = d.to_specs()
    assert (sp.name, sp.passage, sp.escalator_side, sp.ground_el, sp.tread, sp.stair_offset) == ("A", "EX2", -1, 109.3, 0.28, None)
    d.items[0].stair_offset = "-2"
    assert d.to_specs()[0].stair_offset == -2.0
    d.items[0].ground_el = " "
    assert d.to_specs()[0].ground_el is None and "정거장 공통 지표 EL" in preview(d.items[0])
    assert EntranceDraft().ground_el == ""


@pytest.mark.parametrize("field,value,msg", [
    ("ground_el", "x", r"출입구 1: 지표 EL"),
    ("wall_t", "0", "벽·슬래브 두께"),
    ("passage", " ", "출구통로"),
    ("side", "위", "에스컬레이터 쪽"),
])
def test_draft_errors(field, value, msg):
    d = EntranceDrafts(); d.items = [EntranceDraft()]
    setattr(d.items[0], field, value)
    with pytest.raises(ValueError, match=msg):
        d.to_specs()


def test_draft_preview():
    assert "내공 폭 5.26m" in preview(EntranceDraft())
    assert "내공 폭 1.75m" in preview(EntranceDraft(escalator=False))
    assert "확인" in preview(EntranceDraft(stair_width="a"))


# ===================================================== 리팩토링 1단계: 두께 구간 · 계단참 따라 꺾이는 천장 · 흙 덮개 · 버림 콘크리트
ZONES = [(0.0, 0.9), (14.0, 0.8), (24.0, 0.7)]          # 실무 도면처럼 깊은(이음면 쪽) 구간이 두꺼움


def test_thickness_zones_step_outer_faces():
    lay = lay_of(cfg_with({"thickness_zones": ZONES, "wall_t": 0.7}))
    sp = lay.spec
    a = sp.inner_width / 2
    part = {p.code: p for p in lay.box_parts}
    for k, (u0, th) in enumerate(ZONES, start=1):
        w = part[f"WALL_L_Z{k}"]
        assert w.t_range == pytest.approx((a, a + th)) and w.thick == pytest.approx(th)             # 내공면 고정, 바깥면만
        assert w.strips[0].s0 == pytest.approx(u0)
        assert part[f"ROOF_Z{k}"].t_range == pytest.approx((-(a + th), a + th)) if f"ROOF_Z{k}" in part else True
        tan = math.tan(math.radians(30.0))
        par = [st for st in part[f"FLOOR_S_Z{k}"].strips                                     # 경사부(상·하면 나란함)
               if abs((st.zb1 - st.zb0) / (st.s1 - st.s0) - tan) < 1e-9 and abs((st.zt_end - st.zt) / (st.s1 - st.s0) - tan) < 1e-9]
        assert par and all(st.zt - st.zb0 == pytest.approx(th * math.sqrt(1 + tan * tan)) for st in par)   # 직각 두께 = 구간 두께
    assert part["END_WALL_S"].thick == pytest.approx(0.7) and lay.u["end"] - lay.u["top"] == pytest.approx(0.7)
    assert part["JOINT_WALL_L"].thick == pytest.approx(0.9) and lay.u["truss_lo"] == pytest.approx(0.9 + sp.lower_margin)
    plain = lay_of(cfg_with())
    assert "WALL_L" in {p.code for p in plain.box_parts}                                     # 구간 없으면 예전 이름


def test_roof_follows_stair_landings_and_cover():
    lay = lay_of(cfg_with())
    roof = sorted((s for p in lay.box_parts if p.code.startswith("ROOF") for s in p.strips), key=lambda s: s.s0)
    u_re = lay.u["roof_end"]
    bottom = lambda x: next(s for s in roof if s.s0 - 1e-9 <= x <= s.s1 + 1e-9).zb_at(x)
    nose = nose_fn(lay)
    u0 = lay.u["stair0"]
    noses = [(u0 + ua, zt) for p in lay.stair.parts for ua, ub, zt in p.surfaces if u0 + ua < u_re]
    gaps = [bottom(x) - z for x, z in noses]
    assert min(gaps) == pytest.approx(lay.spec.stair_headroom, abs=1e-6)                     # 디딤판 코 위 계단 머리 높이
    assert all(bottom(x) >= nose(x) + lay.spec.esc_headroom - 1e-6 for x in (s.s0 for s in roof) if x > lay.u["wp_lo"])
    landings = [(u0 + ua, u0 + ub) for p in lay.stair.parts if p.kind.value == "LANDING" for ua, ub, zt in p.surfaces
                if u0 + ub < u_re]
    flat = [s for s in roof if abs(s.zb1 - s.zb0) < 1e-9 and s.s0 > lay.u["wp_lo"]]
    assert landings and flat                                                                 # 계단참에서 천장이 수평으로 꺾임
    assert all(any(l0 - 1e-6 <= s.s0 <= l1 + 1e-6 for l0, l1 in landings) for s in flat)
    # 흙 덮개: 천장 상면이 지표 − 덮개에 닿는 곳에서 끝
    cov = lay_of(cfg_with({"roof_cover": 1.5}))
    last = max((s for p in cov.box_parts if p.code.startswith("ROOF") for s in p.strips), key=lambda s: s.s1)
    assert last.zt_end == pytest.approx(cov.ground - 1.5, abs=1e-6) and cov.u["roof_end"] < u_re


def test_lean_concrete_under_floor(tmp_path):
    eng = StationCADEngine(cfg_with({"lean_t": 0.14, "thickness_zones": ZONES}))
    lay = eng.entrances.entrances[0].layout
    a = lay.spec.inner_width / 2
    part = {p.code: p for p in lay.box_parts}
    for k, (u0, th) in enumerate(ZONES, start=1):
        ln = part[f"LEAN_Z{k}"]
        assert ln.t_range == pytest.approx((-(a + th + 0.155), a + th + 0.155))
        fl = part[f"FLOOR_S_Z{k}"]
        x = (ln.strips[0].s0 + ln.strips[0].s1) / 2
        assert ln.strips[0].zt_at(x) == pytest.approx(next(s for s in fl.strips if s.s0 <= x <= s.s1).zb_at(x), abs=1e-9)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "l.ifc"))
    lean = [s for s in f.by_type("IfcSlab") if "_LEAN_" in s.Name]
    assert len(lean) == 3 and all(s.PredefinedType == "BASESLAB" for s in lean)
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    ent = eng.entrances.entrances[0]
    for name, m in eng.entrances.strip_members(ent):                                         # 구간 부재도 체적 교차 검증
        formula = m.shape.volume + sum(p.volume for p in getattr(m, "pieces", []))
        mesh = sum(PM.mesh_volume(q) for q in part_faces(ent.frame, m)) + \
            sum(PM.mesh_volume(p.faces()) for p in getattr(m, "pieces", []))
        assert mesh == pytest.approx(formula, rel=1e-7)
        assert ifc_world_volume(by_name[name]) == pytest.approx(formula, rel=1e-6)


@pytest.mark.parametrize("zones,msg", [([(5.0, 0.0)], "두께는 0보다"), ([(-1.0, 0.8)], "0 이상"),
                                       ([(3.0, 0.8), (3.0, 0.9)], "겹칩니다")])
def test_thickness_zone_errors(zones, msg):
    with pytest.raises(ValueError, match=msg):
        StationCADEngine(cfg_with({"thickness_zones": zones}))


def test_draft_zones_and_window(tmp_path):
    from gui.entrance_draft import EntranceDraft, zones_summary
    d = EntranceDraft(passage="EX1", thick_zones=[["14", "0.8"], ["", ""], ["0", "0.9"]], roof_cover="1", lean_t="0.14")
    sp = d.to_spec("출입구")
    assert sp.thickness_zones == [(0.0, 0.9), (14.0, 0.8)] and sp.roof_cover == 1.0 and sp.lean_t == 0.14
    assert zones_summary(d) == "두께 구간: u 0~ 0.9, u 14~ 0.8"
    d.thick_zones = [["a", "0.8"]]
    with pytest.raises(ValueError, match="두께 구간 1"):
        d.to_spec("출입구")
    import tkinter as tk
    from gui.gui_app import StationBIMApp
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("디스플레이가 없어 GUI 테스트를 건너뜀")
    app = StationBIMApp(root, recent_file=str(tmp_path / "recent.json"), watch=False)
    try:
        et = app.entrance_tab
        et.add_entrance()
        it = et.drafts.items[0]
        win = et.open_zones(0)
        win.update()
        it_add = [w for w in win.winfo_children() if isinstance(w, tk.Frame)][-1].winfo_children()[0]
        it_add.invoke()                                                                      # + 구간 추가
        assert it.thick_zones == [["0", it.wall_t]] and "u 0~" in et._zone_labels[0].cget("text")
        et._zone_vars[0][1].set("0.9")
        assert it.thick_zones[0][1] == "0.9" and "0.9" in et._zone_labels[0].cget("text")
        from gui.project_file import open_project, save_project
        save_project(tmp_path / "z.ssbim", app.collect_state())                             # 프로젝트 파일 왕복
        assert open_project(tmp_path / "z.ssbim").entrance_drafts[0].thick_zones == [["0", "0.9"]]
        win.destroy()
    finally:
        root.destroy()


# ===================================================== 리팩토링 2단계: 정거장 상세 에스컬레이터
def test_entrance_escalator_detail_steps_and_floor_clearance(tmp_path):
    from escalators.escalator_type import EscalatorPartKind as EK
    from exporter.dae_exporter import element_materials, stair_face_frames
    eng = StationCADEngine(cfg_with())
    ent = eng.entrances.entrances[0]
    esc, lay = ent.escalator, ent.layout
    kinds = {p.kind for p in esc.parts}
    assert {EK.TRUSS, EK.SKIRT, EK.INNER_DECK, EK.OUTER_DECK, EK.NEWEL_BASE, EK.FLOOR_PLATE, EK.COMB, EK.CLAD_SIDE} <= kinds
    assert EK.STEPS not in kinds and len(esc.steps) > 50                                      # 개별 스텝
    nl = lay.escalator.nose
    assert len(nl.arcs) == 2                                                                   # 곡선 전이 (하부·상부)
    u_wp = lay.escalator.u_wp
    for a, b in zip(esc.steps, esc.steps[1:]):                                                 # 스텝 코가 코 선 위, 겹침 없음
        ta = max(a.shape.strips, key=lambda s: s.s1 - s.s0)
        assert ta.zt == pytest.approx(nl(a.chain_u)) and ta.s1 <= b.shape.strips[0].s0 + 1e-9
    # 트러스(외장 아래) 하면 ≥ 에스컬레이터 구역 바닥 상면 (상부 볼록 전이에서도 바닥을 파고들지 않음)
    floor = ent.element("FLOOR_E").shape.strips
    for st in next(p for p in esc.parts if p.kind == EK.CLAD_BOTTOM).shape.strips:
        for x in (st.s0 + 1e-6, (st.s0 + st.s1) / 2, st.s1 - 1e-6):                         # 띠 안쪽 (경계의 값 뜀 제외)
            ft = [f.zt_at(x) for f in floor if f.s0 < x < f.s1]
            assert st.zb_at(x) >= max(ft) - 1e-6, x
    # 보기 재질: 핸드레일 검정·스텝 텍스처, 스텝마다 디딤판 텍스처 틀
    eng.build_3d_doc()
    mats = element_materials(eng)
    rail = next(p for p in esc.parts if p.kind == EK.HANDRAIL)
    assert {mats[e.dxf.handle].name for e in rail.source_element} == {"에스컬레이터 핸드레일"}
    frames = stair_face_frames(eng)
    assert all(len(s.face_frames) == 6 and set(s.face_frames) <= set(frames) for s in esc.steps)
    # IFC: 스텝 = IfcBuildingElementPart STEP + Pset
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "s.ifc"))
    steps = [e for e in f.by_type("IfcBuildingElementPart") if e.Name.startswith("EN1_ESC_STEP")]
    assert len(steps) == len(esc.steps) and all(s.ObjectType == "STEP" for s in steps)
    assert ifcopenshell.util.element.get_psets(steps[3])["SSBIM_EscalatorStep"]["Index"] == 3


def test_entrance_escalator_starts_at_passage_finished_floor():
    from finishes.finish_spec import FinishSettings
    cfg = cfg_with()
    cfg.finish_settings = FinishSettings(enabled=True)
    lay = lay_of(cfg)
    ffl = cfg.finish_settings.for_room("통로").ffl
    zl, G = lay.escalator.finish_levels
    assert zl == pytest.approx(lay.z_floor + ffl) and G == pytest.approx(lay.ground)       # 스텝 면 = 통로 바닥 마감면 ~ 지표
    assert lay.escalator.nose(-5.0) == pytest.approx(zl) and lay.escalator.rise == pytest.approx(G - zl)


# ===================================================== 리팩토링 3단계: 계단 마감 (계단석 분리 구조)
def _fin_cfg(**kw):
    from finishes.finish_spec import FinishSettings
    cfg = cfg_with(kw or {})
    cfg.finish_settings = FinishSettings(enabled=True)
    return cfg


@pytest.mark.parametrize("method", ["plate", "solid", "concrete"])
def test_entrance_stair_finish_stack(method):
    import dataclasses as dc
    import random
    cfg = _fin_cfg()
    cfg.finish_settings.stair = dc.replace(cfg.finish_settings.stair, method=method)
    eng = StationCADEngine(cfg)
    ent = eng.entrances.entrances[0]
    lay, st = ent.layout, ent.stair
    zl = lay.escalator.finish_levels[0]
    assert st.finishes and lay.stair.finish_base == pytest.approx(zl)
    srf = sorted(s for p in st.parts for s in p.surfaces)
    assert srf[0][2] == pytest.approx(zl + lay.stair.riser)                                   # 첫 디딤판 = 마감면 + 단높이
    members = [(p.t_range, s) for p in st.parts for s in p.shape.strips] + \
        [(f.t_range, s) for f in st.finishes for s in f.shape.strips]
    tc = (lay.spec.stair_spec().t_lo + lay.spec.stair_spec().t_hi) / 2
    u_lo, u_hi = srf[0][0] + 0.05, lay.u["top"] - 0.05
    rng = random.Random(5)
    for _ in range(300):                                                                       # 연직 쌓임: 겹침·빈틈 없음, 맨 위 = 걷는 면
        u = rng.uniform(u_lo, u_hi)
        col = sorted((s.zb_at(u), s.zt_at(u)) for (t0, t1), s in members if t0 < tc < t1 and s.s0 < u < s.s1)
        col = [c for c in col if c[1] - c[0] > 1e-9]
        for (b0, t0_), (b1, t1_) in zip(col, col[1:]):
            assert t0_ <= b1 + 1e-6 and b1 - t0_ < 1e-6, (u, col)
        cover = [z for a, b, z in srf if a - 1e-9 <= u <= b + 1e-9]                       # 디딤판·계단참 (출입구 좌표)
        walk = max(cover) if cover else lay.ground                                           # 마지막 디딤판 뒤 = 지표 높이 도착부
        assert col[-1][1] == pytest.approx(walk, abs=1e-6), (u, col[-1], walk)


def test_entrance_stair_finish_sides_textures_and_ifc(tmp_path):
    from exporter.dae_exporter import stair_face_frames
    eng = StationCADEngine(_fin_cfg())
    ent = eng.entrances.entrances[0]
    sp = ent.layout.spec.stair_spec()
    side = [f for f in ent.stair.finishes if f.code == "SIDE"]
    part_t = ent.layout.spec.zones()["partition"]
    assert side and all(abs(f.t_range[1] - part_t[0]) < 1e-9 or abs(f.t_range[0] - part_t[1]) < 1e-9 for f in side)   # 에스컬레이터(칸막이) 쪽만
    assert all(f.t_range[0] > sp.t_lo + 1e-6 or f.t_range[1] < sp.t_hi - 1e-6 for f in side)
    eng.build_3d_doc()
    frames = stair_face_frames(eng)
    tread = [f for f in ent.stair.finishes if f.code == "TREAD"]
    assert tread and all(f.face_frames and set(f.face_frames) <= set(frames) for f in tread)       # 디딤판마다 계단석 한 장
    assert {e.dxf.layer for f in ent.stair.finishes for e in f.source_element} == {"FIN_STAIR"}
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "f.ifc"))
    covs = [c for c in f.by_type("IfcCovering") if c.Name.startswith("EN1_STAIR_FIN_")]
    assert len(covs) == len(ent.stair.finishes)
    rel = next(r for r in f.by_type("IfcRelCoversBldgElements") if r.RelatingBuildingElement.Name == "EN1_STAIR")
    assert set(rel.RelatedCoverings) == set(covs)
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    for name, m in eng.entrances.strip_members(ent):                                           # 마감 포함 체적 교차 검증
        if not name.startswith("EN1_STAIR"):
            continue
        formula = m.shape.volume
        mesh = sum(PM.mesh_volume(q) for q in part_faces(ent.frame, m))
        assert mesh == pytest.approx(formula, rel=1e-7, abs=1e-8)
        assert ifc_world_volume(by_name[name]) == pytest.approx(formula, rel=1e-6, abs=1e-8)


# ===================================================== 리팩토링 4단계: 내부 마감
def test_entrance_interior_finish_headroom_and_extent():
    cfg = _fin_cfg()
    lay = lay_of(cfg)
    ft = lay.finish_type
    assert ft.name == "통로" and lay.ceiling_raise == pytest.approx(ft.board_t + ft.frame_depth + 0.3 * (1 - ft.face / 0.3))
    fin = {c: (k, m, t, st) for c, k, m, t, st in lay.finish}
    ceil = sorted(fin["FIN_CEILING"][3] + fin["FIN_CEILING_J"][3], key=lambda s: s.s0)
    roof = sorted((s for p in lay.box_parts if p.code.startswith("ROOF") for s in p.strips), key=lambda s: s.s0)
    for st in fin["FIN_CEILING"][3]:                                                         # 천장판 하면 = 천장 슬래브 하면 − 올림
        x = (st.s0 + st.s1) / 2
        r_ = next(s for s in roof if s.s0 <= x <= s.s1)
        assert r_.zb_at(x) - st.zb_at(x) == pytest.approx(lay.ceiling_raise, abs=1e-6)
    cb = lambda x: next(s for s in ceil if s.s0 - 1e-9 <= x <= s.s1 + 1e-9).zb_at(x)
    u0 = lay.u["stair0"]
    noses = [(ua, zt) for p in lay.stair.parts for ua, ub, zt in [(a + u0, b + u0, z) for a, b, z in p.surfaces] if ua < lay.u["roof_end"]]
    assert min(cb(x) - z for x, z in noses) == pytest.approx(lay.spec.stair_headroom, abs=1e-6)     # 천장판 아래 계단 머리 높이
    nose = lay.escalator.nose
    u_wp = lay.escalator.u_wp
    assert all(cb(s.s0) >= nose(s.s0 - u_wp) + lay.spec.esc_headroom - 1e-6 for s in ceil if s.s0 > lay.u["wp_lo"])
    zl = lay.escalator.finish_levels[0]
    assert all(st.zt == pytest.approx(zl) for c in fin if c.startswith("FIN_FLOOR") for st in fin[c][3])   # 바닥 = 통로 마감면
    op = [st for st in fin["FIN_WALL_R"][3] + fin["FIN_WALL_L"][3] if st.s0 >= lay.u["roof_end"] - 1e-9]
    assert op and all(st.zt_end == pytest.approx(lay.ground + lay.spec.parapet) for st in op)          # 개구부 = 파라펫 윗면까지
    assert not lay_of(cfg_with()).finish and lay_of(cfg_with()).ceiling_raise == 0.0               # 마감 끔 = 없음


def test_entrance_interior_finish_no_overlap_and_volumes(tmp_path):
    import random
    eng = StationCADEngine(_fin_cfg())
    ent = eng.entrances.entrances[0]
    members = eng.entrances.strip_members(ent)
    fins = [(n, m) for n, m in members if n.split("_", 1)[1].startswith("FIN_")]
    others = [(n, m) for n, m in members if (n, m) not in fins]
    boxes = [(n, m.t_range, s) for n, m in members for s in m.shape.strips]
    rng = random.Random(9)
    for n, m in fins:                                                                          # 무작위 점: 다른 부재 안에 들지 않음
        t0, t1 = m.t_range
        for st in m.shape.strips:
            for _ in range(4):
                u = rng.uniform(st.s0, st.s1)
                t = rng.uniform(t0, t1)
                z = rng.uniform(st.zb_at(u), st.zt_at(u))
                if st.zt_at(u) - st.zb_at(u) < 1e-6:
                    continue
                for n2, (a0, a1), s2 in boxes:
                    if n2 == n or not (a0 + 1e-9 < t < a1 - 1e-9 and s2.s0 + 1e-9 < u < s2.s1 - 1e-9):
                        continue
                    assert not (s2.zb_at(u) + 1e-7 < z < s2.zt_at(u) - 1e-7), (n, n2, u, t, z)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "i.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    for n, m in fins:
        formula = m.shape.volume
        assert sum(PM.mesh_volume(q) for q in part_faces(ent.frame, m)) == pytest.approx(formula, rel=1e-7, abs=1e-8)
        assert ifc_world_volume(by_name[n]) == pytest.approx(formula, rel=1e-6, abs=1e-8)
    kinds = {e.Name: e.PredefinedType for e in f.by_type("IfcCovering")}
    assert kinds["EN1_FIN_CEILING"] == "CEILING" and kinds["EN1_FIN_WALL_L"] == "CLADDING" and kinds["EN1_FIN_FLOOR1"] == "FLOORING"
    assert {e.dxf.layer for n, m in fins for e in m.source_element or []} <= {"FIN_FLOOR", "FIN_WALL", "FIN_CEILING", "FIN_FRAME"}


def test_entrance_finish_override_and_draft():
    from gui.entrance_draft import EntranceDraft
    cfg = _fin_cfg()
    cfg.entrances[0].finish = "화장실"
    lay = lay_of(cfg)
    assert lay.finish_type.name == "화장실" and next(m for c, k, m, t, s in lay.finish if c == "FIN_WALL_L") == "타일"
    cfg = _fin_cfg()
    cfg.passages[0].finish = "역무실"                                                          # 비우면 통로의 마감 종류
    assert lay_of(cfg).finish_type.name == "역무실"
    d = EntranceDraft(passage="EX1", finish="화장실")
    assert d.to_spec("출입구").finish == "화장실" and EntranceDraft(passage="EX1").to_spec("출입구").finish == ""


# ===================================================== 지상부 1단계: 계단만·ESC 만·ESC n대 + 개구부 시작부 파라펫
def test_escalator_only_and_multiple_escalators(tmp_path):
    from escalators.escalator_type import EscalatorPartKind as EK
    cfg = cfg_with({"stair": False, "escalator_count": 2, "escalator_side": 1})
    eng = StationCADEngine(cfg)
    ent = eng.entrances.entrances[0]
    sp = ent.layout.spec
    assert ent.stair is None and len(ent.escalators) == 2
    assert sp.inner_width == pytest.approx(sp.escalator_zone + sp.esc_truss_width)            # 둘째 대는 트러스 폭만큼만
    z = sp.zones()["escalators"]
    assert z[0][1] == pytest.approx(z[1][0])                                                   # 대 사이 이격 없음
    names = {e.name for e in ent.escalators}
    assert names == {"EN1_ESC1", "EN1_ESC2"}
    clad = [next(p for p in e.parts if p.kind == EK.CLAD_SIDE and p.side == 1) for e in ent.escalators]
    out = [next(p for p in e.parts if p.kind == EK.CLAD_SIDE and p.side == -1) for e in ent.escalators]
    assert clad[0].t_range[1] == pytest.approx(out[1].t_range[0])                              # 트러스 외장끼리 이격 없이 붙음
    m = (sp.escalator_zone - sp.esc_truss_width) / 2
    assert ent.escalators[0].t_range[0] == pytest.approx(-sp.inner_width / 2 + m)              # 벽 쪽 여유 = 1대일 때와 같음
    codes = {p.code for p in ent.layout.box_parts}
    assert "FLOOR_S" not in codes and "PARTITION" not in codes and "END_WALL_S" not in codes and "FLOOR_E" in codes
    # 두 측벽 모두 에스컬레이터 쪽 바닥(트러스 하면) 위
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "m.ifc"))
    assert len([t for t in f.by_type("IfcTransportElement") if t.Name.startswith("EN1_ESC")]) == 2
    assert not [s for s in f.by_type("IfcStair") if s.Name.startswith("EN1")]
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    for name, m in eng.entrances.strip_members(ent):
        formula = m.shape.volume + sum(p.volume for p in getattr(m, "pieces", []))
        assert ifc_world_volume(by_name[name]) == pytest.approx(formula, rel=1e-6, abs=1e-8)
    # 계단 + 에스컬레이터 3대: 계단 | 칸막이 | ESC × 3
    lay = lay_of(cfg_with({"escalator_count": 3}))
    z = lay.spec.zones()
    m = (lay.spec.escalator_zone - lay.spec.esc_truss_width) / 2
    assert len(lay.escalators) == 3 and z["escalators"][0][0] == pytest.approx(z["partition"][1] + m)     # 칸막이 쪽 여유
    assert z["escalators"][1][0] == pytest.approx(z["escalators"][0][1]) and z["escalators"][2][1] == pytest.approx(z["escalator"][1] - m)
    assert lay.spec.inner_width == pytest.approx(lay.spec.stair_width + lay.spec.partition_t + lay.spec.escalator_zone
                                                 + 2 * lay.spec.esc_truss_width)


def test_stair_only_and_rules():
    lay = lay_of(cfg_with({"escalator": False, "stair_width": 4.6}))
    assert lay.escalators == [] and lay.stair is not None
    with pytest.raises(ValueError, match="하나는 있어야"):
        StationCADEngine(cfg_with({"escalator": False, "stair": False}))
    with pytest.raises(ValueError, match="대수"):
        StationCADEngine(cfg_with({"escalator_count": 0}))


def test_roof_end_parapet():
    lay = lay_of(cfg_with())
    sp = lay.spec
    par = next(p for p in lay.box_parts if p.code == "PARAPET")
    u_re = lay.u["roof_end"]
    T = sp.thick_at(u_re)
    a = sp.inner_width / 2
    assert par.t_range == pytest.approx((-(a + T), a + T))
    assert par.strips[0].s0 == pytest.approx(u_re - T) and par.strips[-1].s1 == pytest.approx(u_re)
    assert all(st.zt == pytest.approx(lay.ground + sp.parapet) for st in par.strips)
    roof = max((s for p in lay.box_parts if p.code.startswith("ROOF") for s in p.strips), key=lambda s: s.s1)
    assert par.strips[-1].zb1 == pytest.approx(roof.zt_end)                                    # 천장 상면 위에 섬


def test_draft_stair_and_count():
    from gui.entrance_draft import EntranceDraft, preview
    d = EntranceDraft(passage="EX1", stair=False, escalator_count="2")
    sp = d.to_spec("출입구")
    assert not sp.stair and sp.escalator_count == 2 and "2대 붙임" in preview(d) and "계단 없음" in preview(d)
    d.escalator_count = "x"
    with pytest.raises(ValueError, match="정수"):
        d.to_spec("출입구")
    d.escalator, d.escalator_count = False, "1"
    with pytest.raises(ValueError, match="하나는"):
        d.to_spec("출입구")


# ===================================================== 지상부 2단계: 상부 승강구 높임 + 바깥 경사로·계단
def test_raised_top_landing_ramp_and_steps(tmp_path):
    import math as _m
    cfg = cfg_with({"top_rise": 0.45, "ramp_width": 1.2, "ramp_ratio": 12.0, "parapet": 0.6})
    eng = StationCADEngine(cfg)
    ent = eng.entrances.entrances[0]
    lay = ent.layout
    G, Gt = lay.ground, lay.top_level
    assert Gt == pytest.approx(G + 0.45)
    assert lay.escalator.finish_levels[1] == pytest.approx(Gt)                               # 에스컬레이터 위 끝 = 승강구
    top = max(z for p in lay.stair.parts for _, _, z in p.surfaces)
    assert top <= Gt + 1e-9 and lay.stair.parts[-1].strips[-1].zt == pytest.approx(Gt)        # 계단 도착 = 승강구
    part = {p.code: p for p in lay.box_parts}
    assert all(st.zt_end == pytest.approx(Gt) for st in part["END_WALL_S"].strips)           # 앞면 개방 (끝벽 = 승강구 높이까지)
    ramp, stair = part["OUT_RAMP"], part["OUT_STAIR"]
    a = lay.spec.inner_width / 2
    assert ramp.t_range == pytest.approx((a - 1.2, a))                                       # 에스컬레이터 쪽(+t) 벽 옆
    (rs,) = ramp.strips
    assert (rs.s0, rs.zt, rs.zt_end) == (pytest.approx(lay.u["end"]), pytest.approx(Gt), pytest.approx(G))
    assert rs.s1 - rs.s0 == pytest.approx(0.45 * 12)
    n = _m.ceil(0.45 / lay.spec.out_riser_max - 1e-9)
    assert len(stair.strips) == n - 1 and stair.t_range == pytest.approx((-a, a - 1.2))
    assert [st.zt for st in stair.strips] == pytest.approx([Gt - k * 0.45 / n for k in range(1, n)])
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "r.ifc"))
    assert [e.Name for e in f.by_type("IfcRampFlight")] == ["EN1_OUT_RAMP"]
    assert "EN1_OUT_STAIR" in [e.Name for e in f.by_type("IfcStairFlight")]
    # 높임 없으면 예전 (끝벽 = 지표 + 파라펫, 바깥 부재 없음)
    plain = lay_of(cfg_with())
    assert not [p for p in plain.box_parts if p.code.startswith("OUT")]
    assert plain.top_level == pytest.approx(plain.ground)


def test_raised_landing_finish_and_draft():
    from finishes.finish_spec import FinishSettings
    from gui.entrance_draft import EntranceDraft
    cfg = cfg_with({"top_rise": 0.3})
    cfg.finish_settings = FinishSettings(enabled=True)
    lay = lay_of(cfg)
    assert "FIN_END_WALL" not in {c for c, *_ in lay.finish}                                 # 앞면 개방: 끝벽 마감 없음
    op = [s for c, k, m, t, st in lay.finish if c == "FIN_WALL_L" for s in st if s.s0 >= lay.u["roof_end"] - 1e-9]
    assert op and all(s.zt_end == pytest.approx(lay.ground + lay.spec.parapet) for s in op)       # 파라펫 = 지표(GL) 기준
    sp = EntranceDraft(passage="EX1", top_rise="0.45", ramp_width="0").to_spec("출입구")
    assert sp.top_rise == 0.45 and sp.ramp_width == 0.0
    lay = lay_of(cfg_with({"top_rise": 0.45, "ramp_width": 0.0, "parapet": 0.6}))
    assert "OUT_RAMP" not in {p.code for p in lay.box_parts}                                 # 경사로 폭 0 = 계단만


# ===================================================== 실무 평면도: 개구부 내공 축소 · 바깥면 사선 전이
OPEN = {"thickness_zones": ZONES, "wall_t": 0.7, "open_narrow": 0.2, "open_wall_t": 0.3, "taper_ratio": 2.0}


def _in_taper(q, u, t, z):
    f = (u - q.u0) / (q.u1 - q.u0)
    ta, tb = q.ta0 + (q.ta1 - q.ta0) * f, q.tb0 + (q.tb1 - q.tb0) * f
    zb, zt = q.zb0 + (q.zb1 - q.zb0) * f, q.zt0 + (q.zt1 - q.zt0) * f
    return ta + 1e-7 < t < tb - 1e-7 and zb + 1e-7 < z < zt - 1e-7


def test_opening_narrow_and_outer_taper():
    lay = lay_of(cfg_with(OPEN))
    a = lay.spec.inner_width / 2
    a_o, u_re = a - 0.2, lay.u["roof_end"]
    part = {p.code: p for p in lay.box_parts}
    wl = part["WALL_L_Z4"]                                                                    # 개구부 (u_re 뒤) 측벽
    assert wl.strips[0].s0 == pytest.approx(u_re) and wl.t_range == pytest.approx((a_o, a_o + 0.3)) and wl.thick == 0.3
    assert part["WALL_R_Z4"].t_range == pytest.approx((-(a_o + 0.3), -a_o))
    assert part["WALL_L_Z3"].t_range == pytest.approx((a, a + 0.7))                         # 천장 구간은 그대로
    assert part["END_WALL_S"].t_range[0] == pytest.approx(-(a_o + 0.3))
    assert part["FLOOR_E_Z4"].t_range[1] == pytest.approx(a_o + 0.3)
    # 개구부 시작: 바깥면 a + 0.7 → a_o + 0.3 (차 0.6) 을 개구부 안으로 2 × 0.6 = 1.2 사선
    w = sorted(wl.pieces, key=lambda q: q.u0)
    assert w[0].u0 == pytest.approx(u_re) and w[-1].u1 == pytest.approx(u_re + 1.2)
    assert w[0].tb0 == pytest.approx(a + 0.7) and w[-1].tb1 == pytest.approx(a_o + 0.3)
    assert all(q.ta0 == pytest.approx(a_o + 0.3) for q in w)
    for code in ("FLOOR_E_Z4", "FLOOR_S_Z4"):                                                # 바닥 슬래브 바깥면도
        assert part[code].pieces and max(q.u1 for q in part[code].pieces) == pytest.approx(u_re + 1.2)
    # 두께 구간 경계(0.9 → 0.8, u 14): 두꺼운 쪽 바깥면이 얇은 구간 안으로 2 × 0.1 (측벽·바닥·천장)
    for code in ("WALL_L_Z2", "ROOF_Z2", "FLOOR_S_Z2"):
        z2 = part[code].pieces
        assert min(q.u0 for q in z2) == pytest.approx(14.0) and max(q.u1 for q in z2) == pytest.approx(14.2)
    assert not part["WALL_L_Z1"].pieces and not part["PARAPET"].pieces
    # 계단: 개구부 쪽 조각은 벽 쪽(−t) 변이 축소된 내공면, 천장 구간은 계단 구역 전체 폭
    s0, s1 = lay.spec.zones()["stair"]
    for p in lay.stair.parts:
        t = p.t_range if p.t_range is not None else (s0, s1)
        assert t == pytest.approx((-a_o, s1) if p.strips[0].s0 >= u_re - 1e-9 else (s0, s1))
        assert all(st.s1 <= u_re + 1e-9 for st in p.strips) or all(st.s0 >= u_re - 1e-9 for st in p.strips)
    plain = lay_of(cfg_with({"thickness_zones": ZONES, "wall_t": 0.7}))                     # 기본값: 예전과 같음 (직각 계단, 축소 없음)
    assert not any(p.pieces for p in plain.box_parts) and "WALL_L_Z4" not in {p.code for p in plain.box_parts}


def test_opening_narrow_finish_overlap_and_volumes(tmp_path):
    import random
    eng = StationCADEngine(_fin_cfg(**OPEN))
    ent = eng.entrances.entrances[0]
    lay = ent.layout
    a, fin = lay.spec.inner_width / 2, lay.spec_stair_finish
    a_o, u_re, face = a - 0.2, lay.u["roof_end"], lay.finish_type.face
    nos = sorted(f.t_range for f in lay.stair.finish if f.code == "NOSING")                 # 논슬립 벽 쪽 끝 = 벽 면 + nosing_end
    assert [r[0] for r in nos] == pytest.approx(sorted([-a + fin.nosing_end, -a_o + fin.nosing_end]))
    wf = {c: (t, s) for c, k, m, t, s in lay.finish}
    assert wf["FIN_WALL_L_O"][0][0] == pytest.approx(a_o - face)                             # 개구부 벽 마감 표면
    assert wf["FIN_WALL_L_RET"][1][0].s0 == pytest.approx(u_re - face)                       # 꺾임 패널: 개구부 벽 끝면 앞
    assert wf["FIN_WALL_L"][1][-1].s1 == pytest.approx(u_re - face)
    members = [(n, m) for n, m in eng.entrances.strip_members(ent) if "_ESC" not in n]
    boxes = [(n, m.t_range, s) for n, m in members for s in m.shape.strips]
    tapers = [(n, q) for n, m in members for q in getattr(m, "pieces", []) if hasattr(q, "ta0")]
    assert tapers
    rng = random.Random(4)
    samples = []
    for n, m in members:
        t0, t1 = m.t_range
        for st in m.shape.strips:
            for _ in range(3):
                u = rng.uniform(st.s0, st.s1)
                if st.zt_at(u) - st.zb_at(u) > 1e-6:
                    samples.append((n, u, rng.uniform(t0, t1), rng.uniform(st.zb_at(u), st.zt_at(u))))
    for n, q in tapers:
        for _ in range(20):
            u = rng.uniform(q.u0, q.u1)
            f = (u - q.u0) / (q.u1 - q.u0)
            ta, tb = q.ta0 + (q.ta1 - q.ta0) * f, q.tb0 + (q.tb1 - q.tb0) * f
            zb, zt = q.zb0 + (q.zb1 - q.zb0) * f, q.zt0 + (q.zt1 - q.zt0) * f
            if tb - ta > 1e-6 and zt - zb > 1e-6:
                samples.append((n + "#taper", u, rng.uniform(ta, tb), rng.uniform(zb, zt)))
    for n, u, t, z in samples:                                                               # 서로 겹치지 않음 (쐐기 포함)
        for n2, (a0, a1), s2 in boxes:
            if n2 == n or not (a0 + 1e-9 < t < a1 - 1e-9 and s2.s0 + 1e-9 < u < s2.s1 - 1e-9):
                continue
            assert not (s2.zb_at(u) + 1e-7 < z < s2.zt_at(u) - 1e-7), (n, n2, u, t, z)
        for n2, q in tapers:
            if n2 + "#taper" != n and q.u0 + 1e-9 < u < q.u1 - 1e-9:
                assert not _in_taper(q, u, t, z), (n, n2, u, t, z)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "o.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    for name, m in eng.entrances.strip_members(ent):                                         # 체적: 공식 = 메쉬 = IFC
        formula = m.shape.volume + sum(p.volume for p in getattr(m, "pieces", []))
        mesh = sum(PM.mesh_volume(q) for q in part_faces(ent.frame, m)) + \
            sum(PM.mesh_volume(p.faces()) for p in getattr(m, "pieces", []))
        assert mesh == pytest.approx(formula, rel=1e-7, abs=1e-8)
        assert ifc_world_volume(by_name[name]) == pytest.approx(formula, rel=1e-6, abs=1e-8)
    wedge = sum(q.volume for n, q in tapers if n == "EN1_WALL_L_Z4")                         # 쐐기 체적 = 삼각 평면 × 높이 (평균)
    assert wedge > 0


def test_opening_narrow_rules_and_draft():
    from gui.entrance_draft import EntranceDraft
    with pytest.raises(ValueError, match="트러스 옆 여유"):
        lay_of(cfg_with({"open_narrow": 0.9}))
    with pytest.raises(ValueError, match="개구부 벽 두께"):
        lay_of(cfg_with({"open_wall_t": 0.0}))
    with pytest.raises(ValueError, match="바깥면 전이"):
        lay_of(cfg_with({"taper_ratio": -1.0}))
    sp = EntranceDraft(passage="EX1").to_spec("출입구")
    assert sp.taper_ratio == 2.0 and sp.open_wall_t is None and sp.open_narrow == 0.0        # 화면 기본 = 실무 평면도 기울기
    sp = EntranceDraft(passage="EX1", open_narrow="0.2", open_wall_t="0.3").to_spec("출입구")
    assert (sp.open_narrow, sp.open_wall_t) == (0.2, 0.3)
    with pytest.raises(ValueError, match="개구부 벽 두께"):
        EntranceDraft(passage="EX1", open_wall_t="-1").to_spec("출입구")


# ===================================================== 실무 상세 "a": 앞마당 접속 슬래브 (상부 승강구 높임 + 바깥 = forecourt)
FORE = {"top_rise": 0.165, "outdoor": "forecourt", "fc_flat": 1.243, "open_narrow": 0.2, "open_wall_t": 0.3, "wall_t": 0.3}


def test_forecourt_matches_detail_a(tmp_path):
    import random
    eng = StationCADEngine(cfg_with(FORE))
    ent = eng.entrances.entrances[0]
    lay = ent.layout
    G, u0 = lay.ground, lay.u["end"]
    part = {p.code: p for p in lay.box_parts}
    assert not [c for c in part if c.startswith("OUT_")]                                     # 경사로·계단 대신 앞마당
    a_o = lay.spec.inner_width / 2 - 0.2
    assert all(part[c].t_range == pytest.approx((-a_o, a_o)) for c in ("FC_PAVE", "FC_SLAB", "FC_BEAM", "FC_LEAN", "FC_FOOT"))

    def rel(st):
        return (st.s0 - u0, st.s1 - u0, st.zb0 - G, st.zb1 - G, st.zt - G, st.zt_end - G)
    # 실무 상세 치수 (끝벽 바깥면·지표 기준): 포장 GL+165 평탄 1,243 → 기울기 1/12, 끝단 보 바깥면 3,150 에서 슬래브 윗면 −94
    assert [x for s in part["FC_PAVE"].strips for x in rel(s)] == pytest.approx(
        [0, 1.243, 0.065, 0.065, 0.165, 0.165, 1.243, 3.15, 0.065, 0.065 - 1.907 / 12, 0.165, 0.165 - 1.907 / 12])
    assert rel(part["FC_SLAB"].strips[0]) == pytest.approx((0, 1.243, -0.235, -0.235, 0.065, 0.065))
    beam = [rel(s) for s in part["FC_BEAM"].strips]
    assert beam[0][:2] == pytest.approx((2.56, 2.85)) and beam[0][4] - beam[0][2] == pytest.approx(0.0)   # 헌치 (삼각)
    assert beam[1][:4] == pytest.approx((2.85, 3.15, -0.77, -0.77))                          # 보 하면 = 평탄 슬래브 하면 − 535
    (foot,) = part["FC_FOOT"].strips
    assert rel(foot) == pytest.approx((2.695, 3.305, -0.91, -0.91, -0.77, -0.77))
    assert rel(part["FC_LEAN"].strips[0]) == pytest.approx((0, 1.243, -0.375, -0.375, -0.235, -0.235))
    assert part["FC_LEAN"].strips[-1].s1 - u0 == pytest.approx(2.85)                        # 버림 = 헌치 따라 보 안쪽 면까지
    # 서로 겹치지 않음 (앞마당 부재끼리 + 박스)
    fc = [(p.code, p.t_range, s) for p in lay.box_parts for s in p.strips]
    rng = random.Random(7)
    for code, (t0, t1), st in fc:
        if not code.startswith("FC_"):
            continue
        for _ in range(30):
            u = rng.uniform(st.s0, st.s1)
            if st.zt_at(u) - st.zb_at(u) < 1e-6:
                continue
            t, z = rng.uniform(t0, t1), rng.uniform(st.zb_at(u), st.zt_at(u))
            for c2, (a0, a1), s2 in fc:
                if c2 != code and a0 + 1e-9 < t < a1 - 1e-9 and s2.s0 + 1e-9 < u < s2.s1 - 1e-9:
                    assert not (s2.zb_at(u) + 1e-7 < z < s2.zt_at(u) - 1e-7), (code, c2, u, t, z)
    # 출력: 포장 = 바닥 마감 레이어·IfcCovering(FLOORING, 화강석), 보 = IfcWall, 버림 = IfcSlab BASESLAB, 체적 공식 = 메쉬 = IFC
    els = {e.code: e for e in ent.elements}
    assert els["FC_PAVE"].material == "화강석" and els["FC_LEAN"].material == "Lean_Concrete"
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "fc.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    assert by_name["EN1_FC_PAVE"].is_a("IfcCovering") and by_name["EN1_FC_PAVE"].PredefinedType == "FLOORING"
    assert by_name["EN1_FC_BEAM"].is_a("IfcWall") and by_name["EN1_FC_FOOT"].PredefinedType == "BASESLAB"
    for code in ("FC_PAVE", "FC_SLAB", "FC_BEAM", "FC_LEAN", "FC_FOOT"):
        m = els[code]
        formula = m.shape.volume
        mesh = sum(PM.mesh_volume(q) for q in part_faces(ent.frame, m))
        assert mesh == pytest.approx(formula, rel=1e-7)
        assert ifc_world_volume(by_name[m.name]) == pytest.approx(formula, rel=1e-6)
    w = 2 * a_o
    assert els["FC_PAVE"].shape.volume == pytest.approx(w * 0.1 * 3.15)                       # 연직 두께 일정
    assert els["FC_SLAB"].shape.volume == pytest.approx(w * 0.3 * 3.15)
    eng.build_3d_doc()
    assert {e.dxf.layer for e in els["FC_PAVE"].source_element} == {"FIN_FLOOR"}                # 포장 = 바닥 마감 레이어


def test_forecourt_rules_and_draft():
    from gui.entrance_draft import EntranceDraft
    auto = lay_of(cfg_with({"top_rise": 0.165, "outdoor": "forecourt"}))                     # 평탄 길이 자동: 끝에서 지표
    pave = {p.code: p for p in auto.box_parts}["FC_PAVE"]
    assert pave.strips[0].s1 - auto.u["end"] == pytest.approx(3.15 - 0.165 * 12)
    assert pave.strips[-1].zt_end == pytest.approx(auto.ground)
    with pytest.raises(ValueError, match="지표보다 .* 높습니다"):
        lay_of(cfg_with({"top_rise": 0.165, "outdoor": "forecourt", "fc_flat": 2.0}))
    with pytest.raises(ValueError, match="지표보다 .* 낮습니다"):
        lay_of(cfg_with({"top_rise": 0.165, "outdoor": "forecourt", "fc_flat": 0.5}))
    with pytest.raises(ValueError, match="끝단 보 깊이"):
        lay_of(cfg_with({"top_rise": 0.165, "outdoor": "forecourt", "fc_beam_h": 0.1}))
    with pytest.raises(ValueError, match="바깥 접근 형식"):
        lay_of(cfg_with({"top_rise": 0.165, "outdoor": "plaza"}))
    sp = EntranceDraft(passage="EX1").to_spec("출입구")
    assert sp.outdoor == "forecourt" and sp.fc_flat is None and sp.fc_length == 3.15        # 화면 기본 = 실무 상세 앞마당
    sp = EntranceDraft(passage="EX1", outdoor="경사로·계단", fc_flat="0").to_spec("출입구")
    assert sp.outdoor == "steps" and sp.fc_flat == 0.0
    with pytest.raises(ValueError, match="앞마당 평탄 길이"):
        EntranceDraft(passage="EX1", fc_flat="-1").to_spec("출입구")


# ===================================================== 승강구 구조 (실무 종단·상세 "a") · 파라펫 두께 (상세 "d")
def _no_overlap(parts, seed=11, n=25):
    import random
    rng = random.Random(seed)
    boxes = [(p.code, p.t_range, s) for p in parts for s in p.strips]
    for code, (t0, t1), st in boxes:
        for _ in range(n):
            u = rng.uniform(st.s0, st.s1)
            if st.zt_at(u) - st.zb_at(u) < 1e-6:
                continue
            t, z = rng.uniform(t0, t1), rng.uniform(st.zb_at(u), st.zt_at(u))
            for c2, (a0, a1), s2 in boxes:
                if c2 != code and a0 + 1e-9 < t < a1 - 1e-9 and s2.s0 + 1e-9 < u < s2.s1 - 1e-9:
                    assert not (s2.zb_at(u) + 1e-7 < z < s2.zt_at(u) - 1e-7), (code, c2, u, t, z)


def test_landing_structure_matches_detail(tmp_path):
    eng = StationCADEngine(cfg_with(dict(FORE, top_ffl=0.1)))
    ent = eng.entrances.entrances[0]
    lay = ent.layout
    G, Gt, D = lay.ground, lay.top_level, lay.spec.esc_truss_depth
    u_hi, u_top, end = lay.u["truss_hi"], lay.u["top"], lay.u["end"]
    part = {p.code: p for p in lay.box_parts}
    (ls,) = part["LANDING_E"].strips                                                         # 승강구 슬래브 200, 윗면 GL+65
    assert (ls.s0, ls.s1, ls.zb0 - G, ls.zt - G) == pytest.approx((u_hi, u_top, -0.135, 0.065))
    (fe,) = part["FIN_TOP_E"].strips
    assert (fe.zb0 - G, fe.zt - G) == pytest.approx((0.065, 0.165))                         # 승강구 마감 100 → 걷는 면 GL+165
    (fw,) = part["FIN_TOP_W"].strips
    assert (fw.s0, fw.s1, fw.zb0, fw.zt) == pytest.approx((u_top, end, Gt - 0.1, Gt))        # 상단 끝벽 위 마감
    assert all(s.zt_end == pytest.approx(Gt - 0.1) for c in ("END_WALL_S", "END_WALL_E") for s in part[c].strips)
    assert part["END_WALL_E"].strips[0].zb0 == pytest.approx(Gt - D)                         # 끝벽 = 바닥(트러스 하면 높이)부터
    flo = [s for p in lay.box_parts if p.code.startswith("FLOOR_E") for s in p.strips if s.s0 >= u_hi - 1e-9]
    assert flo and all(s.zt == pytest.approx(Gt - D) and s.zt_end == pytest.approx(Gt - D) for s in flo)   # 아래 빈 공간
    _no_overlap(lay.box_parts)
    els = {e.code: e for e in ent.elements}
    assert els["FIN_TOP_E"].material == "화강석"
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "land.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    assert by_name["EN1_LANDING_E"].is_a("IfcSlab") and by_name["EN1_LANDING_E"].PredefinedType == "LANDING"
    assert by_name["EN1_FIN_TOP_E"].is_a("IfcCovering") and by_name["EN1_FIN_TOP_W"].PredefinedType == "FLOORING"
    for code in ("LANDING_E", "FIN_TOP_E", "FIN_TOP_W", "END_WALL_E", max(c for c in els if c.startswith("FLOOR_E"))):
        m = els[code]
        formula = m.volume
        mesh = sum(PM.mesh_volume(q) for q in part_faces(ent.frame, m)) + sum(PM.mesh_volume(p.faces()) for p in m.pieces)
        assert mesh == pytest.approx(formula, rel=1e-7)
        assert ifc_world_volume(by_name[m.name]) == pytest.approx(formula, rel=1e-6)
    eng.build_3d_doc()
    assert {e.dxf.layer for e in els["FIN_TOP_E"].source_element} == {"FIN_FLOOR"}
    # 마감 두께 0 (모델 기본): 슬래브 윗면 = 승강구, 마감 부재 없음, 끝벽 = 승강구 높이
    plain = lay_of(cfg_with({"top_rise": 0.165}))
    pp = {p.code: p for p in plain.box_parts}
    assert "FIN_TOP_E" not in pp and pp["LANDING_E"].strips[0].zt == pytest.approx(plain.top_level)
    with pytest.raises(ValueError, match="트러스 높이"):
        lay_of(cfg_with({"top_ffl": 0.5, "landing_t": 0.8}))


def test_parapet_thickness_and_ground_reference(tmp_path):
    from gui.entrance_draft import EntranceDraft
    eng = StationCADEngine(cfg_with(dict(OPEN, parapet_t=0.25, parapet=0.5)))
    ent = eng.entrances.entrances[0]
    lay = ent.layout
    G, u_re, u_top = lay.ground, lay.u["roof_end"], lay.u["top"]
    a_o = lay.spec.inner_width / 2 - 0.2
    part = {p.code: p for p in lay.box_parts}
    par = part["PARAPET"]                                                                    # 천장 끝 가로 파라펫 = 끝면에서 안쪽 0.25
    assert (par.strips[0].s0, par.strips[-1].s1) == pytest.approx((u_re - 0.25, u_re)) and par.thick == 0.25
    assert all(s.zt == pytest.approx(G + 0.5) for s in par.strips)                          # 윗면 = 지표 + 파라펫
    for code, rng in (("PARAPET_L", (a_o, a_o + 0.25)), ("PARAPET_R", (-a_o - 0.25, -a_o))):   # 측벽 지표 위 = 얇은 파라펫 (내공면 고정)
        p = part[code]
        assert p.t_range == pytest.approx(rng)
        assert [(s.s0, s.s1, s.zb0, s.zt) for s in p.strips] == [pytest.approx((u_re, u_top, G, G + 0.5))]
    op = [s for p in lay.box_parts if p.code.startswith("WALL_L") for s in p.strips if s.s0 >= u_re - 1e-9]
    assert op and all(s.zt_end == pytest.approx(G) for s in op)                              # 개구부 벽 = 지표까지
    end_par = part["PARAPET_END"]                                                            # 높임 없음: 끝벽 지표 위도 파라펫
    assert (end_par.strips[0].s0, end_par.strips[0].s1) == pytest.approx((u_top, u_top + 0.25))
    _no_overlap(lay.box_parts, n=8)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "par.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    for e in ent.elements:
        if e.code.startswith("PARAPET"):
            assert by_name[e.name].is_a("IfcWall")
            assert ifc_world_volume(by_name[e.name]) == pytest.approx(e.volume, rel=1e-6)
    # 비우면 예전 (가로 파라펫 = 천장 끝 두께, 측벽 파라펫 없음), 높이는 지표 기준
    plain = lay_of(cfg_with({"top_rise": 0.165}))
    pp = {p.code: p for p in plain.box_parts}
    assert "PARAPET_L" not in pp and pp["PARAPET"].thick == pytest.approx(plain.spec.thick_at(plain.u["roof_end"]))
    assert all(s.zt == pytest.approx(plain.ground + plain.spec.parapet) for s in pp["PARAPET"].strips)
    with pytest.raises(ValueError, match="파라펫 두께"):
        lay_of(cfg_with(dict(OPEN, parapet_t=0.5)))
    with pytest.raises(ValueError, match="파라펫 높이"):
        lay_of(cfg_with({"top_rise": 0.4, "parapet": 0.3}))
    sp = EntranceDraft(passage="EX1").to_spec("출입구")
    assert sp.parapet_t is None and sp.top_ffl == 0.1 and sp.landing_t == 0.2                # 화면 기본 = 실무 상세 승강구 마감
    assert EntranceDraft(passage="EX1", parapet_t="0.3").to_spec("출입구").parapet_t == 0.3


# ===================================================== 캐노피 (철골 + 평판 유리 지붕) · 앞 출구 사인
CANOPY = dict(FORE, top_ffl=0.1, parapet_t=0.3, canopy=True, exit_number="3", exit_dest="검단신도시\n시청")


def test_canopy_layout_and_outputs(tmp_path):
    eng = StationCADEngine(cfg_with(CANOPY))
    ent = eng.entrances.entrances[0]
    lay = ent.layout
    sp, G, Gt = lay.spec, lay.ground, lay.top_level
    u_re, u_top, end = lay.u["roof_end"], lay.u["top"], lay.u["end"]
    cp = {p.code: p for p in lay.canopy}
    a_o = sp.inner_width / 2 - 0.2
    t_post = a_o + 0.15                                                                       # 파라펫(0.3) 두께 가운데
    posts = sorted((p.strips[0].s0 + p.strips[0].s1) / 2 for c, p in cp.items() if c.startswith("CP_POST_L"))
    assert posts[0] == pytest.approx(u_re + 0.1) and posts[-1] == pytest.approx(u_top - 0.1)
    assert max(b - a for a, b in zip(posts, posts[1:])) <= sp.cp_spacing + 1e-9               # 간격 ≤ 상한, 고르게
    zb = lambda u: Gt + sp.cp_height - sp.cp_slope * (end + sp.cp_front - u)
    for c, p in cp.items():
        if c.startswith("CP_POST"):
            s = p.strips[0]
            assert abs(abs(sum(p.t_range) / 2) - t_post) < 1e-9
            assert s.zb0 == pytest.approx(G + sp.parapet) and s.zt == pytest.approx(zb(s.s0))   # 파라펫 윗면 ~ 보 하면
    bl = cp["CP_BEAM_L"].strips[0]
    assert (bl.s0, bl.s1) == pytest.approx((u_re - 0.3, end + sp.cp_front))                  # 가로 파라펫 바깥면 ~ 앞 내밈
    assert (bl.zb0, bl.zb1) == pytest.approx((zb(bl.s0), zb(bl.s1)))
    gl = cp["CP_GLASS"]
    assert gl.t_range == pytest.approx((-(t_post + sp.cp_side), t_post + sp.cp_side))
    assert gl.strips[0].zb0 == pytest.approx(zb(bl.s0) + sp.cp_beam_h)
    walls = [p for c, p in cp.items() if c.startswith("CP_WALL")]                           # 외부 차단 유리벽: 옆·뒤, 앞은 열림
    side = sorted((p.strips[0].s0, p.strips[0].s1) for c, p in cp.items() if c.startswith("CP_WALL_L"))
    assert side[0] == pytest.approx((u_re - 0.3, u_re)) and len(side) == len(posts)          # 뒤 끝 ~ 첫 기둥, 기둥 사이
    assert all(b - a == pytest.approx(posts[1] - posts[0] - sp.cp_post) for a, b in side[1:])
    assert max(s1 for _, s1 in side) <= u_top + 1e-9                                         # 앞(출구) 쪽엔 없음
    wb = cp["CP_WALL_B"].strips[0]
    assert (wb.s0 + wb.s1) / 2 == pytest.approx(u_re - 0.3 + sp.cp_beam_w / 2)
    for p in walls:
        s = p.strips[0]
        assert s.zb0 == pytest.approx(G + sp.parapet) and s.zt == pytest.approx(zb(s.s0))
    sg = cp["CP_SIGN"]
    assert sg.t_range == pytest.approx((-1.2, 1.2)) and sg.strips[-1].s1 == pytest.approx(end + sp.cp_front)
    assert sg.strips[0].zb0 - Gt >= 2.1 - 1e-9
    _no_overlap(lay.canopy + lay.box_parts, n=10)
    # IFC: 기둥 IfcColumn · 보 IfcBeam · 유리 IfcPlate · 사인 IfcBuildingElementProxy(SIGNAGE), 체적 공식 = 메쉬 = IFC
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "cp.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    kinds = {"CP_POST": "IfcColumn", "CP_BEAM": "IfcBeam", "CP_GLASS": "IfcPlate", "CP_SIGN": "IfcBuildingElementProxy",
             "CP_WALL": "IfcPlate"}
    for e in ent.canopy:
        el = by_name[e.name]
        assert el.is_a(kinds[e.kind])
        mesh = sum(PM.mesh_volume(q) for q in part_faces(ent.frame, e))
        assert mesh == pytest.approx(e.volume, rel=1e-7)
        assert ifc_world_volume(el) == pytest.approx(e.volume, rel=1e-6)
    assert by_name["EN1_CP_WALL_B"].PredefinedType == "CURTAIN_PANEL"
    sign = by_name["EN1_CP_SIGN"]
    assert sign.ObjectType == "SIGNAGE" and sign.Description == "3 출구: 검단신도시 / 시청"
    # 3D 레이어 · 사인 이미지 (DAE textures/entrance_sign_001.png)
    eng.build_3d_doc()
    layers = {e.kind: {x.dxf.layer for x in e.source_element} for e in ent.canopy}
    assert layers["CP_POST"] == {"STRUCT_CANOPY"} and layers["CP_GLASS"] == layers["CP_WALL"] == {"STRUCT_CANOPY_GLASS"}
    assert layers["CP_SIGN"] == {"STRUCT_SIGN", "STRUCT_SIGN_FACE"}
    (name, img, frame, faces), = eng.entrances.sign_images()
    assert img.size[0] / img.size[1] == pytest.approx(2.4 / 0.6, rel=0.02) and frame[3:5] == pytest.approx((2.4, 0.6))
    eng.generate_dae(str(tmp_path / "d" / "m.dae"))
    assert (tmp_path / "d" / "textures" / "entrance_sign_001.png").exists()


def test_canopy_rules_and_draft():
    from gui.entrance_draft import EntranceDraft
    assert not lay_of(cfg_with(FORE)).canopy                                                  # 모델 기본 = 없음
    with pytest.raises(ValueError, match="2.1m"):
        lay_of(cfg_with(dict(CANOPY, cp_height=2.4)))
    with pytest.raises(ValueError, match="보 사이"):
        lay_of(cfg_with(dict(CANOPY, cp_sign_w=6.0)))
    with pytest.raises(ValueError, match="보 폭"):
        lay_of(cfg_with(dict(CANOPY, cp_beam_w=0.3)))
    nos = lay_of(cfg_with(dict(CANOPY, cp_sign=False, cp_wall=False)))
    assert not {p.code for p in nos.canopy if p.code.startswith(("CP_SIGN", "CP_WALL"))}
    with pytest.raises(ValueError, match="유리벽 두께"):
        lay_of(cfg_with(dict(CANOPY, cp_wall_t=0.2)))
    eng = StationCADEngine(cfg_with(dict(CANOPY, exit_number="", exit_dest="")))
    assert eng.entrances.entrances[0].exit_number == "1"                                      # 비우면 통로 순번
    sp = EntranceDraft(passage="EX1", exit_number="2", exit_dest="시청 / 공원").to_spec("출입구")
    assert sp.canopy and sp.cp_wall and sp.exit_number == "2" and sp.exit_dest == "시청\n공원"                # 화면 기본 = 캐노피 있음
