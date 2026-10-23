"""곡선 선형(평면 곡선 + 완화곡선 + 종곡선) 대응 테스트"""
import hashlib, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.shape
import pytest

from columns.column_params import ColumnParameters, FloorColumnSpec
from config.alignment import Alignment
from config.alignment_io import alignment_from_dict, describe, load_alignment
from config.curved_alignment import (CurvedAlignment, HElement, HorizontalAlignment, VerticalProfile,
                                     horizontal_from_pi)
from engine.bim_engine import BIMEngine
from engine.cad_engine import StationCADEngine
from helper import prism_member as PM
from test_patch import ParabolicProfile, _bbox, _q, make_cfg, user_example

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "curve_alignment.json")
SAMPLE_EL = os.path.join(ROOT, "samples", "curve_alignment_elements.json")
NO_COLS = lambda: ColumnParameters(floors={1: FloorColumnSpec(rows=[])})


def s_curve():
    ha = horizontal_from_pi(0.0, [(0, 0), (500, 0), (900, 400), (1500, 400)], radii=[400, 500], spirals=[60, 80])
    return CurvedAlignment(ha, VerticalProfile([(0, 100, 0), (450, 104, 150), (1000, 98, 0)]))


def curved_cfg(start=330.0, columns=None, **station):
    """STA 330~530: 직선에서 완화곡선을 지나 원곡선으로 들어가는 구간 + 종곡선"""
    cfg = make_cfg(columns if columns is not None else user_example())
    cfg.align, cfg.station.start_station = s_curve(), start
    for k, v in station.items():
        setattr(cfg.station, k, v)
    return cfg


def arc_cfg(radius, left=True, length=200.0, heading=0.0, origin=(0.0, 0.0)):
    k = (1 if left else -1) / radius
    ha = HorizontalAlignment(0.0, *origin, math.radians(heading), [HElement(1000.0, k, k)])
    cfg = make_cfg(NO_COLS())
    cfg.align = CurvedAlignment(ha, VerticalProfile([(0, 100, 0), (1000, 103, 0)]))
    cfg.station.start_station, cfg.station.length = 0.0, length
    return cfg


def members(eng):
    out = []
    for pk in eng.walls.wall_packages: out += pk.walls
    for pk in eng.slabs.slab_packages: out += pk.slabs
    for pk in eng.platform.platform_packages: out += pk.platforms
    return out


# ===================================================== 선형 수학
def test_arc_points_stay_on_circle():
    R, th0 = 400.0, math.radians(30)
    ha = HorizontalAlignment(0.0, 10.0, 20.0, th0, [HElement(300.0, 1 / R, 1 / R)])
    cx, cy = 10.0 - R * math.sin(th0), 20.0 + R * math.cos(th0)
    for s in range(0, 301, 10):
        x, y = ha.point_at(s)
        assert math.hypot(x - cx, y - cy) == pytest.approx(R, abs=1e-9)
    assert ha.azimuth_at(300.0) - ha.azimuth_at(0.0) == pytest.approx(300 / R)
    assert ha.curvature_at(150.0) == pytest.approx(1 / R)


def test_clothoid_matches_numeric_integration():
    L, Rs, th0 = 120.0, 500.0, 0.4
    ha = HorizontalAlignment(0.0, 0.0, 0.0, th0, [HElement(L, 0.0, 1 / Rs)])

    def simpson(f, a, b, n=20000):
        h = (b - a) / n
        return (f(a) + f(b) + sum((4 if i % 2 else 2) * f(a + i * h) for i in range(1, n))) * h / 3
    th = lambda u: th0 + u * u / (2 * L * Rs)
    for s in (20.0, 60.0, 120.0):
        x, y = ha.point_at(s)
        assert (x, y) == pytest.approx((simpson(lambda u: math.cos(th(u)), 0, s), simpson(lambda u: math.sin(th(u)), 0, s)), abs=1e-8)
    assert ha.curvature_at(60.0) == pytest.approx(0.5 / Rs)         # 곡률은 거리에 선형


