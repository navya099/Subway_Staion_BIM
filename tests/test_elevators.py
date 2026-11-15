"""엘리베이터 (승강로 + 내린 피트 + 오버헤드 + 카(바닥·벽·천장·문), 정지층 출입구·슬래브 오프닝 자동) 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import pytest

from elevators.elevator_spec import ElevatorSpec
from engine.cad_engine import StationCADEngine
from helper import prism_member as PM
from helper.strip_member import part_faces
from test_curved import NO_COLS, curved_cfg
from test_patch import make_cfg, user_example
from test_stairs import stair

# user_example: 3개 층 각 6m (바닥 1.2, 중간 0.4, 천장 0.4), 내공 폭 18, 승강장 t ±3.9 ~ ±9 (높이 1.1 + 두께 0.2 = 상면 1.3)
PLAT = dict(lower_floor=1, upper_floor=3, s_center=60, t_center=6.5, door_side="-t")     # 왼쪽 승강장 위
UPPER = dict(lower_floor=2, upper_floor=3, s_center=100, t_center=-6.5, door_side="+s", through=True, car_floor=3)


def cfg_with(*evs, curved=False, stairs=()):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(user_example())
    cfg.elevators = [e if isinstance(e, ElevatorSpec) else ElevatorSpec(**e) for e in evs]
    cfg.stairs = list(stairs)
    return cfg


def eng_with(*evs, **kw):
    return StationCADEngine(cfg_with(*evs, **kw))


def rel(cfg, s, z):
    return z - (cfg.lv(s) - cfg.station.offset)


# ===================================================== 배치
def test_platform_elevator_heights_and_openings():
    cfg = cfg_with(PLAT)
    lay = cfg.elevator_layouts()[0]
    assert lay.on_platform and lay.stop_rel == {1: pytest.approx(1.3), 2: 6.0, 3: 12.0}
    lo, hi = (rel(cfg, 60, z) for z in lay.z_range)
    assert lo == pytest.approx(-1.2)                         # 피트 슬래브(−0.8 ~ −0.2)가 바닥 슬래브 안에서 끝남 → 하면까지 채움
    assert hi == pytest.approx(12 + 4.0 + 0.3)
    assert lay.opening.slabs == [0, 1, 2] and lay.opening.name == "EV1_SHAFT"
    assert (lay.opening.s_start, lay.opening.length, lay.opening.t_center, lay.opening.width) == \
        pytest.approx((58.5 - 0.3 + 0.3, 3.0, 6.5, 3.0))
    assert lay.platform_hole == ("EV1_SHAFT", 58.5, 61.5, 5.0, 8.0)
    assert len(lay.door_openings) == 3 and {d[1] for d in lay.door_openings} == {"WALL_NT"}


def test_upper_elevator_pit_hangs_into_lower_floor_and_through_doors():
    cfg = cfg_with(UPPER)
    lay = cfg.elevator_layouts()[0]
    assert not lay.on_platform and lay.opening.slabs == [1, 2] and lay.platform_hole is None
    assert rel(cfg, 100, lay.z_range[0]) == pytest.approx(6 - 1.5 - 0.6)
    assert sorted({d[1] for d in lay.door_openings}) == ["WALL_NS", "WALL_PS"] and len(lay.door_openings) == 4


def test_parts_and_volume_by_hand():
    ev = eng_with(UPPER).elevators.elevators[0]
    codes = {e.code for e in ev.elements}
    assert codes == {"PIT", "TOP", "WALL_PS", "WALL_NS", "WALL_PT", "WALL_NT", "CAR_FLOOR", "CAR_ROOF",
                     "CAR_WALL_PS", "CAR_WALL_NS", "CAR_WALL_PT", "CAR_WALL_NT", "CAR_DOOR_PS", "CAR_DOOR_NS"}
    H = (12 + 4.0) - (6 - 1.5)                                   # 벽 높이: 피트 바닥 상면 ~ 오버헤드
    door = 0.9 * 2.1 * 0.3
    assert ev.element("WALL_PS").volume == pytest.approx(3.0 * 0.3 * H - 2 * door)     # 정지층 2개 출입구
    assert ev.element("WALL_PT").volume == pytest.approx(2.4 * 0.3 * H)
    assert ev.element("PIT").volume == pytest.approx(3.0 * 3.0 * 0.6)
    assert ev.element("TOP").volume == pytest.approx(3.0 * 3.0 * 0.3)
    # 카 (+s 문: 깊이 s 1.5, 폭 t 1.6, 벽 0.05) — 벽 + 문 = 닫힌 상자 벽
    cw, ch = 0.05, 2.3
    assert ev.element("CAR_FLOOR").volume == pytest.approx(1.6 * 1.7 * 0.1)
    assert ev.element("CAR_WALL_PS").volume + ev.element("CAR_DOOR_PS").volume == pytest.approx(cw * 1.7 * ch)
    assert ev.element("CAR_DOOR_PS").volume == pytest.approx(cw * 0.9 * 2.1)


def test_car_parks_on_chosen_floor():
    for car, z in ((1, 1.3), (2, 6.0), (3, 12.0)):
        cfg = cfg_with({**PLAT, "car_floor": car})
        ev = StationCADEngine(cfg).elevators.elevators[0]
        top = ev.element("CAR_FLOOR").parts[0].z_range[1]
        assert rel(cfg, 60, top) == pytest.approx(z)
        door = ev.element("CAR_DOOR_NT").parts[0]
        assert door.t_range[0] == pytest.approx(6.5 - 0.75 - 0.05)                      # −t 쪽 카 벽 자리


def test_station_slabs_and_platform_are_cut():
    eng = eng_with(PLAT)
    holes = [o for pk in eng.slabs.slab_packages for sl in pk.slabs for o in sl.openings if "EV1" in o.name]
    assert len(holes) == 3
    plat = [o for pk in eng.platform.platform_packages for pl in pk.platforms for o in pl.openings]
    assert [o.kind.code for o in plat] == ["ELEV"]


# ===================================================== 검증
@pytest.mark.parametrize("kw,msg", [
    ({"upper_floor": 1}, "위여야"),
    ({"upper_floor": 4}, "범위"),
    ({"car_floor": 3, "upper_floor": 2}, "카 정지층"),
    ({"door_side": "x"}, "문 방향"),
    ({"car_width": 2.4}, "카 외곽"),
    ({"door_w": 1.7}, "문 폭"),
    ({"overhead": 2.0}, "오버헤드"),
    ({"overhead": 5.7}, "본체 천장"),
    ({"door_h": 5.0, "car_height": 5.1, "overhead": 5.5}, "문 높이|본체 천장"),
    ({"t_center": 4.0}, "걸쳐"),
    ({"lower_floor": 2, "t_center": 8.0}, "내공 폭"),
    ({"s_center": 0.5}, "내공 길이"),
    ({"wall_t": 0.0}, "0보다"),
])
def test_invalid_elevator_rejected(kw, msg):
    with pytest.raises(ValueError, match=msg):
        eng_with({**PLAT, **kw})


def test_pit_reaching_lower_floor_rejected():
    with pytest.raises(ValueError, match="아래층"):
        eng_with({**UPPER, "pit_depth": 5.5, "overhead": 4.0})


def test_overlaps_rejected():
    with pytest.raises(ValueError, match="서로 겹칩니다"):
        eng_with(PLAT, {**PLAT, "s_center": 61, "name": "B"})
    with pytest.raises(ValueError, match="ST1 와 EV1_SHAFT"):                         # 위층 슬래브 자동 오프닝끼리 먼저 걸림
        eng_with(PLAT, stairs=[stair(lower=1, s=56.0, name="ST1")])
    from elevators.elevator_check import check_elevator_layouts                    # 평면 겹침 검사 자체 (오프닝 검사보다 뒤)
    cfg = cfg_with({**UPPER, "s_center": 49.0, "t_center": 6.5}, stairs=[stair(lower=1, s=40.0, name="ST1")])
    with pytest.raises(ValueError, match="계단 ST1"):
        check_elevator_layouts(cfg, cfg.elevator_layouts(), cfg.stair_layouts(), [])
    with pytest.raises(ValueError, match="지지벽체"):
        eng_with({**PLAT, "t_center": 7.4, "inner_t": 2.4})
    with pytest.raises(ValueError, match="이름이 중복"):
        eng_with({**PLAT, "name": "A"}, {**UPPER, "name": "A"})


# ===================================================== 체적 교차 검증 (공식 ↔ 3D 메쉬 ↔ IFC)
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("kw,curved", [(PLAT, False), (UPPER, False), ({**PLAT, "upper_floor": 2}, True)])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, kw, curved):
    eng = eng_with(kw, curved=curved)
    cfg = eng.cfg
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "e.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    rel_tol = 1e-4 if curved else 1e-7
    for e in eng.elevators.elevators[0].elements:
        mesh = sum(PM.mesh_volume(q) for p in e.parts for q in part_faces(cfg, p))
        assert mesh == pytest.approx(e.volume, rel=rel_tol), e.name
        assert ifc_world_volume(by_name[e.name]) == pytest.approx(e.volume, rel=rel_tol), e.name


def test_ifc_structure(tmp_path):
    eng = eng_with(PLAT)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "e.ifc"))
    asm = next(a for a in f.by_type("IfcElementAssembly") if a.ObjectType == "ELEVATOR")
    assert asm.Name == "EV1" and ifcopenshell.util.element.get_container(asm).Name == "B3F"
    kids = ifcopenshell.util.element.get_decomposition(asm)
    car = next(k for k in kids if k.is_a("IfcTransportElement"))
    assert car.PredefinedType == "ELEVATOR"
    car_parts = ifcopenshell.util.element.get_decomposition(car)
    assert {k.is_a() for k in car_parts} == {"IfcBuildingElementPart", "IfcDoor"}
    assert {k.PredefinedType for k in kids if k.is_a("IfcSlab")} == {"BASESLAB", "ROOF"}
    wall_nt = next(k for k in kids if k.Name == "EV1_WALL_NT")
    ops = [r.RelatedOpeningElement for r in f.by_type("IfcRelVoidsElement") if r.RelatingBuildingElement == wall_nt]
    assert len(ops) == 3 and all(o.ObjectType == "ELEVATOR_DOOR" for o in ops)


# ===================================================== 도면
def test_drawings(tmp_path):
    eng = eng_with(PLAT)
    ev = eng.elevators.elevators[0]
    msp = ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace()
    n_car = sum(len(fs) for e in ev.car for p in e.parts for fs in part_faces(eng.cfg, p))
    assert len(msp.query('3DFACE[layer=="STRUCT_ELEVATOR_CAR"]')) == n_car
    items = eng.elevators.section_items(60.0)
    assert {it.layer for it in items} == {"SEC_CONCRETE", "SEC_ELEVATOR"} and [it.label[0] for it in items if it.label] == ["EV1"]
    cut = eng.elevators.profile_items(6.5)
    assert any(it.layer == "PROF_CONCRETE" for it in cut) and any(it.layer == "PROF_ESCALATOR" for it in cut)
    side = eng.elevators.profile_items(0.0)
    assert [it.layer for it in side] == ["PROF_BEYOND"]
    for fl, n in ((1, 5), (2, 4), (3, 4)):                                            # 카는 최하층(기본)에만
        assert len(eng.elevators.plan_items(0.0, floor=fl)) == n
    path = eng.generate_plan_dxf(tmp_path / "p.dxf", floors=[1, 2, 3])
    assert len(ezdxf.readfile(path).modelspace().query('LWPOLYLINE[layer=="PLAN_ELEVATOR"]')) == 13


def test_build_all_outputs(tmp_path):
    from engine.bim_engine import BIMEngine
    assert len(BIMEngine.build(cfg_with(PLAT, UPPER), tmp_path)) == 5


# ===================================================== 입력 초안
from gui.elevator_draft import ElevatorDraft, ElevatorDrafts, preview


def test_draft_converts_and_follows_floors():
    d = ElevatorDraft(sta_center="160", t_center="6.5", door="+s (종점 방향)", through=True, upper_floor=3, car_floor=2)
    sp = d.to_spec("엘리베이터 1", 100.0)
    assert (sp.s_center, sp.door_side, sp.through, sp.upper_floor, sp.car_floor) == (60.0, "+s", True, 3, 2)
    assert "정지 B3F ~ B1F (3개 층), 카 B2F, 문 +s 관통형" in preview(d, 100.0, 3)
    ds = ElevatorDrafts(); ds.items = [d]
    assert ds.ensure_floors(2) and (d.lower_floor, d.upper_floor, d.car_floor) == (1, 2, 2)
    d.inner_s = "x"
    with pytest.raises(ValueError, match="엘리베이터 1: 승강로 내공 s"):
        ds.to_specs(0.0)
    assert "확인" in preview(d, 0.0, 2)
