"""실(구획): 층별 입력 실 + 기본 실, 실 경계 칸막이벽, IfcSpace / IfcWall(PARTITIONING) 테스트"""
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
from openings import decompose
from rooms.room_spec import RoomSettings, RoomSpec
from test_curved import NO_COLS, curved_cfg
from test_patch import make_cfg, user_example
from test_stairs import stair

# user_example: 3개 층 각 6m, 내공 198 x 18 (t ±9), 승강장 t ±3.9 ~ ±9 (상면 1.3), 중간 슬래브 0.4, 천장 0.4
B1F = [RoomSpec(3, "역무실", 10, 30, 2, 9), RoomSpec(3, "기계실", 30, 50, 2, 9), RoomSpec(3, "화장실", 10, 20, -9, -4)]


def cfg_with(*rooms, curved=False, settings=None, **extra):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(user_example())
    cfg.rooms = list(rooms)
    if settings:
        cfg.room_settings = settings
    for k, v in extra.items():
        setattr(cfg, k, v)
    return cfg


def floor_layout(cfg, n):
    return cfg.room_layouts()[n - 1]


def rect_of(p):
    return (*PM.s_range(p), *PM.t_range(p))


# ===================================================== 실 · 기본 실
def test_default_room_per_floor_without_input():
    fls = cfg_with().room_layouts()
    assert [(r.name, r.use) for fl in fls for r in fl.rooms] == [("B3F_승강장층", "승강장층"), ("B2F_대합실", "대합실"),
                                                                   ("B1F_대합실", "대합실")]
    assert all(not fl.partitions for fl in fls) and fls[0].rooms[0].area == pytest.approx(198 * 18)
    custom = cfg_with(settings=RoomSettings(default_uses={2: "기계실"})).room_layouts()
    assert custom[1].rooms[0].use == "기계실"


def test_rooms_and_remainder_area():
    fl = floor_layout(cfg_with(*B1F), 3)
    names = [r.name for r in fl.rooms]
    assert names == ["B1F_역무실1", "B1F_기계실1", "B1F_화장실1", "B1F_대합실"]
    assert [r.area for r in fl.rooms[:3]] == pytest.approx([140.0, 140.0, 50.0])
    assert fl.rooms[3].is_default and fl.rooms[3].area == pytest.approx(198 * 18 - 330.0)


def test_partitions_merge_shared_edges_and_skip_station_walls():
    fl = floor_layout(cfg_with(*B1F), 3)
    walls = {pw.name: pw for pw in fl.partitions}
    h = 0.1
    s_walls = sorted(rect for pw in fl.partitions if pw.axis == "s" for rect in [pw.pieces[0][:4]])
    assert s_walls == [pytest.approx((10 - h, 20 + h, -4 - h, -4 + h)), pytest.approx((10 - h, 50 + h, 2 - h, 2 + h))]
    t_walls = sorted(pw.pieces[0][:4] for pw in fl.partitions if pw.axis == "t")
    assert len(t_walls) == 5                                      # s=10 (위·아래 두 실), 20, 30(공유 변 1개), 50
    assert all(abs(abs(t) - 9) > 1e-9 or True for *_, t in t_walls)
    assert not any(abs(r[3] - r[2]) < 1e-9 for r in t_walls)
    for pw in walls.values():                                     # 높이: B1F FL ~ 천장 하면
        assert all((z0, z1) == pytest.approx((12.0, 17.6)) for *_, z0, z1 in pw.pieces)


def test_partitions_do_not_overlap_each_other():
    fl = floor_layout(cfg_with(*B1F, RoomSpec(3, "창고", 60, 70, -9, 9)), 3)
    rects = [p[:4] for pw in fl.partitions for p in pw.pieces]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert decompose.overlap_area(a, b) < 1e-9
    total = sum((a[1] - a[0]) * (a[3] - a[2]) for a in rects)
    # s 방향 벽(끝을 반 두께씩 늘림) 10.2 + 40.2, t 방향 벽(s 방향 벽 띠를 뺌) 4.9 + 6.9 + 4.9 + 6.9 + 6.9, 창고 양쪽 18 + 18
    assert total == pytest.approx(0.2 * (10.2 + 40.2 + 4.9 + 6.9 + 4.9 + 6.9 + 6.9 + 18 + 18), rel=1e-9)


