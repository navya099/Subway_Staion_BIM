"""천장 기구 (매입 조명·디퓨저): 자동 격자 배치, 천장판·천장틀 비우기, 겹침·체적, IFC, 웹 뷰어 배치(인스턴스) 자료, 천장판 텍스처 격자, 입력"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataclasses
import gzip
import itertools
import json

import ifcopenshell
import numpy as np
import pytest

from config.widening import WidenSpec
from engine.cad_engine import StationCADEngine
from finishes.finish_check import check_finish_type
from finishes.finish_spec import FinishType, default_finishes
from fixtures.fixture_layout import CELL, DIFF, EDGE, FACE, LIGHT_L, LIGHT_W, spread
from helper import prism_member as PM
from helper.strip_member import _fan
from rooms.room_spec import RoomSpec
from smokewalls.smoke_spec import SmokeBarrierSettings
from stairs.stair_spec import StairSpec
from test_finishes import cfg_with, ifc_world_volume
from test_widening import cfg_w


def lit(light=2.4, diff=4.8):
    return {k: (dataclasses.replace(v, light_s=light, light_t=light, diff_gap=diff) if v.ceiling else v) for k, v in default_finishes().items()}


def rects(eng, kind=None, room=None):
    return [e for e in eng.fixtures.elements if (kind is None or e.kind == kind) and (room is None or e.room == room)]


def hit(a, b, tol=1e-6):
    return min(a[1], b[1]) - max(a[0], b[0]) > tol and min(a[3], b[3]) - max(a[2], b[2]) > tol


def plan(p):
    return (*PM.s_range(p), *PM.t_range(p))


def on_grid(x, half=False):
    r = (x / CELL - (0.5 if half else 0.0)) % 1.0
    return min(r, 1.0 - r) < 1e-6


# ===================================================== 배치
def test_spread_and_defaults():
    assert spread(0, 10, 2.4) == pytest.approx([1.25, 3.75, 6.25, 8.75])
    assert spread(0, 1, 2.4) == pytest.approx([0.5])
    assert not any(ft.has_light or ft.has_diffuser for ft in default_finishes().values())          # 모델 기본은 없음
    assert not FinishType(ceiling=False, light_s=2.4, light_t=2.4, diff_gap=4.8).has_light          # 천장이 없으면 없음
    for kw, msg in ((dict(light_s=2.4), "두 방향"), (dict(light_s=0.5, light_t=2.4), "1.2m 이상"), (dict(diff_gap=0.6), "디퓨저 간격"),
                    (dict(light_s=-1), "조명 간격")):
        with pytest.raises(ValueError, match=msg):
            check_finish_type(FinishType(**kw))
    eng = StationCADEngine(cfg_with(no_cols=True))
    assert not eng.fixtures.elements


def test_grid_room_positions_and_counts():
    eng = StationCADEngine(cfg_with(RoomSpec(2, "역무실", 20, 44, -9, -2, name="OFF"), table=lit(), no_cols=True))
    L, D = rects(eng, "LIGHT", "OFF"), rects(eng, "DIFFUSER", "OFF")
    ft = eng.cfg.finish_settings.for_room("역무실")
    n_s, n_t = round((24 - 0.2 - 2 * ft.pface) / 2.4), round((7 - 0.1 - ft.pface - ft.face) / 2.4)
    assert len(L) == n_s * n_t and {e.along for e in L} == {"s"}
    for e in L:
        s0, s1, t0, t1 = e.rect
        assert (s1 - s0, t1 - t0) == pytest.approx((LIGHT_L, LIGHT_W))
        assert on_grid((s0 + s1) / 2) and on_grid((t0 + t1) / 2, half=True)                         # 진행방향 두 칸, t 는 칸 가운데
    for e in D:
        s0, s1, t0, t1 = e.rect
        assert s1 - s0 == pytest.approx(DIFF) and on_grid((s0 + s1) / 2, True) and on_grid((t0 + t1) / 2, True)
    assert D and len({round(e.rect[2], 3) for e in L}) == n_t
    # 실 천장 안 (벽 마감 표면에서 EDGE 이상)
    for e in L + D:
        assert 20 + 0.1 + ft.pface + EDGE - 1e-6 <= e.rect[0] and e.rect[1] <= 44 - 0.1 - ft.pface - EDGE + 1e-6
        assert -9 + ft.face + EDGE - 1e-6 <= e.rect[2] and e.rect[3] <= -2 - 0.1 - ft.pface - EDGE + 1e-6
    # 세로로 긴 실은 조명이 t 방향
    eng = StationCADEngine(cfg_with(RoomSpec(2, "역무실", 20, 24, -9, 8, name="OFF"), table=lit(), no_cols=True))
    L = rects(eng, "LIGHT", "OFF")
    assert L and {e.along for e in L} == {"t"}
    assert all(e.rect[3] - e.rect[2] == pytest.approx(LIGHT_L) and on_grid((e.rect[2] + e.rect[3]) / 2) for e in L)


@pytest.fixture(scope="module")
def busy():
    cfg = cfg_with(RoomSpec(2, "역무실", 20, 40, 2, 9, name="OFF"), RoomSpec(2, "기계실", 60, 80, -9, -3, name="MEC"), table=lit(),
                   stairs=[StairSpec(lower_floor=2, s_start=100.0, direction=1, t_center=-6.0, width=2.0, name="ST")])
    cfg.smoke_settings = SmokeBarrierSettings(enabled=True)
    return StationCADEngine(cfg)


def test_no_overlap_with_ceiling_frames_walls_openings(busy):
    eng = busy
    cfg = eng.cfg
    ops = [(o.s_start, o.s_end, o.t_lo, o.t_hi) for o in cfg.all_openings()]
    for n in (1, 2, 3):
        els = [e for e in eng.fixtures.elements if e.floor == n]
        assert els
        for a, b in itertools.combinations(els, 2):
            assert not hit(a.rect, b.rect), (a.name, b.name)
        names = {r.name for r in eng.finishes.rooms if r.floor == n}
        fin = [(x.name, x.code, p) for x in eng.finishes.all_elements() if f"FIN_{x.room}" in names for p in x.pieces
               if x.code in ("CEILING", "FRAME", "WALL", "COLUMN")]
        for e in els:
            for nm, code, p in fin:
                if not hit(e.rect, plan(p)):
                    continue
                z0 = PM.z_off(cfg, p)
                for q in (e.body, e.face):
                    a0 = PM.z_off(cfg, q)
                    assert min(a0 + q.shape.height, z0 + p.shape.height) - max(a0, z0) < 1e-6, (e.name, nm, code)
            if n < 3:
                assert not any(hit(e.rect, o) for o, op in zip(ops, cfg.all_openings()) if n in op.slabs)
        for fn, s, t, hs, ht, rad in eng.finishes._columns(eng.columns):                              # 원기둥 둘레 마감과 떨어짐
            for e in els:
                assert fn != n or rad is None or not hit(e.rect, (s - rad, s + rad, t - rad, t + rad))
    smoke = [tuple(q[:4]) for sb in __import__("smokewalls.smoke_layout", fromlist=["x"]).layout_smoke_barriers(cfg) for ps in sb.parts.values() for q in ps]
    assert smoke and not any(hit(e.rect, q) for e in eng.fixtures.elements if e.floor == 2 for q in smoke)
    assert not rects(eng, room="MEC")                                                              # 천장 없는 실
    assert all(e.rect[2] > 3.9 - 1e-9 or e.rect[3] < -3.9 + 1e-9 for e in eng.fixtures.elements if e.floor == 1)   # 승강장 위만


def test_ceiling_area_is_cut_exactly(busy):
    cfg = busy.cfg
    table = {k: dataclasses.replace(v, light_s=0.0, light_t=0.0, diff_gap=0.0) for k, v in cfg.finish_settings.table.items()}
    import copy
    c2 = copy.deepcopy(cfg)
    c2.finish_settings = dataclasses.replace(cfg.finish_settings, table=table)
    bare = StationCADEngine(c2)
    for r, q in zip(busy.finishes.rooms, bare.finishes.rooms):
        if r.element("CEILING") is None:
            continue
        area = lambda e: sum(p.shape.length * p.shape.width for p in e.pieces)
        holes = sum((e.rect[1] - e.rect[0]) * (e.rect[3] - e.rect[2]) for e in rects(busy, room=r.room))
        assert area(r.element("CEILING")) == pytest.approx(area(q.element("CEILING")) - holes, rel=1e-9)
        assert r.element("FLOOR").volume == pytest.approx(q.element("FLOOR").volume)               # 바닥·벽은 그대로
        assert r.element("WALL").volume == pytest.approx(q.element("WALL").volume)


def test_heights_and_volume(busy):
    for e in busy.fixtures.elements:
        r = next(x for x in busy.finishes.rooms if x.room == e.room)
        assert e.z == pytest.approx(r.ceiling_rel)
        assert PM.z_off(busy.cfg, e.face) == pytest.approx(e.z - FACE[e.kind]) and PM.z_off(busy.cfg, e.body) == pytest.approx(e.z)
        w, l = e.rect[1] - e.rect[0], e.rect[3] - e.rect[2]
        assert e.volume == pytest.approx(w * l * (e.depth + FACE[e.kind]))


@pytest.mark.parametrize("curved", [False, True])
def test_mesh_ifc_and_instances_agree(tmp_path, curved):
    cfg = cfg_with(RoomSpec(2, "역무실", 20, 40, 2, 9, name="OFF"), curved=curved, table=lit(4.8, 9.6), no_cols=not curved)
    eng = StationCADEngine(cfg)
    els = eng.fixtures.elements
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "f.ifc"))
    by = {x.Name: x for x in f.by_type("IfcLightFixture") + f.by_type("IfcAirTerminal")}
    assert len(by) == len(els)
    tol = 1e-4 if curved else 1e-6
    for e in els[:12] + els[-6:]:
        x = by[e.name]
        assert x.is_a() == ("IfcLightFixture" if e.kind == "LIGHT" else "IfcAirTerminal")
        assert x.PredefinedType == ("DIRECTIONSOURCE" if e.kind == "LIGHT" else "DIFFUSER")
        quads = [q for p in (e.body, e.face) for q in PM.sweep_quads(PM.rings(cfg, p))]
        quads = [t for q in quads for t in _fan(q)] if curved else quads
        assert PM.mesh_volume(quads) == pytest.approx(e.volume, rel=tol)
        assert ifc_world_volume(x) == pytest.approx(e.volume, rel=tol)
    # 천장틀·천장판(삼각형 면 집합) 체적도 그대로
    for x in eng.finishes.all_elements():
        if x.code in ("FRAME", "CEILING") and x.room == "OFF":
            el = next(q for q in f.by_type("IfcProduct") if q.Name == x.name)
            assert ifc_world_volume(el) == pytest.approx(x.volume, rel=1e-4 if curved else 1e-6)
    # 웹 뷰어 배치: 변환한 꼭짓점 = 3D DXF 의 3DFACE 꼭짓점
    from exporter.web_viewer import build_web_data
    data, packed = build_web_data(eng)
    buf = gzip.decompress(packed)
    org = np.array(data["origin"])
    seen = {}
    for it in data["instances"]:
        pos = np.frombuffer(buf, np.float32, it["nv"] * 3, it["pos"]).reshape(-1, 3).astype(float)
        rows = np.frombuffer(buf, np.float32, it["count"] * 10, it["items"]).reshape(-1, 10).astype(float)
        idx = np.frombuffer(buf, np.uint32, it["nt"] * 3, it["idx"])
        assert idx.max() < it["nv"] and it["nt"] == 12
        for x, y, z, co, si, k, sc, s, h, eid in rows:
            m = np.array([[co * sc, -si, 0], [si * sc, co, 0], [k, 0, 1]])
            seen.setdefault(data["elements"][int(eid)]["name"], []).append(pos @ m.T + [x, y, z])
    assert set(seen) == {e.name for e in els} and data["instanced_triangles"] == 24 * len(els)
    step = max(1, len(els) // 25)
    for e in els[::step]:
        want = np.array(sorted({tuple(np.round(np.array(v) - org, 4)) for p in (e.body, e.face) for q in PM.mesh_faces(cfg, p) for v in q}))
        got = np.concatenate(seen[e.name])
        d = np.linalg.norm(want[:, None, :] - got[None, :, :], axis=2).min(axis=1)
        assert d.max() < (3e-3 if curved else 1e-3), (e.name, d.max())
    layers = {c["layer"] for c in data["chunks"]}
    assert not layers & {"FIN_LIGHT", "FIN_DIFFUSER"}                                                # 묶음에는 되풀이하지 않음
    groups = {g["name"]: g["on"] for g in data["groups"]}
    assert groups["조명·디퓨저"] and groups["천장판"] and not groups["천장틀"]
    light = [it for it in data["instances"] if it["light"]]
    assert light and all(it["tex"] == "light_on" for it in light) and "light_off" in data["images"]


def test_pocket_room_fixtures():
    cfg = cfg_w(WidenSpec(side=1, floors=[2], s_start=50, s_end=80, amount=2.0))
    cfg.finish_settings.enabled = True
    cfg.finish_settings.table = lit()
    eng = StationCADEngine(cfg)
    els = [e for e in eng.fixtures.elements if e.floor == 2]
    assert els
    ceil = [p for x in eng.finishes.all_elements() if x.code == "CEILING" and x.level == "B2F" for p in x.pieces]
    for e in els:
        m = ((e.rect[0] + e.rect[1]) / 2, (e.rect[2] + e.rect[3]) / 2)
        for p in ceil:
            s0, s1 = PM.s_range(p)
            if s0 + 1e-6 < m[0] < s1 - 1e-6:
                t0, t1 = PM.t_range_at(p, m[0])
                assert not t0 + 1e-6 < m[1] < t1 - 1e-6
    assert any(e.rect[3] > 9.0 for e in els)                                                        # 넓어진 포켓 천장에도


# ===================================================== 텍스처 · 도면 · 입력
def test_textures_and_ceiling_grid():
    from exporter.dae_exporter import element_materials, stair_face_frames, tread_uv
    cfg = cfg_with(RoomSpec(2, "역무실", 20, 40, 2, 9, name="OFF"), table=lit(), no_cols=True)
    eng = StationCADEngine(cfg)
    eng.build_3d_doc()
    mats, frames = element_materials(eng), stair_face_frames(eng)
    for e in eng.fixtures.elements[:40]:
        for ent in e.face_entities:
            assert mats[ent.dxf.handle].texture == ("light_on" if e.kind == "LIGHT" else "diffuser") and ent.dxf.handle in frames
        assert all(mats[ent.dxf.handle].texture == "" for ent in e.body_entities)
        s0, s1, t0, t1 = e.rect
        fr = frames[e.face_entities[0].dxf.handle]
        pts = np.array([[*cfg.to_world(s, t), 0.0] for s, t in ((s0, t0), (s1, t1))])
        assert tread_uv(fr, pts) == pytest.approx(np.array([[0, 0], [1, 1]]), abs=1e-3)               # 이미지 한 장
    n = 0
    for x in eng.finishes.all_elements():                                                            # 천장판 줄눈 = 정거장 0.6 격자
        if x.code != "CEILING":
            continue
        for ent in x.source_element:
            fr = frames.get(ent.dxf.handle)
            if fr is None:
                continue
            for s, t in ((30.0, 1.2), (30.6, 2.4), (90.0, -3.0)):
                uv = tread_uv(fr, np.array([[*cfg.to_world(s, t), 0.0]]))[0]
                assert abs(uv - np.round(uv)).max() < 2e-3
            n += 1
    assert n > 10


def test_section_profile_items():
    cfg = cfg_with(RoomSpec(2, "역무실", 20, 40, 2, 9, name="OFF"), table=lit(), no_cols=True)
    eng = StationCADEngine(cfg)
    e = rects(eng, "LIGHT", "OFF")[0]
    sec = [i for i in eng.fixtures.section_items((e.rect[0] + e.rect[1]) / 2) if i.name == e.name]
    assert len(sec) == 2 and {i.layer for i in sec} == {"SEC_FINISH"}
    assert [i for i in eng.fixtures.profile_items((e.rect[2] + e.rect[3]) / 2) if e.name in i.name]
    assert eng.fixtures.plan_items(2.0, 2) == []


def test_drafts_and_old_project(tmp_path):
    from gui.finish_draft import FinishDrafts, FinishTypeDraft, preview
    from gui.project_file import ProjectState, open_project, save_project
    by = {x.name: x for x in FinishDrafts().items}
    assert (by["대합실"].light_s, by["대합실"].diff_gap) == ("2.4", "4.8") and by["기계실"].light_s == "0"
    assert "조명 2.4×2.4 간격" in preview(by["대합실"]) and "디퓨저 4.8 간격" in preview(by["대합실"])
    assert FinishDrafts().to_settings().table["대합실"].has_light
    bad = FinishTypeDraft(light_s="x")
    with pytest.raises(ValueError, match="조명 간격 s"):
        bad.to_type("마감")
    assert FinishTypeDraft(ceiling=False, light_s="x").to_type("").has_light is False                  # 천장 없으면 검사하지 않음
    st = ProjectState()
    st.finish_drafts = [FinishTypeDraft(name="A", light_s="3", diff_gap="0"), FinishTypeDraft(name="B", ceiling=False)]
    save_project(tmp_path / "a.ssbim", st)
    back = open_project(tmp_path / "a.ssbim").finish_drafts
    assert [(x.light_s, x.diff_gap) for x in back] == [("3", "0"), ("0", "0")]
    raw = json.loads((tmp_path / "a.ssbim").read_text(encoding="utf-8"))

    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ("light_s", "light_t", "diff_gap")}
        return [strip(x) for x in o] if isinstance(o, list) else o
    (tmp_path / "b.ssbim").write_text(json.dumps(strip(raw), ensure_ascii=False), encoding="utf-8")
    assert [x.light_s for x in open_project(tmp_path / "b.ssbim").finish_drafts] == ["2.4", "0"]


def test_template_has_lights():
    from exporter.live_viewer import live_html
    html = live_html()
    assert 'id="lights"' in html and "InstancedMesh" in html and "lightState" in html