def test_horizontal_from_pi_geometry():
    pts = [(0, 0), (500, 0), (900, 400), (1500, 400)]
    ha = horizontal_from_pi(1000.0, pts, radii=[400, 500], spirals=[60, 80])
    assert ha.point_at(1000.0) == pytest.approx((0, 0)) and ha.azimuth_at(1000.0) == pytest.approx(0)
    assert ha.point_at(ha.end_station) == pytest.approx((1500, 400), abs=1e-6)         # 정확히 종점에 도착
    assert ha.azimuth_at(ha.end_station) == pytest.approx(0, abs=1e-9)                 # 종점 방향 = 마지막 직선 방향
    for b in ha.breakpoints():                                                         # 요소 경계에서 위치/방향/곡률 연속
        assert ha.point_at(b - 1e-7) == pytest.approx(ha.point_at(b + 1e-7), abs=1e-5)
        assert ha.azimuth_at(b - 1e-7) == pytest.approx(ha.azimuth_at(b + 1e-7), abs=1e-8)
        assert ha.curvature_at(b - 1e-7) == pytest.approx(ha.curvature_at(b + 1e-7), abs=1e-7)
    # 각 곡선의 시점(TS)/종점(ST) 접선이 교점(IP)을 지나고 TS~IP, ST~IP 거리가 같음
    groups, cur = [], None
    for e, st in zip(ha.elements, ha._starts):
        curved = e.k0 != 0 or e.k1 != 0
        if curved and cur is None: cur = [st, st + e.length]
        elif curved: cur[1] = st + e.length
        elif cur is not None: groups.append(cur); cur = None
    assert len(groups) == 2
    for (ts, st_), ip in zip(groups, [(500, 0), (900, 400)]):
        for sta in (ts, st_):
            (x, y), th = ha.point_at(sta), ha.azimuth_at(sta)
            assert (ip[0] - x) * math.sin(th) - (ip[1] - y) * math.cos(th) == pytest.approx(0, abs=1e-9)
        assert math.hypot(ip[0] - ha.point_at(ts)[0], ip[1] - ha.point_at(ts)[1]) == pytest.approx(
            math.hypot(ip[0] - ha.point_at(st_)[0], ip[1] - ha.point_at(st_)[1]), abs=1e-9)


@pytest.mark.parametrize("call,msg", [
    (lambda: horizontal_from_pi(0, [(0, 0), (500, 0), (900, 400)], radii=[400, 500]), "교점이 1개이므로"),
    (lambda: horizontal_from_pi(0, [(0, 0), (300, 0), (520, 180), (900, 180)], radii=[400, 500]), "곡선이 겹칩니다"),
    (lambda: horizontal_from_pi(0, [(0, 0), (500, 0), (600, 10)], radii=[400], spirals=[300]), "완화곡선 2개"),
    (lambda: horizontal_from_pi(0, [(0, 0), (500, 0), (900, 400)], radii=[0]), "곡선반경은 0보다"),
    (lambda: horizontal_from_pi(0, [(0, 0), (0, 0)], radii=[]), "위치가 같습니다"),
    (lambda: horizontal_from_pi(0, [(0, 0)], radii=[]), "2개 이상"),
    (lambda: HorizontalAlignment(0, 0, 0, 0, [HElement(0.0)]), "길이는 0보다"),
    (lambda: HorizontalAlignment(0, 0, 0, 0, []), "비어 있습니다"),
])
def test_horizontal_validation(call, msg):
    with pytest.raises(ValueError, match=msg):
        call()