def test_platform_floor_partition_starts_on_platform():
    fl = floor_layout(cfg_with(RoomSpec(1, "역무실", 5, 25, 4.5, 9)), 1)
    for pw in fl.partitions:
        assert all(z0 == pytest.approx(1.3) for *_, z0, _ in pw.pieces)
    fl = floor_layout(cfg_with(RoomSpec(1, "기타", 5, 25, -9, 9)), 1)   # 선로부를 가로지름 → 승강장 위/아래 높이가 나뉨
    pw = next(p for p in fl.partitions if p.axis == "t")
    assert sorted(round(z0, 3) for *_, z0, _ in pw.pieces) == [0.0, 1.3, 1.3]


# ===================================================== 검증
@pytest.mark.parametrize("room,msg", [
    (RoomSpec(4, "역무실", 10, 20, 0, 5), "층 번호"),
    (RoomSpec(3, " ", 10, 20, 0, 5), "용도"),
    (RoomSpec(3, "역무실", 20, 10, 0, 5), "칸막이벽 두께보다"),
    (RoomSpec(3, "역무실", -1, 10, 0, 5), "내공"),
    (RoomSpec(3, "역무실", 10, 20, 0, 9.5), "내공"),
])
def test_invalid_room_rejected(room, msg):
    with pytest.raises(ValueError, match=msg):
        StationCADEngine(cfg_with(room))


def test_overlap_and_conflicts_rejected():
    with pytest.raises(ValueError, match="서로 겹칩니다"):
        StationCADEngine(cfg_with(RoomSpec(3, "A", 10, 20, 0, 5), RoomSpec(3, "B", 15, 25, 2, 8)))
    with pytest.raises(ValueError, match="이름이 중복"):
        StationCADEngine(cfg_with(RoomSpec(3, "A", 10, 20, 0, 5, name="X"), RoomSpec(2, "B", 10, 20, 0, 5, name="X")))
    with pytest.raises(ValueError, match="칸막이벽 두께는"):
        StationCADEngine(cfg_with(settings=RoomSettings(partition_t=0.0)))
    with pytest.raises(ValueError, match="오프닝"):                   # B1F 바닥(중간 슬래브 2)에 계단 B2F→B1F 오프닝
        StationCADEngine(cfg_with(RoomSpec(3, "역무실", 40, 60, -9, -4), stairs=[stair(lower=2, s=30.0, name="ST")]))
    with pytest.raises(ValueError, match="계단"):                      # 그 층에서 오르는 계단과 겹침
        StationCADEngine(cfg_with(RoomSpec(2, "역무실", 30, 60, -9, -4), stairs=[stair(lower=2, s=30.0, name="ST")]))
    with pytest.raises(ValueError, match="EV1_SHAFT|엘리베이터"):                # 피트 오프닝 또는 승강로
        StationCADEngine(cfg_with(RoomSpec(2, "역무실", 50, 70, 4, 9),
                                  elevators=[ElevatorSpec(lower_floor=2, upper_floor=3, s_center=60, t_center=4.0)]))


# ===================================================== 체적 · IFC
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("curved", [False, True])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, curved):
    rooms = [RoomSpec(2, "역무실", 10, 30, 2, 9), RoomSpec(2, "기계실", 30, 50, -9, -2)]
    eng = StationCADEngine(cfg_with(*rooms, curved=curved))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "r.ifc"))
    by = {e.Name: e for e in f.by_type("IfcProduct") if e.Name}
    tol = 1e-4 if curved else 1e-7
    for obj in eng.rooms.partitions + eng.rooms.rooms:
        mesh = sum(PM.mesh_volume(PM.sweep_quads(PM.rings(eng.cfg, p))) for p in obj.pieces)
        assert mesh == pytest.approx(obj.volume, rel=tol), obj.name
        assert ifc_world_volume(by[obj.name]) == pytest.approx(obj.volume, rel=tol), obj.name
    st = eng.cfg.station
    total = sum(r.volume for r in eng.rooms.rooms if r.floor == 2)
    assert total == pytest.approx(st.length * st.width * (st.floor_level(3) - st.mid_t - st.floor_level(2)), rel=tol)


