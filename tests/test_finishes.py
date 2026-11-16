"""건축 마감 (용도별 마감표 → 실별 바닥·벽·기둥·승강로·천장·천장틀) 테스트"""
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
from finishes.finish_spec import FILL_VOID, FinishSettings, FinishType, default_finishes
from helper import prism_member as PM
from helper.strip_member import _fan
from openings import decompose
from rooms.room_spec import SEPARATION, DoorSpec, RoomSettings, RoomSpec
from test_curved import NO_COLS, curved_cfg
from test_patch import make_cfg, user_example

# user_example: 3개 층 각 6m (중간 슬래브 0.4, 천장 0.4), 내공 198 x 18, 승강장 t ±3.9 ~ ±9 (상면 1.3), 기둥 t=0 열


def cfg_with(*rooms, curved=False, table=None, default_uses=None, **extra):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(NO_COLS() if extra.pop("no_cols", False) else user_example())
    cfg.rooms = list(rooms)
    cfg.room_settings = RoomSettings(default_uses=default_uses or {})
    cfg.finish_settings = FinishSettings(enabled=True, table=table or default_finishes())
    for k, v in extra.items():
        setattr(cfg, k, v)
    return cfg


def fin(eng, room):
    return next(r for r in eng.finishes.rooms if r.room == room)


def rect_area(pieces):
    return sum(p.shape.length * p.shape.width for p in pieces)


# ===================================================== 기본·마감표
def test_disabled_by_default_and_table():
    assert StationCADEngine(make_cfg(user_example())).finishes.rooms == []
    t = default_finishes()
    assert t["통신실"].floor_fill == FILL_VOID and t["통신실"].ffl == 0.45 and not t["기계실"].ceiling
    fs = FinishSettings(table=t)
    assert fs.for_room("미등록용도").name == "기본" and fs.for_room("대합실", "화장실").name == "화장실"
    with pytest.raises(ValueError, match="마감표에 없습니다"):
        fs.for_room("대합실", "없는마감")


# ===================================================== 바닥
def test_floor_layers_and_access_floor():
    eng = StationCADEngine(cfg_with(RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF"),
                                    RoomSpec(2, "통신실", 40, 60, 2, 9, name="TEL"), no_cols=True))
    off, tel = fin(eng, "OFF"), fin(eng, "TEL")
    # 칸막이벽 중심선 기준 20 x 7 → 마감 영역 = (20 − 0.2) x (7 − 0.1) (본체 벽 쪽 t=9 는 0)
    area = 19.8 * 6.9
    top = off.element("FLOOR")
    assert rect_area(top.pieces) == pytest.approx(area)
    assert {round(PM.z_off(eng.cfg, p), 6) for p in top.pieces} == {round(6.0 + 0.1 - 0.03, 6)}
    assert off.element("FILL").volume == pytest.approx(area * 0.07)
    assert tel.element("FILL") is None and tel.element("FLOOR").volume == pytest.approx(area * 0.035)   # 빈 공간
    assert tel.ffl_rel == pytest.approx(6.45)


def test_platform_floor_finish_only_on_platform():
    eng = StationCADEngine(cfg_with(no_cols=True))
    plat = fin(eng, "B3F_승강장층")
    pieces = plat.element("FLOOR").pieces
    assert rect_area(pieces) == pytest.approx(2 * (9 - 3.9) * 198)                # 좌·우 승강장만
    assert all(PM.z_off(eng.cfg, p) == pytest.approx(1.3 + 0.07) for p in pieces)
    assert plat.ceiling_rel == pytest.approx(1.3 + 0.1 + 3.0)
    # 천장·천장틀도 승강장 위만 (선로 구간 t ±3.9 안쪽에는 천장 마감 없음)
    ceil = plat.element("CEILING").pieces
    assert rect_area(ceil) == pytest.approx(2 * (9 - 3.9) * 198)
    assert all(abs(p.pos_y) - p.shape.width / 2 >= 3.9 - 1e-9 for p in ceil + plat.element("FRAME").pieces)


def test_floor_skips_openings_stairs_and_shafts():
    ev = ElevatorSpec(lower_floor=2, upper_floor=3, s_center=100, t_center=-6.0, door_side="+t")
    eng = StationCADEngine(cfg_with(no_cols=True, elevators=[ev]))
    hall = fin(eng, "B1F_대합실")
    S0, S1, T0, T1 = ev.outer_rect()
    for p in hall.element("FLOOR").pieces + hall.element("CEILING").pieces:
        assert decompose.overlap_area((*PM.s_range(p), *PM.t_range(p)), (S0, S1, T0, T1)) < 1e-9
    assert rect_area(hall.element("FLOOR").pieces) == pytest.approx(198 * 18 - (S1 - S0) * (T1 - T0))


