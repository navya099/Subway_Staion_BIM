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


# ===================================================== 투시형 승강로 (실무 표준도 068·069: 강관 + 유리 + 금속 패널, RC 피트, 90도형)
GLASS = dict(lower_floor=2, upper_floor=3, s_center=100, t_center=-6.5, shaft="glass", inner_s=3.0, inner_t=2.71,
             door_floors=["-s", "+t"], car_floor=3)


def _glass_parts(lay):
    out = {}
    for p in lay.parts:
        out.setdefault(p.code, []).append(p)
    return out


def test_glass_shaft_layout():
    import random
    from elevators.elevator_engine import ev_part_faces
    cfg = cfg_with(GLASS)
    lay = cfg.elevator_layouts()[0]
    sp = lay.spec
    S0, S1, T0, T1 = sp.outer_rect()
    assert (S1 - S0, T1 - T0) == pytest.approx((3.84, 3.55))                                  # 실무 유리 외곽 3,840 × 3,550
    parts = _glass_parts(lay)
    assert "TOP" not in parts and not [c for c in parts if c.startswith("WALL_")]              # RC 승강로 벽·천장 슬래브 없음
    assert lay.opening.slabs == [1, 2] and lay.opening.width == pytest.approx(3.55)
    r = lambda z: rel(cfg, 100, z)
    # 기둥: 유리 바깥면에서 0.25 안쪽, 피트 바닥(6 − 1.5) ~ 최상 정지층(B1F, 12) 위 천장 슬래브 하면(18 − 0.4)
    (col,) = parts["COL_NN"]
    assert sum(col.s_range) / 2 == pytest.approx(S0 + 0.25) and sum(col.t_range) / 2 == pytest.approx(T0 + 0.25)
    assert [r(z) for z in col.z_range] == pytest.approx([4.5, 17.6])
    # 유리: 정지 바닥 + 0.07 부터 줄 1.3 / 1.2 / 0.5, 문 없는 면은 최대 2.0 폭으로 고르게 (3.55 → 2장)
    g = parts["GLASS_PS_B2F"]
    assert len(g) == 2 * 3 and sorted({round(r(p.z_range[0]), 3) for p in g}) == pytest.approx([6.07, 7.37, 8.57])
    # 문 면 (B2F = −s): 문 자리(폭 0.9)는 맨 위 줄만, 문 열림 높이 = 문 높이(2.1) 이상 첫 줄눈 (0.07 + 2.5)
    door = [p for p in parts["GLASS_NS_B2F"] if abs(sum(p.t_range) / 2 - sp.t_center) < 1e-6]
    assert len(door) == 1 and r(door[0].z_range[0]) == pytest.approx(6 + 2.57)
    assert [(d[1], d[2]) for d in lay.door_openings] == [("GLASS_NS_B2F", 2), ("GLASS_PT_B1F", 3)]
    # 가로재: 줄눈 3곳 × 4면, 문 면은 문 머리(2.57)보다 낮은 줄(1.37)만 문 자리에서 끊김
    assert len(parts["GIRT_PS_B2F"]) == 3 and len(parts["GIRT_NS_B2F"]) == 2 + 1 + 1
    # 금속 패널 띠: 유리 윗면 ~ 다음 정지층 유리 아래 / 최상층은 위 슬래브 하면
    (pb,) = parts["PANEL_PS_B2F"]
    assert [r(z) for z in pb.z_range] == pytest.approx([9.07, 12.07])
    assert [r(z) for z in parts["PANEL_PS_B1F"][0].z_range] == pytest.approx([15.07, 17.6])
    # RC 피트: 바닥 슬래브 + 둘레 벽 (피트 바닥 ~ B3F/B2F 중간 슬래브 하면)
    assert [r(z) for z in parts["PIT_WALL_PS"][0].z_range] == pytest.approx([3.9, 5.6])
    # 부재끼리 겹치지 않음 (상자 내부 점 → 다른 상자·기둥·가로재 밖)
    import numpy as np
    boxes = [p for p in lay.parts if p.solid is None]
    solids = [p for p in lay.parts if p.solid is not None]

    def inside(faces, q):
        for f in faces:
            a, b, c = (np.array(f[i]) for i in range(3))
            if np.dot(np.cross(b - a, c - a), np.array(q) - a) > -1e-7:
                return False
        return True
    rng = random.Random(3)
    for p in boxes:
        st = p.shape.strips[0]
        for _ in range(15):
            s, t, z = rng.uniform(st.s0, st.s1), rng.uniform(*p.t_range), rng.uniform(st.zb0, st.zt)
            for q in boxes:
                if q is not p:
                    s2 = q.shape.strips[0]
                    assert not (s2.s0 + 1e-7 < s < s2.s1 - 1e-7 and q.t_range[0] + 1e-7 < t < q.t_range[1] - 1e-7
                                and s2.zb0 + 1e-7 < z < s2.zt - 1e-7), (p.code, q.code)
            x, y = cfg.to_world(s, t)
            assert not any(inside(q.solid.faces(), (x, y, z)) for q in solids), p.code
    for p in lay.parts:                                                                        # 체적 공식 = 메쉬
        assert PM.mesh_volume(ev_part_faces(cfg, p)) == pytest.approx(p.volume, rel=1e-7), p.code


