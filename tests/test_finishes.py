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


def flush_table():
    """이격 없는 마감표 (벽 마감 0.05 를 구조체 면에 바로 붙임) — 이격 도입 전 기하를 검사하는 테스트용"""
    import dataclasses
    return {k: (dataclasses.replace(v, wall_t=0.05, wall_face=None) if v.wall_face is not None else v)
            for k, v in default_finishes().items()}


def cfg_with(*rooms, curved=False, table=None, default_uses=None, **extra):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(NO_COLS() if extra.pop("no_cols", False) else user_example())
    cfg.rooms = list(rooms)
    cfg.room_settings = RoomSettings(default_uses=default_uses or {})
    cfg.finish_settings = FinishSettings(enabled=True, table=table or flush_table())
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
    assert rect_area(ceil) == pytest.approx(2 * (9 - 3.9 - 0.05) * (198 - 0.1))   # 측벽·단부 벽 마감 표면(0.05)에서 끝남
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
    door = 1.0 * 2.1                                           # 문 높이는 바닥 마감면부터
    assert off.element("WALL").volume == pytest.approx(f * (length * h - door))
    hall = fin(eng, "B2F_대합실")                                 # 칸막이벽 바깥쪽에도 대합실 벽 마감 (문 자리 비움)
    outside = [p for p in hall.element("WALL").pieces if abs(PM.t_range(p)[1] - 1.9) < 1e-9]
    # 실 경계 s 10 ~ 30 + 바깥 모서리 너머(벽 반두께 0.1 + 마감 0.05)씩 — 직각으로 도는 대합실 마감과 모서리에서 만남
    assert outside and sum(p.shape.volume for p in outside) == pytest.approx(0.05 * ((20.0 + 2 * 0.15) * 3.0 - 1.0 * 2.1))


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
    assert sum(p.shape.volume for p in shaft) == pytest.approx(f * (perim * 3.0 - 0.9 * 2.1))   # 출입구(문 0.9 x 2.1, 정지 바닥 = 마감면)


