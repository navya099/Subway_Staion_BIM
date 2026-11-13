"""출구통로 (측벽 직각 박스 + L자 꺾임, 헌치, 구배, 본체 측벽 오프닝) 테스트"""
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
from helper.box_piece import footprints_overlap
from openings.opening_kind import OpeningKind
from passages.passage_spec import PassageSpec
from passages.passage_type import PassagePartKind as K
from test_curved import NO_COLS, curved_cfg
from test_patch import _q, make_cfg, user_example
from walls.wall_shape_type import WallRole


def ps(floor=3, side=1, s=50.0, name="", **kw):
    return PassageSpec(floor=floor, side=side, s_center=s, name=name, **kw)


def L_SHAPE(**kw):
    return ps(side=-1, s=120.0, length1=12.0, length2=20.0, turn=-1, **kw)


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


# ===================================================== 좌표계·배치
def test_frame_starts_at_outer_wall_face_perpendicular_to_alignment():
    cfg = cfg_with(ps(side=1, name="A"), L_SHAPE(name="B"))
    st = cfg.station
    for lay in cfg.passage_layouts():
        fr, sp = lay.frame, lay.spec
        t_face = st.width / 2.0 + st.wall_t_at(sp.floor)
        assert fr.t_face == pytest.approx(t_face)
        assert fr.world(0.0, 0.0) == pytest.approx(cfg.to_world(sp.s_center, sp.side * t_face))
        th = cfg.theta_at(sp.s_center)
        assert (fr.nx, fr.ny) == pytest.approx((-sp.side * math.sin(th), sp.side * math.cos(th)))     # 본체에서 멀어지는 직교 방향
        assert (fr.dx, fr.dy) == pytest.approx((sp.turn * math.cos(th), sp.turn * math.sin(th)))      # 꺾임 = 선형 접선 방향
        assert lay.z_floor == pytest.approx(cfg.lv(sp.s_center) - st.offset + st.floor_level(sp.floor))
    # 직선 선형: 통로 좌표 (X, 0) 이 정거장 (s_c, side·(t_face + X)) 와 정확히 일치
    a = cfg.passage_layouts()[0]
    for X in (0.0, 5.0, 15.0):
        assert a.frame.world(X, 0.0) == pytest.approx(cfg.to_world(50.0, a.frame.t_face + X))


def test_straight_passage_volumes_match_hand_formula():
    sp = ps(bottom_haunch_w=0.2, bottom_haunch_h=0.25)
    eng = eng_with(sp)
    p = eng.passages.all_passages()[0]
    a, b, H, L1 = sp.half_in, sp.half_out, sp.inner_height, sp.length1
    th, bh = 0.3 * 0.3 / 2, 0.2 * 0.25 / 2
    assert [e.name for e in p.elements] == ["EX1_S1_FLOOR", "EX1_S1_ROOF", "EX1_S1_WALL_A", "EX1_S1_WALL_B"]
    assert p.element("S1_FLOOR").volume == pytest.approx(L1 * 2 * b * sp.floor_t + 2 * bh * L1)
    assert p.element("S1_ROOF").volume == pytest.approx(L1 * 2 * b * sp.roof_t + 2 * th * L1)
    assert p.element("S1_WALL_A").volume == pytest.approx(L1 * sp.wall_t * H)
    clear = L1 * 2 * a * H - 2 * (th + bh) * L1                  # 내공 단면(헌치 뺀) x 길이
    outer = L1 * 2 * b * (H + sp.floor_t + sp.roof_t)
    assert p.volume == pytest.approx(outer - clear)


