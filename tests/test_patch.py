import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import ifcopenshell
import pytest

from boxs.box_shape import BoxShape
from columns.column_params import (ColumnParameters, ColumnRowSpec, ColumnSpec, FloorColumnSpec)
from columns.column_shape_type import ColumnShapeType as T
from config.alignment_config import AlignmentConfig
from config.master_config import StationProjectConfig
from config.station_config import StationParameters
from engine.bim_engine import BIMEngine
from engine.cad_engine import StationCADEngine
from gui.tk_adapter import TkAdapter
from platforms.platform_params import PlatformParameters

RECT = lambda w, d: ColumnSpec(T.RECTANGLE, width=w, depth=d)
CIRC = lambda r: ColumnSpec(T.CIRCLE, radius=r)


def make_cfg(columns=None, floors=3):
    return StationProjectConfig(
        station=StationParameters(start_station=0.0, length=200.0, width=20.0, height=18.0, floors=floors,
                                  wall_t=1.0, floor_t=1.2, slab_t=0.4),
        platform=PlatformParameters(4.4, 1.7, 0.2, 1.1, support_t=0.3),
        column=columns or ColumnParameters(),
        align=AlignmentConfig(0, 286.4826, -85.3896, 123.45, 575.9987, 437.4075, 134.45))


def user_example():
    """B3 승강장층: 사각 0.4x1.0 1열 / B2 기능실: 원기둥 φ1.0 2열 / B1 대합실: 원+사각 혼합 1열"""
    return ColumnParameters(sync_with_platform=True, floors={
        1: FloorColumnSpec([ColumnRowSpec(0.0, 10.0, 1.0, [RECT(0.4, 1.0)])]),
        2: FloorColumnSpec([ColumnRowSpec(-3.0, 10.0, 1.0, [CIRC(0.5)]),
                            ColumnRowSpec(+3.0, 10.0, 1.0, [CIRC(0.5)])]),
        3: FloorColumnSpec([ColumnRowSpec(0.0, 8.0, 1.0, [CIRC(0.5), RECT(0.8, 0.8)])]),
    })


def test_default_config_builds():
    eng = StationCADEngine(make_cfg())
    assert [p.level for p in eng.columns.column_packages] == ["B3F", "B2F", "B1F"]


def test_user_example_layout():
    eng = StationCADEngine(make_cfg(user_example()))
    pk = {p.level: p for p in eng.columns.column_packages}
    assert pk["B3F"].total_count == 20                      # 1열, 간격 10m (s=2..198)
    assert pk["B2F"].total_count == 40                      # 2열
    assert {c.pos_y for c in pk["B2F"].columns} == {-3.0, 3.0}
    kinds = [c.shape_type for c in pk["B1F"].columns[:4]]    # 혼합 순환
    assert kinds == [T.CIRCLE, T.RECTANGLE, T.CIRCLE, T.RECTANGLE]
    assert all(c.shape.height > 0 for p in pk.values() for c in p.columns)


def test_3d_faces_not_duplicated(tmp_path):
    eng = StationCADEngine(make_cfg(user_example()))
    path = eng.generate_3d_dxf(tmp_path / "a" / "3d.dxf")      # 폴더 자동 생성
    faces = len(ezdxf.readfile(path).modelspace().query('3DFACE[layer=="STRUCT_COLUMN"]'))
    expected = sum(6 if c.shape_type == T.RECTANGLE else 72
                   for p in eng.columns.column_packages for c in p.columns)
    assert faces == expected


def test_build_all_outputs_and_ifc_storeys(tmp_path):
    cfg = make_cfg(user_example())
    paths = BIMEngine.build(cfg, tmp_path)
    assert len(paths) == 5 and all(os.path.exists(p) for p in paths)
    f = ifcopenshell.open(paths[-1])
    by_storey = {rel.RelatingStructure.Name: len([e for e in rel.RelatedElements if e.is_a("IfcColumn")])
                 for rel in f.by_type("IfcRelContainedInSpatialStructure")}
    assert by_storey == {"B3F": 20, "B2F": 40, "B1F": 25}
    assert len(f.by_type("IfcMaterial")) == 1                  # 재질 공유
    assert len(f.by_type("IfcCircleProfileDef")) > 0