# ===================================================== 벽
def test_wall_finish_on_station_and_partition_faces_with_door_holes():
    room = RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF", doors=[DoorSpec("-t", 20.0, 1.0, 2.1)])
    eng = StationCADEngine(cfg_with(room, no_cols=True))
    off = fin(eng, "OFF")
    f, h = 0.05, 2.7                                            # 역무실: 벽 0.05, 벽 높이 = 바닥 마감면 ~ 천장판 하면 = 2.7
    # 둘레(마감면): s 방향 19.8 (t=2 칸막이벽, t=9 본체 벽) ×2, t 방향 6.9 − 2f ×2 (모서리 겹침 없음)
    length = 19.8 * 2 + (6.9 - 2 * f) * 2
    door = 1.0 * (6.0 + 2.1 - (6.0 + 0.1))                     # 마감면 위 문 높이 2.0
    assert off.element("WALL").volume == pytest.approx(f * (length * h - door))
    hall = fin(eng, "B2F_대합실")                                 # 칸막이벽 바깥쪽에도 대합실 벽 마감 (문 자리 비움)
    outside = [p for p in hall.element("WALL").pieces if abs(PM.t_range(p)[1] - 1.9) < 1e-9]
    assert outside and sum(p.shape.volume for p in outside) == pytest.approx(0.05 * (20.0 * 3.0 - 1.0 * 2.0))   # 실 경계 s 10 ~ 30


def test_wall_finish_skips_virtual_separation_and_passage_opening():
    from passages.passage_spec import PassageSpec, station_path
    rooms = [RoomSpec(3, "대합실", 40, 70, -9, 9, boundary=SEPARATION, name="PAID")]
    cfg = cfg_with(*rooms, no_cols=True, default_uses={3: "복도"},
                   passages=[PassageSpec(floor=3, path=station_path([(55, 10, None), (55, 25, 0)]))])
    eng = StationCADEngine(cfg)
    paid = fin(eng, "PAID")
    ws = paid.element("WALL").pieces
    assert not any(p.shape.length < 0.1 for p in ws)                                    # s=40, 70 가상선 → t 방향 벽 마감 없음
    left = [p for p in ws if PM.t_range(p)[1] == pytest.approx(9.0)]                    # 통로 오프닝(s 53 ~ 57, 높이 3) 비움
    assert sum(p.shape.volume for p in left) == pytest.approx(0.05 * (30 * 3.0 - 4.0 * (3.0 - 0.1)))


def test_concrete_rooms_have_no_finish_geometry():
    eng = StationCADEngine(cfg_with(RoomSpec(2, "기계실", 10, 30, 2, 9, name="MEC"), no_cols=True))
    assert fin(eng, "MEC").elements == []


# ===================================================== 기둥·승강로 둘레
def test_column_and_shaft_rings():
    ev = ElevatorSpec(lower_floor=2, upper_floor=3, s_center=100, t_center=-6.0, door_side="+t")
    eng = StationCADEngine(cfg_with(elevators=[ev]))
    hall = fin(eng, "B2F_대합실")
    col = hall.element("COLUMN")
    f = 0.05
    rings = col.boxes                                            # B2F 원기둥 φ1.0 둘레 16각형
    assert rings and len(rings) % 16 == 0
    one = sum(b.volume for b in rings[:16])
    import math
    side = 2 * 0.5 * math.tan(math.pi / 16)
    assert one == pytest.approx(16 * f * (side + math.tan(math.pi / 16) * f) * 3.0)
    S0, S1, T0, T1 = ev.outer_rect()
    shaft = [p for p in col.pieces if S0 - f - 1e-9 <= PM.s_range(p)[0] and PM.s_range(p)[1] <= S1 + f + 1e-9]
    perim = 2 * (S1 - S0 + 2 * f) + 2 * (T1 - T0)
    assert sum(p.shape.volume for p in shaft) == pytest.approx(f * (perim * 3.0 - 0.9 * 2.0))   # 출입구(문 0.9 x 마감면 위 2.0)


