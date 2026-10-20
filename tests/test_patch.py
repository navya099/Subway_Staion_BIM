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
        platform=PlatformParameters(4.4, 1.7, 0.2, 1.1),
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
    by_storey = {rel.RelatingStructure.Name: len(rel.RelatedElements)
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
        plat_thick="0.2", plat_height="1.1", platform_type="0", col_interval="10", col_width="0.8",
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