def test_l_shape_walls_and_slabs_cover_union_exactly():
    """L자: 바닥 슬래브 평면 = 두 구간 외곽의 합집합, 벽 평면 = 외곽 합집합 − 내공 합집합 (끝단은 개방)"""
    sp = L_SHAPE()
    eng = eng_with(sp)
    p = eng.passages.all_passages()[0]
    a, b, H, L1, L2 = sp.half_in, sp.half_out, sp.inner_height, sp.length1, sp.length2
    outer = (L1 + b) * 2 * b + (L2 - b) * 2 * b                   # 첫 구간(모서리 포함) + 두 번째 구간
    clear = (L1 + a) * 2 * a + (L2 - a) * 2 * a
    floors = p.element("S1_FLOOR").volume + p.element("S2_FLOOR").volume
    assert floors == pytest.approx(outer * sp.floor_t)
    walls = sum(e.volume for e in p.elements if e.kind == K.WALL)
    assert walls == pytest.approx((outer - clear) * H)
    assert {e.name.split("_", 1)[1] for e in p.elements} == {"S1_FLOOR", "S1_ROOF", "S1_WALL_A", "S1_WALL_B",
                                                              "S2_FLOOR", "S2_ROOF", "S2_WALL_OUT", "S2_WALL_IN"}


@pytest.mark.parametrize("sp", [ps(bottom_haunch_w=0.2, bottom_haunch_h=0.2), L_SHAPE(bottom_haunch_w=0.2, bottom_haunch_h=0.2)])
def test_pieces_do_not_overlap(sp):
    pieces = [q for e in eng_with(sp).passages.all_passages()[0].elements for q in e.pieces]
    for i, p in enumerate(pieces):
        for q in pieces[i + 1:]:
            (a0, a1), (b0, b1) = p.z_range, q.z_range
            if min(a1, b1) - max(a0, b0) > 1e-6 and footprints_overlap(p.footprint(), q.footprint()):
                # 평면·높이 범위가 겹치는 경우는 헌치 삼각형과 그 위 천장(또는 아래 바닥)뿐: 실제 단면은 겹치지 않아야 함
                tri, other = (p, q) if len(p.sect) == 3 else (q, p)
                assert len(tri.sect) == 3 and len(other.sect) == 4
                assert min(d for _, d in other.sect) >= max(d for _, d in tri.sect) - 1e-9 or \
                    max(d for _, d in other.sect) <= min(d for _, d in tri.sect) + 1e-9


def test_grade_rises_away_and_corner_is_level():
    sp = L_SHAPE(grade_permil=30.0)
    cfg = cfg_with(sp)
    lay = cfg.passage_layouts()[0]
    g, b, L1, L2 = 0.03, sp.half_out, sp.length1, sp.length2
    z0 = lay.z_floor
    floor1 = next(e for e in lay.elements if e.code == "S1_FLOOR").pieces
    floor2 = next(e for e in lay.elements if e.code == "S2_FLOOR").pieces
    sloped, flat = floor1
    assert (sloped.a0, sloped.a1, sloped.slope) == pytest.approx((0.0, L1 - b, g))
    assert sloped.z0 == pytest.approx(z0)
    assert (flat.slope, flat.z0) == pytest.approx((0.0, z0 + g * (L1 - b)))          # 꺾임부 수평
    (s2,) = floor2
    assert (s2.a0, s2.a1, s2.slope) == pytest.approx((b, L2, g))
    assert s2.z0 == pytest.approx(z0 + g * (L1 - b))                                  # 꺾임부 높이에서 이어서 오름
    assert s2.z_ref(L2) == pytest.approx(z0 + g * (L1 - b + L2 - b))


# ===================================================== 본체 측벽 오프닝
def test_side_wall_opening_cut_into_pieces():
    sp = ps(side=1, s=50.0)
    base = StationCADEngine(make_cfg(user_example()))
    eng = eng_with(sp)
    w = wall(eng, "B1F", WallRole.RIGHT)
    assert PM.t_range(w)[0] > 0                                                      # side +1 = t 큰 쪽 벽 (코드 R)
    (o,) = w.openings
    assert o.kind is OpeningKind.PASSAGE and o.name == "OPEN_EX1_WALL_B1F_R"
    fl = eng.cfg.station.floor_level(3)
    assert o.s_range == pytest.approx((48.0, 52.0)) and o.t_range == pytest.approx((fl, fl + 3.0))
    assert len(w.pieces) == 3                                                        # 앞·뒤 + 오프닝 위 인방
    ref = wall(base, "B1F", WallRole.RIGHT)
    assert w.net_volume == pytest.approx(ref.shape.volume - 4.0 * 1.0 * 3.0)
    assert wall(eng, "B1F", WallRole.LEFT).pieces == [] and wall(eng, "B2F", WallRole.RIGHT).pieces == []