# ===================================================== 천장·천장틀
def test_ceiling_board_and_frame_grid():
    eng = StationCADEngine(cfg_with(RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF"), no_cols=True))
    off = fin(eng, "OFF")
    assert off.ceiling_rel == pytest.approx(6.0 + 0.1 + 2.7)
    board = off.element("CEILING")
    assert rect_area(board.pieces) == pytest.approx(19.7 * 6.8)          # 칸막이벽 반두께 + 벽 마감 표면(0.05)까지 뺌
    ft = default_finishes()["역무실"]
    frame = off.element("FRAME").pieces
    bars = [p for p in frame if p.shape.width > 1]               # t 방향 바 (M바): s 0.6 격자
    carriers = [p for p in frame if p.shape.length > 1]
    s_pos = sorted(round(p.pos_x, 6) for p in bars)
    assert s_pos[0] == pytest.approx(10.2) and all(abs(b - a - 0.6) < 1e-6 for a, b in zip(s_pos, s_pos[1:]))
    assert len(carriers) == len([t for t in [k * 0.9 for k in range(-20, 20)] if 2.15 < t < 8.95])
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
    assert s.enabled and set(s.table) == set(default_finishes()) and s.table["기계실"] == default_finishes()["기계실"]
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



# ===================================================== 벽 마감 이격 (구조체 면 → 마감 표면)
GAP_FACE, GAP_T = 0.15, 0.0016          # 기본 금속패널 (실무 상세 WB-14)


def gap_cfg(*rooms, **kw):
    return cfg_with(*rooms, table=default_finishes(), **kw)


def test_default_panel_face_and_validation():
    t = default_finishes()
    assert t["대합실"].face == GAP_FACE and t["대합실"].wall_t == GAP_T and t["대합실"].wall_gap == pytest.approx(0.1484)
    assert t["화장실"].face == t["화장실"].wall_t == 0.03 and t["공조실"].face == 0.0          # 타일·면처리는 이격 없음
    assert FinishType("x").face == 0.05                                                         # 비우면 이격 없음
    bad = dict(default_finishes(), 대합실=FinishType("대합실", wall_t=0.05, wall_face=0.03))
    with pytest.raises(ValueError, match="마감면 거리"):
        StationCADEngine(cfg_with(table=bad))


def test_wall_finish_offset_on_station_wall_and_corners():
    eng = StationCADEngine(gap_cfg(no_cols=True))
    hall = fin(eng, "B2F_대합실")
    walls = hall.element("WALL").pieces
    left = [p for p in walls if p.shape.length > 100]                      # 왼쪽(+t)·오른쪽 측벽 마감
    for p in left:
        y0, y1 = p.pos_y - p.shape.width / 2, p.pos_y + p.shape.width / 2
        assert abs(y1) == pytest.approx(9 - 0.1484) or abs(y0) == pytest.approx(9 - 0.1484)
        assert p.shape.width == pytest.approx(GAP_T)
        s0, s1 = PM.s_range(p)
        assert s0 == pytest.approx(0.1484) and s1 == pytest.approx(198 - 0.1484)   # 단부 벽 이격 공간에는 안 들어감
    ends = [p for p in walls if p.shape.length < 1]                        # 단부 벽 마감 (t 방향)
    assert ends and all(min(PM.s_range(p)) == pytest.approx(0.1484) or max(PM.s_range(p)) == pytest.approx(198 - 0.1484)
                        for p in ends)
    # 모서리: 단부 마감은 측벽 마감 표면까지 (겹침·빈틈 없음)
    for p in ends:
        assert p.shape.width == pytest.approx(18 - 2 * 0.15)
    # 천장판은 마감 표면에서 끝남, 바닥은 구조체 면까지
    assert rect_area(hall.element("CEILING").pieces) == pytest.approx((198 - 0.3) * (18 - 0.3))
    assert rect_area(hall.element("FLOOR").pieces) == pytest.approx(198 * 18)


def test_wall_finish_offset_on_partition_and_column_rings():
    room = RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF")
    eng = StationCADEngine(gap_cfg(room))
    off = fin(eng, "OFF")
    t_low = [p for p in off.element("WALL").pieces if p.shape.length > 10 and p.pos_y < 5]     # t=2 칸막이벽 면
    # 칸막이벽은 본체 벽 이격(0.1484)과 따로 — 칸막이 마감면 거리를 비우면 이격 없이 벽 면에 붙음
    assert t_low and all(p.pos_y - p.shape.width / 2 == pytest.approx(2 + 0.1) for p in t_low)
    cfg = gap_cfg(room)
    cfg.finish_settings.table["역무실"].partition_face = 0.15
    off2 = fin(StationCADEngine(cfg), "OFF")
    t_low = [p for p in off2.element("WALL").pieces if p.shape.length > 10 and p.pos_y < 5]
    assert t_low and all(p.pos_y - p.shape.width / 2 == pytest.approx(2 + 0.1 + 0.1484) for p in t_low)
    # B2F 원기둥(φ1.0) 둘레: 반지름 0.5 + 이격에 외접하는 16각형
    hall = fin(eng, "B2F_대합실")
    import math
    ring = hall.element("COLUMN").boxes[:16]
    r = 0.5 + 0.1484
    side = 2 * r * math.tan(math.pi / 16)
    assert sum(b.volume for b in ring) == pytest.approx(16 * GAP_T * (side + math.tan(math.pi / 16) * GAP_T) * 3.0, rel=1e-9)


@pytest.mark.parametrize("curved", [False, True])
def test_wall_finish_offset_volumes_mesh_and_ifc(tmp_path, curved):
    rooms = [RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF", doors=[DoorSpec("-t", 20.0)])]
    eng = StationCADEngine(gap_cfg(*rooms, curved=curved))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "f.ifc"))
    by = {e.Name: e for e in f.by_type("IfcProduct") if e.Name}
    tol = 1e-4 if curved else 1e-7
    for e in eng.finishes.all_elements():
        if e.code not in ("WALL", "COLUMN", "CEILING"):
            continue
        quads = [q for p in e.pieces for q in PM.sweep_quads(PM.rings(eng.cfg, p))]
        if curved:
            quads = [t for q in quads for t in _fan(q)]
        mesh = PM.mesh_volume(quads) + sum(PM.mesh_volume(b.faces()) for b in e.boxes)
        assert mesh == pytest.approx(e.volume, rel=tol), e.name
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=tol), e.name
    off = next(s for s in f.by_type("IfcSpace") if s.Name == "OFF")
    pset = ifcopenshell.util.element.get_psets(off)["SSBIM_SpaceFinish"]
    assert pset["WallFinishFace"] == pytest.approx(GAP_FACE) and pset["WallFinishGap"] == pytest.approx(0.1484)