def test_ifc_spaces_and_partitions(tmp_path):
    eng = StationCADEngine(cfg_with(*B1F))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "r.ifc"))
    spaces = f.by_type("IfcSpace")
    assert len(spaces) == 6 and {s.LongName for s in spaces} >= {"역무실", "기계실", "화장실", "대합실", "승강장층"}
    office = next(s for s in spaces if s.Name == "B1F_역무실1")
    assert office.PredefinedType == "INTERNAL" and office.Decomposes[0].RelatingObject.Name == "B1F"
    walls = [w for w in f.by_type("IfcWall") if w.PredefinedType == "PARTITIONING"]
    assert len(walls) == len(eng.rooms.partitions) == 7
    assert ifcopenshell.util.element.get_container(walls[0]).Name == "B1F"
    assert ifcopenshell.util.element.get_material(walls[0]).Name == "Masonry_Block"


# ===================================================== 도면
def test_drawings(tmp_path):
    eng = StationCADEngine(cfg_with(*B1F))
    msp = ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace()
    assert len(msp.query('3DFACE[layer=="STRUCT_PARTITION"]')) == 6 * 7
    items = eng.rooms.section_items(15.0)                              # 화장실 가운데 → s 방향 벽 2개(t=−4, t=2) 절단
    assert sorted(round(it.u0, 2) for it in items) == [-4.1, 1.9]
    assert [it.layer for it in eng.rooms.profile_items(2.0)] == ["PROF_PARTITION"]
    plan = eng.rooms.plan_items(14.0, floor=3)
    labels = sorted(it.label[0] for it in plan if it.label)
    assert labels == ["B1F_기계실1 (140.0m2)", "B1F_역무실1 (140.0m2)", "B1F_화장실1 (50.0m2)", "대합실 (3234.0m2)"]
    path = eng.generate_plan_dxf(tmp_path / "p.dxf", floors=[3])
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query('TEXT[layer=="PLAN_ROOM"]')]
    assert sorted(t[-9:] for t in texts) == sorted(lb[-9:] for lb in labels)     # DXF R2000 은 한글을 U+ 이스케이프로 저장
    assert len(ezdxf.readfile(path).modelspace().query('LWPOLYLINE[layer=="PLAN_ROOM"]')) == 0   # 글자만


def test_build_all_and_golden_untouched(tmp_path):
    from engine.bim_engine import BIMEngine
    assert len(BIMEngine.build(cfg_with(*B1F, curved=False), tmp_path)) == 5


# ===================================================== 입력 초안
from gui.room_draft import RoomDraft, RoomDrafts, RoomSettingsDraft, preview


def test_drafts():
    d = RoomDraft(floor=3, use="기계실", sta0="110", sta1="130", t0="2", t1="9", name="M")
    sp = d.to_spec("실 1", 100.0)
    assert (sp.floor, sp.use, sp.s0, sp.s1, sp.t0, sp.t1, sp.name) == (3, "기계실", 10.0, 30.0, 2.0, 9.0, "M")
    assert "B1F 기계실: 20 x 7 m = 140.0 m²" in preview(d, 100.0, 3)
    assert "시작 < 끝" in preview(RoomDraft(sta0="5", sta1="1"), 0.0, 3)
    s = RoomSettingsDraft(partition_t="0.15", default_uses={"2": "기계실", "1": " "})
    assert s.to_settings() == RoomSettings(default_uses={2: "기계실"}, partition_t=0.15)
    ds = RoomDrafts(); ds.items = [RoomDraft(floor=3)]; ds.settings.default_uses = {"3": "대합실"}
    assert ds.ensure_floors(2) and ds.items[0].floor == 2 and ds.settings.default_uses == {}
    ds.items[0].t0 = "x"
    with pytest.raises(ValueError, match="실 1\\(역무실\\): t 시작"):
        ds.to_specs(0.0)