def test_ifc_position_matches_wcs():
    cfg = make_cfg()
    from exporter.ifc_exporter import IFCExporter
    ex = IFCExporter(cfg)
    pl = ex._create_local_placement(0.0, 0.0, 5.0)
    assert pl.RelativePlacement.Location.Coordinates[:2] == pytest.approx(cfg.origin())


def test_start_station_shifts_origin_and_level():
    a = make_cfg()
    b = make_cfg(); b.station.start_station = 100.0
    assert b.lv(0) == pytest.approx(a.lv(100.0))
    assert b.origin() != pytest.approx(a.origin())


def test_box_volume_no_double_count():
    b = BoxShape(use_top_hunch=False, is_start_closed=True, start_wall_t=1.0)
    iw, ih = b.width - 2 * b.wall_t, b.height - b.slab_b - b.slab_t
    assert b.volume == pytest.approx(b.width * b.height * b.length - iw * ih * (b.length - 1.0))


class W:  # tkinter 없이 쓰는 가짜 위젯
    def __init__(self, v): self.v = v
    def get(self): return self.v


def entries(floors=2):
    e = {k: W(v) for k, v in dict(
        bp_x="286.4826", bp_y="-85.3896", bp_z="123.45", ep_x="575.9987", ep_y="437.4075", ep_z="134.45",
        bp_station="0.0", start_station="0.0", length="200", width="20", offset="0", height="12",
        floors=str(floors), wall_t="1.0", floor_t="1.2", slab_t="1.0", track_spacing="4.4", plat_offset="1.7",
        plat_thick="0.2", plat_height="1.1", support_t="0.3", platform_type="0", col_interval="10", col_width="0.8",
        col_depth="0.8", sync_all=True).items()}
    return e


def test_adapter_maps_slabs_and_defaults():
    cfg = TkAdapter.collect_entries(entries())
    assert (cfg.station.floor_t, cfg.station.slab_t) == (1.2, 1.0)
    assert cfg.column.target_floors == [1, 2]


def test_adapter_per_floor_circle():
    e = entries(); e["floor_1_type"] = W("원기둥"); e["floor_1_radius"] = W("0.6")
    cfg = TkAdapter.collect_entries(e)
    spec = cfg.column.floors[2].rows[0].pattern[0]
    assert spec.shape_type == T.CIRCLE and spec.radius == 0.6
    assert cfg.column.floors[1].rows[0].pattern[0].shape_type == T.RECTANGLE


def test_bad_floor_index_raises():
    cp = ColumnParameters(floors={5: FloorColumnSpec()})
    with pytest.raises(ValueError):
        StationCADEngine(make_cfg(cp))


# ---------------- 벽체 ----------------
import math
import numpy as np
import ifcopenshell.geom
import ifcopenshell.util.shape
from walls.wall_engine import WallEngine


def test_walls_per_level_and_volume():
    cfg = make_cfg()
    we = WallEngine(cfg)
    st = cfg.station
    assert [p.level for p in we.wall_packages] == ["B3F", "B2F", "B1F"]
    assert all(p.total_count == 4 for p in we.wall_packages)
    assert [w.name for w in we.wall_packages[0].walls] == ["WALL_B3F_START", "WALL_B3F_L", "WALL_B3F_R", "WALL_B3F_END"]
    # 층별 높이 합 = H - 천장슬래브, 총 체적 = 측벽 2 + 마감벽 2 (겹침 없음)
    h = st.height - st.slab_t
    expected = 2 * (st.length - 2 * st.wall_t) * st.wall_t * h + 2 * st.wall_t * st.width * h
    assert sum(p.total_volume for p in we.wall_packages) == pytest.approx(expected)


def test_wall_3d_faces(tmp_path):
    eng = StationCADEngine(make_cfg())
    path = eng.generate_3d_dxf(tmp_path / "3d.dxf")
    faces = len(ezdxf.readfile(path).modelspace().query('3DFACE[layer=="STRUCT_WALL"]'))
    assert faces == 3 * 4 * 6


