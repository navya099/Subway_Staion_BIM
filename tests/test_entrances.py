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
                     "JOINT_WALL_L", "JOINT_WALL_R", "PARTITION"}
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
        assert mesh == pytest.approx(formula, rel=1e-7)
        assert ifc_world_volume(by_name[name]) == pytest.approx(formula, rel=1e-6)


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
    faces = list(ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace().query('3DFACE[layer=="STRUCT_ENTRANCE"]'))
    expect = sum(len(fs) for _, m in eng.entrances.strip_members(ent) for fs in part_faces(ent.frame, m)) + \
        sum(len(p.faces()) for p in ent.element("ROOF").pieces)
    assert len(faces) == expect
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


# ===================================================== 입력 초안
from gui.entrance_draft import SIDE_RIGHT, EntranceDraft, EntranceDrafts, preview


def test_draft_converts():
    d = EntranceDrafts()
    d.items = [EntranceDraft(name="A", passage="EX2", side=SIDE_RIGHT, ground_el="109.3", tread="0.28", stair_offset="")]
    (sp,) = d.to_specs()
    assert (sp.name, sp.passage, sp.escalator_side, sp.ground_el, sp.tread, sp.stair_offset) == ("A", "EX2", -1, 109.3, 0.28, None)
    d.items[0].stair_offset = "-2"
    assert d.to_specs()[0].stair_offset == -2.0


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