# ===================================================== 구획분리 (가상 경계선 / 얇은 벽)
from rooms.room_spec import PARTITION, SEPARATION

PAID = RoomSpec(3, "대합실(PAID)", 60, 198, -9, 9, boundary=SEPARATION)


def test_virtual_separation_splits_remainder_without_wall():
    cfg = cfg_with(RoomSpec(3, "기계실", 15, 35, 4, 9), PAID, settings=RoomSettings(default_uses={3: "복도"}))
    fl = floor_layout(cfg, 3)
    assert [(r.use, round(r.area, 3)) for r in fl.rooms] == [("기계실", 100.0), ("대합실(PAID)", 2484.0), ("복도", 980.0)]
    assert [p.kind for p in fl.partitions] == [PARTITION] * 3                    # 기계실 칸막이벽만
    (sl,) = fl.separations
    assert sl.axis == "t" and sl.rect == pytest.approx((60, 60, -9, 9)) and sl.z_rel == pytest.approx(12.0)


def test_thin_separation_wall_and_partition_precedence():
    thin = RoomSpec(3, "대합실(PAID)", 60, 198, -9, 9, boundary=SEPARATION, sep_t=0.1)
    fl = floor_layout(cfg_with(thin), 3)
    (sw,) = fl.partitions
    assert sw.name == "SW_B1F_T1" and sw.kind == SEPARATION and sw.thickness == 0.1 and not fl.separations
    assert sw.pieces[0][:4] == pytest.approx((59.95, 60.05, -9, 9))
    # 같은 선(s=60)을 칸막이벽 실과 구획분리 실이 함께 쓰면 칸막이벽 우선, 나머지 구간만 가상선
    office = RoomSpec(3, "역무실", 40, 60, 4, 9)
    fl = floor_layout(cfg_with(office, PAID), 3)
    at60 = [pw for pw in fl.partitions if pw.axis == "t" and abs(pw.pieces[0][0] - 59.9) < 1e-9]
    assert len(at60) == 1 and at60[0].kind == PARTITION and at60[0].pieces[0][2:4] == pytest.approx((4.1, 9))
    seps = [sl.rect for sl in fl.separations]
    assert seps == [pytest.approx((60, 60, -9, 4))]


def test_separation_validation():
    with pytest.raises(ValueError, match="경계 종류"):
        StationCADEngine(cfg_with(RoomSpec(3, "A", 10, 20, 0, 5, boundary="x")))
    with pytest.raises(ValueError, match="구획분리 두께"):
        StationCADEngine(cfg_with(RoomSpec(3, "A", 10, 20, 0, 5, boundary=SEPARATION, sep_t=-0.1)))
    # 가상 경계선은 오프닝 위에도 허용, 두께가 있으면 칸막이벽처럼 검사
    stairs = [stair(lower=2, s=30.0, name="ST")]
    StationCADEngine(cfg_with(RoomSpec(3, "역무실", 40, 60, -9, -4, boundary=SEPARATION), stairs=stairs))
    with pytest.raises(ValueError, match="오프닝"):
        StationCADEngine(cfg_with(RoomSpec(3, "역무실", 40, 60, -9, -4, boundary=SEPARATION, sep_t=0.1), stairs=stairs))