def test_ifc_walls_geometry_matches_model(tmp_path):
    cfg = make_cfg()
    eng = StationCADEngine(cfg)
    path = eng.generate_ifc(tmp_path / "m.ifc")
    f = ifcopenshell.open(path)
    walls = [w for w in f.by_type("IfcWall") if w.Name.startswith("WALL_")]   # PLATW_ 는 승강장 지지벽체
    assert len(walls) == 12
    by_storey = {}
    for rel in f.by_type("IfcRelContainedInSpatialStructure"):  # 층마다 벽/기둥 rel이 따로 있음 → 합산
        n = len([e for e in rel.RelatedElements if e.is_a("IfcWall") and e.Name.startswith("WALL_")])
        by_storey[rel.RelatingStructure.Name] = by_storey.get(rel.RelatingStructure.Name, 0) + n
    assert by_storey == {"B3F": 4, "B2F": 4, "B1F": 4}

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    ox, oy = cfg.origin(); th = cfg.align.theta
    model = {w.name: w for p in eng.walls.wall_packages for w in p.walls}
    for el in walls:
        w = model[el.Name]
        shp = ifcopenshell.geom.create_shape(settings, el)
        v = np.array(shp.geometry.verts).reshape(-1, 3)
        # 모델 기준 8개 꼭짓점 → WCS
        s0, s1, t0, t1, z0, z1 = eng.walls.wall_corners(w)
        h = w.shape.height
        pts = []
        for s, t, z in [(s0, t0, z0), (s0, t1, z0), (s1, t0, z1), (s1, t1, z1),
                        (s0, t0, z0 + h), (s0, t1, z0 + h), (s1, t0, z1 + h), (s1, t1, z1 + h)]:
            x = ox + s * math.cos(th) - t * math.sin(th)
            y = oy + s * math.sin(th) + t * math.cos(th)
            pts.append((x, y, z))
        pts = np.array(pts)
        assert v.min(axis=0) == pytest.approx(pts.min(axis=0), abs=1e-4), el.Name
        assert v.max(axis=0) == pytest.approx(pts.max(axis=0), abs=1e-4), el.Name
        assert ifcopenshell.util.shape.get_volume(shp.geometry) == pytest.approx(w.shape.volume, rel=1e-6), el.Name


# ---------------- 슬래브 ----------------
from slabs.slab_engine import SlabEngine
from slabs.slab_shape_type import SlabKind


def test_slabs_per_level_and_kinds():
    se = SlabEngine(make_cfg())
    pk = {p.level: [s.name for s in p.slabs] for p in se.slab_packages}
    assert pk == {"B3F": ["SLAB_B3F_FLOOR"], "B2F": ["SLAB_B2F_MID"], "B1F": ["SLAB_B1F_MID", "SLAB_B1F_ROOF"]}
    kinds = {s.name: s.kind for p in se.slab_packages for s in p.slabs}
    assert kinds["SLAB_B3F_FLOOR"] == SlabKind.FLOOR and kinds["SLAB_B1F_ROOF"] == SlabKind.ROOF


def test_slab_plus_wall_volume_matches_envelope():
    """슬래브+벽체 체적 = 외곽 박스 - 내부 공동 + 중간 슬래브 (겹침/누락 없음)"""
    cfg = make_cfg(); st = cfg.station
    solid = (sum(p.total_volume for p in SlabEngine(cfg).slab_packages)
             + sum(p.total_volume for p in WallEngine(cfg).wall_packages))
    W, L, wt = st.width, st.length, st.wall_t
    ext = W * L * (st.floor_t + st.height)
    void = (W - 2 * wt) * (L - 2 * wt) * (st.height - st.slab_t)
    mids = (st.floors - 1) * (W - 2 * wt) * (L - 2 * wt) * st.slab_t
    assert solid == pytest.approx(ext - void + mids)


def test_single_floor_station_builds(tmp_path):
    cfg = make_cfg(ColumnParameters.uniform(1), floors=1)
    paths = BIMEngine.build(cfg, tmp_path)
    f = ifcopenshell.open(paths[-1])
    assert {s.Name for s in f.by_type("IfcSlab") if s.Name.startswith("SLAB_")} == {"SLAB_1F_FLOOR", "SLAB_1F_ROOF"}


def test_slab_3d_faces(tmp_path):
    eng = StationCADEngine(make_cfg())
    path = eng.generate_3d_dxf(tmp_path / "3d.dxf")
    faces = len(ezdxf.readfile(path).modelspace().query('3DFACE[layer=="STRUCT_SLAB"]'))
    assert faces == 4 * 6