def test_vertical_profile_parabola():
    vp = VerticalProfile([(1000, 100, 0), (1300, 106, 120), (1600, 94, 200), (1900, 100, 0)])
    g1, g2 = vp.g[0], vp.g[1]
    assert vp.elevation_at(1300) - 106 == pytest.approx((g2 - g1) * 120 / 8)            # PVI 에서 종곡선 중앙 오프셋 = Δg·L/8
    for sta in (1240, 1360, 1500, 1700):                                                # 시작/끝 연속
        assert vp.elevation_at(sta - 1e-7) == pytest.approx(vp.elevation_at(sta + 1e-7), abs=1e-5)
        assert vp.grade_at(sta - 1e-7) == pytest.approx(vp.grade_at(sta + 1e-7), abs=1e-6)
    for sta in range(1000, 1901, 17):                                                   # 구배 = 표고의 미분
        assert vp.grade_at(sta) == pytest.approx((vp.elevation_at(sta + 1e-4) - vp.elevation_at(sta - 1e-4)) / 2e-4, abs=1e-8)
    assert vp.elevation_at(1100) == pytest.approx(100 + vp.g[0] * 100)                  # 종곡선 밖은 직선 구배


@pytest.mark.parametrize("pvis,msg", [
    ([(0, 100, 0)], "2개 이상"),
    ([(0, 100, 0), (0, 101, 0)], "측점은 증가"),
    ([(0, 100, 10), (100, 101, 0)], "종곡선장은 0이어야"),
    ([(0, 100, 0), (100, 101, -5), (200, 100, 0)], "종곡선장은 0 이상"),
    ([(0, 100, 0), (100, 101, 250), (200, 100, 0)], "겹칩니다"),
    ([(0, 100, 0), (100, 101, 100), (150, 100, 100), (400, 99, 0)], "겹칩니다"),
])
def test_vertical_validation(pvis, msg):
    with pytest.raises(ValueError, match=msg):
        VerticalProfile(pvis)


def test_curved_alignment_range_and_properties():
    a = s_curve()
    assert not a.is_straight and a.start_station == 0.0 and a.end_station == pytest.approx(1000.0)   # 평면(~2626)·종단(1000) 교집합
    a.validate()
    far = CurvedAlignment(HorizontalAlignment(0, 0, 0, 0, [HElement(100.0)]), VerticalProfile([(500, 1, 0), (600, 2, 0)]))
    with pytest.raises(ValueError, match="겹치지 않습니다"):
        far.validate()


def test_sample_stations_rules():
    a = s_curve()
    st = a.sample_stations(300.0, 700.0)
    assert st[0] == 300.0 and st[-1] == 700.0
    assert all(b - a_ <= 5.0 + 1e-9 for a_, b in zip(st, st[1:]))                                    # 최대 간격 5m
    for bp in a.breakpoints():                                                                       # 곡선 시작/끝(변곡) 측점은 반드시 포함
        if 300.0 < bp < 700.0:
            assert any(abs(bp - x) < 1e-6 for x in st), bp
    assert max(abs(a.azimuth_at(b) - a.azimuth_at(a_)) for a_, b in zip(st, st[1:])) <= 0.02 + 1e-6   # 현마다 방향 변화 ≤ 0.02rad
    assert make_cfg().align.sample_stations(0, 500) == [0, 500]                                      # 직선은 양 끝점만


def test_default_curvature_is_numeric_derivative_of_azimuth():
    class Spin(Alignment):
        start_station, end_station = 0.0, 100.0
        def point_at(self, s): return (s, 0.0)
        def azimuth_at(self, s): return 0.003 * s
        def elevation_at(self, s): return 0.0
    assert Spin().curvature_at(50.0) == pytest.approx(0.003, rel=1e-6)


# ===================================================== 설정 검증
def test_station_range_and_tight_radius_rules():
    cfg = curved_cfg(); cfg.validate()
    cfg.station.start_station = 900.0                                   # 정거장 끝(1100)이 선형 끝(1000)을 넘음
    with pytest.raises(ValueError, match="선형 범위"):
        cfg.validate()
    tight = arc_cfg(15.0)                                              # 반경 15m < 정거장 폭 20m
    with pytest.raises(ValueError, match="곡선반경"):
        tight.validate()
    arc_cfg(60.0).validate()                                           # 반경 > 폭이면 통과