def test_wall_section_shows_lintel_at_opening(tmp_path):
    eng = eng_with(ps(side=1, s=50.0))
    cfg = eng.cfg
    path = eng.generate_section_dxf([50.0], tmp_path / "s.dxf")
    base = StationCADEngine(make_cfg(user_example())).generate_section_dxf([50.0], tmp_path / "b.dxf")
    right = lambda pl: min(q[0] for q in pl.get_points()) > 9.0 - 1e-6 and max(q[0] for q in pl.get_points()) <= 10.0 + 1e-6
    walls = [pl for pl in _q(path, "SEC_CONCRETE") if right(pl)]
    ref = [pl for pl in _q(base, "SEC_CONCRETE") if right(pl)]
    assert len(ref) == 1 and len(walls) == 2                                        # 합쳐진 측벽이 오프닝 아래/위로 나뉨
    zf = cfg.lv(50.0) + cfg.station.floor_level(3)
    tops = sorted(max(q[1] for q in pl.get_points()) for pl in walls)
    bottoms = sorted(min(q[1] for q in pl.get_points()) for pl in walls)
    assert tops[0] == pytest.approx(zf) and bottoms[1] == pytest.approx(zf + 3.0)


def test_floor1_passage_cuts_plan_wall(tmp_path):
    cfg = cfg_with(ps(floor=1, side=1, s=50.0, inner_height=2.5), columns=NO_COLS())
    cfg.platform.plat_thick = 0.0                                                    # 승강장 없음 (통로가 승강장 높이와 무관하게)
    eng = StationCADEngine(cfg)
    path = eng.generate_plan_dxf(tmp_path / "p.dxf")
    outl = _q(path, "PLAN_OUTLINE")
    assert any(abs(max(q[0] for q in pl.get_points()) - 48.0) < 1e-6 for pl in outl)  # 측벽이 오프닝 앞에서 끊김
    assert len(_q(path, "PLAN_PASSAGE")) == 2
    assert "EX1 EXIT" in [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT")]


# ===================================================== 검증
@pytest.mark.parametrize("sp,msg", [
    (ps(floor=0), "범위"),
    (ps(floor=4), "범위"),
    (ps(side=0), "측벽 방향"),
    (ps(turn=2), "꺾임 방향"),
    (ps(inner_width=0.0), "내공 폭"),
    (ps(length2=-1.0), "꺾임 후 길이"),
    (ps(top_haunch_w=0.3, top_haunch_h=0.0), "헌치"),
    (ps(top_haunch_w=2.0), "헌치 폭"),
    (ps(top_haunch_h=1.6, bottom_haunch_w=0.2, bottom_haunch_h=1.5), "헌치 높이의 합"),
    (ps(length1=2.0, length2=10.0), "외폭의 절반"),
    (ps(length2=2.0), "외폭의 절반"),
    (ps(s=1.0), "내공 길이"),
    (ps(s=197.5), "내공 길이"),
    (ps(inner_height=5.7), "내공 높이"),
])
def test_invalid_passage_rejected(sp, msg):
    with pytest.raises(ValueError, match=msg):
        StationCADEngine(cfg_with(sp))


def test_thicker_lower_or_upper_wall_rejected():
    cfg = cfg_with(ps(floor=2, s=50.0))
    cfg.station.wall_ts = [1.2, 1.0, 1.0]
    with pytest.raises(ValueError, match="아래층"):
        StationCADEngine(cfg)
    cfg = cfg_with(ps(floor=2, s=50.0, inner_height=5.5, roof_t=0.8))      # 천장 상면 FL+6.3 > 위층 FL+6.0
    cfg.station.wall_ts = [1.0, 1.0, 1.2]
    with pytest.raises(ValueError, match="위층"):
        StationCADEngine(cfg)


def test_overlapping_passages_and_names_rejected():
    with pytest.raises(ValueError, match="겹칩니다"):
        StationCADEngine(cfg_with(ps(s=50.0), ps(s=53.0)))
    StationCADEngine(cfg_with(ps(s=50.0), ps(s=55.2)))                                 # 벽이 맞닿기만 하면 허용
    StationCADEngine(cfg_with(ps(floor=3, s=50.0), ps(floor=1, s=50.0, inner_height=2.5)))   # 다른 층 (높이가 다름)
    with pytest.raises(ValueError, match="이름이 중복"):
        StationCADEngine(cfg_with(ps(name="X"), ps(s=120.0, name="X")))


# ===================================================== 체적 교차 검증 (공식 ↔ 3D 메쉬 ↔ IFC)
def ifc_world_volume(el):
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(st, el).geometry)