def test_ifc_slabs_geometry_matches_model(tmp_path):
    cfg = make_cfg()
    eng = StationCADEngine(cfg)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "s.ifc"))
    slabs = [s for s in f.by_type("IfcSlab") if s.Name.startswith("SLAB_")]  # 승강장(PLAT_)은 별도
    assert len(slabs) == 4
    assert {s.Name: s.PredefinedType for s in slabs} == {
        "SLAB_B3F_FLOOR": "BASESLAB", "SLAB_B2F_MID": "FLOOR", "SLAB_B1F_MID": "FLOOR", "SLAB_B1F_ROOF": "ROOF"}
    storey_of = {}
    for rel in f.by_type("IfcRelContainedInSpatialStructure"):
        for e in rel.RelatedElements:
            if e.is_a("IfcSlab") and e.Name.startswith("SLAB_"):
                storey_of[e.Name] = rel.RelatingStructure.Name
    assert storey_of == {"SLAB_B3F_FLOOR": "B3F", "SLAB_B2F_MID": "B2F", "SLAB_B1F_MID": "B1F", "SLAB_B1F_ROOF": "B1F"}

    settings = ifcopenshell.geom.settings(); settings.set("use-world-coords", True)
    ox, oy = cfg.origin(); th = cfg.align.theta
    model = {s.name: s for p in eng.slabs.slab_packages for s in p.slabs}
    for el in slabs:
        sl = model[el.Name]
        shp = ifcopenshell.geom.create_shape(settings, el)
        v = np.array(shp.geometry.verts).reshape(-1, 3)
        s0, s1, t0, t1, z0, z1 = eng.slabs.slab_corners(sl)
        h = sl.shape.thickness
        pts = np.array([(ox + s * math.cos(th) - t * math.sin(th), oy + s * math.sin(th) + t * math.cos(th), z)
                        for s, t, z in [(s0, t0, z0), (s0, t1, z0), (s1, t0, z1), (s1, t1, z1),
                                        (s0, t0, z0 + h), (s0, t1, z0 + h), (s1, t0, z1 + h), (s1, t1, z1 + h)]])
        assert v.min(axis=0) == pytest.approx(pts.min(axis=0), abs=1e-4), el.Name
        assert v.max(axis=0) == pytest.approx(pts.max(axis=0), abs=1e-4), el.Name
        assert ifcopenshell.util.shape.get_volume(shp.geometry) == pytest.approx(sl.shape.volume, rel=1e-6), el.Name


# ---------------- 승강장 (ㅠ형: 슬래브 + 지지벽체) ----------------
from platforms.platform_engine import PlatformEngine
from platforms.platform_type import PlatformPart, PlatformSide


def test_platform_objects_and_volume():
    cfg = make_cfg(); st, pf = cfg.station, cfg.platform
    pe = PlatformEngine(cfg)
    assert [p.level for p in pe.platform_packages] == ["B3F"]
    plats = pe.platform_packages[0].platforms
    assert [p.name for p in plats] == [
        "PLAT_B3F_L", "PLATW_B3F_L_TRACK", "PLATW_B3F_L_OUT", "PLAT_B3F_R", "PLATW_B3F_R_TRACK", "PLATW_B3F_R_OUT"]
    width = (st.width / 2 - st.wall_t) - (pf.track_spacing / 2 + pf.plat_offset)   # 5.1m
    L = st.length - 2 * st.wall_t
    slabs = [p for p in plats if p.part == PlatformPart.SLAB]
    legs = [p for p in plats if p.part == PlatformPart.SUPPORT_WALL]
    assert len(slabs) == 2 and len(legs) == 4
    assert slabs[0].shape.width == pytest.approx(width)
    assert pe.platform_packages[0].total_volume == pytest.approx(
        2 * width * L * pf.plat_thick + 4 * pf.support_t * L * pf.plat_height)
    # 다리: 바닥 슬래브 상면 ~ 승강장 슬래브 하면, 슬래브 끝단과 일치(ㅠ형)
    for leg in legs:
        s0, s1, t0, t1, z0, z1 = pe.platform_corners(leg)
        assert z0 == pytest.approx(cfg.lv(s0) - st.offset)            # 바닥 슬래브 상면
        assert leg.shape.thickness == pytest.approx(pf.plat_height)
        assert leg.shape.width == pytest.approx(pf.support_t)
    for slab in slabs:
        assert pe.platform_corners(slab)[4] == pytest.approx(cfg.lv(st.wall_t) - st.offset + pf.plat_height)
    # 좌/우 대칭, 벽체 안쪽 면 사이에 위치
    assert slabs[0].pos_y == pytest.approx(-slabs[1].pos_y)
    for p in plats:
        s0, s1, t0, t1, z0, z1 = pe.platform_corners(p)
        assert s0 == pytest.approx(st.wall_t) and s1 == pytest.approx(st.length - st.wall_t)
        assert min(t0, t1) >= -(st.width / 2 - st.wall_t) - 1e-9 and max(t0, t1) <= st.width / 2 - st.wall_t + 1e-9