def test_wall_face_drafts_round_trip_and_old_project():
    from gui.finish_draft import FinishTypeDraft, preview
    from gui.project_file import ProjectState
    d = FinishTypeDraft.from_type(default_finishes()["대합실"])
    assert d.wall_face == "0.15" and d.wall_t == "0.0016"
    ft = d.to_type("x")
    assert ft.face == 0.15 and ft.wall_gap == pytest.approx(0.1484)
    assert "구조면→표면 0.15" in preview(d) and "이격 0.1484" in preview(d)
    d.wall_face = ""
    assert d.to_type("x").wall_face is None and d.to_type("x").wall_gap == 0                 # 비우면 이격 없음
    d.wall_face = "0.001"
    with pytest.raises(ValueError, match="마감면 거리"):
        d.to_type("x")
    # 옛 프로젝트 파일(마감면 거리 칸 없음)은 이격 없이 열림
    st = ProjectState()
    raw = st.to_dict()
    for x in raw["finish_drafts"]:
        x.pop("wall_face", None)
    back = ProjectState.from_dict(raw)
    assert all(x.wall_face == "" for x in back.finish_drafts)
    assert ProjectState.from_dict(st.to_dict()).finish_drafts[0].wall_face == "0.15"


# ===================================================== 계단·ESC 오프닝: 아래층 천장 마감 기준 머리 높이 + 옆 여유
from escalators.escalator_spec import EscalatorSpec
from stairs.stair_spec import StairSpec


def _open(eng, name):
    return next(o for o in eng.cfg.all_openings() if o.name == name)


def _surfaces(eng, name):
    lay = next(x for x in eng.cfg.stair_layouts() if x.name == name)
    return lay, [(ua, ub, zt) for p in lay.parts for ua, ub, zt in p.surfaces]


def test_stair_opening_uses_lower_floor_ceiling_for_headroom():
    """B2F→B1F 계단: 대합실 천장판 하면(FL+0.1+3.0) 이 슬래브 하면(FL+5.6) 보다 낮아 오프닝이 길어짐.
    오프닝 밖 걷는 면은 천장판까지 머리 높이 2.1 이상, 오프닝 시작 면은 부족"""
    sp = StairSpec(lower_floor=2, s_start=60.0, direction=1, t_center=-6.0, width=2.0, name="ST")
    flat = StationCADEngine(cfg_with(no_cols=True, stairs=[sp], table=flush_table()))
    off_cfg = cfg_with(no_cols=True, stairs=[sp])
    off_cfg.finish_settings.enabled = False
    plain = StationCADEngine(off_cfg)
    o_fin, o_off = _open(flat, "ST"), _open(plain, "ST")
    assert o_fin.length > o_off.length + 1.0 and o_fin.s_end == pytest.approx(o_off.s_end)
    cfg, st = flat.cfg, flat.cfg.station
    ceil = st.floor_level(2) + 0.1 + 3.0
    lay, surfs = _surfaces(flat, "ST")
    for ua, ub, zt in surfs:
        s_mid = 60.0 + (ua + ub) / 2.0
        head = min(cfg.lv(60.0 + ua), cfg.lv(60.0 + ub)) - st.offset + ceil - zt
        if 60.0 + ub <= o_fin.s_start + 1e-9:
            assert head >= 2.1 - 1e-9, s_mid                          # 오프닝 밖: 천장판까지 머리 높이 확보
    first = min((ua for ua, ub, zt in surfs if 60.0 + ua >= o_fin.s_start - 1e-9))
    assert 60.0 + first == pytest.approx(o_fin.s_start)
    # 천장판·천장틀은 오프닝 자리에 없음 (위 슬래브 오프닝을 뺌)
    hall = fin(flat, "B2F_대합실")
    for p in hall.element("CEILING").pieces + hall.element("FRAME").pieces:
        s0, s1 = PM.s_range(p)
        t0, t1 = p.pos_y - p.shape.width / 2, p.pos_y + p.shape.width / 2
        assert not (s0 < o_fin.s_end - 1e-6 and s1 > o_fin.s_start + 1e-6 and t0 < -5 - 1e-6 and t1 > -7 + 1e-6)


