"""출구통로 마감: 바닥·벽·천장판·천장틀, 접합부(본체·분기) 연장, 끝 폐합 벽 마감, 천장이 안 들어갈 때 경고, 겹침·체적 교차 검증"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random

import ifcopenshell
import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from finishes.finish_spec import FinishSettings
from helper import prism_member as PM
from passages.passage_finish import CEILING, FILL, FLOOR, FRAME, WALL, ceiling_fit, room_wall_hole
from passages.passage_spec import PassageSpec, station_path
from test_curved import NO_COLS
from test_finishes import ifc_world_volume
from test_passages import ell, zigzag
from test_patch import make_cfg

H_OK = 3.5          # 기본 '통로' 천장(마감면 + 3.0, 판·틀 포함 3.173m)이 상부 헌치(0.3) 아래 들어가는 내공 높이 (≥ 3.323)


def cfg_pf(H=H_OK, extra=(), finish=True, **kw):
    cfg = make_cfg(NO_COLS())
    cfg.passages = [PassageSpec(floor=3, path=ell(), name="A", inner_height=H, **kw),
                    PassageSpec(floor=3, path=zigzag(), name="B", inner_height=H, close_end=True), *extra]
    cfg.finish_settings = FinishSettings(enabled=finish)
    return cfg


def pieces_of(eng, name):
    return [(e.code, p) for e in eng.passage_finishes.elements if e.passage == name for p in e.pieces]


def _inside(faces, q, tol=1e-7):
    c = np.mean([np.mean(f, axis=0) for f in faces], axis=0)
    for f in faces:
        f = np.asarray(f, dtype=float)
        n = np.cross(f[1] - f[0], f[2] - f[0])
        if np.linalg.norm(n) < 1e-12 and len(f) > 3:
            n = np.cross(f[2] - f[0], f[3] - f[0])
        if np.linalg.norm(n) < 1e-12:
            continue
        if np.dot(n, c - f[0]) > 0:
            n = -n
        if np.dot(n, q - f[0]) > tol:
            return False
    return True


def test_ceiling_too_high_warns_and_builds_without_ceiling():
    eng = StationCADEngine(cfg_pf(H=3.0))
    assert len(eng.warnings) == 2 and "3.32m 이상" in eng.warnings[0] and "천장 없이" in eng.warnings[0]
    assert not eng.passage_finishes.element("A", CEILING) and not eng.passage_finishes.element("A", FRAME)
    ft = eng.cfg.finish_settings.for_room("통로")
    sp = eng.cfg.passages[0]
    ok, need = ceiling_fit(sp, ft)
    assert not ok and need == pytest.approx(ft.ffl + ft.ceiling_h + ft.board_t + ft.frame_depth + 0.3 * (1 - ft.face / 0.3))
    # 벽 마감은 헌치 아래까지 (벽 마감재 뒷면 자리의 헌치 하면)
    tops = {max(dz for _, dz in p.sect) for c, p in pieces_of(eng, "A") if c == WALL and p.a0 >= 0}
    assert max(tops) == pytest.approx(3.0 - 0.3 * (1 - (ft.face - ft.wall_t) / 0.3))
    assert not StationCADEngine(cfg_pf()).warnings
    assert not StationCADEngine(cfg_pf(H=3.0, finish=False)).passage_finishes.elements      # 마감 끔 = 없음


def test_parts_volumes_formula_mesh_and_ifc(tmp_path):
    eng = StationCADEngine(cfg_pf())
    cfg = eng.cfg
    ft = cfg.finish_settings.for_room("통로")
    lay = {x.name: x for x in cfg.passage_layouts()}
    a = cfg.passages[0].half_in
    wst = 1.0                                                           # 본체 외벽 두께 (접합부 연장)
    # 바닥 마감재 = 구조 벽 면 사이 × 두께 × (경로 평면 길이 + 본체 벽 두께) — 연귀는 체적을 바꾸지 않음
    for name, end_wall in (("A", 0.0), ("B", 0.6)):
        Lp = lay[name].plan_length + wst - end_wall
        assert eng.passage_finishes.element(name, FLOOR).volume == pytest.approx(2 * a * ft.floor_t * Lp, rel=1e-9)
        assert eng.passage_finishes.element(name, FILL).volume == pytest.approx(2 * a * (ft.ffl - ft.floor_t) * Lp, rel=1e-9)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    by = {x.Name: x for x in f.by_type("IfcCovering") + f.by_type("IfcMember")}
    for e in eng.passage_finishes.elements:
        mesh = sum(PM.mesh_volume(p.faces()) for p in e.pieces)
        assert mesh == pytest.approx(e.volume, rel=1e-7)
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=1e-6), e.name
    kinds = {x.Name: x.PredefinedType for x in f.by_type("IfcCovering")}
    assert kinds["A_FIN_FLOOR"] == "FLOORING" and kinds["A_FIN_WALL"] == "CLADDING" and kinds["A_FIN_CEILING"] == "CEILING"


def test_no_overlap_with_structure_room_finishes_and_each_other():
    eng = StationCADEngine(cfg_pf())
    cfg = eng.cfg
    fin = [(e.name, p.faces()) for e in eng.passage_finishes.elements for p in e.pieces]
    struct = [(e.name, p.faces()) for ps in eng.passages.all_passages() for e in ps.elements for p in e.pieces]
    room = [(e.name, PM.mesh_faces(cfg, p)) for e in eng.finishes.all_elements() for p in e.pieces]
    others = fin + struct + room
    box = lambda fs: (np.min([v for f in fs for v in f], axis=0), np.max([v for f in fs for v in f], axis=0))
    boxes = [box(fs) for _, fs in others]
    rng = random.Random(3)
    for name, fs in fin:
        lo, hi = box(fs)
        near = [o for o, (l2, h2) in zip(others, boxes) if o[1] is not fs and np.all(l2 <= hi + 0.01) and np.all(h2 >= lo - 0.01)]
        for _ in range(25):
            q = lo + (hi - lo) * np.array([rng.random() for _ in range(3)])
            if not _inside(fs, q):
                continue
            hit = next((n2 for n2, f2 in near if _inside(f2, q)), None)
            assert hit is None, (name, hit, q)


def test_junction_extends_into_station_wall_and_room_hole_shrinks():
    cfg = cfg_pf()
    cfg.passages[0].finish = "역무실"                                    # 천장 2.7 (실 천장 3.0 보다 낮음 → 그 위 실 벽 마감 남음)
    eng = StationCADEngine(cfg)
    ft = cfg.finish_settings.for_room("역무실")
    rf = cfg.finish_settings.for_room("대합실")                          # 3층(최상층) 기본 실 = 대합실
    gap = ft.face - ft.wall_t
    ws = [p for c, p in pieces_of(eng, "A") if c == WALL and p.local.get("seg") == 0]
    assert min(p.a0 for p in ws) == pytest.approx(-(1.0 + rf.face))     # 벽 마감 = 실 벽 마감 표면까지
    fl = [p for c, p in pieces_of(eng, "A") if c == FLOOR and p.local.get("seg") == 0]
    assert min(p.a0 for p in fl) == pytest.approx(-1.0)                 # 바닥 = 본체 벽 안쪽 면까지
    cl = [p for c, p in pieces_of(eng, "A") if c == CEILING and p.local.get("seg") == 0]
    assert min(p.a0 for p in cl) == pytest.approx(-(1.0 + rf.face) + rf.wall_t)   # 천장판 = 실 벽 마감재 뒷면까지
    op = next(o for o in cfg.wall_openings() if o[0] == "A")
    s0, s1, z0, z1 = room_wall_hole(cfg, op)
    assert (s0, s1) == pytest.approx((op[3] + gap, op[4] - gap)) and z1 == pytest.approx(op[5] + ft.ffl + ft.ceiling_h)
    # 실 벽 마감은 그 구멍만 비움: 통로 마감 개구부 바로 위(천장판 하면 위)에 실 벽 마감이 있음
    s_mid = (s0 + s1) / 2
    walls = [p for e in eng.finishes.all_elements() if e.code == "WALL" for p in e.pieces]
    above = [p for p in walls if p.pos_x - p.shape.length / 2 <= s_mid <= p.pos_x + p.shape.length / 2
             and p.pos_y < -8.0 and abs(p.pos_z - (cfg.lv(p.pos_x) - cfg.station.offset + z1)) < 1e-6]
    assert above


def test_close_end_wall_finish_and_branch_cut():
    eng = StationCADEngine(cfg_pf())
    ft = eng.cfg.finish_settings.for_room("통로")
    sp = eng.cfg.passages[1]
    endw = [p for c, p in pieces_of(eng, "B") if c == WALL and min(v for v, _ in p.sect) < 0 < max(v for v, _ in p.sect)]
    assert len(endw) == 1 and endw[0].length == pytest.approx(ft.wall_t)
    # 분기: 부모 A 가 아닌 길게 뻗은 통로에 자식 C (부모 측벽 마감 개구부 + 자식 마감이 부모 마감 표면까지)
    par = PassageSpec(floor=3, path=station_path([(50, None, None), (50, 30, 0), (80, 30, 0)]), name="P", inner_height=H_OK)
    ch = PassageSpec(floor=3, path=station_path([(70, None, None), (70, 40, 0)]), name="C", parent="P", inner_height=H_OK,
                     finish="역무실")                                    # 천장 2.7 → 부모(3.0) 벽 마감에 인방이 남음
    cft = FinishSettings(enabled=True).for_room("역무실")
    cfg = make_cfg(NO_COLS())
    cfg.passages = [par, ch]
    cfg.finish_settings = FinishSettings(enabled=True)
    eng = StationCADEngine(cfg)
    lay = {x.name: x for x in cfg.passage_layouts()}["C"]
    side_walls = [p for c, p in pieces_of(eng, "P") if c == WALL and p.local.get("seg") == 1
                  and (min(v for v, _ in p.sect) > 0) == (lay.side > 0)]
    lint = [p for p in side_walls if p.local.get("lintel")]
    w = cfg.passages[1].half_in - (cft.face - cft.wall_t)
    assert lint and lint[0].a0 == pytest.approx(lay.branch_a - w) and lint[0].a1 == pytest.approx(lay.branch_a + w)
    assert min(dz for _, dz in lint[0].sect) == pytest.approx(cft.ffl + cft.ceiling_h)        # 자식 천장판 하면 위는 남김
    cw = [p for c, p in pieces_of(eng, "C") if c == WALL and p.local.get("seg") == 0]
    assert min(p.a0 for p in cw) == pytest.approx(-(0.6 + ft.face))                          # 부모(통로) 마감 표면까지


def test_passage_finish_override_and_tab_draft():
    from gui.passage_draft import PassageDraft
    cfg = cfg_pf()
    cfg.passages[0].finish = "화장실"
    eng = StationCADEngine(cfg)
    assert eng.passage_finishes.element("A", WALL).material == "타일"
    assert eng.passage_finishes.element("B", WALL).material == "금속패널"
    d = PassageDraft()
    assert d.finish == "(통로)"
    d.finish = "화장실"
    d.vertices = []
    from gui.passage_draft import VertexDraft
    d.vertices = [VertexDraft(x="50", y="", z=""), VertexDraft(x="50", y="25", z="0")]
    assert d.to_spec("통로", 0.0).finish == "화장실"
    d.finish = "(통로)"
    assert d.to_spec("통로", 0.0).finish == ""
