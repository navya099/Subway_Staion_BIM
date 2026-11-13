"""출구통로 (경로 폴리선: 선형 상대 / 절대 좌표, 임의 각도 연귀 꺾임, 꼭짓점 높이, 헌치, 본체 측벽 오프닝) 테스트"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import pytest

from engine.cad_engine import StationCADEngine
from helper import prism_member as PM
from openings.opening_kind import OpeningKind
from passages.passage_spec import PassageSpec, PathVertex, station_path, world_path
from passages.passage_type import PassagePartKind as K
from test_curved import NO_COLS, curved_cfg
from test_patch import _q, make_cfg, user_example
from walls.wall_shape_type import WallRole

TF = 10.0                                   # 기본 예제 외벽 바깥면 |t| (내공 18/2 + 벽 1.0)
D45 = 10 / math.sqrt(2)


def straight(s=50.0, side=1, length=15.0):
    return station_path([(s, side * TF, None), (s, side * (TF + length), 0)])


def ell(s=120.0):
    """오른쪽(−t)으로 5m 수평 → 5m 동안 0.3m 오름 → 3m 수평 → 직각으로 꺾어 시점 방향 20m 수평"""
    return station_path([(s, -TF, None), (s, -TF - 5, 0), (s, -TF - 10, 0.3), (s, -TF - 13, 0.3), (s - 20, -TF - 13, 0.3)])


def zigzag(s=160.0):
    """왼쪽으로 8m → 45° 꺾어 10m → 다시 45° 꺾어 선형과 나란히 10m"""
    return station_path([(s, TF, None), (s, TF + 8, 0), (s + D45, TF + 8 + D45, 0), (s + D45 + 10, TF + 8 + D45, 0)])


def ps(path=None, floor=3, name="", **kw):
    return PassageSpec(floor=floor, path=path if path is not None else straight(), name=name, **kw)


def cfg_with(*passages, curved=False, columns=None):
    cfg = curved_cfg(columns=NO_COLS()) if curved else make_cfg(columns or user_example())
    cfg.passages = list(passages)
    return cfg


def eng_with(*passages, **kw):
    return StationCADEngine(cfg_with(*passages, **kw))


def by_name(eng, name):
    return next(p for p in eng.passages.all_passages() if p.name == name)


def wall(eng, level, role):
    return next(w for pk in eng.walls.wall_packages if pk.level == level for w in pk.walls if w.role == role)


def plan_len(p):
    return sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(p.vertices, p.vertices[1:]))


# ===================================================== 역변환 (to_station)
@pytest.mark.parametrize("curved", [False, True])
def test_to_station_inverts_to_world(curved):
    cfg = cfg_with(curved=curved)
    for s in (0.0, 37.5, 120.0, 198.0, 230.0):
        for t in (-30.0, -10.6, 0.0, 12.0, 40.0):
            assert cfg.to_station(*cfg.to_world(s, t)) == pytest.approx((s, t), abs=1e-9)


# ===================================================== 경로 해석
def test_station_and_world_vertices_give_the_same_passage():
    cfg = cfg_with()
    st = cfg.station
    w = [cfg.to_world(s, t) for s, t, _ in ((50.0, TF, None), (50.0, TF + 15, 0))]
    e0 = cfg.lv(50.0) - st.offset + st.floor_level(3)
    a = cfg_with(ps(straight(), name="A"), ps(world_path([(*w[0], None), (*w[1], e0)]), name="B")).passage_layouts()
    key = lambda p: (round(p.ox, 6), round(p.oy, 6), round(p.a1, 6), tuple(p.sect))
    pa, pb = (sorted(a[n].pieces(), key=key) for n in (0, 1))
    assert len(pa) == len(pb)
    for p, q in zip(pa, pb):
        assert (p.ox, p.oy, p.ux, p.uy, p.a1, p.z0, p.slope) == pytest.approx((q.ox, q.oy, q.ux, q.uy, q.a1, q.z0, q.slope))
        assert p.sect == q.sect
    # 꼭짓점마다 방식을 섞어도 됨
    mixed = cfg_with(ps([PathVertex("station", 50.0, TF, None), PathVertex("world", *w[1], e0)])).passage_layouts()[0]
    for v, (s0, t0) in zip(mixed.vertices, [(50.0, TF), (50.0, TF + 15)]):
        assert (v.s, v.t) == pytest.approx((s0, t0))


def test_vertex_heights_relative_and_absolute():
    cfg = cfg_with(ps(ell()))
    lay = cfg.passage_layouts()[0]
    st = cfg.station
    e0 = cfg.lv(120.0) - st.offset + st.floor_level(3)
    assert lay.z_floor == pytest.approx(e0)
    assert [v.z - e0 for v in lay.vertices] == pytest.approx([0.0, 0.0, 0.3, 0.3, 0.3])
    assert lay.side == -1 and lay.corners == [3]
    # 조각 기준 표고·구배: 경사 구간만 구배, 나머지 수평
    floor_pieces = [p for e in lay.elements if e.code.endswith("FLOOR") for p in e.pieces if len(p.sect) == 4]
    slopes = sorted(round(p.slope, 9) for p in floor_pieces)
    assert slopes == [0.0, 0.0, 0.0, pytest.approx(0.06)]


def test_runs_group_elements_between_corners():
    p = by_name(eng_with(ps(ell(), name="L")), "L")
    names = [e.name for e in p.elements]
    assert names == ["L_S1_FLOOR", "L_S1_ROOF", "L_S1_WALL_L", "L_S1_WALL_R",
                     "L_S2_FLOOR", "L_S2_ROOF", "L_S2_WALL_L", "L_S2_WALL_R"]
    assert len(p.element("S1_FLOOR").pieces) == 3                     # 일직선 꼭짓점(경사 변화점)에서 나뉜 조각 3개
    assert len(p.element("S2_FLOOR").pieces) == 1


# ===================================================== 형상 (체적 공식)
@pytest.mark.parametrize("path", [straight(), ell(), zigzag()])
def test_volumes_follow_centerline_length(path):
    """연귀 접합은 재료를 더하거나 빼지 않는다: 벽 = 2·벽두께·H·L, 바닥 = 외폭·두께·L, 천장 = 외폭·두께·L + 헌치 (L = 중심선 평면 길이)"""
    sp = ps(path, bottom_haunch_w=0.2, bottom_haunch_h=0.25)
    p = eng_with(sp).passages.all_passages()[0]
    L = plan_len(p)
    walls = sum(e.volume for e in p.elements if e.kind == K.WALL)
    floors = sum(e.volume for e in p.elements if e.kind == K.FLOOR)
    roofs = sum(e.volume for e in p.elements if e.kind == K.ROOF)
    assert walls == pytest.approx(2 * sp.wall_t * sp.inner_height * L)
    assert floors == pytest.approx(2 * sp.half_out * sp.floor_t * L + 2 * (0.2 * 0.25 / 2) * L)
    assert roofs == pytest.approx(2 * sp.half_out * sp.roof_t * L + 2 * (0.3 * 0.3 / 2) * L)


@pytest.mark.parametrize("path", [ell(), zigzag()])
def test_pieces_do_not_overlap(path):
    pieces = [q for e in eng_with(ps(path, bottom_haunch_w=0.2, bottom_haunch_h=0.2)).passages.all_passages()[0].elements
              for q in e.pieces]
    def box(sect):
        return min(v for v, _ in sect), max(v for v, _ in sect), min(d for _, d in sect), max(d for _, d in sect)

    for i, p in enumerate(pieces):
        for q in pieces[i + 1:]:
            if p.local["seg"] == q.local["seg"]:
                # 같은 구간: 기준 표고가 같으므로 단면 좌표(v, dz)에서 비교. 헌치 삼각형은 내공 모서리에 있어 사각 단면과 면적이 겹치지 않음
                if len(p.sect) == 4 and len(q.sect) == 4:
                    (pv0, pv1, pd0, pd1), (qv0, qv1, qd0, qd1) = box(p.sect), box(q.sect)
                    assert min(pv1, qv1) - max(pv0, qv0) < 1e-9 or min(pd1, qd1) - max(pd0, qd0) < 1e-9
    # 다른 구간끼리(경사 변화점의 직각 끝, 꺾임부 연귀)는 체적 공식 시험(벽 = 2·두께·H·L 정확히 일치)과
    # 연귀 맞닿음 시험(test_miter_joint_is_on_the_bisector)이 겹침·틈이 없음을 보장한다


def test_miter_joint_is_on_the_bisector():
    """꺾임부: 앞 구간 끝 단면과 뒤 구간 시작 단면이 같은 점에서 만남 (벽 바깥·안쪽 모서리 모두)"""
    lay = cfg_with(ps(zigzag())).passage_layouts()[0]
    walls = [p for e in lay.elements if e.code.endswith("WALL_L") for p in e.pieces]
    a, b = walls[0], walls[1]
    end_a = sorted(round(c, 9) for p in a.rings()[1] for c in p)
    start_b = sorted(round(c, 9) for p in b.rings()[0] for c in p)
    assert end_a == pytest.approx(start_b)


# ===================================================== 검증
@pytest.mark.parametrize("sp,msg", [
    (ps(floor=0), "범위"),
    (ps(path=station_path([(50, TF, None)])), "2개 이상"),
    (ps(path=[PathVertex("polar", 50, TF, None), PathVertex("station", 50, 20, 0)]), "형식"),
    (ps(inner_width=0.0), "내공 폭"),
    (ps(top_haunch_w=0.3, top_haunch_h=0.0), "헌치"),
    (ps(top_haunch_w=2.0), "헌치 폭"),
    (ps(inner_height=5.7), "내공 높이"),
    (ps(station_path([(50, TF + 0.5, None), (50, TF + 15, 0)])), "외벽 바깥면"),
    (ps(station_path([(50, TF, None), (52, TF + 15, 0)])), "직각"),
    (ps(station_path([(50, TF, None), (50, TF - 5, 0)])), "직각"),               # 본체 안쪽으로
    (ps(station_path([(50, TF, 0.2), (50, TF + 15, 0)])), "FL"),
    (ps(station_path([(50, TF, None), (50, TF + 15, None)])), "높이를 입력"),
    (ps(station_path([(50, TF, None), (50, TF + 8, 0), (50, TF + 8, 0), (60, TF + 8, 0)])), "같습니다"),
    (ps(station_path([(50, TF, None), (50, TF + 8, 0), (60, TF + 8, 0.5)])), "수평"),
    (ps(station_path([(50, TF, None), (50, TF + 8, 0), (50, TF + 10, 0.2), (60, TF + 10, 0.2)])), "수평"),
    (ps(station_path([(50, TF, None), (50, TF + 8, 0), (51, TF + 2, 0)])), "꺾임각"),
    (ps(station_path([(50, TF, None), (50, TF + 12, 0), (51, TF + 12, 0), (51, TF + 4, 0)])), "너무 짧"),   # 같은 쪽 두 번 꺾임
    (ps(station_path([(1.0, TF, None), (1.0, TF + 15, 0)])), "내공 길이"),
])
def test_invalid_passage_rejected(sp, msg):
    with pytest.raises(ValueError, match=msg):
        StationCADEngine(cfg_with(sp))


def test_world_vertex_off_wall_and_self_crossing_rejected():
    cfg = cfg_with()
    x, y = cfg.to_world(50.0, TF + 3)
    with pytest.raises(ValueError, match="외벽 바깥면"):
        StationCADEngine(cfg_with(ps(world_path([(x, y, None), (*cfg.to_world(50.0, TF + 15), 0.0)]))))
    loop = station_path([(50, TF, None), (50, TF + 20, 0), (60, TF + 20, 0), (60, TF + 10, 0), (45, TF + 10, 0)])
    with pytest.raises(ValueError, match="스스로 겹칩니다"):
        StationCADEngine(cfg_with(ps(loop)))


def test_thicker_lower_or_upper_wall_rejected():
    cfg = cfg_with(ps(straight(), floor=2))
    cfg.station.wall_ts = [1.2, 1.0, 1.0]
    with pytest.raises(ValueError, match="아래층"):
        StationCADEngine(cfg)
    cfg = cfg_with(ps(straight(), floor=2, inner_height=5.5, roof_t=0.8))      # 천장 상면 FL+6.3 > 위층 FL+6.0
    cfg.station.wall_ts = [1.0, 1.0, 1.2]
    with pytest.raises(ValueError, match="위층"):
        StationCADEngine(cfg)


def test_overlapping_passages_and_names_rejected():
    with pytest.raises(ValueError, match="겹칩니다"):
        StationCADEngine(cfg_with(ps(straight(50.0)), ps(straight(53.0))))
    StationCADEngine(cfg_with(ps(straight(50.0)), ps(straight(55.2))))           # 벽이 맞닿기만 하면 허용
    with pytest.raises(ValueError, match="이름이 중복"):
        StationCADEngine(cfg_with(ps(name="X"), ps(straight(120.0), name="X")))


# ===================================================== 본체 측벽 오프닝
def test_side_wall_opening_cut_into_pieces():
    base = StationCADEngine(make_cfg(user_example()))
    eng = eng_with(ps(straight(50.0)))
    w = wall(eng, "B1F", WallRole.RIGHT)
    assert PM.t_range(w)[0] > 0                                                      # 왼쪽(+t) = 벽 코드 R
    (o,) = w.openings
    assert o.kind is OpeningKind.PASSAGE and o.name == "OPEN_EX1_WALL_B1F_R"
    fl = eng.cfg.station.floor_level(3)
    assert o.s_range == pytest.approx((48.0, 52.0)) and o.t_range == pytest.approx((fl, fl + 3.0))
    assert len(w.pieces) == 3
    assert w.net_volume == pytest.approx(wall(base, "B1F", WallRole.RIGHT).shape.volume - 4.0 * 1.0 * 3.0)


def test_wall_section_shows_lintel_at_opening(tmp_path):
    eng = eng_with(ps(straight(50.0)))
    cfg = eng.cfg
    path = eng.generate_section_dxf([50.0], tmp_path / "s.dxf")
    base = StationCADEngine(make_cfg(user_example())).generate_section_dxf([50.0], tmp_path / "b.dxf")
    right = lambda pl: min(q[0] for q in pl.get_points()) > 9.0 - 1e-6 and max(q[0] for q in pl.get_points()) <= 10.0 + 1e-6
    walls = [pl for pl in _q(path, "SEC_CONCRETE") if right(pl)]
    assert len([pl for pl in _q(base, "SEC_CONCRETE") if right(pl)]) == 1 and len(walls) == 2
    zf = cfg.lv(50.0) + cfg.station.floor_level(3)
    assert sorted(max(q[1] for q in pl.get_points()) for pl in walls)[0] == pytest.approx(zf)


def test_floor1_passage_in_plan(tmp_path):
    cfg = cfg_with(ps(straight(50.0), floor=1, inner_height=2.5), columns=NO_COLS())
    cfg.platform.plat_thick = 0.0
    path = StationCADEngine(cfg).generate_plan_dxf(tmp_path / "p.dxf")
    assert any(abs(max(q[0] for q in pl.get_points()) - 48.0) < 1e-6 for pl in _q(path, "PLAN_OUTLINE"))
    assert len(_q(path, "PLAN_PASSAGE")) == 2
    assert "EX1 EXIT" in [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]
    # 곡선(WCS 평면도)에서도 다각형 그대로 옮겨 그림
    cc = cfg_with(ps(zigzag(), floor=1, inner_height=2.5), curved=True)
    cc.platform.plat_thick = 0.0
    assert len(_q(StationCADEngine(cc).generate_plan_dxf(tmp_path / "c.dxf"), "PLAN_PASSAGE")) == 6


# ===================================================== 체적 교차 검증 (공식 ↔ 3D 메쉬 ↔ IFC)
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("curved", [False, True])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, curved):
    eng = eng_with(ps(straight(), bottom_haunch_w=0.2, bottom_haunch_h=0.2, name="A"), ps(ell(), name="B"),
                   ps(zigzag(), name="C"), curved=curved)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    els = {e.Name: e for e in f.by_type("IfcSlab") + f.by_type("IfcWall")}
    for p in eng.passages.all_passages():
        for e in p.elements:
            assert sum(PM.mesh_volume(q.faces()) for q in e.pieces) == pytest.approx(e.volume, rel=1e-9)
            assert ifc_world_volume(els[e.name]) == pytest.approx(e.volume, rel=1e-6)
            rep = els[e.name].Representation.Representations[0].RepresentationType
            assert rep == ("Tessellation" if any(q.skewed for q in e.pieces) else "SweptSolid")
    assert els["A_S1_FLOOR"].Representation.Representations[0].RepresentationType == "SweptSolid"
    for w in [w for pk in eng.walls.wall_packages for w in pk.walls if w.openings]:
        assert ifc_world_volume(els[w.name]) == pytest.approx(w.net_volume, rel=1e-4)


def test_ifc_assembly_structure(tmp_path):
    eng = eng_with(ps(name="A"), ps(ell(), name="B"))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    asms = {a.Name: a for a in f.by_type("IfcElementAssembly")}
    assert set(asms) == {"A", "B"}
    for name in ("A", "B"):
        a = asms[name]
        assert a.PredefinedType == "USERDEFINED" and a.ObjectType == "EXIT_PASSAGE"
        assert ifcopenshell.util.element.get_container(a).Name == "B1F"
        parts = {p.Name: p for p in ifcopenshell.util.element.get_decomposition(a)}
        assert set(parts) == {e.name for e in by_name(eng, name).elements}
        assert parts[f"{name}_S1_FLOOR"].PredefinedType == "FLOOR" and parts[f"{name}_S1_ROOF"].PredefinedType == "ROOF"
        assert parts[f"{name}_S1_WALL_L"].is_a("IfcWall")
    voids = {r.RelatedOpeningElement.Name: r.RelatingBuildingElement.Name for r in f.by_type("IfcRelVoidsElement")}
    assert voids == {"OPEN_A_WALL_B1F_R": "WALL_B1F_R", "OPEN_B_WALL_B1F_L": "WALL_B1F_L"}


# ===================================================== 도면
def test_3d_dxf_faces(tmp_path):
    eng = eng_with(ps(), ps(ell()), ps(zigzag()))
    faces = list(ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace().query('3DFACE[layer=="STRUCT_PASSAGE"]'))
    assert len(faces) == sum(len(q.sect) + 2 for p in eng.passages.all_passages() for e in p.elements for q in e.pieces)


@pytest.mark.parametrize("curved", [False, True])
def test_section_is_exact_plane_cut(curved):
    """횡단면: s=120 (L 통로 첫 구간을 길이 방향) / s=110 (두 번째 구간을 가로질러). 단면 꼭짓점은 모두 절단면 위"""
    eng = eng_with(ps(ell(), name="B"), curved=curved)
    items = eng.passages.section_items(120.0)
    names = {it.name for it in items}
    assert {"B_S1_FLOOR", "B_S1_ROOF"} <= names and any(n.startswith("B_S2_WALL") for n in names)   # 꺾임부 바깥 벽 단면
    assert [it.label[0] for it in items if it.label] == ["B"]
    floor_bottoms = [min(z for _, z in it.poly) for it in items if it.name == "B_S1_FLOOR"]
    e0 = eng.cfg.passage_layouts()[0].z_floor
    assert min(floor_bottoms) == pytest.approx(e0 - 0.6, abs=1e-6)              # 접합부 바닥 슬래브 하면
    items = eng.passages.section_items(110.0)
    names = sorted(it.name for it in items)
    assert names.count("B_S2_FLOOR") == 1 and names.count("B_S2_WALL_L") == 1 and names.count("B_S2_WALL_R") == 1
    if not curved:                                                                 # 직선: 두 번째 구간 단면 폭 = 외폭
        ws = [w for it in items for w, _ in it.poly]
        assert max(ws) - min(ws) == pytest.approx(2 * 2.6)


def test_build_all_outputs_straight_and_curved(tmp_path):
    from engine.bim_engine import BIMEngine
    for curved in (False, True):
        paths = BIMEngine.build(cfg_with(ps(), ps(ell()), ps(zigzag()), curved=curved), tmp_path / str(curved))
        assert len(paths) == 5 and all(os.path.getsize(p) > 0 for p in paths)


def test_no_passages_keeps_walls_whole():
    eng = StationCADEngine(make_cfg(user_example()))
    assert eng.passages.passage_packages == [] and eng.cfg.wall_openings() == []
    assert all(not w.pieces and not w.openings for pk in eng.walls.wall_packages for w in pk.walls)


# ===================================================== 입력 초안 (화면 비의존)
from gui.opening_draft import KIND_LABELS
from gui.passage_draft import MODE_STATION, MODE_WORLD, PassageDraft, PassageDrafts, VertexDraft, default_draft, preview


def test_draft_station_mode_converts_sta():
    d = PassageDrafts()
    d.items = [PassageDraft(name="E", floor=3, vertices=[VertexDraft("184.45", "10", ""), VertexDraft("184.45", "25", "0"),
                                                          VertexDraft("204.45", "25", "0")])]
    (sp,) = d.to_specs(134.45)
    assert sp.name == "E" and [(v.mode, v.x, v.y, v.z) for v in sp.path] == [
        ("station", pytest.approx(50.0), 10.0, None), ("station", pytest.approx(50.0), 25.0, 0.0),
        ("station", pytest.approx(70.0), 25.0, 0.0)]


def test_draft_world_mode_keeps_absolute():
    d = PassageDrafts()
    d.items = [PassageDraft(mode=MODE_WORLD, vertices=[VertexDraft("300.5", "-80.25", ""), VertexDraft("310", "-70", "125.3")])]
    (sp,) = d.to_specs(134.45)
    assert [(v.mode, v.x, v.y, v.z) for v in sp.path] == [("world", 300.5, -80.25, None), ("world", 310.0, -70.0, 125.3)]


@pytest.mark.parametrize("field,value,msg", [
    ("inner_width", "0", "내공 폭"),
    ("top_haunch_w", "-1", "0 이상"),
    ("mode", "극좌표", "좌표 방식"),
])
def test_draft_errors_name_the_passage(field, value, msg):
    d = PassageDrafts(); d.items = [default_draft(3, 50.0, TF)]
    setattr(d.items[0], field, value)
    with pytest.raises(ValueError, match=msg):
        d.to_specs(0.0)


def test_draft_vertex_errors_name_the_vertex():
    d = PassageDrafts(); d.items = [default_draft(3, 50.0, TF)]
    d.items[0].vertices[1].z = ""
    with pytest.raises(ValueError, match=r"출구통로 1 꼭짓점 2: 높이"):
        d.to_specs(0.0)
    d.items[0].vertices[1].z = "0"; d.items[0].vertices[0].x = "a"
    with pytest.raises(ValueError, match=r"꼭짓점 1: STA"):
        d.to_specs(0.0)


def test_default_draft_and_preview():
    it = default_draft(3, 80.0, TF)
    sp = it.to_spec("", 0.0)
    assert sp.floor == 3 and [(v.x, v.y, v.z) for v in sp.path] == [(80.0, TF, None), (80.0, TF + 15, 0.0)]
    StationCADEngine(cfg_with(sp))                                                   # 기본 초안 그대로 유효
    text = preview(it, 0.0)
    assert "꼭짓점 2개" in text and "평면 길이 약 15.00m" in text and "STA 78.00 ~ 82.00" in text
    assert "확인" in preview(PassageDraft(vertices=[VertexDraft("x", "1", "")]), 0.0)
    assert MODE_STATION != MODE_WORLD


def test_draft_floor_clamped():
    d = PassageDrafts(); d.items = [PassageDraft(floor=3)]
    assert d.ensure_floors(2) is True and d.items[0].floor == 2 and d.ensure_floors(2) is False


def test_slab_opening_kinds_exclude_passage():
    assert "출구통로" not in KIND_LABELS and len(KIND_LABELS) == 4
