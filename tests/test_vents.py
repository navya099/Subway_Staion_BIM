"""환기구 (출구통로 경로 + 연속박스(n련) 단면 + 수직구 + 끝 금속 그릴) 테스트"""
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
from passages.passage_spec import PassageSpec, station_path, world_path
from test_curved import NO_COLS, curved_cfg
from test_patch import make_cfg, user_example
from ventilations.vent_spec import VentSpec

# user_example: 3개 층 각 6m, 내공 폭 18, 외벽 1.0 → 측벽 바깥면 t = ±10, 최상층(3) FL = 12
SHAFT_END = [(50, 10, None), (50, 30, 0), (50, 30, 12)]
MID_SHAFT = [(50, 10, None), (50, 30, 0), (50, 30, 8), (50, 45, 8)]
U_TURN = [(50, 10, None), (50, 30, 0), (50, 30, 8), (50, 20, 8), (50, 20, 14)]
TURN = [(150, -10, None), (150, -25, 0), (170, -25, 0), (170, -25, 10)]
DUCT_END = [(50, 10, None), (50, 30, 0)]


def vent(points, **kw):
    return VentSpec(floor=kw.pop("floor", 3), path=station_path(points), **kw)


def eng_with(*vents, curved=False, passages=()):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(user_example())
    cfg.vents, cfg.passages = list(vents), list(passages)
    return StationCADEngine(cfg)


def the_vent(eng):
    return eng.vents.vents[0]


# ===================================================== 단면 · 부재 구성
def test_cell_layout():
    sp = VentSpec(cells=4, cell_width=2.5, mid_wall_t=0.4, wall_t=0.6)
    assert sp.inner_width == pytest.approx(11.2) and sp.half_out == pytest.approx(6.2)
    flat = lambda rs: [x for r in rs for x in r]
    assert flat(sp.cell_ranges()) == pytest.approx([-5.6, -3.1, -2.7, -0.2, 0.2, 2.7, 3.1, 5.6])
    assert flat(sp.mid_ranges()) == pytest.approx([-3.1, -2.7, -0.2, 0.2, 2.7, 3.1])
    assert VentSpec(cells=1).mid_ranges() == [] and VentSpec(shaft_depth=None).depth == 3.0


def test_shaft_at_end_volume_by_hand():
    """덕트 L=20 (+D/2 = 21.5) → 끝 벽 → 수직구 (천장 상면 3.6 ~ 12) → 상단 그릴. 손 계산과 같아야 함"""
    vt = the_vent(eng_with(vent(SHAFT_END)))
    codes = {e.code for e in vt.elements}
    assert codes == {"D1_FLOOR", "D1_ROOF", "D1_WALL_L", "D1_WALL_R", "D1_MID1", "D1_MID2", "D1_MID3", "D1_END_E",
                     "V1_WALL_B", "V1_WALL_F", "V1_WALL_L", "V1_WALL_R", "V1_MID1", "V1_MID2", "V1_MID3"}
    b2, L, D, h = 12.4, 21.5, 3.0, 12.0 - 3.6
    expect = {"D1_FLOOR": b2 * 0.6 * L,
              "D1_ROOF": b2 * 0.6 * (L - D) + 2.4 * 0.6 * D + 8 * 0.045 * (L - D),     # 구멍 구간은 벽 위 띠만, 헌치 8개
              "D1_WALL_L": 0.6 * 3 * L, "D1_MID2": 0.4 * 3 * L, "D1_END_E": b2 * 4.2 * 0.6,
              "V1_WALL_B": 0.6 * b2 * h, "V1_WALL_L": D * 0.6 * h, "V1_MID1": D * 0.4 * h}
    for code, v in expect.items():
        assert vt.element(code).volume == pytest.approx(v), code
    assert vt.volume == pytest.approx(680.1)
    assert vt.grill_at_shaft and len(vt.grills) == 4 and vt.shafts == [1]