def test_platform_without_support_walls():
    cfg = make_cfg(); cfg.platform.support_t = 0.0
    names = [p.name for p in PlatformEngine(cfg).platform_packages[0].platforms]
    assert names == ["PLAT_B3F_L", "PLAT_B3F_R"]


def test_platform_3d_faces_once(tmp_path):
    eng = StationCADEngine(make_cfg())
    path = eng.generate_3d_dxf(tmp_path / "3d.dxf")
    faces = len(ezdxf.readfile(path).modelspace().query('3DFACE[layer=="STRUCT_PLATFORM"]'))
    assert faces == 6 * 6          # 슬래브 2 + 지지벽체 4 (이전: 5m 세그먼트마다 반복)


def test_platform_section_draws_pi_shape(tmp_path):
    eng = StationCADEngine(make_cfg())
    path = eng.generate_section_dxf([100.0], tmp_path / "sec.dxf")
    polys = ezdxf.readfile(path).modelspace().query('LWPOLYLINE[layer=="SEC_PLATFORM"]')
    assert len(polys) == 2 + 4     # 슬래브 2 + 다리 4


def test_columns_follow_platform_or_floor():
    """승강장 위 기둥은 승강장 상면, 선로 사이 기둥은 바닥 슬래브 상면에 선다"""
    cp = ColumnParameters(sync_with_platform=True, floors={
        1: FloorColumnSpec([ColumnRowSpec(0.0, 10.0, 1.0, [RECT(0.4, 1.0)]),
                            ColumnRowSpec(6.0, 10.0, 1.0, [CIRC(0.5)])]),
        2: FloorColumnSpec(), 3: FloorColumnSpec()})
    cfg = make_cfg(cp); st, pf = cfg.station, cfg.platform
    eng = StationCADEngine(cfg)
    b3 = eng.columns.column_packages[0]
    for c in b3.columns:
        floor_top = cfg.lv(c.pos_x) - st.offset
        expected = floor_top + (pf.plat_height + pf.plat_thick if c.pos_y == 6.0 else 0.0)
        assert c.pos_z == pytest.approx(expected), c.name
    plat = eng.platform.platform_packages[0].platforms[0]
    s0, s1, *_ , z0, z1 = eng.platform.platform_corners(plat)
    on = next(c for c in b3.columns if c.pos_y == 6.0)
    assert on.pos_z == pytest.approx(z0 + (on.pos_x - s0) / (s1 - s0) * (z1 - z0) + plat.shape.thickness)


def test_column_straddling_platform_edge_raises():
    cp = ColumnParameters(floors={1: FloorColumnSpec([ColumnRowSpec(3.9, 10.0, 1.0, [CIRC(0.5)])])})
    with pytest.raises(ValueError):
        StationCADEngine(make_cfg(cp, floors=3))


def test_user_example_columns_clear_of_platforms():
    eng = StationCADEngine(make_cfg(user_example()))
    for plat in eng.platform.platform_packages[0].platforms:
        _, _, pt0, pt1, _, _ = eng.platform.platform_corners(plat)
        for c in eng.columns.column_packages[0].columns:    # 승강장과 같은 높이대는 최하층(B3F)뿐
            lo, hi = c.pos_y - c.shape.half_t, c.pos_y + c.shape.half_t
            assert hi <= min(pt0, pt1) or lo >= max(pt0, pt1)


