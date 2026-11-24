"""실 문: 문틀·문짝(양개·자동문 두 짝)·손잡이·문턱 형상, 열림 방향·경첩, 바닥 마감면 기준 높이, 겹침·체적, IFC, 웹 뷰어 문 움직임 자료, 입력"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import itertools
import math

import ifcopenshell
import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from exporter import door_anim
from helper import prism_member as PM
from rooms.door_parts import FRAME_LIP, FRAME_W, LEAF_T, hinge_low
from rooms.room_spec import DOOR_KINDS, DoorSpec, RoomSpec
from test_finishes import cfg_with, ifc_world_volume
from test_skirting import skirted

KINDS = list(DOOR_KINDS)


CFG = None                       # 지금 시험하는 설정 (box 의 높이 = FL 기준 — 종단구배를 뺌)


def box(p):
    """RoomPiece → (s0, s1, t0, t1, z0, z1) — z 는 FL 기준"""
    z = PM.z_off(CFG, p)
    return (*PM.s_range(p), *PM.t_range(p), z, z + p.shape.height)


def hit(a, b, tol=1e-6):
    return all(min(a[i + 1], b[i + 1]) - max(a[i], b[i]) > tol for i in (0, 2, 4))


def cfg_one(door, finish=True, **kw):
    """중간층 실 하나 (s 20 ~ 40, t 0 ~ 7) — 네 변 모두 칸막이벽"""
    cfg = cfg_with(RoomSpec(2, "역무실", 20, 40, 0, 7, name="OFF", doors=[door]), table=skirted(partition_face=kw.pop("pface", None)), no_cols=True)
    cfg.finish_settings.enabled = finish
    global CFG
    CFG = cfg
    return cfg


CENTER = {"+t": 30.0, "-t": 30.0, "+s": 3.5, "-s": 3.5}


@pytest.mark.parametrize("side", list(CENTER))
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("swing, hinge, pface", [("in", None, None), ("out", "left", 0.08), ("in", "right", 0.08)])
def test_no_overlap_with_walls_finishes_floor(side, kind, swing, hinge, pface):
    cfg = cfg_one(DoorSpec(side, CENTER[side], 1.4, 2.1, kind, swing=swing, hinge=hinge), pface=pface)
    eng = StationCADEngine(cfg)
    (d,) = eng.rooms.doors
    parts = [(p.name, box(p.piece)) for p in d.parts]
    others = [(pw.name, box(p)) for pw in eng.rooms.partitions for p in pw.pieces]
    others += [(e.name, box(p)) for e in eng.finishes.all_elements() for p in e.pieces if e.code != "FRAME"]
    for (n, a), (m, b) in itertools.combinations(parts, 2):
        assert not hit(a, b), (n, m)
    for n, a in parts:
        for m, b in others:
            assert not hit(a, b), (n, m, a, b)
    ft = cfg.finish_settings.for_room("역무실")                                       # 문틀 = 양쪽 마감 표면 + FRAME_LIP
    f = [b for n, b in parts if "FRAME" in n]
    lo, hi = (2, 3) if side in ("+t", "-t") else (0, 1)
    assert max(b[hi] for b in f) - min(b[lo] for b in f) == pytest.approx(0.2 + 2 * ft.pface + 2 * FRAME_LIP)
    leaves = {p.leaf for p in d.parts if p.leaf}
    assert leaves == ({1, 2} if kind in ("양개 여닫이", "자동문") else {1}) == {m.leaf for m in d.motions}


def moved(box_, m, k=1.0):
    """문짝 상자의 평면 꼭짓점을 열림 k 로 옮김 (정거장 로컬)"""
    s0, s1, t0, t1 = box_[:4]
    out = []
    for s, t in ((s0, t0), (s1, t0), (s1, t1), (s0, t1)):
        if m.kind == "slide":
            out.append((s + m.move[0] * k, t + m.move[1] * k))
        else:
            a = math.radians(m.angle * k)
            x, y = s - m.pivot[0], t - m.pivot[1]
            out.append((m.pivot[0] + x * math.cos(a) - y * math.sin(a), m.pivot[1] + x * math.sin(a) + y * math.cos(a)))
    return out


@pytest.mark.parametrize("side", list(CENTER))
@pytest.mark.parametrize("swing", ["in", "out"])
@pytest.mark.parametrize("hinge", [None, "left", "right"])
def test_swing_opens_to_chosen_side_and_hinge(side, swing, hinge):
    eng = StationCADEngine(cfg_one(DoorSpec(side, CENTER[side], 1.0, 2.1, swing=swing, hinge=hinge)))
    (d,) = eng.rooms.doors
    (m,) = d.motions
    leaf = next(box(p.piece) for p in d.parts if p.code == "LEAF")
    pts = np.array(moved(leaf, m))
    i = 1 if side in ("+t", "-t") else 0                                              # 벽 직교 좌표
    wall = {"+t": 7.0, "-t": 0.0, "+s": 40.0, "-s": 20.0}[side]
    inward = -1 if side in ("+s", "+t") else 1
    want = inward if swing == "in" else -inward
    assert ((pts[:, i] - wall) * want).min() > 0.1 and ((pts[:, i] - wall) * want).max() > 0.9      # 90° 열려 그쪽으로 나옴
    u = pts[:, 1 - i].mean() - CENTER[side]                                           # 경첩 쪽에 섬
    assert (u < 0) == hinge_low(side, hinge)
    if hinge is not None:                                                             # 실 안에서 볼 때 왼쪽/오른쪽
        view = np.array([0.0, 0.0]); view[i] = -inward
        left = np.array([-view[1], view[0]])
        assert (left[1 - i] * u > 0) == (hinge == "left")
    # 열린 문짝은 문틀·벽과 부딪히지 않음 (도는 동안에도 벽 속으로 들어가지 않음)
    frames = [box(p.piece) for p in d.parts if p.code == "FRAME"][:2]
    walls = [box(p) for pw in eng.rooms.partitions for p in pw.pieces if box(p)[5] > leaf[5]]
    for k in np.linspace(0, 1, 13):
        q = np.array(moved((leaf[0] + 1e-4, leaf[1] - 1e-4, leaf[2] + 1e-4, leaf[3] - 1e-4), m, k))
        for a in np.linspace(0, 1, 9):
            for b in np.linspace(0, 1, 5):
                s, t = (q[0] * (1 - a) * (1 - b) + q[1] * a * (1 - b) + q[2] * a * b + q[3] * (1 - a) * b)
                for f in frames + [w for w in walls if w[4] < leaf[5] - 0.5]:
                    assert not (f[0] + 2e-3 < s < f[1] - 2e-3 and f[2] + 2e-3 < t < f[3] - 2e-3), (k, s, t, f)
    # 평면 기호 = 열린 문짝 (경첩에서 문짝 폭만큼 열리는 쪽으로)
    (sym,) = d.symbol
    assert sym[0] == pytest.approx(m.pivot) and abs(sym[-1][i] - sym[0][i]) == pytest.approx(1.0 - 2 * FRAME_W - 2 * 0.004)


def test_ifc_operation_left_right_mirror():
    """경첩을 바꾸면 LEFT ↔ RIGHT, 열림 방향을 바꿔도 (보는 방향이 반대라) 바뀜"""
    ops = {}
    for swing, hinge in itertools.product(("in", "out"), ("left", "right")):
        eng = StationCADEngine(cfg_one(DoorSpec("-t", 30.0, swing=swing, hinge=hinge)))
        ops[swing, hinge] = eng.rooms.doors[0].operation
    # 바깥으로 여는 문은 실 안에서 여는 방향을 봄 → 실 안 기준 왼쪽 = LEFT, 안으로 여는 문은 밖에서 보므로 반대
    assert ops == {("out", "left"): "SINGLE_SWING_LEFT", ("out", "right"): "SINGLE_SWING_RIGHT",
                   ("in", "left"): "SINGLE_SWING_RIGHT", ("in", "right"): "SINGLE_SWING_LEFT"}


def test_height_from_finished_floor_and_sill():
    on, off = (StationCADEngine(cfg_one(DoorSpec("-t", 30.0), finish=f)) for f in (True, False))
    a, b = on.rooms.doors[0], off.rooms.doors[0]
    ffl = on.cfg.finish_settings.for_room("역무실").ffl
    assert a.ffl == pytest.approx(ffl) and b.ffl == 0
    z = lambda d, code: sorted((round(box(p.piece)[4] - box(d.opening)[4], 6), round(box(p.piece)[5] - box(d.opening)[4], 6)) for p in d.parts if p.code == code)
    assert z(a, "SILL") == [(0.0, round(ffl, 6))] and z(b, "SILL") == []
    assert z(a, "FRAME")[0] == (round(ffl, 6), round(ffl + 2.1, 6)) and z(b, "FRAME")[0] == (0.0, 2.1)
    assert z(a, "LEAF")[0][0] == pytest.approx(ffl + 0.008)
    assert a.opening.shape.height == pytest.approx(2.1 + ffl) and b.opening.shape.height == pytest.approx(2.1)
    leaf = next(p for p in a.parts if p.code == "LEAF").piece
    assert min(leaf.shape.length, leaf.shape.width) == pytest.approx(LEAF_T)


@pytest.mark.parametrize("kind", KINDS)
def test_ifc_volume_and_materials(tmp_path, kind):
    from exporter.dae_exporter import element_materials
    eng = StationCADEngine(cfg_one(DoorSpec("-t", 30.0, 1.4, 2.1, kind)))
    (d,) = eng.rooms.doors
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "d.ifc"))
    (el,) = [x for x in f.by_type("IfcDoor") if x.Name == d.name]
    mesh = sum(PM.mesh_volume(PM.mesh_faces(eng.cfg, p.piece)) for p in d.parts)
    assert mesh == pytest.approx(d.volume, rel=1e-7) and ifc_world_volume(el) == pytest.approx(d.volume, rel=1e-6)
    assert el.OverallWidth == 1.4 and el.OverallHeight == 2.1 and el.OperationType == d.operation
    assert el.FillsVoids[0].RelatingOpeningElement.Name == f"OPEN_{d.name}"
    eng.build_3d_doc()
    mats = element_materials(eng)
    for p in d.parts:
        for ent in p.source_element:
            if p.code == "GLASS":
                assert ent.dxf.layer == "STRUCT_DOOR_GLASS" and ent.dxf.handle not in mats
            else:
                assert ent.dxf.layer == "STRUCT_DOOR" and mats[ent.dxf.handle].name == p.material


def test_web_viewer_door_data():
    doors = [DoorSpec("-t", 23.0, name="A"), DoorSpec("-t", 27.0, 1.6, kind="양개 여닫이", name="B", swing="out"),
             DoorSpec("-t", 33.0, 1.2, kind="자동문", name="C"), DoorSpec("+s", 3.5, kind="미닫이", name="E", hinge="right")]
    cfg = cfg_with(RoomSpec(2, "역무실", 20, 40, 0, 7, name="OFF", doors=doors), table=skirted(), no_cols=True)
    global CFG
    CFG = cfg
    eng = StationCADEngine(cfg)
    eng.build_3d_doc()
    data, tags = door_anim.build(eng)
    by = {x["name"]: x for x in data}
    assert [by[n]["auto"] for n in "ABCE"] == [False, False, True, False]
    assert [len(by[n]["leaves"]) for n in "ABCE"] == [1, 2, 2, 1]
    for d in eng.rooms.doors:                                                         # 태그 = 움직이는 문짝 부재만
        x = by[d.name]
        assert set(x["parts"]) == {p.name for p in d.parts}
        for p in d.parts:
            got = {tags.get(ent.dxf.handle) for ent in p.source_element}
            assert got == ({None} if p.leaf == 0 else {f"D|{data.index(x)}|{p.leaf}"})
        # 세계 좌표 움직임 = 정거장 로컬 움직임 (열린 문짝 꼭짓점)
        for m in d.motions:
            lf = x["leaves"][f"D|{data.index(x)}|{m.leaf}"]
            leaf = next(box(p.piece) for p in d.parts if p.code == "LEAF" and p.leaf == m.leaf)
            for (s, t), (s0, t0) in zip(moved(leaf, m), ((leaf[0], leaf[2]), (leaf[1], leaf[2]), (leaf[1], leaf[3]), (leaf[0], leaf[3]))):
                x0, y0 = cfg.to_world(s0, t0)
                if lf["kind"] == "swing":
                    a = math.radians(lf["angle"])
                    dx, dy = x0 - lf["px"], y0 - lf["py"]
                    wx, wy = lf["px"] + dx * math.cos(a) - dy * math.sin(a), lf["py"] + dx * math.sin(a) + dy * math.cos(a)
                else:
                    wx, wy = x0 + lf["dx"], y0 + lf["dy"]
                assert (wx, wy) == pytest.approx(cfg.to_world(s, t), abs=1e-4)
    from exporter.web_viewer import build_web_data
    web, _ = build_web_data(eng)
    assert [x["name"] for x in web["doors"]] == ["A", "B", "C", "E"]
    anim = {c.get("anim") for c in web["chunks"]}
    assert {f"D|{i}|{k}" for i, x in enumerate(web["doors"]) for k in range(1, len(x["leaves"]) + 1)} <= anim
    names = {e["name"] for e in web["elements"]}
    assert all(set(x["parts"]) <= names for x in web["doors"])
    w = web["doors"][0]
    assert abs(w["x"]) < 1e4 and w["x"] == pytest.approx(by["A"]["x"] - web["origin"][0], abs=1e-4)


def test_invalid_and_auto_needs_wall():
    for kw, msg in ((dict(swing="up"), "열림 방향"), (dict(hinge="top"), "경첩"), (dict(width=0.4), "문틀·손잡이보다 작습니다")):
        with pytest.raises(ValueError, match=msg):
            StationCADEngine(cfg_one(DoorSpec("-t", 30.0, **kw)))
    with pytest.raises(ValueError, match="자동문은 양옆에"):
        StationCADEngine(cfg_one(DoorSpec("+s", 1.2, 2.0, 2.1, "자동문")))
    StationCADEngine(cfg_one(DoorSpec("+s", 3.5, 2.0, 2.1, "자동문")))


def test_template_and_drafts(tmp_path):
    from exporter.live_viewer import live_html
    html = live_html()
    assert "const DOOR" in html and 'id="hint"' in html and "DOOR.use()" in html
    from gui.project_file import ProjectState, open_project, save_project
    from gui.room_draft import DoorDraft, RoomDraft
    d = DoorDraft(center="120", swing="바깥쪽", hinge="경첩 왼쪽", kind="자동문").to_spec("문", 100.0)
    assert (d.swing, d.hinge, d.kind) == ("out", "left", "자동문")
    old = DoorDraft(center="120").to_spec("문", 100.0)
    assert (old.swing, old.hinge) == ("in", None)
    st = ProjectState()
    st.room_drafts = [RoomDraft(doors=[DoorDraft(swing="바깥쪽", hinge="경첩 오른쪽")])]
    save_project(tmp_path / "a.ssbim", st)
    assert open_project(tmp_path / "a.ssbim").room_drafts[0].doors[0].hinge == "경첩 오른쪽"
    with pytest.raises(ValueError, match="열림·경첩"):
        DoorDraft(swing="위").to_spec("문", 0.0)