def test_roof_hole_is_exactly_the_cells():
    vt = the_vent(eng_with(vent(SHAFT_END)))
    roof = vt.element("D1_ROOF").pieces
    over = [p for p in roof if p.a0 >= 18.5 - 1e-9]                          # 수직구 구간 [L−D/2, L+D/2]
    widths = sorted(round(max(v for v, _ in p.sect) - min(v for v, _ in p.sect), 6) for p in over)
    assert widths == [0.4, 0.4, 0.4, 0.6, 0.6]                              # 바깥 벽 2 + 중벽 3 위 띠
    assert all(p.a1 <= 18.5 + 1e-9 for p in roof if len(p.sect) == 3)      # 헌치는 구멍 앞에서 끝


def test_mid_shaft_upper_duct_has_floor_hole_and_start_wall():
    vt = the_vent(eng_with(vent(MID_SHAFT)))
    assert {"D2_END_S", "D2_FLOOR", "D2_ROOF"} <= {e.code for e in vt.elements} and not vt.grill_at_shaft
    floor = vt.element("D2_FLOOR").pieces
    assert sum(1 for p in floor if p.a1 <= 1.5 + 1e-9) == 5                  # [−D/2, D/2] 는 벽 위 띠만
    shaft_top = max(p.z_range[1] for e in vt.elements if e.code.startswith("V1") for p in e.pieces)
    assert shaft_top == pytest.approx(min(p.z_range[0] for p in floor))      # 수직구 위 = 위 덕트 바닥 하면
    e0 = vt.vertices[0].z
    assert shaft_top == pytest.approx(e0 + 8 - 0.6)


def test_u_turn_and_turn_paths_build():
    vt = the_vent(eng_with(vent(U_TURN)))
    assert vt.shafts == [1, 3] and {"V1_WALL_F", "V2_WALL_F", "D2_END_S", "D2_END_E"} <= {e.code for e in vt.elements}
    vt = the_vent(eng_with(vent(TURN)))
    assert vt.corners == [1] and any(p.skewed for p in vt.element("D1_ROOF").pieces)


def test_duct_end_grill_is_vertical_bars_in_each_cell():
    vt = the_vent(eng_with(vent(DUCT_END, cells=2, cell_width=1.0, grill_gap=0.1, grill_bar=0.05, grill_frame=0.1)))
    assert not vt.grill_at_shaft and not vt.shafts
    g = vt.element("GRILL1")
    bars = g.pieces[4:]                                                     # 칸 v −1.2 ~ −0.2, 테두리 안 −1.1 ~ −0.3 (0.8)
    assert len(bars) == 4                                                   # int((0.8 − 0.1) / 0.15) = 4
    starts = sorted(min(v for v, _ in b.sect) for b in bars)
    assert starts == pytest.approx([-1.1 + 0.12 * k + 0.05 * (k - 1) for k in range(1, 5)])   # 틈 (0.8 − 0.2) / 5 = 0.12 등간격
    assert all(p.a0 == pytest.approx(20 - 0.1) and p.a1 == pytest.approx(20) for p in g.pieces)
    roof = vt.element("D1_ROOF").pieces
    assert all(p.a1 <= 20 - 0.1 + 1e-9 for p in roof if len(p.sect) == 3)  # 그릴 자리 헌치 없음


# ===================================================== 측벽 칸별 오프닝
def test_station_wall_opening_per_cell():
    eng = eng_with(vent(SHAFT_END))
    wall = next(w for pk in eng.walls.wall_packages if pk.level == "B1F" for w in pk.walls if w.openings)
    ops = sorted(o.s_range for o in wall.openings)
    assert ops == [pytest.approx(r) for r in [(44.4, 46.9), (47.3, 49.8), (50.2, 52.7), (53.1, 55.6)]]
    assert {o.kind.code for o in wall.openings} == {"VENT_DUCT"}