def test_no_ceiling_room_keeps_slab_basis_and_side_clear():
    sp = StairSpec(lower_floor=2, s_start=60.0, direction=1, t_center=-6.0, width=2.0, name="ST", side_clear=0.3)
    mech = RoomSpec(2, "기계실", 50, 100, -9, -3, name="MECH")                  # 천장 없는 실 → 슬래브 하면 기준
    on_cfg = cfg_with(mech, no_cols=True, stairs=[sp], table=flush_table())
    on_cfg.finish_settings.stair.enabled = False                   # 계단 마감은 디딤판 높이를 바꾸므로 끄고 천장 기준만 비교
    on = StationCADEngine(on_cfg)
    off_cfg = cfg_with(mech, no_cols=True, stairs=[sp])
    off_cfg.finish_settings.enabled = False
    off = StationCADEngine(off_cfg)
    a, b = _open(on, "ST"), _open(off, "ST")
    assert a.length == pytest.approx(b.length) and a.width == pytest.approx(2.0 + 0.6)   # 옆 여유 양쪽 0.3
    with pytest.raises(ValueError, match="옆 여유"):
        StationCADEngine(cfg_with(no_cols=True, stairs=[StairSpec(lower_floor=2, s_start=60.0, side_clear=-0.1)]))


def test_escalator_opening_uses_lower_floor_ceiling_and_side_clear():
    e = EscalatorSpec(lower_floor=1, s_wp=60.0, direction=1, t_center=-6.0, name="ES", side_clear=0.2)   # 승강장 위 (천장 = 승강장 상면 + 3.1)
    on = StationCADEngine(cfg_with(no_cols=True, escalators=[e], table=flush_table()))
    off_cfg = cfg_with(no_cols=True, escalators=[e])
    off_cfg.finish_settings.enabled = False
    off = StationCADEngine(off_cfg)
    a, b = _open(on, "ES"), _open(off, "ES")
    assert a.length > b.length + 1.0 and a.width == pytest.approx(e.truss_width + 0.4)
    assert max(a.s_start + a.length, a.s_start) == pytest.approx(b.s_start + b.length)


def test_side_clear_drafts():
    from gui.escalator_draft import EscalatorDraft
    from gui.stair_draft import StairDraft
    assert StairDraft(side_clear="0.25").to_spec("x", 0.0).side_clear == 0.25
    assert EscalatorDraft().to_spec("x", 0.0).side_clear == 0.0
    with pytest.raises(ValueError, match="오프닝 옆 여유"):
        StairDraft(side_clear="-1").to_spec("x", 0.0)


def test_upper_escalator_pit_does_not_cut_lower_ceiling():
    """버그: B2F 에서 오르는 에스컬레이터의 하부 피트(아래 슬래브 오프닝)가 B3F 천장판까지 뚫음.
    피트는 슬래브 두께 안에서 트러스가 막으므로 아래층 천장은 그대로, 그 층(B2F) 바닥 마감만 피트 자리 비움"""
    e = EscalatorSpec(lower_floor=2, s_wp=60.0, direction=1, t_center=-6.0, truss_depth=0.35, name="ES")
    eng = StationCADEngine(cfg_with(no_cols=True, escalators=[e], table=flush_table()))
    pit = _open(eng, "ES_PIT")
    assert pit.slabs == [1]

    def hits(pieces):
        out = []
        for p in pieces:
            s0, s1 = PM.s_range(p)
            t0, t1 = p.pos_y - p.shape.width / 2, p.pos_y + p.shape.width / 2
            if s0 < pit.s_end - 1e-6 and s1 > pit.s_start + 1e-6 and t0 < pit.t_hi - 1e-6 and t1 > pit.t_lo + 1e-6:
                out.append(p)
        return out
    low = fin(eng, "B3F_승강장층")
    assert hits(low.element("CEILING").pieces)                      # B3F 천장은 피트 아래에도 있음
    hall = fin(eng, "B2F_대합실")
    assert not hits(hall.element("FLOOR").pieces)                   # B2F 바닥 마감은 피트 자리 비움


# ===================================================== 마감 미적용 처리: 계단·ESC 아래 바닥, 오프닝 둘레
def _gap_cfg():
    from escalators.escalator_spec import EscalatorSpec
    return cfg_with(no_cols=True, stairs=[StairSpec(lower_floor=2, s_start=60.0, direction=1, t_center=-6.0, width=2.0, name="ST")],
                    escalators=[EscalatorSpec(lower_floor=2, s_wp=100.0, direction=1, t_center=-6.0, truss_depth=0.35, name="ES")])


