"""슬래브 오프닝 (직사각형: 계단 / 에스컬레이터 / 엘리베이터 / 환기·설비) 테스트"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.shape
import pytest

from engine.cad_engine import StationCADEngine
from helper import prism_member as PM
from openings.decompose import overlap_area, subtract_intervals, subtract_rects
from openings.opening_kind import OpeningKind
from openings.opening_spec import OpeningSpec
from test_curved import NO_COLS, curved_cfg
from test_patch import _q, make_cfg, user_example


def op(kind=OpeningKind.ESCALATOR, s=20.0, length=12.0, t=6.0, width=3.0, slabs=(1,), name=""):
    return OpeningSpec(kind, s, length, t, width, list(slabs), name)


def cfg_with(*ops, curved=False):
    cfg = curved_cfg() if curved else make_cfg(user_example())
    cfg.openings = list(ops)
    return cfg


def slab_by_no(eng, n):
    return next(s for pk in eng.slabs.slab_packages for s in pk.slabs if s.slab_no == n)


# ===================================================== 분해 (순수 기하)
def area(r):
    return (r[1] - r[0]) * (r[3] - r[2])


def check_partition(region, holes, pieces):
    assert sum(map(area, pieces)) == pytest.approx(area(region) - sum(area(h) for h in holes))
    for i, a in enumerate(pieces):
        assert region[0] - 1e-9 <= a[0] < a[1] <= region[1] + 1e-9 and region[2] - 1e-9 <= a[2] < a[3] <= region[3] + 1e-9
        assert all(overlap_area(a, h) < 1e-9 for h in holes)
        assert all(overlap_area(a, b) < 1e-9 for b in pieces[i + 1:])


REGION = (0.0, 100.0, -9.0, 9.0)


@pytest.mark.parametrize("holes", [
    [],
    [(10, 20, 2, 5)],                                   # 안쪽 구멍 → 4조각
    [(0, 10, -9, 9)],                                   # 폭 전체를 가르는 구멍 (한쪽 끝)
    [(40, 50, -9, 0)],                                  # 한쪽 가장자리에 붙은 구멍
    [(10, 20, 2, 5), (30, 40, -5, 0), (35, 60, 3, 9)],  # 서로 다른 위치 여러 개
    [(10, 20, 2, 5), (20, 30, 2, 5)],                   # 맞닿은 구멍
    [(10, 20, 2, 5), (10, 20, -5, -2)],                 # 같은 s 구간에 두 개
])
def test_subtract_rects_is_exact_partition(holes):
    check_partition(REGION, holes, subtract_rects(REGION, holes))


def test_subtract_rects_piece_counts():
    assert subtract_rects(REGION, []) == [REGION]
    assert len(subtract_rects(REGION, [(10, 20, 2, 5)])) == 4              # 앞, 뒤, 구멍 옆 좌/우
    assert len(subtract_rects(REGION, [(0, 10, -9, 9)])) == 1              # 한 덩어리가 통째로 남음
    assert len(subtract_rects(REGION, [(0, 100, -9, 9)])) == 0


def test_subtract_intervals():
    assert subtract_intervals(0, 10, []) == [(0, 10)]
    assert subtract_intervals(0, 10, [(2, 3), (5, 7)]) == [(0, 2), (3, 5), (7, 10)]
    assert subtract_intervals(0, 10, [(-1, 4), (3, 12)]) == []


# ===================================================== 검증
@pytest.mark.parametrize("o,msg", [
    (op(length=0.0), "0보다"),
    (op(width=-1.0), "0보다"),
    (op(slabs=()), "하나 이상"),
    (op(slabs=(1, 1)), "중복"),
    (op(slabs=(4,)), "범위"),
    (op(slabs=(-1,)), "범위"),
    (op(s=-0.5), "내공 길이"),
    (op(s=190.0, length=10.0), "내공 길이"),
    (op(t=8.0, width=4.0), "내공 폭"),
    (op(t=-8.0, width=4.0), "내공 폭"),
])
def test_invalid_opening_rejected(o, msg):
    with pytest.raises(ValueError, match=msg):
        StationCADEngine(cfg_with(o))


def test_overlapping_openings_rejected_only_on_shared_slab():
    with pytest.raises(ValueError, match="겹칩니다"):
        StationCADEngine(cfg_with(op(s=20), op(OpeningKind.STAIR, s=25, t=7.0)))
    StationCADEngine(cfg_with(op(s=20, slabs=(1,)), op(OpeningKind.STAIR, s=25, t=7.0, slabs=(2,))))   # 슬래브가 달라 허용
    StationCADEngine(cfg_with(op(s=20), op(OpeningKind.STAIR, s=32.0, t=6.0)))                       # 맞닿음만 허용


def test_duplicate_names_rejected():
    with pytest.raises(ValueError, match="중복"):
        StationCADEngine(cfg_with(op(name="X"), op(OpeningKind.STAIR, s=60, slabs=(2,), name="X")))


def test_opening_on_columns_rejected_with_floor_name():
    with pytest.raises(ValueError, match="B3F 기둥"):                        # 1층 기둥 t=0, s=11 ±0.2
        StationCADEngine(cfg_with(op(s=5.0, length=10.0, t=0.0, width=2.0, slabs=(1,))))
    with pytest.raises(ValueError, match="B2F 기둥"):                        # 2층 원기둥 t=±3, φ1.0, s=1, 11, ...
        StationCADEngine(cfg_with(op(s=9.0, length=4.0, t=3.0, width=1.0, slabs=(1,))))
    # 같은 위치라도 기둥이 없는 슬래브 번호면 통과: 천장(3)은 3층 기둥만 만남
    StationCADEngine(cfg_with(op(s=9.0, length=4.0, t=3.0, width=1.0, slabs=(3,))))


def test_column_touching_edge_is_allowed():
    # 1층 기둥 s=11 ±0.2 (t ±0.5): 오프닝이 기둥 옆면에 딱 붙으면 통과
    StationCADEngine(cfg_with(op(s=11.2, length=5.0, t=0.0, width=1.0, slabs=(1,))))


# ===================================================== BIM 객체
def test_no_openings_keeps_single_member():
    eng = StationCADEngine(make_cfg(user_example()))
    for pk in eng.slabs.slab_packages:
        for s in pk.slabs:
            assert s.pieces == [] and s.openings == [] and s.members == [s]
            assert s.net_volume == pytest.approx(s.shape.volume)


def test_opening_creates_pieces_and_objects():
    eng = StationCADEngine(cfg_with(op(slabs=(1, 2))))
    s1, s2, s0 = slab_by_no(eng, 1), slab_by_no(eng, 2), slab_by_no(eng, 0)
    assert s0.openings == [] and s0.pieces == []
    assert len(s1.openings) == 1 and len(s2.openings) == 1 and len(s1.pieces) == 4
    o = s1.openings[0]
    assert o.name == "OPEN_ESC1_SLAB_B2F_MID" and o.kind is OpeningKind.ESCALATOR and o.slab_name == s1.name
    cfg = eng.cfg
    assert o.shape.thickness == s1.shape.thickness
    for sta in (20.0, 26.0, 32.0):                                      # 슬래브와 같은 두께, 같은 (구배를 따르는) 높이
        assert PM.z_at(cfg, o, sta) == pytest.approx(PM.z_at(cfg, s1, sta))
    assert o.s_range == (20.0, 32.0) and o.t_range == (4.5, 7.5)


def test_auto_names_per_kind_and_custom_names():
    eng = StationCADEngine(cfg_with(op(), op(OpeningKind.STAIR, s=50), op(OpeningKind.STAIR, s=80, name="S-A"),
                                    op(OpeningKind.ESCALATOR, s=110)))
    names = [o.name.split("_")[1] for o in slab_by_no(eng, 1).openings]
    assert names == ["ESC1", "STAIR1", "S-A", "ESC2"]


def test_pieces_cover_slab_minus_holes_straight():
    eng = StationCADEngine(cfg_with(op(slabs=(1,)), op(OpeningKind.ELEVATOR, s=60, length=3, t=-5, width=3, slabs=(1,))))
    sl = slab_by_no(eng, 1)
    gross = sl.shape.volume
    holes = sum(o.shape.volume for o in sl.openings)
    assert holes == pytest.approx(12 * 3 * sl.shape.thickness + 3 * 3 * sl.shape.thickness)
    assert sl.net_volume == pytest.approx(gross - holes)
    # 슬래브 번호가 다른 슬래브는 그대로
    assert slab_by_no(eng, 2).net_volume == pytest.approx(slab_by_no(eng, 2).shape.volume)


def test_net_volume_on_curved_alignment_with_slope():
    cfg = cfg_with(op(s=30, length=15, t=6.0, width=3.0, slabs=(1, 3)),
                   op(OpeningKind.VENT, s=100, length=6, t=-5.0, width=2.0, slabs=(1,)), curved=True)
    cfg.column = NO_COLS()
    eng = StationCADEngine(cfg)
    for n in (1, 3):
        sl = slab_by_no(eng, n)
        assert sl.net_volume == pytest.approx(sl.shape.volume - sum(o.shape.volume for o in sl.openings), rel=1e-12)
        # 조각의 곡선 체적 보정이 정확하다: 3D 메쉬 체적과 일치
        for m in sl.pieces:                                              # 조각마다 3D 메쉬 체적 = 모델 체적 (기존 부재와 같은 허용오차)
            assert PM.mesh_volume(PM.sweep_quads(PM.rings(cfg, m))) == pytest.approx(m.shape.volume, rel=1e-4)
        mesh = sum(PM.mesh_volume(PM.sweep_quads(PM.rings(cfg, m))) for m in sl.pieces)
        assert mesh == pytest.approx(sl.net_volume, rel=1e-4)
        assert sl.net_volume < sl.shape.volume


def test_package_volume_uses_net():
    eng = StationCADEngine(cfg_with(op(slabs=(1,))))
    pk = next(p for p in eng.slabs.slab_packages if p.level == "B2F")
    sl = slab_by_no(eng, 1)
    assert pk.total_volume == pytest.approx(sum(s.net_volume for s in pk.slabs))
    assert sl.net_volume < sl.shape.volume


# ===================================================== 출력
def test_3d_dxf_face_count_and_nothing_over_hole(tmp_path):
    cfg = cfg_with(op(slabs=(1,)))
    eng = StationCADEngine(cfg)
    path = eng.generate_3d_dxf(tmp_path / "m.dxf")
    base = StationCADEngine(make_cfg(user_example())).generate_3d_dxf(tmp_path / "b.dxf")
    faces = lambda p: list(ezdxf.readfile(p).modelspace().query('3DFACE[layer=="STRUCT_SLAB"]'))
    assert len(faces(path)) == len(faces(base)) - 6 + 4 * 6              # 슬래브 1개(6면) 대신 조각 4개(각 6면)
    sl = slab_by_no(eng, 1)
    s_lo, s_hi = sl.openings[0].s_range
    t_lo, t_hi = sl.openings[0].t_range
    eps, th = 1e-6, sl.shape.thickness
    x0, y0 = cfg.origin(); a = cfg.theta_at(0.0)                         # 직선 선형: WCS → 정거장 로컬 (s, t) 역변환
    checked = 0
    for f in faces(path):                                                # 오프닝 직사각형 안쪽에는 이 슬래브 두께 범위의 꼭짓점이 없다
        for k in range(4):
            x, y, z = f.dxf.get(f"vtx{k}")
            s = (x - x0) * math.cos(a) + (y - y0) * math.sin(a)
            t = -(x - x0) * math.sin(a) + (y - y0) * math.cos(a)
            if -eps <= z - PM.z_at(cfg, sl, s) <= th + eps and -eps <= s <= cfg.station.length + eps:
                checked += 1
                assert not (s_lo + eps < s < s_hi - eps and t_lo + eps < t < t_hi - eps)
    assert checked >= 4 * 8                                              # 이 슬래브 조각 4개(각 8 꼭짓점)를 실제로 검사함

    top_area = 0.0                                                       # 상면 면들의 평면 면적 합 = 전체 면적 - 오프닝 면적
    for f in faces(path):
        loc = []
        for k in range(4):
            x, y, z = f.dxf.get(f"vtx{k}")
            s = (x - x0) * math.cos(a) + (y - y0) * math.sin(a)
            t = -(x - x0) * math.sin(a) + (y - y0) * math.cos(a)
            loc.append((s, t, z - PM.z_at(cfg, sl, s)))
        if all(abs(c[2] - th) < 1e-6 for c in loc) and len({round(c[0], 6) for c in loc} | {round(c[1], 6) for c in loc}) >= 3:
            top_area += abs(0.5 * sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(loc, loc[1:] + loc[:1])))
    assert top_area == pytest.approx(sl.shape.length * sl.shape.width - (s_hi - s_lo) * (t_hi - t_lo))


def test_section_dxf_has_gap_at_opening(tmp_path):
    cfg = cfg_with(op(slabs=(1,)))
    eng = StationCADEngine(cfg)
    base_eng = StationCADEngine(make_cfg(user_example()))
    sl = slab_by_no(eng, 1)

    def mid_pieces(engine, sta, name):
        items = _q(engine.generate_section_dxf([sta], tmp_path / name), "SEC_CONCRETE")
        zb = PM.z_at(cfg, sl, sta)
        return items, [p for p in items if abs(min(q[1] for q in p.get_points()) - zb) < 1e-6]

    width = lambda pl: max(q[0] for q in pl.get_points()) - min(q[0] for q in pl.get_points())
    all_in, mid_in = mid_pieces(eng, 26.0, "a.dxf")                      # s=26: 오프닝(s 20~32) 안
    all_out, mid_out = mid_pieces(eng, 40.0, "b.dxf")                    # s=40: 오프닝 밖
    base_all, _ = mid_pieces(base_eng, 26.0, "c.dxf")
    assert len(mid_in) == 2 and len(mid_out) == 1
    assert sum(width(p) for p in mid_in) == pytest.approx(cfg.station.width - 3.0)
    assert width(mid_out[0]) == pytest.approx(cfg.station.width)
    assert len(all_in) == len(base_all) + 1 and len(all_out) == len(base_all)
    spans = sorted((min(q[0] for q in p.get_points()), max(q[0] for q in p.get_points())) for p in mid_in)
    assert spans == [(pytest.approx(-9.0), pytest.approx(4.5)), (pytest.approx(7.5), pytest.approx(9.0))]


def test_section_label_drawn_once_per_mid_slab(tmp_path):
    cfg = cfg_with(op(slabs=(1, 2)))
    path = StationCADEngine(cfg).generate_section_dxf([26.0], tmp_path / "s.dxf")
    texts = [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    assert texts.count("B2F SLAB") == 1 and texts.count("B1F SLAB") == 1


def test_profile_dxf_gap_follows_slope(tmp_path):
    cfg = cfg_with(op(s=14.0, length=4.0, t=0.0, width=1.0, slabs=(1,)))   # 중심선(t=0) 위, 1층 기둥(s=11, 21)을 피함
    eng = StationCADEngine(cfg)
    sl = slab_by_no(eng, 1)
    base = _q(StationCADEngine(make_cfg(user_example())).generate_profile_dxf(tmp_path / "b.dxf"), "PROF_CONCRETE")
    got = _q(eng.generate_profile_dxf(tmp_path / "p.dxf"), "PROF_CONCRETE")
    assert len(got) == len(base) + 1
    mine = [p for p in got if abs(min(q[1] for q in p.get_points()) - PM.z_at(cfg, sl, min(q[0] for q in p.get_points()))) < 1e-6
            or abs(min(q[1] for q in p.get_points()) - PM.z_at(cfg, sl, max(q[0] for q in p.get_points()))) < 1e-6]
    spans = sorted((round(min(q[0] for q in p.get_points()), 6), round(max(q[0] for q in p.get_points()), 6)) for p in mine
                   if abs(max(q[1] for q in p.get_points()) - min(q[1] for q in p.get_points())) > 0.3)
    assert (0.0, 14.0) in spans and (18.0, 198.0) in spans               # 구멍 구간 14~18 이 비어 있음
    for p in got:                                                        # 모든 윤곽의 하단이 슬래브 구배선 위에 있음 (조각도 같은 구배)
        pts = p.get_points()
        if any(abs(q[0] - 14.0) < 1e-9 for q in pts) and any(abs(q[1] - PM.z_at(cfg, sl, 14.0)) < 1e-6 for q in pts):
            return
    raise AssertionError("구멍 시작 경계(s=14)에서 슬래브 하단 표고가 맞는 조각을 찾지 못함")


def test_centerline_clear_of_opening_keeps_profile_unchanged(tmp_path):
    cfg = cfg_with(op())                                                  # t 4.5~7.5 이라 중심선과 무관
    got = _q(StationCADEngine(cfg).generate_profile_dxf(tmp_path / "p.dxf"), "PROF_CONCRETE")
    base = _q(StationCADEngine(make_cfg(user_example())).generate_profile_dxf(tmp_path / "b.dxf"), "PROF_CONCRETE")
    assert len(got) == len(base)


# ===================================================== IFC
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("curved", [False, True])
def test_ifc_slab_is_single_element_with_openings_and_net_volume(tmp_path, curved):
    ops = [op(s=30, length=15, t=6.0, width=3.0, slabs=(1, 3)),
           op(OpeningKind.ELEVATOR, s=100, length=3, t=-5.0, width=3.0, slabs=(1,))]
    cfg = cfg_with(*ops, curved=curved)
    if curved:
        cfg.column = NO_COLS()
    eng = StationCADEngine(cfg)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "o.ifc"))
    slabs = {s.Name: s for s in f.by_type("IfcSlab")}
    base = StationCADEngine(make_cfg(user_example()) if not curved else _curved_plain()).generate_ifc(tmp_path / "b.ifc")
    assert len(slabs) == len(ifcopenshell.open(base).by_type("IfcSlab"))      # 슬래브 개수는 변하지 않음 (1슬래브 = 1 IfcSlab)

    rep = "Tessellation" if curved else "SweptSolid"
    sl1 = slab_by_no(eng, 1)
    ifc1 = slabs[sl1.name]
    assert len(ifc1.Representation.Representations[0].Items) == len(sl1.pieces) > 1
    assert ifc1.Representation.Representations[0].RepresentationType == rep
    assert ifc_world_volume(ifc1) == pytest.approx(sl1.net_volume, rel=1e-4)
    assert sl1.net_volume < sl1.shape.volume

    # 오프닝: 슬래브마다 IfcOpeningElement + IfcRelVoidsElement (오프닝 1개가 슬래브 2개를 뚫으면 2개)
    voids = f.by_type("IfcRelVoidsElement")
    assert len(voids) == 3 and len(f.by_type("IfcOpeningElement")) == 3
    by_slab = {}
    for r in voids:
        by_slab.setdefault(r.RelatingBuildingElement.Name, []).append(r.RelatedOpeningElement)
    assert sorted(len(v) for v in by_slab.values()) == [1, 2]
    assert len(by_slab[sl1.name]) == 2
    assert {o.ObjectType for o in by_slab[sl1.name]} == {"ESC", "ELEV"}
    for sl in (sl1, slab_by_no(eng, 3)):
        for o in by_slab[sl.name]:
            m = next(x for x in sl.openings if x.name == o.Name)
            assert ifc_world_volume(o) == pytest.approx(m.shape.volume, rel=1e-4)
    # 오프닝 없는 슬래브는 기존 표현 그대로
    plain = slabs[slab_by_no(eng, 0).name]
    assert len(plain.Representation.Representations[0].Items) == 1


def _curved_plain():
    c = curved_cfg(); c.column = NO_COLS(); return c


def test_ifc_pieces_do_not_overlap_each_other(tmp_path):
    """조각 체적의 합 = 합쳐진 형상 체적: 조각끼리 겹치거나 구멍을 덮는 부분이 없다 (직선, 구배 있음)"""
    cfg = cfg_with(op(s=30, length=15, t=6.0, width=3.0, slabs=(1,)), op(OpeningKind.VENT, s=34, length=3, t=-3.0, width=2.0, slabs=(1,)))
    eng = StationCADEngine(cfg)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    sl = slab_by_no(eng, 1)
    el = next(s for s in f.by_type("IfcSlab") if s.Name == sl.name)
    items = el.Representation.Representations[0].Items
    assert all(i.is_a("IfcExtrudedAreaSolid") for i in items)
    each = sum(abs(_poly_area(i.SweptArea.OuterCurve)) * i.Depth for i in items)       # 조각 압출 체적의 합 (단면적 x 압출 깊이)
    assert each == pytest.approx(sl.net_volume, rel=1e-9)
    assert ifc_world_volume(el) == pytest.approx(each, rel=1e-6)                       # 형상 엔진이 계산한 체적 = 합 → 조각이 겹치지 않음


def _poly_area(curve):
    pts = [p.Coordinates for p in curve.Points]
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:]))


def test_build_all_outputs_with_openings(tmp_path):
    from engine.bim_engine import BIMEngine
    cfg = cfg_with(op(slabs=(1, 2)), op(OpeningKind.STAIR, s=60, length=8, t=-6.0, width=3.0, slabs=(0, 1, 2, 3), name="ST-1"))
    paths = BIMEngine.build(cfg, tmp_path)
    assert len(paths) == 5 and all(os.path.getsize(p) > 0 for p in paths)


# ===================================================== 입력 초안 (화면 비의존)
from gui.opening_draft import OpeningDraft, OpeningDrafts, slab_choice_label


def test_draft_converts_sta_to_local_s_and_kind_labels():
    d = OpeningDrafts()
    d.items = [OpeningDraft("계단", "ST1", "154.45", "8", "-6", "3", {0, 1}),
               OpeningDraft("환기·설비", "", "200", "2", "5", "2", {3})]
    a, b = d.to_specs(3, 134.45)
    assert (a.kind, a.name, a.slabs) == (OpeningKind.STAIR, "ST1", [0, 1])
    assert a.s_start == pytest.approx(20.0) and a.s_end == pytest.approx(28.0) and (a.t_lo, a.t_hi) == (-7.5, -4.5)
    assert b.kind is OpeningKind.VENT and b.s_start == pytest.approx(65.55) and b.slabs == [3]


@pytest.mark.parametrize("field,value,msg", [
    ("sta_start", "x", r"오프닝 1\(계단\): 시작 측점"),
    ("length", "0", "길이은\\(는\\) 0보다"),
    ("width", "-2", "폭은\\(는\\) 0보다"),
    ("t_center", "", "t 위치"),
    ("kind", "수영장", "용도가 올바르지"),
])
def test_draft_errors_name_the_opening(field, value, msg):
    d = OpeningDrafts(); d.items = [OpeningDraft()]
    setattr(d.items[0], field, value)
    with pytest.raises(ValueError, match=msg):
        d.to_specs(3, 0.0)


def test_draft_drops_slab_numbers_beyond_floor_count():
    d = OpeningDrafts(); d.items = [OpeningDraft(slabs={1, 3})]
    assert d.ensure_floors(2) is True and d.items[0].slabs == {1}
    assert d.ensure_floors(2) is False
    d.items[0].slabs = {1, 3}
    assert d.to_specs(2, 0.0)[0].slabs == [1]


def test_slab_choice_labels():
    assert [slab_choice_label(3, n) for n in range(4)] == ["본체 바닥", "B3F/B2F 중간", "B2F/B1F 중간", "본체 천장"]
    assert [slab_choice_label(1, n) for n in range(2)] == ["본체 바닥", "본체 천장"]