# ===================================================== 검증
@pytest.mark.parametrize("pts,kw,msg", [
    ([(50, 10, None), (50, 10, 5)], {}, "수평으로 나가야"),
    ([(50, 10, None), (50, 30, 0), (50, 30, -5)], {}, "아래로"),
    ([(50, 10, None), (50, 30, 0), (50, 30, 0)], {}, "위치가 같습니다"),
    ([(50, 10, None), (50, 30, 0), (50, 30, 6), (50, 30, 9)], {}, "연속"),
    ([(50, 10, None), (50, 30, 1), (50, 30, 9)], {}, "앞 덕트 구간은 수평"),
    ([(50, 10, None), (50, 30, 0), (50, 30, 8), (65, 30, 8)], {}, "같은 선"),
    ([(50, 10, None), (50, 30, 0), (50, 30, 8), (50, 45, 9)], {}, "뒤 덕트 구간은 수평"),
    ([(50, 10, None), (50, 30, 0), (50, 30, 3)], {}, "너무 낮습니다"),
    ([(50, 10, None), (50, 12, 0), (50, 12, 9)], {}, "너무 짧습니다"),
    ([(50, 10, None), (50, 30, 0)], {"cells": 0}, "련 수"),
    ([(50, 10, None), (50, 30, 0)], {"cell_height": 7.0}, "내공 높이"),
    ([(50, 10, None), (50, 30, 0)], {"haunch_w": 1.3}, "칸 폭의 절반"),
    ([(50, 10, None), (50, 30, 0)], {"grill_frame": 1.3}, "테두리"),
    ([(50, 10, None), (50, 30, 0)], {"mid_wall_t": 0.0}, "중벽"),
    ([(3, 10, None), (3, 30, 0)], {}, "내공 길이"),
    ([(50, 9, None), (50, 30, 0)], {}, "외벽 바깥면"),
])
def test_invalid_vent_rejected(pts, kw, msg):
    with pytest.raises(ValueError, match=msg):
        eng_with(vent(pts, **kw))


def test_overlaps_rejected():
    with pytest.raises(ValueError, match="서로 겹칩니다"):
        eng_with(vent(SHAFT_END), vent([(52, 10, None), (52, 30, 0)], name="B"))
    with pytest.raises(ValueError, match=r"출구통로 EX1 이\(가\) 서로 겹칩니다"):        # 통로가 덕트를 가로지름
        eng_with(vent(DUCT_END), passages=[PassageSpec(floor=3, path=station_path([(70, 10, None), (70, 25, 0), (50, 25, 0)]))])
    with pytest.raises(ValueError, match="이름이 중복"):
        eng_with(vent(SHAFT_END, name="A"), vent([(150, -10, None), (150, -30, 0)], name="A"))


# ===================================================== 체적 교차 검증 (공식 ↔ 3D 메쉬 ↔ IFC)
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("pts,curved", [(SHAFT_END, False), (MID_SHAFT, False), (TURN, False), (U_TURN, True)])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, pts, curved):
    eng = eng_with(vent(pts), curved=curved)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "v.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    vt = the_vent(eng)
    for e in vt.elements + vt.grills:
        mesh = sum(PM.mesh_volume(p.faces()) for p in e.pieces)
        assert mesh == pytest.approx(e.volume, rel=1e-7), e.name
        assert ifc_world_volume(by_name[e.name]) == pytest.approx(e.volume, rel=1e-6), e.name


def test_ifc_structure(tmp_path):
    eng = eng_with(vent(SHAFT_END))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "v.ifc"))
    asm = next(a for a in f.by_type("IfcElementAssembly") if a.ObjectType == "VENTILATION")
    assert asm.Name == "VS1" and ifcopenshell.util.element.get_container(asm).Name == "B1F"
    kids = ifcopenshell.util.element.get_decomposition(asm)
    grills = [k for k in kids if k.is_a("IfcAirTerminal")]
    assert len(grills) == 4 and {g.PredefinedType for g in grills} == {"GRILLE"}
    assert ifcopenshell.util.element.get_material(grills[0]).Name == "Steel"
    walls = {k.Name for k in kids if k.is_a("IfcWall")}
    assert {"VS1_D1_MID1", "VS1_D1_END_E", "VS1_V1_WALL_F"} <= walls
    assert {k.PredefinedType for k in kids if k.is_a("IfcSlab")} == {"FLOOR", "ROOF"}
    ops = [o for o in f.by_type("IfcOpeningElement") if o.Name.startswith("OPEN_VS1_C")]
    assert len(ops) == 4