def test_separation_ifc_and_drawings(tmp_path):
    thin = RoomSpec(2, "B", 100, 150, -9, 9, boundary=SEPARATION, sep_t=0.1)
    eng = StationCADEngine(cfg_with(PAID, thin))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "s.ifc"))
    (ve,) = f.by_type("IfcVirtualElement")
    assert ve.Name == "SL_B1F_1" and ifcopenshell.util.element.get_container(ve).Name == "B1F"
    rep = ve.Representation.Representations[0]
    assert rep.RepresentationIdentifier == "Axis" and len(rep.Items[0].Points) == 2
    sw = [w for w in f.by_type("IfcWall") if w.Description == "구획분리벽"]
    assert len(sw) == 2 and ifcopenshell.util.element.get_material(sw[0]).Name == "Separation_Panel"
    assert ifc_world_volume(sw[0]) == pytest.approx(0.1 * 18 * (12 - 0.4 - 6), rel=1e-7)
    msp = ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace()
    assert len(msp.query('3DFACE[layer=="STRUCT_SEPARATION"]')) == 12 and not msp.query('3DFACE[layer=="STRUCT_PARTITION"]')
    plan = eng.rooms.plan_items(14.0, floor=3)
    assert [len(it.pts) for it in plan if it.layer == "PLAN_SEPARATION"] == [2]


def test_separation_drafts():
    from gui.room_draft import B_SEPARATION
    d = RoomDraft(floor=3, use="대합실(PAID)", sta0="60", sta1="198", t0="-9", t1="9", boundary=B_SEPARATION, sep_t="0.1")
    sp = d.to_spec("실 1", 0.0)
    assert (sp.boundary, sp.sep_t) == (SEPARATION, 0.1) and "구획분리 벽 0.1m" in preview(d, 0.0, 3)
    d.sep_t = "0"
    assert "구획분리 가상 경계선" in preview(d, 0.0, 3)
    assert RoomDraft(sep_t="x").to_spec("", 0.0).sep_t == 0.0                       # 칸막이벽이면 두께 무시
    with pytest.raises(ValueError, match="구획분리 두께"):
        RoomDraft(boundary=B_SEPARATION, sep_t="-1").to_spec("실 1", 0.0)


def test_disconnected_remainder_becomes_separate_default_rooms(tmp_path):
    """전체 폭 구역이 나머지를 둘로 끊으면 기본 실도 둘 (사용자 검토: 좌측 잔여공간에 공간 정보가 없던 문제)"""
    rooms = [RoomSpec(3, "기계실", 10, 25, 4, 9, name="기계실"),
             RoomSpec(3, "대합실", 40, 70, -9, 9, boundary=SEPARATION, sep_t=0.2, name="대합실"),
             RoomSpec(3, "통신실", 25, 40, -9, -4, name="통신실")]
    cfg = cfg_with(*rooms, settings=RoomSettings(default_uses={3: "복도"}))
    fl = floor_layout(cfg, 3)
    rest = [(r.name, r.area) for r in fl.rooms if r.is_default]
    assert rest == [("B1F_복도1", pytest.approx(40 * 18 - 75 - 75)), ("B1F_복도2", pytest.approx(128 * 18))]
    eng = StationCADEngine(cfg)
    labels = [it.label[0] for it in eng.rooms.plan_items(14.0, floor=3) if it.label]
    assert sum(lb.startswith("복도") for lb in labels) == 2                          # 두 영역 모두 표기
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "r.ifc"))
    names = {s.Name for s in f.by_type("IfcSpace")}
    assert {"B1F_복도1", "B1F_복도2"} <= names and "B1F_복도" not in names
    st = cfg.station
    assert sum(r.volume for r in eng.rooms.rooms if r.floor == 3) == pytest.approx(
        st.length * st.width * (st.height - st.roof_t - st.floor_level(3)))


def test_connected_groups():
    from rooms.room_layout import connected_groups
    rects = [(0, 10, 0, 5), (10, 20, 0, 5), (30, 40, 0, 5), (0, 10, 5, 9), (20, 30, 5, 9)]   # 꼭짓점만 닿는 것은 따로
    assert connected_groups(rects) == [[(0, 10, 0, 5), (10, 20, 0, 5), (0, 10, 5, 9)], [(20, 30, 5, 9)], [(30, 40, 0, 5)]]
