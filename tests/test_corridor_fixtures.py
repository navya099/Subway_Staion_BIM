"""출구통로·출입구 천장 조명·디퓨저: 대칭 격자, 꺾임(연귀)·경사·끝 폐합, 천장판·천장틀 비우기, 겹침·체적, IFC·DAE·웹 뷰어, 단면·종단"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataclasses
import gzip
import itertools
import math
import random

import ifcopenshell
import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from finishes.finish_spec import FinishSettings, default_finishes
from fixtures.corridor_layout import bands, cut_boxes, mitre_region, straight_runs
from fixtures.fixture_layout import CELL, DIFF, EDGE, FACE, LIGHT_L, LIGHT_W
from helper import prism_member as PM
from helper import trap_region as T
from helper.box_piece import BoxPiece
from passages.passage_finish import CEILING, FRAME
from preview.preview_render import station_of
from test_entrances import _fin_cfg
from test_finishes import ifc_world_volume
from test_fixtures import lit
from test_passage_finish import _inside, cfg_pf


def cfg_p(light=2.4, diff=4.8, **kw):
    cfg = cfg_pf(**kw)
    cfg.finish_settings = FinishSettings(enabled=True, table=lit(light, diff))
    return cfg


def cfg_e(**kw):
    cfg = _fin_cfg(**kw)
    cfg.passages[0].inner_height = 3.5
    zp = cfg.passage_layouts()[-1].vertices[-1].z
    cfg.entrances[0].ground_el = zp + 17.287
    cfg.finish_settings = FinishSettings(enabled=True, table=lit())
    return cfg


@pytest.fixture(scope="module")
def pas():
    return StationCADEngine(cfg_p())


@pytest.fixture(scope="module")
def ent():
    return StationCADEngine(cfg_e())


def els(eng, host, kind=None):
    return [e for e in eng.corridor_fixtures.elements if e.host == host and (kind is None or e.kind == kind)]


def true_len(e):
    return (e.rect[1] - e.rect[0]) * math.sqrt(1 + e.body.slope ** 2)


# ===================================================== 작은 도구
def test_mitre_region_area_and_shape():
    assert T.area(mitre_region(10.0, 0.0, 0.0, 2.0)) == pytest.approx(40.0)
    for tp, ke in ((1.0, 0.0), (-0.4, -0.4), (1.0, -1.0), (0.5, 0.9)):
        r = mitre_region(10.0, tp, ke, 2.0)
        assert T.area(r) == pytest.approx(4.0 * 10.0)                                     # 연귀는 넓이를 바꾸지 않음
        for a, v in ((0.1, 0.0), (9.9, 0.0)):
            assert T.contains(r, a, v)
        assert not T.contains(r, tp * 1.5 - 0.05, 1.5) and T.contains(r, tp * 1.5 + 0.05, 1.5)
        assert not T.contains(r, 10 + ke * 1.5 + 0.05, 1.5) and T.contains(r, 10 + ke * 1.5 - 0.05, 1.5)


def test_bands_and_cut_boxes_keep_volume_minus_holes():
    assert [(a, b, len(h)) for a, b, h in bands(-2, 2, [(0, 1, -1, 0), (3, 4, -1, 0), (6, 7, 1, 1.5)])] == [(-2, -1, 0), (-1, 0, 2), (0, 1, 0), (1, 1.5, 1), (1.5, 2, 0)]
    p = BoxPiece(1, 2, 0.6, 0.8, 0.0, 10.0, [(-2, 3.0), (2, 3.0), (2, 3.01), (-2, 3.01)], 5.0, 0.05, 1.0, -1.0, {"seg": 0})
    holes = [(3.0, 4.2, -1.2, -0.9), (3.0, 4.2, 0.9, 1.2), (5.0, 5.6, -0.3, 0.3), (0.2, 1.4, -1.5, -1.2)]
    out = cut_boxes([p], 0, holes)
    area = sum((h[1] - h[0]) * (h[3] - h[2]) for h in holes)
    assert sum(q.volume for q in out) == pytest.approx(p.volume - area * 0.01, rel=1e-9) and all(q.volume > 0 for q in out)
    for q in out:                                                                          # 같은 경사면 위
        for x, y, z in q.rings()[0] + q.rings()[1]:
            a = (x - 1) * 0.6 + (y - 2) * 0.8
            assert 3.0 - 1e-9 <= z - (5.0 + 0.05 * a) <= 3.01 + 1e-9
    assert cut_boxes([p], 1, holes) == [p]                                                 # 다른 구간
    bar = BoxPiece(0, 0, 1, 0, 3.0, 3.05, [(-2, 0), (2, 0), (2, 0.04), (-2, 0.04)], 0.0, 0.0, 0.0, 0.0, {"seg": 0})
    cut = cut_boxes([bar], 0, [(2.0, 4.0, -0.5, 0.5), (3.03, 5.0, 1.0, 1.5), (7.0, 8.0, -2, 2)])
    assert sum(q.volume for q in cut) == pytest.approx((4 * 0.05 - 1.0 * 0.05 - 0.5 * 0.02) * 0.04)


def test_straight_runs_merge_collinear():
    r = straight_runs([(0, 2, 3, 3), (2, 4, 3, 4), (4, 6, 4, 5), (6, 7, 5, 5)], 1.0, 6.5)
    assert [(a, b, round(za, 6), round(zb, 6), m) for a, b, za, zb, m in r] == [(1.0, 2, 3, 3, 0.0), (2, 6, 3, 5, 0.5), (6, 6.5, 5, 5, 0.0)]


# ===================================================== 출구통로
def test_default_has_no_corridor_fixtures():
    eng = StationCADEngine(cfg_pf())
    assert eng.corridor_fixtures.elements == []
    assert StationCADEngine(cfg_p(light=0, diff=0)).corridor_fixtures.elements == []
    low = StationCADEngine(cfg_p(H=3.0))                                                    # 천장이 안 들어가면 기구도 없음
    assert low.corridor_fixtures.elements == [] and low.warnings


def test_passage_layout_symmetric_on_grid_inside_ceiling(pas):
    cfg = pas.cfg
    ft = cfg.finish_settings.for_room("통로")
    for lay in pas.passage_finishes.layouts:
        c_half = cfg.passages[0].half_in - ft.face
        pl = next(x for x in cfg.passage_layouts() if x.name == lay.name)
        assert {k for _, _, (k, *_) in lay.fixtures} == {"LIGHT", "DIFFUSER"}
        for i in sorted({s.index for s, _, _ in lay.fixtures}):
            seg = pl.segments[i]
            fx = [f for s, _, f in lay.fixtures if s.index == i]
            k = 1 / math.sqrt(1 + seg.slope ** 2)
            end = seg.length - (pl.spec.wall_t + ft.face if lay.name == "B" and i == len(pl.segments) - 1 else 0.0)
            ke = 0.0 if lay.name == "B" and i == len(pl.segments) - 1 else -seg.tn
            reg = mitre_region(end, seg.tp, ke, c_half)
            for kind, a0, a1, v0, v1, d in fx:
                L, W = (LIGHT_L, LIGHT_W) if kind == "LIGHT" else (DIFF, DIFF)
                assert (a1 - a0) / k == pytest.approx(L) and v1 - v0 == pytest.approx(W)      # 긴 방향 = 통로 방향, 실제 길이
                assert ((v0 + v1) / 2 / CELL) % 1.0 == pytest.approx(0.0, abs=1e-9) or ((v0 + v1) / 2 / CELL) % 1.0 == pytest.approx(1.0, abs=1e-9)
                m = (a0 + a1) / 2 / k / CELL - (0.5 if kind == "DIFFUSER" else 0.0)
                assert abs(m - round(m)) < 1e-6                                                # 축 방향 격자 (구간 시작 원점)
                g = EDGE * 0.999
                q = T.rect(a0 - g * k, a1 + g * k, v0 - g, v1 + g)
                assert T.area(T.intersect([q], reg)) == pytest.approx(T.area([q]), abs=1e-5)   # 둘레 여유까지 천장 안 (연귀 포함)
            if abs(seg.tp) < 1e-9 and abs(seg.tn) < 1e-9:                                      # 꺾이지 않는 구간은 좌우 대칭
                L_ = sorted((round(a, 6), round(-v1, 6), round(-v0, 6)) for k_, a, _, v0, v1, _ in fx if k_ == "LIGHT")
                assert L_ == sorted((round(a, 6), round(v0, 6), round(v1, 6)) for k_, a, _, v0, v1, _ in fx if k_ == "LIGHT")


def test_passage_ceiling_cut_exactly_and_rest_unchanged(pas):
    bare = StationCADEngine(cfg_p(light=0, diff=0))
    for e in pas.passage_finishes.elements:
        b = bare.passage_finishes.element(e.passage, e.code)
        if e.code == CEILING:
            bt = pas.cfg.finish_settings.for_room("통로").board_t
            hole = sum((x.rect[1] - x.rect[0]) * (x.rect[3] - x.rect[2]) for x in els(pas, e.passage))
            assert e.volume == pytest.approx(b.volume - hole * bt, rel=1e-9) and hole > 1
        elif e.code == FRAME:
            assert e.volume < b.volume - 1e-6
        else:
            assert e.volume == pytest.approx(b.volume, rel=1e-12)


def _world_parts(eng):
    cf = [(e.name, p.faces()) for e in eng.corridor_fixtures.elements for p in (e.body, e.face)]
    other = [(e.name, p.faces()) for e in eng.passage_finishes.elements for p in e.pieces]
    other += [(e.name, p.faces()) for ps in eng.passages.all_passages() for e in ps.elements for p in e.pieces]
    for en in eng.entrances.entrances:
        for n, m in eng.entrances.strip_members(en):
            t0, t1 = m.t_range
            from helper.strip_member import strip_faces
            other += [(n, strip_faces(en.frame, s, t0, t1)) for s in m.shape.strips if max(s.zt - s.zb0, s.zt_end - s.zb1) > 1e-9]
            other += [(n, p.faces()) for p in getattr(m, "pieces", [])]
    return cf, other


def _check_no_overlap(eng, n=40):
    cf, other = _world_parts(eng)
    box = lambda fs: (np.min([v for f in fs for v in f], axis=0), np.max([v for f in fs for v in f], axis=0))
    obs = [(nm, fs, *box(fs)) for nm, fs in other + cf]
    rng = random.Random(5)
    for name, fs in cf:
        lo, hi = box(fs)
        near = [(nm, f2) for nm, f2, l2, h2 in obs if f2 is not fs and np.all(l2 <= hi + 1e-6) and np.all(h2 >= lo - 1e-6)]
        for _ in range(n):
            q = lo + (hi - lo) * np.array([rng.random() for _ in range(3)])
            if not _inside(fs, q, -1e-7):
                continue
            hit = next((nm for nm, f2 in near if _inside(f2, q, -1e-6)), None)
            assert hit is None, (name, hit, q)


def test_passage_no_overlap(pas):
    _check_no_overlap(pas)
    for a, b in itertools.combinations(els(pas, "A"), 2):                                      # 다른 구간끼리도 평면에서 안 겹침
        if a.body.ox == b.body.ox and a.body.oy == b.body.oy and a.body.ux == b.body.ux:
            r, q = a.rect, b.rect
            assert not (min(r[1], q[1]) - max(r[0], q[0]) > 1e-6 and min(r[3], q[3]) - max(r[2], q[2]) > 1e-6)


# ===================================================== 출입구
def test_entrance_lights_follow_slope_and_avoid_folds(ent):
    lay = ent.cfg.entrance_layouts()[0]
    L = els(ent, lay.name)
    assert L and {e.kind for e in L} == {"LIGHT"}                                              # 조명만
    assert len({round(e.body.slope, 4) for e in L}) >= 2 and any(e.body.slope > 0.5 for e in L)
    u_re = lay.u["roof_end"]
    ft = lay.finish_type
    for e in L:
        assert true_len(e) == pytest.approx(LIGHT_L) and e.rect[3] - e.rect[2] == pytest.approx(LIGHT_W)
        u0, sl = lay.ceiling_run((e.rect[0] + e.rect[1]) / 2)
        run = next(r for r in lay.ceiling_runs if r[0] == u0)
        g = EDGE / math.sqrt(1 + sl * sl) * 0.999
        assert run[0] + g <= e.rect[0] and e.rect[1] <= run[1] - g and e.body.slope == pytest.approx(sl)   # 꺾이는 선에 걸치지 않음
        for u in e.rect[:2]:                                                                   # 천장판 하면과 같은 면
            z = run[2] + sl * (u - run[0])
            assert e.face.point(u, 0.0, max(d for _, d in e.face.sect))[2] == pytest.approx(z)
        assert e.rect[1] < u_re
    ts = sorted({round((e.rect[2] + e.rect[3]) / 2, 6) for e in L})
    assert ts == sorted(-t for t in ts)                                              # 좌우 대칭
    assert max(abs(t) for t in ts) + LIGHT_W / 2 + EDGE <= max(abs(x) for c, k, m, t, s in lay.finish if c == "FIN_CEILING" or c.startswith("FIN_CEILING_B") for x in t) + 1e-9
    assert ft.has_light


def test_entrance_ceiling_cut_exactly_headroom_unchanged(ent):
    cfg = cfg_e()
    cfg.finish_settings = FinishSettings(enabled=True, table=default_finishes())
    bare = StationCADEngine(cfg)
    vol = lambda eng, kind, pre="": sum(f.shape.volume for f in eng.entrances.entrances[0].finishes if f.kind == kind and f.code.startswith(pre))
    ft = ent.cfg.entrance_layouts()[0].finish_type
    hole = sum((e.rect[1] - e.rect[0]) * (e.rect[3] - e.rect[2]) for e in els(ent, "EN1"))
    assert vol(ent, "CEILING") == pytest.approx(vol(bare, "CEILING") - hole * ft.board_t, rel=1e-9)
    assert vol(ent, "FRAME") < vol(bare, "FRAME")
    for k in ("WALL", "FLOOR", "SKIRT"):
        assert vol(ent, k) == pytest.approx(vol(bare, k), rel=1e-12)
    assert ent.cfg.entrance_layouts()[0].ceiling_raise == bare.cfg.entrance_layouts()[0].ceiling_raise


def test_entrance_no_overlap(ent):
    _check_no_overlap(ent)


# ===================================================== 출력
@pytest.mark.parametrize("which", ["pas", "ent"])
def test_mesh_ifc_web_agree(tmp_path, which, request):
    eng = request.getfixturevalue(which)
    cf = eng.corridor_fixtures
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "c.ifc"))
    by = {x.Name: x for x in f.by_type("IfcLightFixture") + f.by_type("IfcAirTerminal") if x.PredefinedType != "GRILLE"}
    assert len({e.name for e in cf.elements}) == len(cf.elements) and {e.name for e in cf.elements} <= set(by)
    import ifcopenshell.util.element as ue
    for e in cf.elements:
        want = e.body.volume + e.face.volume
        assert e.volume == pytest.approx(want)
        assert sum(PM.mesh_volume(p.faces()) for p in (e.body, e.face)) == pytest.approx(want, rel=1e-7)
        assert ifc_world_volume(by[e.name]) == pytest.approx(want, rel=1e-6)
        assert ue.get_container(by[e.name]).Name == e.level and by[e.name].is_a() == ("IfcLightFixture" if e.kind == "LIGHT" else "IfcAirTerminal")
    ceil = {x.Name: x for x in f.by_type("IfcCovering")}
    for e in eng.passage_finishes.elements:                                                     # 구멍 낸 천장판 체적
        if e.code == CEILING:
            assert ifc_world_volume(ceil[e.name]) == pytest.approx(e.volume, rel=1e-5)
    for en in eng.entrances.entrances:
        for fe in en.finishes:
            if fe.kind == "CEILING":
                assert ifc_world_volume(ceil[fe.name]) == pytest.approx(fe.shape.volume, rel=1e-5)
    from exporter.web_viewer import build_web_data
    data, packed = build_web_data(eng)
    buf = gzip.decompress(packed)
    org = np.array(data["origin"])
    seen, sh = {}, {}
    for it in (x for x in data["instances"] if x["layer"] in ("FIN_LIGHT", "FIN_DIFFUSER")):
        pos = np.frombuffer(buf, np.float32, it["nv"] * 3, it["pos"]).reshape(-1, 3).astype(float)
        for x, y, z, co, si, k, sc, s, h, eid in np.frombuffer(buf, np.float32, it["count"] * 10, it["items"]).reshape(-1, 10).astype(float):
            m = np.array([[co * sc, -si, 0], [si * sc, co, 0], [k, 0, 1]])
            nm = data["elements"][int(eid)]["name"]
            seen.setdefault(nm, []).append(pos @ m.T + [x, y, z])
            sh[nm] = (s, h)
    assert {e.name for e in cf.elements} <= set(seen)
    st = eng.cfg.station
    for e in cf.elements:
        want = np.array([v for p in (e.body, e.face) for q in p.faces() for v in q]) - org
        got = np.concatenate(seen[e.name])
        assert np.linalg.norm(want[:, None] - got[None], axis=2).min(axis=1).max() < 2e-3, e.name
        x, y, z = cf.instance(e)[:3]
        s = float(station_of(eng.cfg, np.array([[x, y]]), -300, st.length + 300)[0])
        assert sh[e.name] == pytest.approx((s, z - (eng.cfg.lv(s) - st.offset)), abs=2e-3)
    assert not {"FIN_LIGHT", "FIN_DIFFUSER"} & {c["layer"] for c in data["chunks"]}


@pytest.mark.parametrize("which", ["pas", "ent"])
def test_face_image_and_ceiling_grid_frames(which, request):
    from exporter.dae_exporter import element_materials, stair_face_frames, tread_uv
    eng = request.getfixturevalue(which)
    eng.build_3d_doc()
    frames, mats = stair_face_frames(eng), element_materials(eng)
    for e in eng.corridor_fixtures.elements:
        assert {mats[x.dxf.handle].name for x in e.face_entities} == {"조명" if e.kind == "LIGHT" else "디퓨저"}
        p = e.face
        a0, a1, v0, v1 = e.rect
        lo = min(d for _, d in p.sect)
        pts = np.array([p.point(a, v, lo) for a, v in ((a0, v0), (a0, v1), (a1, v1), (a1, v0))])
        uv = tread_uv(frames[e.face_entities[0].dxf.handle], pts)
        assert np.allclose(uv, [(0, 0), (1, 0), (1, 1), (0, 1)], atol=1e-6)                      # 면에 한 장 (u 짧은 방향)
    # 천장판 줄눈 = 기구 격자: 조명 가운데의 칸 좌표가 v 방향은 칸 가운데, 축 방향은 칸 경계
    ceil = [x for x in eng.passage_finishes.elements if x.code == CEILING and which == "pas"]
    ceil += [fe for en in eng.entrances.entrances for fe in en.finishes if fe.kind == "CEILING" and which == "ent"]
    fr = {h.dxf.handle: frames[h.dxf.handle] for x in ceil for h in x.source_element if h.dxf.handle in frames}
    assert fr
    for e in eng.corridor_fixtures.elements:
        if e.kind != "LIGHT" or (which == "ent") != e.host.startswith("EN"):
            continue
        c = np.array([cf_center(e)])
        ok = []
        for (o, u, v, w, d) in fr.values():
            if abs(u[0] - e.body.ux) < 1e-9 and abs(u[1] - e.body.uy) < 1e-9 and w == pytest.approx(0.6 / math.sqrt(1 + e.body.slope ** 2), rel=1e-9):
                a, b = tread_uv((o, u, v, w, d), c)[0]
                ok.append(abs(a - round(a)) < 1e-4 and abs(b % 1.0 - 0.5) < 1e-4)
        assert any(ok), e.name


def cf_center(e):
    a0, a1, v0, v1 = e.rect
    return e.face.point((a0 + a1) / 2, (v0 + v1) / 2, 0.0)


def test_section_and_path_profile(pas, ent):
    from engine.path_profile import passage_profile_items as path_items
    name = pas.passage_finishes.layouts[0].name
    it = path_items(pas, name, 0.0)
    e = next(x for x in els(pas, name, "DIFFUSER") if abs(x.rect[2] + x.rect[3]) < 1e-9)
    assert any(i.name == e.name and i.layer == "PROF_FINISH" for i in it)
    L = els(ent, "EN1", "LIGHT")[0]
    it = path_items(ent, "EX1", (L.rect[2] + L.rect[3]) / 2)
    names = {i.name for i in it}
    assert L.name in names
    x, y, _ = cf_center(L)
    s, _ = ent.cfg.to_station(x, y)
    sec = {i.name for i in ent.corridor_fixtures.section_items(s)}
    assert L.name in sec and ent.corridor_fixtures.plan_items(2.0, 1) == []


def test_settings_by_passage_and_entrance_finish():
    cfg = cfg_p()
    t = dict(cfg.finish_settings.table)
    t["어둠"] = dataclasses.replace(t["통로"], name="어둠", light_s=0.0, light_t=0.0)
    cfg.finish_settings = FinishSettings(enabled=True, table=t)
    cfg.passages[1].finish = "어둠"
    eng = StationCADEngine(cfg)
    assert els(eng, "A", "LIGHT") and not els(eng, "B", "LIGHT") and els(eng, "B", "DIFFUSER")     # 통로마다 마감 종류
    assert all(e.face.volume == pytest.approx(true_len(e) / math.sqrt(1 + e.body.slope ** 2) * (e.rect[3] - e.rect[2]) * FACE[e.kind]) for e in eng.corridor_fixtures.elements)