# ===================================================== 천장·천장틀
def test_ceiling_board_and_frame_grid():
    eng = StationCADEngine(cfg_with(RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF"), no_cols=True))
    off = fin(eng, "OFF")
    assert off.ceiling_rel == pytest.approx(6.0 + 0.1 + 2.7)
    board = off.element("CEILING")
    assert rect_area(board.pieces) == pytest.approx(19.8 * 6.9)
    ft = default_finishes()["역무실"]
    frame = off.element("FRAME").pieces
    bars = [p for p in frame if p.shape.width > 1]               # t 방향 바 (M바): s 0.6 격자
    carriers = [p for p in frame if p.shape.length > 1]
    s_pos = sorted(round(p.pos_x, 6) for p in bars)
    assert s_pos[0] == pytest.approx(10.2) and all(abs(b - a - 0.6) < 1e-6 for a, b in zip(s_pos, s_pos[1:]))
    assert len(carriers) == len([t for t in [k * 0.9 for k in range(-20, 20)] if 2.1 < t < 9.0])
    z_bar = PM.z_off(eng.cfg, bars[0])
    assert z_bar == pytest.approx(off.ceiling_rel + ft.board_t)


def test_ceiling_too_high_rejected():
    t = default_finishes()
    t["역무실"] = FinishType("역무실", ceiling_h=5.5)
    with pytest.raises(ValueError, match="천장"):
        StationCADEngine(cfg_with(RoomSpec(2, "역무실", 10, 30, 2, 9), table=t, no_cols=True))


@pytest.mark.parametrize("ft,msg", [
    (FinishType("X", ffl=0.02, floor_t=0.03), "마감 높이"),
    (FinishType("X", ffl=0.1, floor_t=0.0), "마감재 두께도"),
    (FinishType("X", floor_fill="sand"), "바닥 채움"),
    (FinishType("X", frame="Z"), "천장틀"),
    (FinishType("X", bar_spacing=0.0), "바 간격"),
    (FinishType("X", wall_t=-0.1), "벽 마감 두께"),
])
def test_invalid_finish_types(ft, msg):
    t = default_finishes()
    t["X"] = ft
    with pytest.raises(ValueError, match=msg):
        StationCADEngine(cfg_with(table=t, no_cols=True))


def test_room_finish_override():
    eng = StationCADEngine(cfg_with(RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF", finish="화장실"), no_cols=True))
    assert fin(eng, "OFF").finish.name == "화장실"
    with pytest.raises(ValueError, match="마감표에 없습니다"):
        StationCADEngine(cfg_with(RoomSpec(2, "역무실", 10, 30, 2, 9, finish="없음"), no_cols=True))


# ===================================================== 체적 교차 검증 · IFC · 도면
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("curved", [False, True])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, curved):
    rooms = [RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF", doors=[DoorSpec("-t", 20.0)]),
             RoomSpec(2, "통신실", 40, 60, -9, -2, name="TEL")]
    eng = StationCADEngine(cfg_with(*rooms, curved=curved))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "f.ifc"))
    by = {e.Name: e for e in f.by_type("IfcProduct") if e.Name}
    tol = 1e-4 if curved else 1e-7
    for e in eng.finishes.all_elements():
        quads = [q for p in e.pieces for q in PM.sweep_quads(PM.rings(eng.cfg, p))]
        if curved:
            quads = [t for q in quads for t in _fan(q)]
        mesh = PM.mesh_volume(quads) + sum(PM.mesh_volume(b.faces()) for b in e.boxes)
        assert mesh == pytest.approx(e.volume, rel=tol), e.name
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=tol), e.name


def test_ifc_coverings_and_space_pset(tmp_path):
    eng = StationCADEngine(cfg_with(RoomSpec(2, "통신실", 40, 60, -9, -2, name="TEL"), no_cols=True))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "f.ifc"))
    tel = next(s for s in f.by_type("IfcSpace") if s.Name == "TEL")
    covered = [c for rel in tel.HasCoverings for c in rel.RelatedCoverings]
    assert {c.PredefinedType for c in covered} == {"FLOORING", "CEILING"}            # 통신실: 벽 면처리 → 벽 마감 없음
    pset = ifcopenshell.util.element.get_psets(tel)["SSBIM_SpaceFinish"]
    assert pset["FinishType"] == "통신실" and pset["FloorFinishLevel"] == pytest.approx(0.45) and pset["CeilingFrame"] == "M바"
    frame = next(m for m in f.by_type("IfcMember") if m.Name == "FIN_TEL_FRAME")
    assert ifcopenshell.util.element.get_container(frame).Name == "B2F"
    assert ifcopenshell.util.element.get_material(covered[0]).Name in ("액세스 플로어", "알루미늄 천장판")


def test_drawings(tmp_path):
    eng = StationCADEngine(cfg_with(RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF")))
    msp = ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace()
    for layer in ("FIN_FLOOR", "FIN_WALL", "FIN_CEILING", "FIN_FRAME"):
        assert msp.query(f'3DFACE[layer=="{layer}"]'), layer
    assert any(it.layer == "SEC_FINISH" for it in eng.finishes.section_items(20.0))
    assert any(it.layer == "PROF_FINISH" for it in eng.finishes.profile_items(5.0))
    plan = eng.finishes.plan_items(6.0 + 2.0, floor=2)
    assert plan and all(it.layer == "PLAN_FINISH" for it in plan)


# ===================================================== 입력 초안
from gui.finish_draft import FinishDrafts, FinishTypeDraft, preview


def test_finish_drafts():
    ds = FinishDrafts()
    s = ds.to_settings()
    assert s.enabled and set(s.table) == set(default_finishes()) and s.table["통신실"] == default_finishes()["통신실"]
    d = FinishTypeDraft(name="A", ceiling=False, ceiling_h="x")                         # 천장 없으면 천장 입력 무시
    assert d.to_type("").ceiling is False
    assert "천장 없음" in preview(d) and "바닥 FL+0.1" in preview(FinishTypeDraft())
    ds.items.append(FinishTypeDraft(name="대합실"))
    with pytest.raises(ValueError, match="중복"):
        ds.to_settings()
    bad = FinishDrafts()
    bad.items = [FinishTypeDraft(name=" ")]
    with pytest.raises(ValueError, match="마감 종류 이름을 입력"):
        bad.to_settings()