# ===================================================== 부재 형상: 체적 / 간섭 / 배치
def test_curve_factor_is_symmetric_and_matches_geometry():
    eng = StationCADEngine(curved_cfg(columns=NO_COLS()))
    walls = {w.name: w for w in eng.walls.wall_packages[0].walls}
    left, right = walls["WALL_B3F_L"].shape.curve_factor, walls["WALL_B3F_R"].shape.curve_factor
    assert left > 1.0 > right and left + right == pytest.approx(2.0, abs=1e-9)        # 곡선 바깥쪽은 길고 안쪽은 짧다 (t 대칭)
    assert walls["WALL_B3F_START"].shape.curve_factor == pytest.approx(1.0, abs=2e-3)   # 중심에 걸친 부재는 거의 1
    assert eng.slabs.slab_packages[0].slabs[0].shape.curve_factor == pytest.approx(1.0, abs=2e-3)


def test_mesh_volume_matches_formula_for_all_members():
    eng = StationCADEngine(curved_cfg())
    for m in members(eng):
        mv = PM.mesh_volume(PM.sweep_quads(PM.rings(eng.cfg, m)))
        assert mv == pytest.approx(m.shape.volume, rel=1e-4), m.name


@pytest.mark.parametrize("radius,left,heading,origin", [
    (22, True, 0, (0, 0)), (30, False, 123, (300, -80)), (45, True, 250, (0, 0)), (60, False, 37, (-500, 90)),
    (150, True, 310, (300, -80)), (400, False, 200, (0, 0))])
def test_sweeps_are_closed_and_outward_for_any_radius(radius, left, heading, origin):
    """급곡선(정거장이 한 바퀴 이상 도는 경우 포함)에서도 면 방향이 안쪽으로 뒤집히지 않음"""
    cfg = arc_cfg(radius, left, heading=heading, origin=origin)
    eng = StationCADEngine(cfg)
    for m in members(eng):
        assert PM.mesh_volume(PM.sweep_quads(PM.rings(cfg, m))) == pytest.approx(m.shape.volume, rel=2e-3), m.name


def test_to_world_offsets_follow_the_circle():
    cfg = arc_cfg(400.0)                                               # 좌회전 → 곡률 중심은 선형 왼쪽 400m
    cx, cy = 0.0, 400.0
    for s in (10.0, 80.0, 190.0):
        for t in (-9.0, 0.0, 9.0):
            x, y = cfg.to_world(s, t)
            assert math.hypot(x - cx, y - cy) == pytest.approx(400.0 - t, abs=1e-9)    # 왼쪽(+t)은 안쪽 = 반경이 작음


def test_curved_model_has_no_interference():
    eng = StationCADEngine(curved_cfg())
    cfg, parts = eng.cfg, []
    for m in members(eng):
        s0, s1 = PM.s_range(m); t0, t1 = PM.t_range(m); v = m.shape.vertical
        parts.append((m.name, s0, s1, t0, t1, lambda s, m=m, v=v: (PM.z_at(cfg, m, s), PM.z_at(cfg, m, s) + v)))
    for pk in eng.columns.column_packages:
        for c in pk.columns:
            hs, ht = c.shape.half_s, c.shape.half_t
            zr = (c.pos_z, c.pos_z + c.shape.height)
            parts.append((c.name, c.pos_x - hs, c.pos_x + hs, c.pos_y - ht, c.pos_y + ht, lambda s, zr=zr: zr))
    tol, bad = 0.02, []
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            ds, dt = min(a[2], b[2]) - max(a[1], b[1]), min(a[4], b[4]) - max(a[3], b[3])
            if ds <= tol or dt <= tol:
                continue
            sm = (max(a[1], b[1]) + min(a[2], b[2])) / 2
            (alo, ahi), (blo, bhi) = a[5](sm), b[5](sm)
            if min(ahi, bhi) - max(alo, blo) > tol:
                bad.append((a[0], b[0]))
    assert bad == []