@pytest.mark.parametrize("curved", [False, True])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, curved):
    eng = eng_with(ps(bottom_haunch_w=0.2, bottom_haunch_h=0.2), L_SHAPE(grade_permil=30.0), curved=curved)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    els = {e.Name: e for e in f.by_type("IfcSlab") + f.by_type("IfcWall")}
    for p in eng.passages.all_passages():
        for e in p.elements:
            assert sum(PM.mesh_volume(q.faces()) for q in e.pieces) == pytest.approx(e.volume, rel=1e-9)
            assert ifc_world_volume(els[e.name]) == pytest.approx(e.volume, rel=1e-6)
            assert els[e.name].Representation.Representations[0].RepresentationType == "SweptSolid"   # 곡선에서도 곧은 압출
    for w in [w for pk in eng.walls.wall_packages for w in pk.walls if w.openings]:
        assert ifc_world_volume(els[w.name]) == pytest.approx(w.net_volume, rel=1e-4)


def test_ifc_assembly_structure(tmp_path):
    eng = eng_with(ps(name="A"), L_SHAPE(name="B"))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    asms = {a.Name: a for a in f.by_type("IfcElementAssembly")}
    assert set(asms) == {"A", "B"}
    for name in ("A", "B"):
        a = asms[name]
        assert a.PredefinedType == "USERDEFINED" and a.ObjectType == "EXIT_PASSAGE"
        assert ifcopenshell.util.element.get_container(a).Name == "B1F"
        parts = {p.Name: p for p in ifcopenshell.util.element.get_decomposition(a)}
        assert set(parts) == {e.name for e in by_name(eng, name).elements}
        assert parts[f"{name}_S1_FLOOR"].is_a("IfcSlab") and parts[f"{name}_S1_FLOOR"].PredefinedType == "FLOOR"
        assert parts[f"{name}_S1_ROOF"].PredefinedType == "ROOF"
        assert parts[f"{name}_S1_WALL_A"].is_a("IfcWall")
    ops = {o.Name: o for o in f.by_type("IfcOpeningElement")}
    assert set(ops) == {"OPEN_A_WALL_B1F_R", "OPEN_B_WALL_B1F_L"} and ops["OPEN_A_WALL_B1F_R"].ObjectType == "PASSAGE"
    voids = {r.RelatedOpeningElement.Name: r.RelatingBuildingElement.Name for r in f.by_type("IfcRelVoidsElement")}
    assert voids == {"OPEN_A_WALL_B1F_R": "WALL_B1F_R", "OPEN_B_WALL_B1F_L": "WALL_B1F_L"}


# ===================================================== 도면
def test_3d_dxf_faces(tmp_path):
    eng = eng_with(ps(), L_SHAPE())
    faces = list(ezdxf.readfile(eng.generate_3d_dxf(tmp_path / "m.dxf")).modelspace().query('3DFACE[layer=="STRUCT_PASSAGE"]'))
    expect = sum(len(q.sect) + 2 for p in eng.passages.all_passages() for e in p.elements for q in e.pieces)
    assert len(faces) == expect