# ===================================================== 도면
def test_3d_dxf_layers_and_section(tmp_path):
    eng = eng_with(vent(TURN))
    vt = the_vent(eng)
    msp = ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace()
    n_conc = sum(len(p.faces()) for e in vt.elements for p in e.pieces)
    n_grill = sum(len(p.faces()) for e in vt.grills for p in e.pieces)
    assert len(msp.query('3DFACE[layer=="STRUCT_VENT"]')) == n_conc
    assert len(msp.query('3DFACE[layer=="STRUCT_GRILL"]')) == n_grill
    items = eng.vents.section_items(160.0)                                  # 덕트 D2(+s 방향) 를 가로지름
    names = {it.name for it in items}
    assert {"VS1_D2_FLOOR", "VS1_D2_MID1", "VS1_D2_ROOF"} <= names and [it.label[0] for it in items if it.label] == ["VS1"]
    cut = [it for it in items if it.name == "VS1_D2_FLOOR"][0]
    assert max(u for u, _ in cut.pts) - min(u for u, _ in cut.pts) == pytest.approx(12.4)


def test_plan_shows_vent_on_its_floor(tmp_path):
    eng = eng_with(vent(SHAFT_END))
    assert not eng.vents.plan_items(14.0, floor=1)
    items = eng.vents.plan_items(14.0, floor=3)
    assert items and items[0].label[0] == "VS1 VENT 4련" and all(it.layer == "PLAN_VENT" for it in items)
    path = eng.generate_plan_dxf(tmp_path / "p.dxf", floors=[3])
    assert ezdxf.readfile(path).modelspace().query('LWPOLYLINE[layer=="PLAN_VENT"]')


def test_world_path_and_build_all(tmp_path):
    from engine.bim_engine import BIMEngine
    cfg = make_cfg(user_example())
    pts = [cfg.to_world(50, 10), cfg.to_world(50, 30)]
    cfg.vents = [VentSpec(floor=3, path=world_path([(*pts[0], None), (*pts[1], cfg.lv(50) - cfg.station.offset + 12),
                                                    (*pts[1], cfg.lv(50) - cfg.station.offset + 25)]))]
    assert len(BIMEngine.build(cfg, tmp_path)) == 5


# ===================================================== 입력 초안
from gui.vent_draft import VentDraft, VentDrafts, default_draft, preview
from gui.passage_draft import VertexDraft


def test_draft_converts_and_preview():
    d = default_draft(3, 50.0, 10.0)
    sp = d.to_spec("환기구 1", 0.0)
    assert (sp.cells, sp.shaft_depth, len(sp.path), sp.path[2].z) == (4, None, 3, 10.0)
    d.shaft_depth, d.cells = "2.5", "6"
    assert d.to_spec("", 0.0).shaft_depth == 2.5 and d.to_spec("", 0.0).cells == 6
    assert "6련 × 2.5×3" in preview(d, 0.0) and "수직 구간 1곳" in preview(d, 0.0) and "수직구 상단 6개" in preview(d, 0.0)
    d.vertices = d.vertices[:2]
    assert "덕트 끝 단면" in preview(d, 0.0)


@pytest.mark.parametrize("field,value,msg", [
    ("cells", "4.5", "련 수가 정수"),
    ("cells", "0", "1 이상"),
    ("grill_gap", "0", "그릴 살 간격"),
    ("shaft_depth", "-1", "수직구 깊이"),
])
def test_draft_errors(field, value, msg):
    ds = VentDrafts()
    ds.items = [VentDraft(vertices=[VertexDraft("10", "10", ""), VertexDraft("10", "20", "0")])]
    setattr(ds.items[0], field, value)
    with pytest.raises(ValueError, match=msg):
        ds.to_specs(0.0)