# ===================================================== 3D DXF / IFC
def test_straight_members_stay_single_prisms_and_curved_are_sweeps(tmp_path):
    straight = StationCADEngine(make_cfg()).generate_3d_dxf(tmp_path / "s.dxf")
    curved = StationCADEngine(curved_cfg(columns=NO_COLS())).generate_3d_dxf(tmp_path / "c.dxf")
    wall_faces = lambda p: len(ezdxf.readfile(p).modelspace().query('3DFACE[layer=="STRUCT_WALL"]'))
    assert wall_faces(straight) == 3 * 4 * 6                            # 직선: 부재당 6면 (변화 없음)
    assert wall_faces(curved) > 3 * 4 * 6 * 5                           # 곡선: 표본 구간마다 4면 + 마개


def test_curved_dxf_wall_vertices_are_exactly_on_offset_curves(tmp_path):
    cfg = curved_cfg(columns=NO_COLS()); eng = StationCADEngine(cfg)
    wall = next(w for pk in eng.walls.wall_packages for w in pk.walls if w.name == "WALL_B3F_L")
    for ring in PM.rings(cfg, wall)[2:-2]:                              # 표본 측점마다 외곽선 위의 점
        (xa, ya, _), (xb, yb, _) = ring[0], ring[1]
        assert math.hypot(xa - xb, ya - yb) == pytest.approx(wall.shape.width, abs=1e-9)    # 두께가 그대로 유지됨


def test_curved_ifc_representation_volume_and_placement(tmp_path):
    cfg = curved_cfg(); eng = StationCADEngine(cfg)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "c.ifc"))
    kinds = {}
    for el in f.by_type("IfcElement"):
        kinds.setdefault((el.is_a(), el.Representation.Representations[0].RepresentationType), 0)
        kinds[(el.is_a(), el.Representation.Representations[0].RepresentationType)] += 1
    assert kinds == {("IfcColumn", "SweptSolid"): 85, ("IfcSlab", "Tessellation"): 6, ("IfcWall", "Tessellation"): 16}
    assert all(fs.Closed for fs in f.by_type("IfcPolygonalFaceSet"))

    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    model = {m.name: m for m in members(eng)}
    for el in f.by_type("IfcElement"):
        if el.Name in model:
            vol = ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)
            assert vol > 0 and vol == pytest.approx(model[el.Name].shape.volume, rel=1e-4), el.Name

    cols = {c.name: c for pk in eng.columns.column_packages for c in pk.columns}
    angles = []
    for el in f.by_type("IfcColumn"):                                   # 기둥: 선형 위 위치 + 그 측점의 진행방향으로 회전
        c, ax = cols[el.Name], el.ObjectPlacement.RelativePlacement
        x, y, _ = ax.Location.Coordinates
        assert (x, y) == pytest.approx(cfg.to_world(c.pos_x, c.pos_y), abs=1e-9)
        d = ax.RefDirection.DirectionRatios
        assert math.atan2(d[1], d[0]) == pytest.approx(cfg.theta_at(c.pos_x), abs=1e-9)
        angles.append(cfg.theta_at(c.pos_x))
    assert max(angles) - min(angles) > math.radians(20)                 # 완화곡선+원곡선을 지나므로 기둥 방향이 실제로 달라짐


def test_straight_ifc_keeps_extruded_solids(tmp_path):
    f = ifcopenshell.open(StationCADEngine(make_cfg()).generate_ifc(tmp_path / "s.ifc"))
    assert {el.Representation.Representations[0].RepresentationType for el in f.by_type("IfcWall")} == {"SweptSolid"}


def test_curved_model_all_outputs_and_ifc_storeys(tmp_path):
    cfg = curved_cfg()
    paths = BIMEngine.build(cfg, tmp_path)
    assert len(paths) == 5 and all(os.path.exists(p) for p in paths)
    f = ifcopenshell.open(paths[-1])
    per = {}
    for rel in f.by_type("IfcRelContainedInSpatialStructure"):
        n = len([e for e in rel.RelatedElements if e.is_a("IfcColumn")])
        per[rel.RelatingStructure.Name] = per.get(rel.RelatingStructure.Name, 0) + n
    assert per == {"B3F": 20, "B2F": 40, "B1F": 25}


