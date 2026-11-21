"""계단·에스컬레이터 오프닝 유리난간: 가장자리(도착 쪽·벽 쪽 제외), 부재 겹침, 높이, 바닥 마감 회피, 체적·IFC, 재질, 초안"""
import itertools
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.shape
import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from escalators.escalator_spec import EscalatorSpec
from helper import prism_member as PM
from railings.railing_layout import CORE, CURB, GLASS, POST, RAIL, SKIRT, layout_railings
from railings.railing_spec import RailingSettings
from stairs.stair_spec import StairSpec
from test_finishes import cfg_with

ST = dict(lower_floor=2, s_start=60.0, direction=1, t_center=-6.0, width=2.0, name="ST")


def make(curved=False, esc=True, finish=True, **spec):
    escs = [EscalatorSpec(lower_floor=2, s_wp=100.0, direction=1, t_center=-6.0, truss_depth=0.35, name="ES")] if esc else []
    cfg = cfg_with(curved=curved, no_cols=True, stairs=[StairSpec(**{**ST, **spec})], escalators=escs)
    cfg.finish_settings.enabled = finish
    cfg.railing_settings = RailingSettings(enabled=True)
    return cfg


def boxes(cfg, railing):
    out = []
    for p in railing.parts:
        for pc in p.pieces:
            s0, s1 = PM.s_range(pc)
            t0, t1 = PM.t_range(pc)
            z0 = PM.z_off(cfg, pc)
            out.append((p.code, s0, s1, t0, t1, z0, z0 + pc.shape.height))
    return out


def overlap(a, b):
    return all(min(a[i + 1], b[i + 1]) - max(a[i], b[i]) > 1e-6 for i in (1, 3, 5))


def test_disabled_by_default():
    cfg = make()
    cfg.railing_settings = RailingSettings()
    assert layout_railings(cfg) == [] and StationCADEngine(cfg).railings.railings == []


def test_edges_skip_arrival_wall_and_escalator_option():
    cfg = make()
    lays = {l.opening: l for l in layout_railings(cfg)}
    assert set(lays) == {"ST", "ES"} and all(l.floor == 3 for l in lays.values())
    assert lays["ST"].edges == ("T0", "T1", "S0")                  # +s 로 오름 → 도착 쪽(S1) 없음
    down = make(direction=-1, s_start=70.0, esc=False)
    assert layout_railings(down)[0].edges == ("T0", "T1", "S1")
    wall = make(t_center=-8.0, esc=False)                           # t −9 ~ −7: −t 쪽은 본체 벽
    assert "T0" not in layout_railings(wall)[0].edges
    cfg.railing_settings.escalators = False
    assert [l.opening for l in layout_railings(cfg)] == ["ST"]


def test_parts_do_not_overlap_and_posts_spaced():
    cfg = make()
    rs = cfg.railing_settings
    eng = StationCADEngine(cfg)
    for r in eng.railings.railings:
        bx = boxes(cfg, r)
        assert not [(a[0], b[0]) for a, b in itertools.combinations(bx, 2) if overlap(a, b)]
        # 유리판은 POST 사이, 한 판 길이 ≤ POST 간격
        for p in r.part(GLASS).pieces:
            assert max(p.shape.length, p.shape.width) <= rs.post_spacing + 1e-9
        assert len(r.part(RAIL).pieces) == 2 * len(r.edges) and len(r.part(CURB).pieces) == len(r.edges)


def test_heights_follow_finished_floor():
    cfg = make()
    rs = cfg.railing_settings
    st = cfg.station
    lay = next(l for l in layout_railings(cfg) if l.opening == "ST")
    ffl = st.floor_level(3) + cfg.finish_settings.table["기본"].ffl
    assert lay.ffl == pytest.approx(ffl)
    top = ffl + rs.curb_h                                           # ㅠ: 석판(폭 전체) 아래 양 옆 걸레받이 + 속채움, 구조 FL 부터
    assert all(z0 == pytest.approx(top - rs.plate_t) and z1 == pytest.approx(top) for *_, z0, z1 in lay.parts[CURB])
    for code in (SKIRT, CORE):
        assert all(z0 == pytest.approx(st.floor_level(3)) and z1 == pytest.approx(top - rs.plate_t) for *_, z0, z1 in lay.parts[code])
    assert len(lay.parts[SKIRT]) == 2 * len(lay.edges) and len(lay.parts[CORE]) == len(lay.edges)
    # 경계석 단면: 석판 폭 = 걸레받이 2 + 속채움 (가장자리마다 같은 평면 넓이)
    area = lambda r: (r[1] - r[0]) * (r[3] - r[2])
    assert sum(map(area, lay.parts[CURB])) == pytest.approx(sum(map(area, lay.parts[SKIRT] + lay.parts[CORE])))
    assert max(z1 for *_, z1 in lay.parts[RAIL]) == pytest.approx(ffl + rs.rail_h1)
    assert max(z1 for *_, z1 in lay.parts[POST]) == pytest.approx(ffl + rs.rail_h1)
    off = make(finish=False)                                        # 마감을 끄면 구조 FL 기준
    assert layout_railings(off)[0].ffl == pytest.approx(st.floor_level(3))