@pytest.mark.parametrize("curved", [False, True])
def test_glass_shaft_outputs(tmp_path, curved):
    from elevators.elevator_engine import ev_part_faces
    kw = dict(GLASS, s_center=60, t_center=6.5, lower_floor=1, upper_floor=2, car_floor=2) if curved else GLASS
    eng = eng_with(kw, curved=curved)
    cfg = eng.cfg
    ev = eng.elevators.elevators[0]
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "g.ifc"))
    by_name = {e.Name: e for e in f.by_type("IfcElement")}
    ent = {"PIT_SLAB": "IfcSlab", "PIT_WALL": "IfcWall", "COLUMN": "IfcColumn", "GIRT": "IfcMember", "GLASS": "IfcPlate",
           "PANEL": "IfcCovering"}
    rel_tol = 1e-4 if curved else 1e-7
    for e in ev.elements:
        if e.kind.name in ent:
            assert by_name[e.name].is_a(ent[e.kind.name]), e.name
        mesh = sum(PM.mesh_volume(ev_part_faces(cfg, p)) for p in e.parts)
        assert mesh == pytest.approx(e.volume, rel=rel_tol), e.name
        assert ifc_world_volume(by_name[e.name]) == pytest.approx(e.volume, rel=rel_tol), e.name
    assert not [o for o in f.by_type("IfcOpeningElement") if o.ObjectType == "ELEVATOR_DOOR"]   # 유리는 문 자리를 비워 만듦
    car = next(k for k in f.by_type("IfcTransportElement") if k.Name == "EV1_CAR")
    assert len([k for k in ifcopenshell.util.element.get_decomposition(car) if k.is_a("IfcDoor")]) == 2   # 90도형 = 카 문 2
    doc = eng.build_3d_doc()
    layers = {e.kind.name: {x.dxf.layer for x in e.source_element} for e in ev.elements}
    assert layers["GLASS"] == {"STRUCT_ELEVATOR_GLASS"} and layers["COLUMN"] == layers["PANEL"] == {"STRUCT_ELEVATOR_FRAME"}
    assert all(len([v for v in (x.dxf.vtx0, x.dxf.vtx1, x.dxf.vtx2, x.dxf.vtx3)]) == 4 for x in doc.modelspace().query("3DFACE"))
    sec = eng.elevators.section_items(ev.elements[0].parts[0].s_range[0] + 0.26)
    assert any(i.layer == "SEC_ELEVATOR" for i in sec)
    assert any(i.name.startswith("EV1_COL") for i in eng.elevators.plan_items(2.0, floor=kw["lower_floor"]))


def test_glass_doors_tactile_and_rules():
    from gui.elevator_draft import ElevatorDraft
    from tactiles.tactile_layout import _auto_blocks
    from tactiles.tactile_spec import TactileSettings
    cfg = cfg_with(GLASS)
    evs = cfg.elevator_layouts()
    S0, S1, T0, T1 = evs[0].outer_rect()
    ts = TactileSettings(enabled=True)
    b2 = [r for name, r in _auto_blocks(cfg, ts, 2, [], [], evs) if name == "EV1"]
    b1 = [r for name, r in _auto_blocks(cfg, ts, 3, [], [], evs) if name == "EV1"]
    assert len(b2) == 1 and b2[0][1] <= S0 and len(b1) == 1 and b1[0][2] >= T1               # 층마다 그 층 문 앞만
    with pytest.raises(ValueError, match="정지층 수"):
        cfg_with(dict(GLASS, door_floors=["-s"])).elevator_layouts()
    with pytest.raises(ValueError, match="문 방향"):
        cfg_with(dict(GLASS, door_floors=["-s", "+x"])).elevator_layouts()
    with pytest.raises(ValueError, match="내공 안으로"):
        cfg_with(dict(GLASS, glass_offset=0.2)).elevator_layouts()
    with pytest.raises(ValueError, match="기둥 사이"):
        cfg_with(dict(GLASS, door_w=3.4, car_width=3.5, inner_s=4.0)).elevator_layouts()
    with pytest.raises(ValueError, match="오버헤드"):
        cfg_with(dict(GLASS, overhead=6.0)).elevator_layouts()
    d = ElevatorDraft(door_floors="-s, +t/−s", glass_rows="1.3, 1.2, 0.5")
    sp = d.to_spec("엘리베이터", 0.0)
    assert sp.shaft == "glass" and sp.door_floors == ["-s", "+t/-s"] and sp.glass_rows == (1.3, 1.2, 0.5)
    assert sp.doors_at(2) == {("t", 1), ("s", -1)}
    assert ElevatorDraft(shaft="RC 승강로").to_spec("e", 0.0).shaft == "rc"