def test_platform_validation():
    cfg = make_cfg(); cfg.platform.track_spacing = 20.0      # 선로간격이 정거장 폭을 넘음
    with pytest.raises(ValueError):
        PlatformEngine(cfg)
    cfg = make_cfg(); cfg.platform.support_t = 3.0           # 다리 2개가 슬래브 폭을 넘음
    with pytest.raises(ValueError):
        PlatformEngine(cfg)
    cfg = make_cfg(); cfg.platform.plat_type = "1"           # 섬식 미지원
    with pytest.raises(NotImplementedError):
        PlatformEngine(cfg)
    cfg = make_cfg(); cfg.platform.plat_thick = 0.0          # 승강장 미설정 → 객체 없음
    assert PlatformEngine(cfg).platform_packages == []


def test_ifc_platforms_geometry_matches_model(tmp_path):
    cfg = make_cfg()
    eng = StationCADEngine(cfg)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    slabs = [e for e in f.by_type("IfcSlab") if e.Name.startswith("PLAT_")]
    legs = [e for e in f.by_type("IfcWall") if e.Name.startswith("PLATW_")]
    assert {e.Name: (e.PredefinedType, e.ObjectType) for e in slabs} == {
        "PLAT_B3F_L": ("USERDEFINED", "PLATFORM"), "PLAT_B3F_R": ("USERDEFINED", "PLATFORM")}
    assert len(legs) == 4 and all(e.PredefinedType == "SOLIDWALL" and e.ObjectType == "PLATFORM_SUPPORT" for e in legs)
    storeys = {e.Name: rel.RelatingStructure.Name for rel in f.by_type("IfcRelContainedInSpatialStructure")
               for e in rel.RelatedElements if e.Name.startswith("PLAT")}
    assert set(storeys.values()) == {"B3F"} and len(storeys) == 6

    settings = ifcopenshell.geom.settings(); settings.set("use-world-coords", True)
    ox, oy = cfg.origin(); th = cfg.align.theta
    model = {p.name: p for pk in eng.platform.platform_packages for p in pk.platforms}
    for el in slabs + legs:
        pl = model[el.Name]
        shp = ifcopenshell.geom.create_shape(settings, el)
        v = np.array(shp.geometry.verts).reshape(-1, 3)
        s0, s1, t0, t1, z0, z1 = eng.platform.platform_corners(pl)
        h = pl.shape.thickness
        pts = np.array([(ox + s * math.cos(th) - t * math.sin(th), oy + s * math.sin(th) + t * math.cos(th), z)
                        for s, t, z in [(s0, t0, z0), (s0, t1, z0), (s1, t0, z1), (s1, t1, z1),
                                        (s0, t0, z0 + h), (s0, t1, z0 + h), (s1, t0, z1 + h), (s1, t1, z1 + h)]])
        assert v.min(axis=0) == pytest.approx(pts.min(axis=0), abs=1e-4), el.Name
        assert v.max(axis=0) == pytest.approx(pts.max(axis=0), abs=1e-4), el.Name
        assert ifcopenshell.util.shape.get_volume(shp.geometry) == pytest.approx(pl.shape.volume, rel=1e-6), el.Name


# ---------------- 전체 모델 간섭(겹침) 검사 ----------------
def _parts(eng):
    """모든 부재를 (이름, s0, s1, t0, t1, z(s)->(하단, 상단)) 로 통일. 구배가 모두 같아 s별 z구간만 비교하면 됨"""
    out = []

    def prism(name, s0, s1, t0, t1, z0, z1, h):
        out.append((name, s0, s1, t0, t1, lambda s, z0=z0, z1=z1, s0=s0, s1=s1, h=h:
                    (z0 + (s - s0) / (s1 - s0) * (z1 - z0), z0 + (s - s0) / (s1 - s0) * (z1 - z0) + h)))

    for pk in eng.walls.wall_packages:
        for w in pk.walls:
            c = eng.walls.wall_corners(w); prism(w.name, *c, w.shape.height)
    for pk in eng.slabs.slab_packages:
        for sl in pk.slabs:
            c = eng.slabs.slab_corners(sl); prism(sl.name, *c, sl.shape.thickness)
    for pk in eng.platform.platform_packages:
        for pl in pk.platforms:
            c = eng.platform.platform_corners(pl); prism(pl.name, *c, pl.shape.thickness)
    for pk in eng.columns.column_packages:
        for c in pk.columns:
            hs, ht = c.shape.half_s, c.shape.half_t
            zr = (c.pos_z, c.pos_z + c.shape.height)
            out.append((c.name, c.pos_x - hs, c.pos_x + hs, c.pos_y - ht, c.pos_y + ht, lambda s, zr=zr: zr))
    return out