def test_floor_finish_and_tactile_avoid_curb():
    cfg = make()
    eng = StationCADEngine(cfg)
    curbs = [p[:4] for l in layout_railings(cfg) for p in l.parts[CURB]]
    for rf in (r for r in eng.finishes.rooms if r.floor == 3):
        for code in ("FLOOR", "FILL"):
            e = rf.element(code)
            for p in (e.pieces if e else []):
                r = (*PM.s_range(p), *PM.t_range(p))
                assert not any(min(r[1], c[1]) - max(r[0], c[0]) > 1e-6 and min(r[3], c[3]) - max(r[2], c[2]) > 1e-6
                               for c in curbs)


@pytest.mark.parametrize("curved", [False, True])
def test_volume_mesh_and_ifc(tmp_path, curved):
    cfg = make(curved=curved, s_start=80.0 if curved else 60.0, esc=not curved)
    eng = StationCADEngine(cfg)
    eng.build_3d_doc()
    assert eng.railings.railings
    rel = 1e-4 if curved else 1e-9
    for e in eng.railings.elements:
        faces = [f.dxf for f in e.source_element]
        o = np.array(faces[0].vtx0, dtype=float)
        v = 0.0
        for d in faces:
            p = [np.array(d.get(f"vtx{i}"), dtype=float) - o for i in range(4)]
            v += np.dot(p[0], np.cross(p[1], p[2])) / 6.0
            if np.linalg.norm(p[3] - p[2]) > 1e-12:
                v += np.dot(p[0], np.cross(p[2], p[3])) / 6.0
        assert v == pytest.approx(e.volume, rel=rel, abs=1e-9)
        layers = {f.dxf.layer for f in e.source_element}
        assert layers == ({"STRUCT_RAILING_GLASS"} if e.code == GLASS else {"STRUCT_RAILING"})
    path = eng.generate_ifc(str(tmp_path / "r.ifc"))
    f = ifcopenshell.open(path)
    rails = f.by_type("IfcRailing")
    assert {r.Name for r in rails if r.PredefinedType == "GUARDRAIL"} == {r.name for r in eng.railings.railings}
    s = ifcopenshell.geom.settings()
    s.set(s.USE_WORLD_COORDS, True)
    want = {e.name: e.volume for e in eng.railings.elements}
    kinds = set()
    for rel_ in f.by_type("IfcRelAggregates"):
        if rel_.RelatingObject.is_a("IfcRailing"):
            for el in rel_.RelatedObjects:
                kinds.add(el.is_a())
                vol = ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(s, el).geometry)
                assert vol == pytest.approx(want[el.Name], rel=rel, abs=1e-8)
    assert kinds == {"IfcBuildingElementPart", "IfcMember", "IfcPlate"}


def test_glass_color_in_viewer_and_dae(tmp_path):
    from exporter.dae_exporter import export_dae
    from exporter.web_viewer import build_web_data
    cfg = make(esc=False)
    cfg.railing_settings.glass_rgb = (255, 0, 0)
    cfg.railing_settings.glass_alpha = 0.5
    eng = StationCADEngine(cfg)
    data, _ = build_web_data(eng)
    glass = [c for c in data["chunks"] if c["layer"] == "STRUCT_RAILING_GLASS"]
    assert glass and glass[0]["color"] == [1.0, 0.0, 0.0] and glass[0]["alpha"] == 0.5
    assert {"화강석", "흑색 걸레받이", "스테인리스"} <= {c["material"] for c in data["chunks"] if c["layer"] == "STRUCT_RAILING"}
    res = export_dae(eng, tmp_path / "m.dae")
    assert "난간 유리" in res.materials and "스테인리스" in res.materials


def test_drawings():
    eng = StationCADEngine(make(esc=False))
    r = eng.railings.railings[0]
    curb = r.part(CURB).pieces[0]
    sta = sum(PM.s_range(curb)) / 2.0
    assert any(it.layer == "SEC_RAILING" for it in eng.railings.section_items(sta))
    assert any(it.layer == "PLAN_RAILING" for it in eng.railings.plan_items(eng.cfg.station.floor_level(3) + 1.0, floor=3))
    assert not eng.railings.plan_items(1.0, floor=1)


@pytest.mark.parametrize("kw, msg", [(dict(curb_w=0), "경계석 폭"), (dict(rail_h2=1.18), "겹칩니다"),
                                     (dict(glass_rgb=(0, 0, 300)), "R, G, B"), (dict(glass_alpha=0), "불투명도"),
                                     (dict(post_d=0.005), "유리 두께")])
def test_invalid_settings(kw, msg):
    with pytest.raises(ValueError, match=msg):
        RailingSettings(enabled=True, **kw).check()


def test_draft_and_project_round_trip():
    from gui.project_file import ProjectState
    from gui.railing_draft import RailingDraft, preview
    d = RailingDraft()
    rs = d.to_settings()
    assert rs.enabled and rs.glass_rgb == (150, 205, 190) and "유리" in preview(d)
    d.glass_rgb = "10; 20; 30"
    assert d.to_settings().glass_rgb == (10, 20, 30)
    d.glass_rgb = "red"
    with pytest.raises(ValueError, match="유리난간: 유리 색"):
        d.to_settings()
    assert "입력값" in preview(d)
    d.enabled = False
    assert not d.to_settings().enabled and "없음" in preview(d)
    st = ProjectState()
    st.railing_draft = RailingDraft(escalators=False, glass_rgb="1, 2, 3", rail_h1="1.1")
    assert ProjectState.from_dict(st.to_dict()).railing_draft == st.railing_draft
    old = st.to_dict()
    del old["railing_draft"]
    assert ProjectState.from_dict(old).railing_draft == RailingDraft()
