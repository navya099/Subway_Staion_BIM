"""배치 객체(비품): 종류 등록부 형상, 벽 붙임·높이, 겹침 오류, 2D·3D·IFC, 웹 뷰어 배치 자료, 입력 초안·프로젝트 파일"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gzip
import itertools
import json
import math

import ifcopenshell
import ifcopenshell.util.element
import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from gui.prop_draft import ANGLES, PropDraft, PropDrafts, default_values, new_draft, preview, titles
from gui.project_file import ProjectState, open_project, save_project
from helper.prism_member import mesh_volume
from openings.opening_kind import OpeningKind
from openings.opening_spec import OpeningSpec
from props.prop_check import circle, depth, rect
from props.prop_kinds import CEILING, FLOOR, HANG, INT, KINDS, NUM, TEXT, WALL
from props.prop_spec import PropSpec, check_props, resolve_prop_names
from rooms.room_spec import DoorSpec, RoomSpec
from stairs.stair_spec import StairSpec
from test_finishes import cfg_with, ifc_world_volume


def values(kind, **kw):
    return {**{f.key: f.default for f in KINDS[kind].fields}, "ceil": 4.0, **kw}


def engine(*specs, **kw):
    kw.setdefault("no_cols", not kw.get("curved"))
    rooms = kw.pop("rooms", [])
    return StationCADEngine(cfg_with(*rooms, props=list(specs), **kw))


def prop(kind, s, t, floor=2, angle=0.0, name="", **vals):
    return PropSpec(kind=kind, floor=floor, s=s, t=t, angle=angle, values=vals, name=name)


# ===================================================== 등록부
def test_kinds_cover_requested_list():
    assert set(KINDS) == {"BENCH", "BIN", "EXT", "TVM", "GATE", "HYDRANT", "PANEL_W", "PANEL_C", "HSIGN"}
    assert {c for c, k in KINDS.items() if k.mount == WALL} == {"HYDRANT", "PANEL_W"}
    assert KINDS["PANEL_C"].mount == CEILING and KINDS["HSIGN"].mount == HANG and KINDS["BENCH"].mount == FLOOR


@pytest.mark.parametrize("kind", list(KINDS))
def test_shapes_do_not_overlap_and_are_counter_clockwise(kind):
    parts = KINDS[kind].build(values(kind))
    for p in parts:
        assert p.z1 > p.z0 and p.volume > 0                                                  # 반시계 (양의 면적)
        if p.image:
            xs = [q[0] for q in p.poly]
            assert len(p.poly) == 4 and p.poly[0] == (min(xs), min(q[1] for q in p.poly))    # 그림 면 번호 규약 (변 1 = +x, 변 3 = −x)
    for a, b in itertools.combinations(parts, 2):
        assert min(a.z1, b.z1) - max(a.z0, b.z0) < 1e-9 or depth(list(a.poly), list(b.poly)) < 1e-9, (kind, a, b)
    z0, z1 = min(p.z0 for p in parts), max(p.z1 for p in parts)
    assert (z1 <= 1e-9) if KINDS[kind].mount == CEILING else z0 >= -1e-9
    if KINDS[kind].mount == WALL:
        assert min(q[0] for p in parts for q in p.poly) == pytest.approx(0.0)                # 뒷면 = 벽
    if KINDS[kind].images:
        imgs = KINDS[kind].images(values(kind))
        assert {p.image for p in parts if p.image} == set(imgs)
        for fn in imgs.values():
            im = fn()
            assert im.width > 10 and im.height > 10


def test_shapes_follow_values():
    gate = KINDS["GATE"].build(values("GATE", n=3, lane=0.7, wide=1.0, cab=0.25))
    ys = [q[1] for p in gate for q in p.poly]
    assert max(ys) - min(ys) == pytest.approx(3 * 0.7 + 1.0 + 5 * 0.25)                       # 통로 3 + 넓은 통로 1, 캐비닛 5
    gate = KINDS["GATE"].build(values("GATE", n=2, wide=0.0))
    assert len([p for p in gate if p.z0 == 0.0]) == 3
    assert len([p for p in KINDS["BIN"].build(values("BIN", n=3)) if p.z0 == 0.0]) == 3
    short = KINDS["HSIGN"].build(values("HSIGN", ceil=3.5))
    assert max(p.z1 for p in short) == 3.5
    assert len(KINDS["HSIGN"].build(values("HSIGN", ceil=2.95))) == 3                        # 천장에 바로 붙으면 행거 없음


def test_depth_and_circle():
    a = rect(0, 2, 0, 2)
    assert depth(a, rect(1.5, 3, 0, 2)) == pytest.approx(0.5) and depth(a, rect(2, 3, 0, 2)) <= 1e-12
    assert depth(a, rect(2.1, 3, 0, 2)) < 0
    c = circle(3.0, 1.0, 0.9)
    assert depth(a, c) < 0.0 and min(math.hypot(x - 3, y - 1) for x, y in c) >= 0.9 - 1e-9   # 외접 다각형


# ===================================================== 입력 검사
def test_spec_checks():
    cfg = cfg_with(no_cols=True)
    assert cfg.props == []
    for sp, msg in ((prop("XX", 10, 0), "종류"), (prop("BENCH", 10, 0, floor=9), "층 번호"), (prop("BENCH", 10, 0, q=1), "알 수 없는 입력"),
                    (prop("BENCH", 10, 0, w=0.1), "길이"), (prop("BIN", 10, 0, n=1.5), "정수"), (prop("GATE", 10, 0, lane=0.4), "통로 폭"),
                    (prop("BENCH", 10, 0, back_h=0.5), "등받이"), (prop("HSIGN", 10, 0, bg="blue"), "#RRGGBB"), (prop("HSIGN", 10, 0, z=1.8), "하단")):
        cfg.props = [sp]
        with pytest.raises(ValueError, match=msg):
            check_props(cfg)
    cfg.props = [prop("BENCH", 10, 0, name="A"), prop("BIN", 20, 0, name="A")]
    with pytest.raises(ValueError, match="중복"):
        check_props(cfg)
    assert resolve_prop_names([prop("BENCH", 0, 0), prop("EXT", 0, 0), prop("BENCH", 0, 0), prop("BENCH", 0, 0, name="X")]) == \
        ["의자 1", "소화기 1", "의자 2", "X"]


# ===================================================== 배치
def test_heights_follow_floor_finish_platform_and_ceiling():
    eng = engine(prop("BENCH", 40, 0, floor=2), prop("BENCH", 40, 6, floor=1), prop("PANEL_C", 50, 0), prop("HSIGN", 60, 0), prop("EXT", 45, 0, floor=3))
    cfg, by = eng.cfg, {e.name: e for e in eng.props.elements}
    ft = cfg.finish_settings.for_room("대합실")
    fl = cfg.station.floor_level
    assert by["의자 1"].z == pytest.approx(fl(2) + ft.ffl)
    r1 = next(r for r in eng.finishes.rooms if r.floor == 1)
    assert by["의자 2"].z > fl(1) + 0.5 and by["의자 2"].z == pytest.approx(r1.ceiling_rel - cfg.finish_settings.for_room("승강장층").ceiling_h)
    assert by["천장 점검구 1"].z == pytest.approx(fl(2) + ft.ffl + ft.ceiling_h)                # 천장판 하면
    rods = [p for p in by["매달림 안내사인 1"].parts if p.z1 > 2.96]
    assert len(rods) == 2 and [p.z1 for p in rods] == pytest.approx([ft.ceiling_h] * 2)          # 천장판까지 행거
    assert by["소화기 1"].level == "B1F" and by["의자 1"].pos_z == pytest.approx(cfg.lv(40) - cfg.station.offset + by["의자 1"].z)


def test_wall_kinds_snap_to_finish_surface_and_face_away():
    room = RoomSpec(2, "역무실", 20, 40, 2, 9, name="OFF")
    eng = engine(prop("HYDRANT", 60, 8.7, name="H+"), prop("HYDRANT", 60, -8.6, name="H-", angle=45.0), prop("PANEL_W", 70, 8.8, name="PN"),
                 prop("PANEL_W", 30, 1.7, name="PART"), prop("HYDRANT", 0.4, 0, name="END"), rooms=[room])
    cfg, by = eng.cfg, {e.name: e for e in eng.props.elements}
    face = cfg.finish_settings.for_room("대합실").face
    assert (by["H+"].t, by["H+"].angle) == pytest.approx((9.0 - face, 270.0)) and by["H+"].s == 60
    assert (by["H-"].t, by["H-"].angle) == pytest.approx((-9.0 + face, 90.0))                 # 입력 방향은 안 씀
    pf = cfg.finish_settings.for_room("대합실").pface
    assert (by["PART"].t, by["PART"].angle) == pytest.approx((2.0 - 0.1 - pf, 270.0))         # 칸막이벽 바깥(대합실) 쪽 마감 표면
    assert (by["END"].s, by["END"].angle) == pytest.approx((face, 0.0))                       # 시점 마감벽
    for e in by.values():                                                                     # 몸은 벽 앞, 뒷면이 벽 표면
        n = math.radians(e.angle)
        ds = [(s - e.s) * math.cos(n) + (t - e.t) * math.sin(n) for p in e.parts for s, t in e.local(p)]
        assert min(ds) == pytest.approx(0.0, abs=1e-9)
    with pytest.raises(ValueError, match="0.5m 안에 붙일 벽이 없습니다"):
        engine(prop("HYDRANT", 60, 5.0))
    eng = engine(prop("HYDRANT", 60, 8.8), table=None)                                        # 마감을 끄면 구조 벽
    cfg2 = cfg_with(no_cols=True, props=[prop("HYDRANT", 60, 8.8)])
    cfg2.finish_settings.enabled = False
    assert StationCADEngine(cfg2).props.elements[0].t == pytest.approx(9.0)


@pytest.mark.parametrize("spec, kw, msg", [
    (prop("BENCH", 20.0, 5.0), dict(rooms=[RoomSpec(2, "역무실", 20, 40, 2, 9, name="OFF")]), "칸막이벽"),
    (prop("BENCH", 30.0, 2.0), dict(rooms=[RoomSpec(2, "역무실", 20, 40, 2, 9, name="OFF", doors=[DoorSpec("-t", 30.0)])]), "문|칸막이벽"),
    (prop("BENCH", 60.0, 8.7), {}, "마감|내공"),
    (prop("BENCH", 60.0, 12.0), {}, "실 안이 아닙니다"),
    (prop("BENCH", 91.0, -6.0, floor=2), dict(stairs=[StairSpec(lower_floor=2, s_start=90.0, direction=1, t_center=-6.0, width=2.0, name="ST")]), "계단 ST"),
    (prop("BENCH", 60.0, 0.0, floor=2), dict(openings=[OpeningSpec(slabs={1}, s_start=58, length=4, t_center=0, width=2, kind=OpeningKind.STAIR)]), "오프닝"),
    (prop("BENCH", 60.0, 3.9, floor=1), {}, "승강장 끝"),
    (prop("TVM", 60.0, 0.0, floor=2, h=3.2), {}, "천장|마감"),
    (prop("HSIGN", 60.0, 0.0, floor=2, z=2.9), {}, "천장|마감"),
])
def test_overlap_errors(spec, kw, msg):
    with pytest.raises(ValueError, match=msg):
        engine(spec, **kw)


def test_overlap_with_columns_and_other_props():
    eng0 = StationCADEngine(cfg_with())
    fn, s, t, *_ = next(c for c in eng0.finishes._columns(eng0.columns) if c[0] == 2)
    with pytest.raises(ValueError, match="기둥"):
        engine(prop("BIN", s, t), no_cols=False)
    with pytest.raises(ValueError, match="비품 의자 1 과"):
        engine(prop("BENCH", 60, 0), prop("BIN", 60.2, 0))
    engine(prop("BENCH", 60, 0), prop("BENCH", 60.5, 0))                                       # 맞닿음은 허용 (깊이 0.5)
    engine(prop("BENCH", 60, 0), prop("HSIGN", 60, 0))                                         # 높이가 떨어져 있으면 허용
    engine(prop("BENCH", 60, 6.0, floor=1), prop("BENCH", 60, 6.0, floor=2))                   # 다른 층


@pytest.mark.parametrize("angle", [0.0, 90.0, 37.0])
def test_hanging_sign_rods_avoid_ceiling_fixtures(angle):
    """행거 끝이 천장판 아래로 나온 조명·디퓨저 면과 만나면 옆으로 옮김 (사용자 화면에서 오류로 막히던 경우)"""
    from props.prop_engine import PropEngine
    from props.prop_kinds import rod_ys
    from test_fixtures import lit
    eng = engine(table=lit())
    moved = 0
    for s in np.arange(60.0, 64.8, 0.35):
        for t in np.arange(-3.0, 3.0, 0.7):
            eng.cfg.props = [prop("HSIGN", float(s), float(t), angle=angle)]
            (e,) = PropEngine(eng.cfg, eng).elements                                           # 오류 없이 놓임
            ys = e.values["rods"]
            assert -1.15 - 1e-9 <= ys[0] and ys[1] <= 1.15 + 1e-9 and ys[1] - ys[0] >= 0.6 - 1e-9
            moved += ys != rod_ys(2.4)
            for p in e.parts[3:]:
                for x in eng.fixtures.elements:
                    if x.floor == 2:
                        assert depth(e.local(p), rect(*x.rect)) <= 1e-9
    assert moved > 5
    eng.cfg.props = [prop("HSIGN", 60.0, 0.0)]
    assert PropEngine(eng.cfg, engine()).elements[0].values["rods"] == pytest.approx(rod_ys(2.4))      # 기구가 없으면 기본 자리
    x = next(q for q in eng.fixtures.elements if q.floor == 2 and q.kind == "LIGHT")
    eng.cfg.props = [prop("PANEL_C", (x.rect[0] + x.rect[1]) / 2, (x.rect[2] + x.rect[3]) / 2)]
    with pytest.raises(ValueError, match=r"천장 기구 LT_.* 4mm 겹칩니다"):
        PropEngine(eng.cfg, eng)


def test_rotation_matters_for_overlap():
    """긴 의자: 0도면 t 방향 1.8, 90도면 s 방향 1.8 — 옆 비품과 겹침 여부가 달라짐"""
    engine(prop("BENCH", 60, 0, angle=0), prop("EXT", 60.6, 0))
    with pytest.raises(ValueError, match="겹칩니다"):
        engine(prop("BENCH", 60, 0, angle=90), prop("EXT", 60.6, 0))
    engine(prop("BENCH", 60, 0, angle=45), prop("EXT", 60.9, 0.9))


# ===================================================== 3D · 2D · IFC
ALL = [prop("BENCH", 40, 1, angle=30.0), prop("BIN", 45, 0, angle=90.0), prop("EXT", 48, 1), prop("TVM", 52, 2, angle=270.0), prop("GATE", 60, 0),
       prop("HYDRANT", 66, 8.7), prop("PANEL_W", 70, -8.7), prop("PANEL_C", 74, 2), prop("HSIGN", 80, 1), prop("BENCH", 90, 6.5, floor=1)]


@pytest.mark.parametrize("curved", [False, True])
def test_mesh_formula_ifc_and_web_agree(tmp_path, curved):
    specs = ALL if not curved else [p for p in ALL if p.kind not in ("HYDRANT", "PANEL_W")] + [prop("HYDRANT", 66, -8.7)]
    eng = engine(*specs, curved=curved, table=None)
    pe, els = eng.props, eng.props.elements
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    by = {x.Name: x for x in f.by_type("IfcProduct") if x.Name}
    for e in els:
        faces = [q for p in e.parts for q in pe.part_faces(e, p)]
        assert mesh_volume(faces) == pytest.approx(e.volume, rel=1e-6) and e.volume > 0         # 바깥 면
        el = by[e.name]
        assert el.is_a() == KINDS[e.kind].ifc[0] and el.PredefinedType == KINDS[e.kind].ifc[1] and el.ObjectType == e.kind
        assert ifc_world_volume(el) == pytest.approx(e.volume, rel=1e-5)
        assert ifcopenshell.util.element.get_container(el).Name == e.level
        ps = ifcopenshell.util.element.get_psets(el)["SSBIM_Prop"]
        assert ps["Kind"] == KINDS[e.kind].label and all(x.label in ps for x in KINDS[e.kind].fields)
        zs = [v[2] for q in faces for v in q]                                                   # 연직·수평 (종단구배를 따르지 않음)
        assert min(zs) == pytest.approx(eng.cfg.lv(e.s) - eng.cfg.station.offset + e.z + min(p.z0 for p in e.parts))
    # 3D DXF 면 = 공식
    doc = eng.build_3d_doc()
    q3 = [d for d in doc.modelspace().query("3DFACE") if d.dxf.layer == "STRUCT_PROP"]
    vol = mesh_volume([tuple(v - doc_o for v in (d.dxf.vtx0, d.dxf.vtx1, d.dxf.vtx2, d.dxf.vtx3)) for d in q3] if (doc_o := q3[0].dxf.vtx0) else [])
    assert vol == pytest.approx(sum(e.volume for e in els), rel=1e-6)
    # 웹 뷰어: 배치로만 보내고, 변환한 꼭짓점 = 3D 면 꼭짓점
    from exporter.web_viewer import build_web_data
    data, packed = build_web_data(eng)
    assert "STRUCT_PROP" not in {c["layer"] for c in data["chunks"]}
    assert "비품" in {g["name"] for g in data["groups"]}
    buf = gzip.decompress(packed)
    seen, tri = {}, 0
    for it in (x for x in data["instances"] if x["layer"] == "STRUCT_PROP"):
        assert it["solid"] and not it["light"]
        pos = np.frombuffer(buf, np.float32, it["nv"] * 3, it["pos"]).reshape(-1, 3).astype(float)
        rows = np.frombuffer(buf, np.float32, it["count"] * 10, it["items"]).reshape(-1, 10).astype(float)
        idx = np.frombuffer(buf, np.uint32, it["nt"] * 3, it["idx"])
        assert idx.max() < it["nv"]
        tri += it["nt"] * it["count"]
        if it["tex"]:
            assert it["tex"] in data["images"] and np.frombuffer(buf, np.float32, it["nv"] * 2, it["uv"]).max() == 1.0
        for x, y, z, co, si, k, sc, s, h, eid in rows:
            assert (k, sc) == (0.0, 1.0)
            m = np.array([[co, -si, 0], [si, co, 0], [0, 0, 1]])
            seen.setdefault(data["elements"][int(eid)]["name"], []).append(pos @ m.T + [x, y, z])
    assert set(seen) == {e.name for e in els} and tri == sum(sum(2 * (len(p.poly) - 2) + 2 * len(p.poly) for p in e.parts) for e in els)
    org = np.array(data["origin"])
    for e in els:
        want = np.array([np.array(v) - org for p in e.parts for q in pe.part_faces(e, p) for v in q])
        got = np.concatenate(seen[e.name])
        assert np.linalg.norm(want[:, None, :] - got[None, :, :], axis=2).min(axis=1).max() < 2e-3, e.name


def test_same_props_share_one_shape():
    from exporter.web_viewer import build_web_data
    eng = engine(prop("BENCH", 40, 0), prop("BENCH", 50, 0, angle=90), prop("BENCH", 60, 0, w=2.4))
    data, _ = build_web_data(eng)
    it = [x for x in data["instances"] if x["layer"] == "STRUCT_PROP"]
    assert sorted({x["count"] for x in it}) == [1, 2]                                           # 길이가 다른 의자는 따로
    assert {x["material"] for x in it} == {"스테인리스", "비품 목재"}


def test_sign_frames_map_whole_image_upright():
    eng = engine(*ALL)
    eng.build_3d_doc()
    out = eng.props.sign_images()
    assert len(out) == 4                                                                        # 발매기·옥내소화전·안내사인 앞뒤
    from exporter.dae_exporter import frame_uv
    for name, img, frame, ents in out:
        (d,) = ents
        pts = [tuple(d.dxf.get(k)) for k in ("vtx0", "vtx1", "vtx2", "vtx3")]
        uv = frame_uv(frame, np.array([pts]), np.zeros(3))[0].tolist()
        assert sorted((round(u), round(v)) for u, v in uv) == [(0, 0), (0, 1), (1, 0), (1, 1)] and np.allclose(uv, np.round(uv), atol=1e-6)
        assert uv[0] == pytest.approx((0, 0), abs=1e-6) and uv[1] == pytest.approx((1, 0), abs=1e-6)   # 아래 왼쪽 → 오른쪽 (바깥에서 볼 때)
        o, u, v, w, h, _ = frame
        n = np.cross(u, v)                                                                      # 바깥 법선 = u × v
        a, b, c = (np.array(p) for p in pts[:3])
        assert np.dot(np.cross(b - a, c - a), n) > 0
        assert img.width / img.height == pytest.approx(w / h, rel=0.02)


def test_dae_and_2d(tmp_path):
    from exporter.dae_exporter import export_dae
    eng = engine(*ALL)
    res = export_dae(eng, tmp_path / "m.dae")
    assert res and "비품 목재" in (tmp_path / "m.dae").read_text(encoding="utf-8")
    pe = eng.props
    assert {i.name for i in pe.plan_items(99.0, 2)} == {e.name for e in pe.elements if e.floor == 2}
    assert {i.name for i in pe.plan_items(99.0, 1)} == {"의자 2"}
    b = pe.elements[1]                                                                          # 쓰레기통 90도 (s 방향 폭 0.8)
    items = [i for i in pe.section_items(45.0) if i.name == b.name]
    base = eng.cfg.lv(45.0) - eng.cfg.station.offset + b.z
    assert min(i.vb0 for i in items) == pytest.approx(base) and pe.section_items(44.5) == []
    assert {i.name for i in pe.profile_items(0.0)} >= {b.name, "매달림 안내사인 1"}
    cab = min(t for p in pe.elements[4].parts for _, t in pe.elements[4].local(p)) + 0.1         # 게이트 첫 캐비닛 가운데
    assert "게이트 1" in {i.name for i in pe.profile_items(cab)} and "게이트 1" not in {i.name for i in pe.profile_items(cab + 0.4)}
    plan = eng.build_plan_doc(floors=[2])
    assert any(x.dxf.layer == "PLAN_PROP" for x in plan.modelspace())
    sec = eng.build_section_doc([45.0])
    assert any(x.dxf.layer == "SEC_PROP" for x in sec.modelspace())


def test_no_props_changes_nothing():
    a, b = engine(), StationCADEngine(cfg_with(no_cols=True))
    assert a.props.elements == [] and len(list(a.build_3d_doc().modelspace())) == len(list(b.build_3d_doc().modelspace()))
    with_p = engine(*ALL)                                                                       # 다른 부재는 그대로 (비품은 파거나 자르지 않음)
    n = lambda e: sum(1 for x in e.build_3d_doc().modelspace() if x.dxf.layer != "STRUCT_PROP")
    assert n(with_p) == n(b)


# ===================================================== 입력 초안 · 프로젝트 파일
def test_draft_defaults_and_conversion():
    for k in KINDS:
        sp = new_draft(k, 2, 134.45, -1.5).to_spec("비품", 100.0)
        assert (sp.kind, sp.floor, sp.s, sp.t) == (k, 2, pytest.approx(34.45), -1.5) and sp.resolved() == PropSpec(kind=k).resolved()
    d = PropDraft(kind="GATE", angle=ANGLES[1], sta="20")
    d.values["n"], d.values["wide"] = "6", ""
    sp = d.to_spec("비품", 0.0)
    assert sp.angle == 90.0 and sp.values["n"] == 6 and isinstance(sp.values["n"], int) and sp.resolved()["wide"] == 0.9     # 빈칸 = 기본값
    d.angle = "37.5"
    assert d.to_spec("비품", 0.0).angle == 37.5
    d.values["n"] = "2.5"
    with pytest.raises(ValueError, match="정수"):
        d.to_spec("비품 1", 0.0)
    d.set_kind("HYDRANT")
    assert d.values == default_values("HYDRANT") and d.is_wall
    d.angle = "엉터리"
    assert d.to_spec("비품", 0.0).angle == 0.0                                                   # 벽 부착은 방향을 안 씀
    d.set_kind("BENCH")
    with pytest.raises(ValueError, match="방향"):
        d.to_spec("비품 1", 0.0)


def test_drafts_titles_floors_and_preview():
    ds = PropDrafts()
    assert preview(ds, 0.0) == "→ 비품 없음"
    ds.items = [new_draft("BENCH", 3, 10), new_draft("BENCH", 1, 20), new_draft("TVM", 1, 30)]
    assert titles(ds) == ["의자 1", "의자 2", "발매기 1"] and "의자 2 · 발매기 1" in preview(ds, 0.0)
    assert ds.ensure_floors(2) and ds.items[0].floor == 2 and not ds.ensure_floors(2)
    ds.items[0].sta = "a"
    assert preview(ds, 0.0).startswith("→ 비품 1")


def test_project_file_round_trip(tmp_path):
    st = ProjectState()
    a, b = new_draft("HSIGN", 2, 33.0, 1.0), new_draft("TVM", 1, 40.0)
    a.values["text"], b.values["w"] = "나가는 곳/Exit", "1.1x"                                  # 잘못된 입력도 그대로
    st.prop_drafts = [a, b]
    save_project(tmp_path / "a.ssbim", st)
    back = open_project(tmp_path / "a.ssbim")
    assert back.prop_drafts == [a, b] and back.key() == st.key()
    raw = json.loads((tmp_path / "a.ssbim").read_text(encoding="utf-8"))
    del raw["prop_drafts"]
    assert ProjectState.from_dict(raw).prop_drafts == []                                         # 옛 파일
    raw["prop_drafts"] = [{"kind": "TVM"}]
    assert ProjectState.from_dict(raw).prop_drafts[0].values == default_values("TVM")
    raw["prop_drafts"] = [{"kind": "TVM", "values": 3}]
    with pytest.raises(ValueError, match="values"):
        ProjectState.from_dict(raw)


def test_field_types():
    for k in KINDS.values():
        assert len({f.key for f in k.fields}) == len(k.fields) and all(f.type in (NUM, INT, TEXT) for f in k.fields)
        for f in k.fields:
            assert f.type == TEXT or f.default > f.lo, (k.code, f.key)