@pytest.mark.parametrize("cols", [None, "user"])
def test_no_overlap_between_members(cols):
    eng = StationCADEngine(make_cfg(user_example() if cols else None))
    parts = _parts(eng)
    tol = 0.02          # 수직 기둥이 구배 슬래브에 맞닿는 곳의 미소 편차(구배×반폭) 허용
    bad = []
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            ds = min(a[2], b[2]) - max(a[1], b[1]); dt = min(a[4], b[4]) - max(a[3], b[3])
            if ds <= tol or dt <= tol:
                continue
            sm = (max(a[1], b[1]) + min(a[2], b[2])) / 2
            (alo, ahi), (blo, bhi) = a[5](sm), b[5](sm)
            if min(ahi, bhi) - max(alo, blo) > tol:
                bad.append((a[0], b[0]))
    assert bad == []


# ---------------- 2D 도면 (객체 기반) ----------------
from helper.view_item import ViewItem, merge_items

NO_COLUMNS = lambda: ColumnParameters(floors={1: FloorColumnSpec(rows=[])})


def _q(path, layer, kind="LWPOLYLINE"):
    return list(ezdxf.readfile(path).modelspace().query(f'{kind}[layer=="{layer}"]'))


def _bbox(pl):
    pts = [(p[0], p[1]) for p in pl.get_points()]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def test_section_cut_members_and_wall_merge(tmp_path):
    cfg = make_cfg(); st = cfg.station
    path = StationCADEngine(cfg).generate_section_dxf([12.0], tmp_path / "s.dxf")   # 기둥 중심 s=12 를 자름
    conc = _q(path, "SEC_CONCRETE")
    assert len(conc) == 1 + 1 + 2 + 2 + 3          # 바닥, 천장, 중간 2, 외벽 2(층별 벽체가 하나로 합쳐짐), 절단 기둥 3
    assert len(_q(path, "SEC_PLATFORM")) == 6        # 승강장 슬래브 2 + 지지벽체 4
    assert _q(path, "SEC_BEYOND") == []              # 같은 열의 앞쪽 기둥은 절단 기둥과 동일 형상이라 생략
    walls = [pl for pl in conc if abs((_bbox(pl)[1] - _bbox(pl)[0]) - st.wall_t) < 1e-6 and (_bbox(pl)[3] - _bbox(pl)[2]) > st.height - 1]
    assert len(walls) == 2 and all(abs((_bbox(w)[3] - _bbox(w)[2]) - (st.height - st.slab_t)) < 1e-6 for w in walls)


def test_section_inside_end_wall(tmp_path):
    path = StationCADEngine(make_cfg(NO_COLUMNS())).generate_section_dxf([0.5], tmp_path / "s.dxf")
    assert len(_q(path, "SEC_CONCRETE")) == 3       # 바닥 + 천장 + 시점 마감벽(전폭 1개)
    assert _q(path, "SEC_PLATFORM") == []           # 승강장은 마감벽 안쪽부터


def test_section_matches_objects(tmp_path):
    """도면의 바닥 슬래브/승강장 슬래브 좌표 = BIM 객체에서 계산한 값 (단일 데이터 원천)"""
    cfg = make_cfg(); st = cfg.station; pf = cfg.platform
    sta = 60.0
    path = StationCADEngine(cfg).generate_section_dxf([sta], tmp_path / "s.dxf")
    floor = next(pl for pl in _q(path, "SEC_CONCRETE") if abs((_bbox(pl)[1] - _bbox(pl)[0]) - st.width) < 1e-6
                 and _bbox(pl)[2] < cfg.lv(sta) - st.offset)
    assert _bbox(floor)[2] == pytest.approx(cfg.lv(sta) - st.offset - st.floor_t)
    slab = next(pl for pl in _q(path, "SEC_PLATFORM") if abs((_bbox(pl)[3] - _bbox(pl)[2]) - pf.plat_thick) < 1e-6)
    assert _bbox(slab)[2] == pytest.approx(cfg.lv(sta) - st.offset + pf.plat_height)