def test_section_cuts_both_segments(tmp_path):
    eng = eng_with(L_SHAPE(name="B"))
    sp = L_SHAPE()
    # s = 120: 첫 구간을 길이 방향으로 자름 → 바닥·천장(구배 구간 + 꺾임부) 과, 꺾임부 바깥 벽·그 헌치의 단면
    items = eng.passages.section_items(120.0)
    assert sorted(it.name for it in items) == ["B_S1_FLOOR", "B_S1_FLOOR", "B_S1_ROOF", "B_S1_ROOF",
                                               "B_S2_ROOF", "B_S2_WALL_OUT"]
    t_lo = min(min(x for x, _ in it.poly) for it in items)
    assert t_lo == pytest.approx(-(10.0 + sp.length1 + sp.half_out))                    # 모서리 바깥까지
    assert [it.label[0] for it in items if it.label] == ["B"]
    # s = 110: 두 번째 구간 단면 → 바닥·천장·벽 2·상부 헌치 2
    items = eng.passages.section_items(110.0)
    names = sorted(it.name for it in items)
    assert names.count("B_S2_ROOF") == 3 and names.count("B_S2_FLOOR") == 1 and "B_S2_WALL_OUT" in names
    xs = [x for it in items for x, _ in it.poly]
    assert (min(xs), max(xs)) == pytest.approx((-(10.0 + sp.length1 + sp.half_out), -(10.0 + sp.length1 - sp.half_out)))


def test_build_all_outputs_straight_and_curved(tmp_path):
    from engine.bim_engine import BIMEngine
    for curved in (False, True):
        paths = BIMEngine.build(cfg_with(ps(), L_SHAPE(grade_permil=20.0), curved=curved), tmp_path / str(curved))
        assert len(paths) == 5 and all(os.path.getsize(p) > 0 for p in paths)


def test_no_passages_keeps_walls_whole():
    eng = StationCADEngine(make_cfg(user_example()))
    assert eng.passages.passage_packages == [] and eng.cfg.wall_openings() == []
    assert all(not w.pieces and not w.openings for pk in eng.walls.wall_packages for w in pk.walls)


# ===================================================== 입력 초안 (화면 비의존)
from gui.opening_draft import KIND_LABELS
from gui.passage_draft import SIDE_MINUS, PassageDraft, PassageDrafts, preview
from gui.stair_draft import UP_MINUS


def test_draft_converts_sta_and_choices():
    d = PassageDrafts()
    d.items = [PassageDraft(name="E", floor=3, side=SIDE_MINUS, turn=UP_MINUS, sta_center="254.45", length2="20",
                            grade_permil="15")]
    (sp,) = d.to_specs(134.45)
    assert (sp.name, sp.floor, sp.side, sp.turn, sp.length2, sp.grade_permil) == ("E", 3, -1, -1, 20.0, 15.0)
    assert sp.s_center == pytest.approx(120.0)


@pytest.mark.parametrize("field,value,msg", [
    ("sta_center", "x", r"출구통로 1: 중심 측점"),
    ("inner_width", "0", "내공 폭"),
    ("top_haunch_w", "-1", "0 이상"),
    ("side", "위", "측벽 방향"),
    ("turn", "위", "꺾임 방향"),
])
def test_draft_errors_name_the_passage(field, value, msg):
    d = PassageDrafts(); d.items = [PassageDraft()]
    setattr(d.items[0], field, value)
    with pytest.raises(ValueError, match=msg):
        d.to_specs(0.0)


def test_draft_floor_clamped_and_preview():
    d = PassageDrafts(); d.items = [PassageDraft(floor=3)]
    assert d.ensure_floors(2) is True and d.items[0].floor == 2 and d.ensure_floors(2) is False
    assert "STA 98.00 ~ 102.00" in preview(PassageDraft(sta_center="100"), 0.0)
    assert "L자" in preview(PassageDraft(sta_center="100", length2="10", turn=UP_MINUS), 0.0)
    assert "확인" in preview(PassageDraft(inner_width="x"), 0.0)


def test_slab_opening_kinds_exclude_passage():
    assert "출구통로" not in KIND_LABELS and len(KIND_LABELS) == 4