# ===================================================== 2D 도면
def test_section_on_curve_follows_vertical_profile(tmp_path):
    cfg = curved_cfg(columns=NO_COLS())
    sta = 100.0
    path = StationCADEngine(cfg).generate_section_dxf([sta], tmp_path / "s.dxf")
    slab = next(pl for pl in _q(path, "SEC_PLATFORM") if abs((_bbox(pl)[3] - _bbox(pl)[2]) - cfg.platform.plat_thick) < 1e-6)
    assert _bbox(slab)[2] == pytest.approx(cfg.lv(sta) - cfg.station.offset + cfg.platform.plat_height)
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert any(f"SLOPE {cfg.grade_permil(sta):.2f}‰" in t for t in texts)               # 종곡선 위에서 구배가 측점마다 다름
    assert round(cfg.grade_permil(25.0), 1) != round(cfg.grade_permil(170.0), 1)


def test_profile_polygons_follow_vertical_curve(tmp_path):
    cfg = curved_cfg(columns=NO_COLS())
    path = StationCADEngine(cfg).generate_profile_dxf(tmp_path / "p.dxf")
    floor = min((pl for pl in _q(path, "PROF_CONCRETE") if len(pl.get_points()) > 20),
                key=lambda pl: sum(p[1] for p in pl.get_points()) / len(pl.get_points()))   # 가장 아래의 다각형 = 바닥 슬래브
    pts = [(p[0], p[1]) for p in floor.get_points()]
    assert len(pts) > 20
    for s, z in pts[:len(pts) // 2]:                                                    # 하단 변: 선형 표고 - offset - 바닥 슬래브 두께
        assert z == pytest.approx(cfg.lv(s) - cfg.station.offset - cfg.station.floor_t, abs=1e-9)
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert any("GRADE AT START" in t for t in texts)


def test_plan_is_wcs_for_curved_and_developed_for_straight(tmp_path):
    cfg = curved_cfg(columns=NO_COLS()); eng = StationCADEngine(cfg)
    world = eng.generate_plan_dxf(tmp_path / "w.dxf")                                   # auto → WCS
    doc = ezdxf.readfile(world)
    assert any("[WCS]" in t.dxf.text for t in doc.modelspace().query("TEXT"))
    outer = max(_q(world, "PLAN_OUTLINE"), key=lambda pl: _bbox(pl)[1] - _bbox(pl)[0])
    pts = [(p[0], p[1]) for p in outer.get_points()]
    assert len(pts) > 30 and pts[0] == pytest.approx(cfg.to_world(0.0, -cfg.station.width / 2), abs=1e-6)
    # 측점선은 선형에 직교: 양 끝이 to_world(s, ±(W/2+2))
    ticks = [(tuple(l.dxf.start)[:2], tuple(l.dxf.end)[:2]) for l in doc.modelspace().query('LINE[layer=="PLAN_SECTION_LINE"]')]
    s_list = [i * cfg.station.sta_tick for i in range(len(ticks))]
    for (a, b), s in zip(ticks, s_list):
        assert a == pytest.approx(cfg.to_world(s, -cfg.station.width / 2 - 2), abs=1e-6)
        assert b == pytest.approx(cfg.to_world(s, cfg.station.width / 2 + 2), abs=1e-6)
    developed = ezdxf.readfile(eng.generate_plan_dxf(tmp_path / "d.dxf", mode="developed"))
    assert any("[DEVELOPED]" in t.dxf.text for t in developed.modelspace().query("TEXT"))
    dev_outer = max(_q(str(tmp_path / "d.dxf"), "PLAN_OUTLINE"), key=lambda pl: _bbox(pl)[1] - _bbox(pl)[0])
    assert _bbox(dev_outer)[:2] == pytest.approx((0.0, cfg.station.length)) and len(dev_outer.get_points()) == 4
    straight = StationCADEngine(make_cfg(NO_COLS())).generate_plan_dxf(tmp_path / "s.dxf")   # 직선 auto → 기존 전개 평면도
    assert not any("[" in t.dxf.text and "]" in t.dxf.text and "STATION PLAN" in t.dxf.text
                   for t in ezdxf.readfile(straight).modelspace().query("TEXT"))
    with pytest.raises(ValueError, match="mode"):
        eng.generate_plan_dxf(tmp_path / "x.dxf", mode="bogus")


# ===================================================== 선형 파일(JSON)
def test_sample_files_load_and_match_direct_construction():
    a = load_alignment(SAMPLE)
    assert isinstance(a, CurvedAlignment) and a.start_station == 0 and a.end_station == pytest.approx(1000.0)
    b = s_curve()
    for sta in (0, 250, 330, 400, 520, 777, 999):
        assert a.point_at(sta) == pytest.approx(b.point_at(sta)) and a.elevation_at(sta) == pytest.approx(b.elevation_at(sta))
    e = load_alignment(SAMPLE_EL)
    assert e.start_station == 1000 and e.end_station == pytest.approx(1820.0)
    # 요소 나열: 직선 200 → 완화곡선 80 → 원곡선 160 → 완화곡선 80 → 직선 300, 총 방향 변화 = 2*80/(2*500) + 160/500
    assert e.azimuth_at(1820.0) - e.azimuth_at(1000.0) == pytest.approx(0.16 + 0.32)
    assert e.curvature_at(1280.0) == pytest.approx(1 / 500)             # 원곡선 구간
    assert "곡선" in describe(a)


def test_alignment_json_other_types_and_vertical_forms():
    s = alignment_from_dict({"type": "straight", "bp_station": 0, "bp_x": 0, "bp_y": 0, "bp_z": 10, "ep_x": 100, "ep_y": 0, "ep_z": 11})
    assert s.elevation_at(100) == pytest.approx(11)
    h = alignment_from_dict({"type": "heading", "bp_station": 5, "bp_x": 1, "bp_y": 2, "bp_z": 3, "heading_deg": 90, "grade_permil": 10, "length": 50})
    assert h.point_at(15) == pytest.approx((1, 12)) and h.end_station == 55
    base = {"type": "curve", "horizontal": {"start_station": 0, "x": 0, "y": 0, "heading_deg": 0, "elements": [{"type": "line", "length": 500}]}}
    a = alignment_from_dict({**base, "vertical": [[0, 100], [250, 102, 100], [500, 99]]})
    b = alignment_from_dict({**base, "vertical": [{"station": 0, "elevation": 100}, {"station": 250, "elevation": 102, "curve_length": 100},
                                                  {"station": 500, "elevation": 99}]})
    assert [a.elevation_at(x) for x in (0, 230, 250, 400)] == pytest.approx([b.elevation_at(x) for x in (0, 230, 250, 400)])


@pytest.mark.parametrize("data,msg", [
    ({}, "선형: 필요한 항목이 없습니다 → type"),
    ({"type": "spline"}, "straight / heading / curve"),
    ({"type": "straight", "bp_x": 0}, "필요한 항목이 없습니다 → bp_station"),
    ({"type": "straight", "bp_station": 0, "bp_x": "abc", "bp_y": 0, "bp_z": 0, "ep_x": 1, "ep_y": 1, "ep_z": 0}, "bp_x: 숫자가 아닙니다"),
    ({"type": "straight", "bp_station": 0, "bp_x": True, "bp_y": 0, "bp_z": 0, "ep_x": 1, "ep_y": 1, "ep_z": 0}, "bp_x: 숫자여야"),
    ({"type": "curve", "vertical": []}, "필요한 항목이 없습니다 → horizontal"),
    ({"type": "curve", "horizontal": {"start_station": 0}, "vertical": [[0, 1], [10, 2]]}, r"points\(교점 방식\) 또는 elements"),
    ({"type": "curve", "horizontal": {"start_station": 0, "points": [[0, 0], [1]], "radii": []}, "vertical": [[0, 1], [10, 2]]}, r"horizontal.points\[1\]"),
    ({"type": "curve", "horizontal": {"start_station": 0, "x": 0, "y": 0, "heading_deg": 0,
                                       "elements": [{"type": "arc", "length": 10, "radius": 100, "direction": "up"}]}, "vertical": [[0, 1], [10, 2]]}, "left 또는 right"),
    ({"type": "curve", "horizontal": {"start_station": 0, "x": 0, "y": 0, "heading_deg": 0,
                                       "elements": [{"type": "clothoid", "length": 10}]}, "vertical": [[0, 1], [10, 2]]}, "line / arc / spiral"),
    ({"type": "curve", "horizontal": {"start_station": 0, "x": 0, "y": 0, "heading_deg": 0, "elements": [{"type": "line", "length": 10}]},
      "vertical": [[0, 1], [5]]}, r"vertical\[1\]"),
    ({"type": "curve", "horizontal": {"start_station": 0, "x": 0, "y": 0, "heading_deg": 0, "elements": [{"type": "line", "length": 10}]},
      "vertical": [[20, 1], [30, 2]]}, "겹치지 않습니다"),
])
def test_alignment_json_errors_are_specific(data, msg):
    try:
        a = alignment_from_dict(data)
        a.validate()
    except ValueError as e:
        import re
        assert re.search(msg, str(e)), str(e)
    else:
        pytest.fail("오류가 나야 함")


def test_load_alignment_reports_file_problems(tmp_path):
    bad = tmp_path / "bad.json"; bad.write_text('{"type": "curve", ', encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.json: JSON 형식 오류 \(줄 1"):
        load_alignment(bad)
    with pytest.raises(ValueError, match="파일을 열 수 없습니다"):
        load_alignment(tmp_path / "nope.json")
    wrong = tmp_path / "wrong.json"; wrong.write_text('{"type": "heading"}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"wrong\.json: heading: 필요한 항목이 없습니다"):
        load_alignment(wrong)
    inf = alignment_from_dict({"type": "curve", "horizontal": {"start_station": 0, "x": 0, "y": 0, "heading_deg": 0, "elements": [
        {"type": "spiral", "length": 50, "radius_start": "inf", "radius_end": 300, "direction": "right"}]}, "vertical": [[0, 1], [50, 2]]})
    assert inf.curvature_at(50.0) == pytest.approx(-1 / 300)             # 우회전 = 음의 곡률, radius "inf" = 직선 쪽 끝


# ===================================================== 직선 출력 보호 (곡선 대응 작업이 직선 결과를 바꾸지 않았는지)
def _snapshot(cfg, tmp_path):
    eng = StationCADEngine(cfg)
    dxf = ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "3d.dxf"))
    faces = sorted((e.dxf.layer, tuple(tuple(round(c, 4) for c in v) for v in (e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx2, e.dxf.vtx3)))
                   for e in dxf.modelspace().query("3DFACE"))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "m.ifc"))
    places = {el.Name: [round(c, 4) for c in el.ObjectPlacement.RelativePlacement.Location.Coordinates] +
                       [round(c, 4) for c in el.ObjectPlacement.RelativePlacement.RefDirection.DirectionRatios]
              for el in f.by_type("IfcElement")}
    storeys = {s.Name: round(s.Elevation, 4) for s in f.by_type("IfcBuildingStorey")}
    texts = sorted(t.dxf.text for t in ezdxf.readfile(eng.generate_section_dxf([25.0, 100.0], tmp_path / "s.dxf")).modelspace().query("TEXT"))
    return hashlib.sha256(json.dumps([faces, places, storeys, texts], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


GOLDEN_STRAIGHT = "cab82da2c62de9c2e8ab17fb814e998c4c04bd5c07cc0f8b0ffe719522c62fc0"


def test_straight_alignment_output_is_unchanged(tmp_path):
    """직선 선형(사용자 예시 배치)의 3D 면 4,140개 · IFC 배치 · 층 표고 · 도면 라벨이 한 점도 달라지지 않음"""
    assert _snapshot(make_cfg(user_example()), tmp_path) == GOLDEN_STRAIGHT