def test_section_circle_chord_and_beyond():
    cp = ColumnParameters(floors={1: FloorColumnSpec([ColumnRowSpec(0.0, 10.0, 1.0, [CIRC(0.5)])])})
    eng = StationCADEngine(make_cfg(cp))
    near = eng.columns.section_items(2.3)            # 중심 s=2 에서 0.3m 떨어진 절단 → 현의 반폭 0.4
    cut = [i for i in near if i.layer == "SEC_CONCRETE"]
    assert len(cut) == 1 and (cut[0].u1 - cut[0].u0) == pytest.approx(0.8)
    between = eng.columns.section_items(7.0)         # 기둥 사이: 절단 없음, 앞쪽(s=12) 기둥 1개만 보임
    assert [i.layer for i in between] == ["SEC_BEYOND"]


def test_profile_cut_and_beyond(tmp_path):
    path = StationCADEngine(make_cfg(NO_COLUMNS())).generate_profile_dxf(tmp_path / "p.dxf")
    assert len(_q(path, "PROF_CONCRETE")) == 1 + 1 + 2 + 2    # 바닥, 천장, 중간 2, 마감벽 2(층별 합침)
    assert len(_q(path, "PROF_BEYOND")) == 2                  # 측면에서 보이는 승강장: 슬래브 + 다리(좌/우·선로측/벽체측 다리는 측면 형상이 같아 1회)
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert "PLATFORM SLAB (FL+1.10m)" in texts


def test_profile_user_example_dedupes_side_columns(tmp_path):
    eng = StationCADEngine(make_cfg(user_example()))
    path = eng.generate_profile_dxf(tmp_path / "p.dxf")
    beyond = _q(path, "PROF_BEYOND")
    assert len(beyond) == 20 + 2     # B2F 의 t=±3 열은 같은 s 라 20개만 + 승강장(슬래브, 다리) 2


def test_plan_cut_level_and_members(tmp_path):
    path = StationCADEngine(make_cfg(NO_COLUMNS())).generate_plan_dxf(tmp_path / "p.dxf")
    assert len(_q(path, "PLAN_OUTLINE")) == 2 + 2     # 벽체 바깥/안쪽 + 승강장 좌/우
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert any("CUT LEVEL: FL+2.0m" in t for t in texts)


def test_plan_shows_only_columns_cut_by_level(tmp_path):
    cp = ColumnParameters(floors={1: FloorColumnSpec([ColumnRowSpec(0.0, 10.0, 1.0, [CIRC(0.5)])]),
                                  2: FloorColumnSpec([ColumnRowSpec(0.0, 10.0, 1.0, [RECT(0.8, 0.8)])]),
                                  3: FloorColumnSpec()})
    path = StationCADEngine(make_cfg(cp)).generate_plan_dxf(tmp_path / "p.dxf")
    assert len(_q(path, "PLAN_OUTLINE", "CIRCLE")) == 20          # B3F 원기둥만 절단 (B2F 사각기둥은 FL+2.0m 위)


def test_station_label_uses_absolute_station(tmp_path):
    cfg = make_cfg(); cfg.station.start_station = 1234.5
    path = StationCADEngine(cfg).generate_section_dxf([25.0], tmp_path / "s.dxf")
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert any("1+259.50" in t for t in texts)


def test_merge_items_only_touching():
    a = ViewItem.rect("a", "L", 0, 1, 0, 5, merge=True)
    b = ViewItem.rect("b", "L", 0, 1, 5, 9, merge=True)       # a 위에 맞닿음 → 합쳐짐
    c = ViewItem.rect("c", "L", 0, 1, 10, 12, merge=True)     # 떨어져 있음 → 별개
    d = ViewItem.rect("d", "L", 2, 3, 0, 5, merge=True)       # 다른 u 구간 → 별개
    out = merge_items([b, a, c, d])
    spans = sorted((i.u0, i.vb0, i.vt0) for i in out)
    assert spans == [(0, 0, 9), (0, 10, 12), (2, 0, 5)]
