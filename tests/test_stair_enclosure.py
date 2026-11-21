"""계단·ESC 옆 벽체 + 하부 창고 (자동 실): 열린 앞면, 노출된 옆 벽, 창고 끝 벽 높이, 묶음, 간섭 없음, IFC, 초안"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ifcopenshell
import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from escalators.escalator_spec import EscalatorSpec
from helper import prism_member as PM
from rooms.room_check import layout_rooms
from rooms.room_spec import RoomSpec
from stairs.stair_enclosure import EnclosureSettings
from stairs.stair_spec import StairSpec
from test_finishes import cfg_with

ST = dict(lower_floor=2, s_start=60.0, direction=1, t_center=-6.0, width=2.0, name="ST")


def make(*rooms, escs=(), **spec):
    cfg = cfg_with(*rooms, no_cols=True, stairs=[StairSpec(**{**ST, **spec})], escalators=list(escs))
    cfg.enclosure_settings = EnclosureSettings(enabled=True)
    return cfg


def autos(cfg):
    return [r for r in cfg.rooms if r.auto]


def hits_members(cfg, box):
    """사각 상자 (s0, s1, t0, t1, z0, z1 — 본체 FL 기준) 가 계단·ESC 부재와 겹치는 표본점"""
    s0, s1, t0, t1, z0, z1 = box
    for lay in cfg.stair_layouts() + cfg.escalator_layouts():
        items = [(st, getattr(p, "t_range", None) or lay.t_range) for p in lay.parts for st in p.strips]
        items += [(st, f.t_range) for f in getattr(lay, "finish", None) or [] for st in f.strips]
        for st, tr in items:
            if min(t1, tr[1]) - max(t0, tr[0]) <= 1e-6:
                continue
            a, b = max(s0, st.s0), min(s1, st.s1)
            for s in (np.linspace(a, b, 9)[1:-1] if b - a > 1e-6 else []):
                base = cfg.lv(s) - cfg.station.offset
                if min(z1 + base, st.zt_at(s)) - max(z0 + base, st.zb_at(s)) > 1e-6:
                    return lay.name, s
    return None


def test_disabled_by_default():
    cfg = make()
    cfg.enclosure_settings = EnclosureSettings()
    StationCADEngine(cfg)
    assert autos(cfg) == []


def test_rooms_open_front_side_walls_and_storage():
    cfg = make()
    eng = StationCADEngine(cfg)
    room, store = autos(eng.cfg)
    lay = cfg.stair_layouts()[0]
    assert room.open_sides == ("-s",) and room.s0 == pytest.approx(lay.s_range[0])           # 앞(첫 챌판)은 열림
    assert room.use == cfg.room_settings.default_use(2) and store.use == "창고"
    assert room.s1 == pytest.approx(store.s0) and store.s1 > lay.s_range[1]
    face = cfg.finish_settings.table["기본"].face
    h = cfg.room_settings.partition_t / 2
    assert room.t0 == pytest.approx(-7.0 - face - h) and room.t1 == pytest.approx(-5.0 + face + h)   # 벽 마감 표면 = 계단 옆면
    assert [d.side for d in store.doors] == ["+s"] and store.doors[0].center == pytest.approx((store.t0 + store.t1) / 2)   # 뒷 벽 가운데
    side = make()
    side.enclosure_settings.door_at = "side"                          # 옆 벽 가운데
    StationCADEngine(side)
    d = autos(side)[1].doors[0]
    assert d.side == "-t" and d.center == pytest.approx((autos(side)[1].s0 + autos(side)[1].s1) / 2)
    fl = layout_rooms(eng.cfg)[1]
    walls = [p for pw in fl.partitions for p in pw.pieces]
    assert not [p for p in walls if p[0] < lay.s_range[0] - 0.5 and p[2] < -6 < p[3]]       # 앞면 벽 없음
    # 창고 끝 벽: 계단 아래를 가로지르고, 윗면 = 계단 하면 (바닥 마감면 + 2.1 이상)
    end = [p for pw in fl.partitions if pw.axis == "t" for p in pw.pieces if abs((p[0] + p[1]) / 2 - store.s0) < 0.01]
    assert end and end[0][5] < cfg.station.floor_level(3) - cfg.station.mid_t - 1.0
    assert end[0][5] >= cfg.station.floor_level(2) + cfg.finish_settings.table["기본"].ffl + 2.1 - 1e-6
    assert len(fl.doors) == 1 and fl.doors[0].name == "ST_창고_D1"


def test_no_wall_or_finish_inside_stair():
    cfg = make()
    eng = StationCADEngine(cfg)
    fl = layout_rooms(eng.cfg)[1]
    for pw in fl.partitions:
        for p in pw.pieces:
            assert hits_members(eng.cfg, p) is None, pw.name
    for rf in (r for r in eng.finishes.rooms if r.floor == 2):
        for e in rf.elements:
            for p in e.pieces:
                z0 = PM.z_off(eng.cfg, p)
                box = (*PM.s_range(p), *PM.t_range(p), z0, z0 + p.shape.height)
                assert hits_members(eng.cfg, box) is None, e.name


def test_validate_twice_is_stable():
    cfg = make()
    StationCADEngine(cfg)
    first = [(r.name, r.rect) for r in autos(cfg)]
    StationCADEngine(cfg)
    assert [(r.name, r.rect) for r in autos(cfg)] == first and len(cfg.rooms) == 2


def test_wall_side_direction_and_grouping():
    wall = make(t_ref="wall-t", t_center=0.0)                      # 오른쪽(−t) 벽 마감 표면에 붙인 계단: −t 쪽은 본체 벽
    wall.enclosure_settings.door_at = "side"
    StationCADEngine(wall)
    room, store = autos(wall)
    assert room.t0 == pytest.approx(-9.0) and [d.side for d in store.doors] == ["+t"]
    down = make(direction=-1, s_start=73.0)
    StationCADEngine(down)
    room, store = autos(down)
    assert room.open_sides == ("+s",) and store.s1 == pytest.approx(room.s0)
    # 나란한 계단 + ESC (같은 방향, t 간격 0.7) → 한 계단실, 사이 벽 없음
    esc = EscalatorSpec(lower_floor=2, s_wp=64.0, direction=1, t_center=-3.5, truss_depth=0.35, name="ES")
    grp = make(escs=[esc])
    eng = StationCADEngine(grp)
    names = [r.name for r in autos(grp)]
    assert names[0] == "ENC_ST_ES"
    fl = layout_rooms(eng.cfg)[1]
    assert not [p for pw in fl.partitions if pw.axis == "s" for p in pw.pieces if -5.0 < (p[2] + p[3]) / 2 < -4.3]


def test_skip_when_user_room_overlaps():
    cfg = make(RoomSpec(2, "역무실", 62, 70, -4.8, -2, name="OFFICE"))      # 계단 옆에 붙은 입력 실 (계단실 벽 자리와 겹침)
    StationCADEngine(cfg)
    assert autos(cfg) == [] and [r.name for r in cfg.rooms] == ["OFFICE"]


def test_ifc_spaces_walls_door(tmp_path):
    eng = StationCADEngine(make())
    f = ifcopenshell.open(eng.generate_ifc(str(tmp_path / "e.ifc")))
    spaces = {s.Name for s in f.by_type("IfcSpace")}
    assert {"ENC_ST", "ST_창고"} <= spaces
    assert "ST_창고_D1" in {d.Name for d in f.by_type("IfcDoor")}


@pytest.mark.parametrize("kw, msg", [(dict(storage_h=0), "창고 높이"), (dict(group_gap=-1), "묶음 간격"),
                                     (dict(storage_use=" "), "창고 용도")])
def test_invalid_settings(kw, msg):
    with pytest.raises(ValueError, match=msg):
        EnclosureSettings(enabled=True, **kw).check()


def test_draft_and_project_round_trip():
    from gui.enclosure_draft import EnclosureDraft, preview
    from gui.project_file import ProjectState
    d = EnclosureDraft()
    assert d.to_settings().enabled and "칸막이벽" in preview(d)
    d.storage_h = "x"
    with pytest.raises(ValueError, match="계단 옆 벽체"):
        d.to_settings()
    assert "입력값" in preview(d)
    d.enabled = False
    assert not d.to_settings().enabled and "없음" in preview(d)
    st = ProjectState()
    st.enclosure_draft = EnclosureDraft(storage=False, storage_use="기계실", door_w="1.2")
    assert ProjectState.from_dict(st.to_dict()).enclosure_draft == st.enclosure_draft
    old = st.to_dict()
    del old["enclosure_draft"]
    assert ProjectState.from_dict(old).enclosure_draft == EnclosureDraft()


def test_open_wall_end_is_capped():
    """열린 끝(계단실 앞)에서 벽과 띄워 붙인 마감 사이 빈 공간을 끝막음 — 양쪽 마감을 벽 끝 + 마감 두께까지, 그 사이를 덮음"""
    import itertools
    from finishes.finish_spec import default_finishes
    cfg = make()
    cfg.finish_settings.table = default_finishes()
    for ft_ in cfg.finish_settings.table.values():                   # 칸막이벽 마감도 금속패널처럼 띄움 (이격 있음)
        if ft_.wall_t > 0:
            ft_.partition_face = 0.15
    eng = StationCADEngine(cfg)
    fl = layout_rooms(eng.cfg)[1]
    wall = next(p for pw in fl.partitions if pw.axis == "s" for p in pw.pieces if -7.6 < p[2] and p[3] < -7.0)   # −t 쪽 옆 벽
    end, c, h = wall[0], (wall[2] + wall[3]) / 2, (wall[3] - wall[2]) / 2
    ft = cfg.finish_settings.table[cfg.room_settings.default_use(2)]
    boxes = []
    for rf in (r for r in eng.finishes.rooms if r.floor == 2):
        for e in rf.elements:
            for p in e.pieces:
                z0 = PM.z_off(eng.cfg, p)
                boxes.append((e.name, *PM.s_range(p), *PM.t_range(p), z0, z0 + p.shape.height))
    cap = [b for b in boxes if b[2] == pytest.approx(end) and b[1] == pytest.approx(end - ft.wall_t)
           and b[3] == pytest.approx(c - h - ft.pgap) and b[4] == pytest.approx(c + h + ft.pgap)]
    assert cap                                                        # 벽 끝면 + 양쪽 이격을 덮는 끝막음
    sides = [b for b in boxes if b[1] == pytest.approx(end - ft.wall_t) and b[2] == pytest.approx(end + h)
             and abs((b[3] + b[4]) / 2 - c) < h + ft.pface + 1e-6]
    assert len(sides) == 2                                            # 양쪽 마감을 벽 끝까지 늘림
    near = [b for b in boxes if b[1] < end + 1 and b[2] > end - 1]
    assert not [(a[0], b[0]) for a, b in itertools.combinations(near, 2)
                if all(min(a[i + 1], b[i + 1]) - max(a[i], b[i]) > 1e-6 for i in (1, 3, 5))]


def test_partition_face_separate_from_station_wall():
    """칸막이벽 마감면 거리는 본체 벽(wall_face)과 따로 — 비우면 이격 없이 벽 면에 붙고, 계단실 벽도 그 거리로 섬"""
    from finishes.finish_spec import default_finishes
    cfg = make()
    cfg.finish_settings.table = default_finishes()
    for ft_ in cfg.finish_settings.table.values():
        ft_.wall_face = 0.5 if ft_.wall_t > 0 else None              # 실무 샘플: 본체 벽 이격 큼
    StationCADEngine(cfg)
    room = next(r for r in cfg.rooms if r.name == "ENC_ST")
    ft = cfg.finish_settings.table[cfg.room_settings.default_use(2)]
    assert ft.pface == pytest.approx(ft.wall_t)
    assert room.t0 == pytest.approx(-7.0 - ft.wall_t - cfg.room_settings.partition_t / 2)   # 0.5 가 아니라 마감 두께만


def test_outer_corner_finishes_meet():
    """다른 실(계단실·창고)의 바깥 모서리를 감싸는 기본 실 벽 마감: s 방향 마감이 모서리를 차지하고 t 방향 마감이 그 뒷면까지 — 틈 없음"""
    import itertools
    cfg = make()
    eng = StationCADEngine(cfg)
    fl = layout_rooms(eng.cfg)[1]
    store = autos(eng.cfg)[1]
    h = cfg.room_settings.partition_t / 2
    hall = next(r for r in eng.finishes.rooms if r.floor == 2 and not r.room.startswith(("ENC", "ST")))
    ft = hall.finish
    pieces = [(*PM.s_range(p), *PM.t_range(p)) for p in hall.element("WALL").pieces]
    corner_s, corner_t = store.s1, store.t0                            # 창고 뒷 벽(+s) × −t 옆 벽 바깥 모서리
    side = [p for p in pieces if p[2] == pytest.approx(corner_t - h - ft.pface) and p[0] < corner_s < p[1]]
    back = [p for p in pieces if p[0] == pytest.approx(corner_s + h + ft.pgap) and p[2] < corner_t < p[3]]
    assert side and side[0][1] == pytest.approx(corner_s + h + ft.pface)        # s 방향 마감이 모서리를 차지
    assert back and back[0][2] == pytest.approx(corner_t - h - ft.pgap)         # t 방향 마감은 그 뒷면까지
    assert not [(a, b) for a, b in itertools.combinations(pieces, 2)
                if min(a[1], b[1]) - max(a[0], b[0]) > 1e-6 and min(a[3], b[3]) - max(a[2], b[2]) > 1e-6]
    assert fl.doors[0].name == "ST_창고_D1"


def test_stair_inside_wall_finish_is_rejected():
    """이슈 #32: 계단이 본체 벽 마감 표면 안쪽으로 들어가면 오류 (예전엔 조용히 겹친 개체 생성) — 벽 마감면 기준점으로 해결"""
    bad = make(t_center=-8.0)                                       # t −9 ~ −7, 마감 표면 |t| = 9 − 0.05
    with pytest.raises(ValueError, match="본체 벽 마감 표면.*0.05m 들어갑니다"):
        StationCADEngine(bad)
    ok = make(t_ref="wall-t", t_center=0.1)                         # 벽 마감 표면에서 0.1 띄움
    StationCADEngine(ok)
    lay = ok.stair_layouts()[0]
    face = ok.finish_settings.table["기본"].face
    assert lay.t_range[0] == pytest.approx(-9.0 + face + 0.1) and lay.t_range[1] - lay.t_range[0] == pytest.approx(2.0)
    assert ok.stairs[0].t_ref == "center"                           # 검증이 중심 t 로 풀어 둠 (두 번 검증해도 같음)