def test_floor_finish_under_stair_and_escalator():
    """바닥 마감은 계단·ESC 가 바닥 마감면 아래로 내려오는 곳만 뺌 (경사부·트러스 아래는 마감)"""
    from finishes.finish_gaps import contact_rects
    from openings import decompose
    eng = StationCADEngine(_gap_cfg())
    st, es = eng.cfg.stair_layouts()[0], eng.cfg.escalator_layouts()[0]
    room = next(r for r in eng.finishes.rooms if r.floor == 2)
    ffl = room.finish.ffl
    c_st = contact_rects(eng.cfg, [st], 2, ffl)
    assert len(c_st) == 1 and c_st[0][0] == pytest.approx(60.0) and 60.0 < c_st[0][1] < 62.0      # 첫 챌판 근처만
    # 접지 끝: 그 s 에서 계단 하면 = 바닥 마감면
    s_end = c_st[0][1]
    zb = min(stp.zb_at(s_end) for p in st.parts for stp in p.strips if stp.s0 - 1e-9 <= s_end <= stp.s1 + 1e-9)
    assert zb == pytest.approx(eng.cfg.lv(s_end) - eng.cfg.station.offset + st.base_level + ffl, abs=1e-6)
    clear = (0.0, 198.0, -9.0, 9.0)
    holes = contact_rects(eng.cfg, [st, es], 2, ffl) + [(o.s_start, o.s_end, o.t_lo, o.t_hi) for o in eng.cfg.all_openings() if 1 in o.slabs]
    want = sum((b - a) * (d - c) for a, b, c, d in decompose.subtract_rects(clear, holes))
    assert rect_area(room.element("FLOOR").pieces) == pytest.approx(want, rel=1e-9)
    assert want > 198 * 18 - (st.s_range[1] - st.s_range[0]) * 2.0 - (es.s_range[1] - es.s_range[0]) * 1.6   # 예전보다 넓음


def test_opening_linings_close_ceiling_plenum():
    """천장 속 막이(천장판 하면 ~ 위 슬래브 하면) + 오프닝 옆면(슬래브 두께), 도착 쪽 없음, 계단·ESC 와 겹치지 않음, 천장판과 안 겹침"""
    eng = StationCADEngine(_gap_cfg())
    cfg, st = eng.cfg, eng.cfg.station
    room = next(r for r in eng.finishes.rooms if r.floor == 2)
    f = room.finish.wall_t
    slab_bot, slab_top = st.floor_level(3) - st.mid_t, st.floor_level(3)
    walls = room.element("WALL").pieces
    lin = [p for p in walls if PM.z_off(cfg, p) > room.ceiling_rel - 1e-6]
    bulk = [p for p in lin if abs(PM.z_off(cfg, p) - room.ceiling_rel) < 1e-6]
    side = [p for p in lin if abs(PM.z_off(cfg, p) - slab_bot) < 1e-6]
    assert len(bulk) == 6 and len(side) == 6                                   # 오프닝 2개 × (긴 변 2 + 시작 쪽 1)
    assert all(p.shape.height == pytest.approx(slab_bot - room.ceiling_rel) for p in bulk)
    assert all(p.shape.height == pytest.approx(slab_top - slab_bot) for p in side)
    for lay in cfg.stair_layouts() + cfg.escalator_layouts():
        o = lay.opening
        arrive = lay.s_at(lay.length) if hasattr(lay, "length") else lay.s_at(lay.u_range[1])
        mine = [p for p in lin if o.s_start - f - 1e-6 <= PM.s_range(p)[0] and PM.s_range(p)[1] <= o.s_end + f + 1e-6
                and o.t_lo - f - 1e-6 <= PM.t_range(p)[0] and PM.t_range(p)[1] <= o.t_hi + f + 1e-6]
        assert mine and all(PM.s_range(p)[1] <= arrive + 1e-6 for p in mine)              # 도착 쪽 가장자리 너머 없음
        for p in side:                                                                     # 옆면 마감 자리에서 부재 상면 ≤ 슬래브 하면
            s0, s1 = PM.s_range(p)
            t0, t1 = PM.t_range(p)
            for part in lay.parts:
                pt0, pt1 = getattr(part, "t_range", None) or lay.t_range
                if min(pt1, t1) - max(pt0, t0) <= 1e-9:
                    continue
                for stp in part.strips:
                    a, b = max(s0, stp.s0), min(s1, stp.s1)
                    if b - a > 1e-6:
                        for s in (a, b):
                            assert stp.zt_at(s) <= cfg.lv(s) - st.offset + slab_bot + 1e-6
    ceil = room.element("CEILING").pieces
    for p in bulk:                                                                         # 막이 자리에는 천장판 없음
        r = (*PM.s_range(p), *PM.t_range(p))
        assert all(min(r[1], PM.s_range(c)[1]) - max(r[0], PM.s_range(c)[0]) <= 1e-9 or
                   min(r[3], PM.t_range(c)[1]) - max(r[2], PM.t_range(c)[0]) <= 1e-9 for c in ceil)
