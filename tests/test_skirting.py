"""걸레받이: 벽 하단(본체 벽·칸막이벽·기둥·승강로), 계단 옆 경사 띠, 출구통로·출입구, 체적·겹침 교차 검증, IFC, 텍스처, 초안"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataclasses
import json
import random

import ifcopenshell
import ifcopenshell.util.element
import numpy as np
import pytest

from config.widening import WidenSpec
from elevators.elevator_spec import ElevatorSpec
from engine.cad_engine import StationCADEngine
from entrances.entrance_engine import part_faces
from escalators.escalator_spec import EscalatorSpec
from finishes.finish_check import check_finish_type
from finishes.finish_layout import stair_band
from finishes.finish_spec import FinishType, default_finishes
from helper import prism_member as PM
from helper.strip_member import _fan
from passages.passage_finish import SKIRT, WALL
from passages.passage_spec import PassageSpec, station_path
from rooms.room_spec import DoorSpec, RoomSpec
from test_entrances import _fin_cfg
from test_finishes import cfg_with, fin, ifc_world_volume
from test_passage_finish import H_OK, _inside, cfg_pf, pieces_of
from test_patch import make_cfg
from test_curved import NO_COLS
from test_stair_enclosure import make as enc_make
from test_widening import cfg_w

H = 0.2


def skirted(table=None, h=H, **kw):
    """벽 마감이 있는 종류 모두에 걸레받이"""
    return {k: (dataclasses.replace(v, skirt_h=h, **kw) if v.wall_t > 0 else v) for k, v in (table or default_finishes()).items()}


def boxes_of(els):
    return [(e.name, p, *PM.s_range(p), *PM.t_range(p)) for e in els for p in e.pieces]


def overlaps(cfg, els, n=6):
    """정거장 로컬 조각끼리 겹치는 (부재, 부재, s)"""
    rnd = random.Random(5)
    bx = sorted(boxes_of(els), key=lambda b: b[2])
    out = []
    for i, (a, p, s0, s1, t0, t1) in enumerate(bx):
        for b, q, a0, a1, b0, b1 in bx[i + 1:]:
            if a0 >= s1 - 1e-6:
                break
            lo, hi = max(s0, a0), min(s1, a1)
            if hi - lo < 1e-6 or min(t1, b1) - max(t0, b0) < 1e-6:
                continue
            for _ in range(n):
                s = rnd.uniform(lo, hi)
                ta, tb = PM.t_range_at(p, s), PM.t_range_at(q, s)
                za, zb = PM.z_range_at(cfg, p, s), PM.z_range_at(cfg, q, s)
                if min(ta[1], tb[1]) - max(ta[0], tb[0]) > 1e-6 and min(za[1], zb[1]) - max(za[0], zb[0]) > 1e-6:
                    out.append((a, b, s))
                    break
    return out


def wall_els(eng):
    return [e for e in eng.finishes.all_elements() if e.code in ("WALL", "SKIRT", "COLUMN", "FLOOR", "FILL")]


# ===================================================== 제원
@pytest.mark.parametrize("face, recess, want", [
    (0.15, 0.01, (0.11, 0.14)),        # 이격이 넉넉하면 표면에서 들어감
    (0.15, 0.0, (0.12, 0.15)),         # 들어감 0 = 같은 면
    (0.03, 0.01, (0.0, 0.02)),         # 이격이 모자라면 두께를 구조체 면까지
    (0.0016, 0.01, (0.0, 0.0016)),     # 들어갈 자리가 없으면 마감재와 같은 자리
])
def test_span(face, recess, want):
    ft = FinishType(wall_t=min(face, 0.0016), skirt_h=0.2, skirt_recess=recess)
    assert ft.skirt_span(face) == pytest.approx(want)


def test_defaults_and_checks():
    assert all(not ft.has_skirt for ft in default_finishes().values())                 # 모델 기본은 없음 (기존 출력 유지)
    assert not FinishType(wall_t=0.0, skirt_h=0.2).has_skirt                           # 면처리 벽은 없음
    for kw, msg in ((dict(skirt_h=-0.1), "걸레받이 높이"), (dict(skirt_recess=-0.1), "들어감"),
                    (dict(skirt_h=0.2, skirt_t=0.0), "걸레받이 두께"), (dict(skirt_h=3.0), "천장 높이")):
        with pytest.raises(ValueError, match=msg):
            check_finish_type(FinishType(**kw))
    eng = StationCADEngine(cfg_with(no_cols=True))
    assert not [e for e in eng.finishes.all_elements() if e.code == "SKIRT"]


# ===================================================== 평 걸레받이
def test_plain_room_volume_and_panel_starts_above():
    eng = StationCADEngine(cfg_with(no_cols=True, table=skirted()))
    r = next(x for x in eng.finishes.rooms if x.floor == 2)
    ft = r.finish
    sk, wall = r.element("SKIRT"), r.element("WALL")
    b, f = ft.skirt_span(ft.face)
    ring = lambda d0, d1: (198 - 2 * d0) * (18 - 2 * d0) - (198 - 2 * d1) * (18 - 2 * d1)
    assert sk.volume == pytest.approx(ring(b, f) * H, rel=1e-9)
    assert wall.volume == pytest.approx(ring(ft.wall_gap, ft.face) * (r.ceiling_rel - r.ffl_rel - H), rel=1e-9)
    assert {round(PM.z_off(eng.cfg, p) - r.ffl_rel, 9) for p in sk.pieces} == {0.0}
    assert {round(PM.z_off(eng.cfg, p) - r.ffl_rel, 9) for p in wall.pieces} == {H}
    assert sk.material == "흑색 걸레받이"


ROOMS = [RoomSpec(2, "역무실", 10, 30, 2, 9, name="OFF", doors=[DoorSpec("-t", 20.0)]),
         RoomSpec(2, "화장실", 40, 60, -9, -2, name="WC")]


@pytest.mark.parametrize("curved", [False, True])
@pytest.mark.parametrize("pface", [None, 0.08])
def test_rooms_columns_shaft_volumes_and_no_overlap(tmp_path, curved, pface):
    cfg = cfg_with(*[dataclasses.replace(r) for r in ROOMS], curved=curved, table=skirted(partition_face=pface))
    if not curved:
        cfg.elevators = [ElevatorSpec(lower_floor=1, upper_floor=3, s_center=120.0, t_center=-6.5, name="EV")]
    eng = StationCADEngine(cfg)
    sk = [e for e in eng.finishes.all_elements() if e.code == "SKIRT"]
    assert sk and (curved or any(e.boxes for e in sk))                                # 원기둥 둘레 고리
    assert not overlaps(eng.cfg, wall_els(eng))
    if not curved:                                                                    # 문 자리·승강로 출입구는 비움
        o = next(d for fl in eng.cfg.room_layouts() for d in fl.doors).opening
        assert not [b for b in boxes_of(sk) if o[0] + 0.01 < b[3] and b[2] < o[1] - 0.01 and b[4] < o[3] + 0.1 and b[5] > o[2] - 0.1
                    and abs(PM.z_off(eng.cfg, b[1]) - 6.1) < 0.01]
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "s.ifc"))
    by = {e.Name: e for e in f.by_type("IfcCovering")}
    tol = 1e-4 if curved else 1e-7
    for e in sk:
        quads = [q for p in e.pieces for q in PM.sweep_quads(PM.rings(eng.cfg, p))]
        quads = [t for q in quads for t in _fan(q)] if curved else quads
        assert PM.mesh_volume(quads) + sum(PM.mesh_volume(b.faces()) for b in e.boxes) == pytest.approx(e.volume, rel=tol)
        assert by[e.name].PredefinedType == "SKIRTINGBOARD"
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=tol)
    off = next(s for s in f.by_type("IfcSpace") if s.Name == "OFF")
    pset = ifcopenshell.util.element.get_psets(off)["SSBIM_SpaceFinish"]
    assert pset["SkirtingHeight"] == pytest.approx(H) and pset["SkirtingMaterial"] == "흑색 걸레받이"
    # 칸막이벽: 이격이 있으면 들어가고, 없으면 패널과 같은 자리
    ft = eng.cfg.finish_settings.for_room("역무실")
    b, fr = ft.skirt_span(ft.pface)
    assert (fr < ft.pface - 1e-9) == (pface is not None)
    ts = {(round(x[4], 4), round(x[5], 4)) for x in boxes_of([fin(eng, "OFF").element("SKIRT")]) if x[3] - x[2] > 5}
    assert (round(2.1 + b, 4), round(2.1 + fr, 4)) in ts


def test_floor_level_covers_same_wall_as_before():
    """걸레받이를 둬도 벽 정면이 비지 않음: 걸레받이 없을 때의 벽 마감 표면 점마다 패널 또는 걸레받이가 있음"""
    mk = lambda t: StationCADEngine(cfg_with(*[dataclasses.replace(r) for r in ROOMS], table=t))
    a, b = mk(skirted()), mk(default_finishes())
    new = boxes_of([e for e in a.finishes.all_elements() if e.code in ("WALL", "SKIRT", "COLUMN")])
    rnd = random.Random(2)
    for name, p, s0, s1, t0, t1 in boxes_of([e for e in b.finishes.all_elements() if e.code in ("WALL", "COLUMN")]):
        for _ in range(12):
            s, t = rnd.uniform(s0, s1), rnd.uniform(t0, t1)
            z0, z1 = PM.z_range_at(b.cfg, p, s)
            for z in (rnd.uniform(z0, z1), z0 + rnd.uniform(0.0, H)):
                assert any(x[2] - 0.05 <= s <= x[3] + 0.05 and x[4] - 0.05 <= t <= x[5] + 0.05
                           and PM.z_range_at(a.cfg, x[1], s)[0] - 1e-6 <= z <= PM.z_range_at(a.cfg, x[1], s)[1] + 1e-6 for x in new), (name, s, t, z)


# ===================================================== 계단·에스컬레이터 옆
def test_stair_band_follows_pitch_line():
    cfg = enc_make()
    cfg.finish_settings.table = skirted(cfg.finish_settings.table)
    StationCADEngine(cfg)
    lay = cfg.stair_layouts()[0]
    band = sorted(stair_band(cfg, lay, H))
    off = cfg.station.offset
    surf = sorted(x for p in lay.parts for x in p.surfaces)
    for ua, ub, z in surf:                                                            # 디딤판 코 = 피치선 + h, 아래 변은 디딤판 아래
        s = lay.s_at(ua)
        b = next(x for x in band if x[0] - 1e-9 <= s + 1e-6 * lay.spec.direction <= x[1] + 1e-9)
        k = (s - b[0]) / (b[1] - b[0])
        rel = z - (cfg.lv(s) - off)
        assert b[3] + (b[5] - b[3]) * k == pytest.approx(rel + H)
        assert b[2] + (b[4] - b[2]) * k <= rel + 1e-9
    assert min(x[0] for x in band) == pytest.approx(lay.s_at(-lay.spec.tread))
    assert max(x[1] for x in band) == pytest.approx(lay.s_at(lay.length))
    top = band[-1]                                                                    # 도착 = 위층 바닥 마감면 + h
    up = cfg.station.floor_level(3) + cfg.finish_settings.for_room("대합실").ffl
    assert top[5] == pytest.approx(up + H) and top[3] == pytest.approx(top[5], abs=0.01)


@pytest.mark.parametrize("direction", [1, -1])
def test_stair_enclosure_band_no_overlap_and_volume(tmp_path, direction):
    escs = [EscalatorSpec(lower_floor=1, s_wp=130.0, direction=direction, t_center=6.0, name="ES")]
    cfg = enc_make(direction=direction, s_start=60.0, escs=escs)
    cfg.finish_settings.table = skirted(cfg.finish_settings.table)
    eng = StationCADEngine(cfg)
    els = wall_els(eng)
    assert not overlaps(cfg, els)
    slopes = [(e, p) for e in els for p in e.pieces if p.ztrap]
    assert {e.code for e, _ in slopes} == {"WALL", "SKIRT"}
    lay = cfg.stair_layouts()[0]
    lo, hi = sorted((lay.s_at(-lay.spec.tread), lay.s_at(lay.length)))
    for e, p in slopes:                                                               # 계단 옆에만 (에스컬레이터 옆은 없음)
        s0, s1 = PM.s_range(p)
        assert lo - 1e-6 <= s0 and s1 <= hi + 1e-6
        if e.code == "SKIRT":
            m = (s0 + s1) / 2
            z0, z1 = PM.z_range_at(cfg, p, m)
            assert z1 - z0 <= lay.riser + H + 1e-6
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "b.ifc"))
    by = {x.Name: x for x in f.by_type("IfcCovering")}
    for e in {id(e): e for e, _ in slopes}.values():
        mesh = sum(PM.mesh_volume(PM.sweep_quads(PM.rings(cfg, p))) for p in e.pieces)
        assert mesh == pytest.approx(e.volume, rel=1e-7)
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=1e-6)
    assert all(PM.mesh_volume(PM.mesh_faces(cfg, p)) > 0 for _, p in slopes)          # 면은 바깥 방향


def test_upper_floor_opening_edge_has_no_flat_skirt():
    """위층 바닥이 뚫린 자리(계단 오프닝) 옆 본체 벽: 평 걸레받이가 허공에 남지 않고 벽 마감이 바닥 마감면까지 내려옴"""
    cfg = enc_make(t_ref="wall-t", t_center=0.0)
    cfg.finish_settings.table = skirted(cfg.finish_settings.table)
    eng = StationCADEngine(cfg)
    o = cfg.stair_layouts()[0].opening
    up = next(r for r in eng.finishes.rooms if r.floor == 3)
    flat = [b for b in boxes_of([up.element("SKIRT")]) if not b[1].ztrap and b[5] < 0 and b[3] - b[2] > 1.0]
    assert flat and not [b for b in flat if min(b[3], o.s_end) - max(b[2], o.s_start) > 1e-6]
    mid = o.s_start + 0.5
    down = [b for b in boxes_of([up.element("WALL")]) if b[2] <= mid <= b[3] and b[5] < 0
            and abs(PM.z_range_at(cfg, b[1], mid)[0] - (cfg.lv(mid) - cfg.station.offset + up.ffl_rel)) < 1e-6]
    assert down
    assert [p for p in up.element("SKIRT").pieces if p.ztrap]                          # 도착부 경사 띠가 이어짐
    assert not overlaps(cfg, wall_els(eng))


def test_shaft_panel_for_escalator_going_backward():
    """−s 로 오르는 ES 옆 계단실 벽: 예전엔 계단 구간 패널의 실을 못 찾아(창고가 s0 쪽) 콘크리트가 보였음"""
    for d in (1, -1):
        cfg = enc_make(escs=[EscalatorSpec(lower_floor=1, s_wp=130.0, direction=d, t_center=6.0, name="ES")])
        eng = StationCADEngine(cfg)
        lay = cfg.escalator_layouts()[0]
        o = lay.opening
        assert o.t_hi > lay.t_range[1] + 1e-5                                         # 벽 마감 두께만큼 넓힌 오프닝
        strip = [b for b in boxes_of([e for e in eng.finishes.all_elements() if e.code == "WALL"])
                 if abs(b[4] - lay.t_range[1]) < 1e-6 and b[2] < o.s_end - 1e-6 and b[3] > o.s_start + 1e-6]
        cover = sum(min(b[3], o.s_end) - max(b[2], o.s_start) for b in strip)
        assert cover >= (o.s_end - o.s_start) - 1e-6, d


# ===================================================== 확폭 포켓
def test_pocket_room_volume(tmp_path):
    cfg = cfg_w(WidenSpec(side=1, floors=[2], s_start=50, s_end=80, amount=2.0))
    cfg.finish_settings.enabled = True
    cfg.finish_settings.table = skirted()
    cfg.rooms = [RoomSpec(2, "역무실", 40, 60, 0, 9.0)]
    eng = StationCADEngine(cfg)
    els = [e for e in wall_els(eng) if eng.finishes]
    assert not overlaps(cfg, els)
    sk = [e for r in eng.finishes.rooms if r.floor == 2 for e in r.elements if e.code == "SKIRT"]
    assert any(p.trap for e in sk for p in e.pieces)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "w.ifc"))
    by = {x.Name: x for x in f.by_type("IfcCovering")}
    for e in sk:
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=1e-6)


# ===================================================== 출구통로
def _pf(**kw):
    cfg = cfg_pf(**kw)
    cfg.finish_settings.table = skirted()
    return cfg


def test_passage_skirt_volume_junction_and_ifc(tmp_path):
    eng = StationCADEngine(_pf())
    cfg = eng.cfg
    ft, rf = cfg.finish_settings.for_room("통로"), cfg.finish_settings.for_room("대합실")
    b, fr = ft.skirt_span(ft.face)
    hb, _ = rf.skirt_span(rf.face)
    lay = {x.name: x for x in cfg.passage_layouts()}
    e = eng.passage_finishes.element("A", SKIRT)
    assert e.volume == pytest.approx(2 * (fr - b) * H * (lay["A"].plan_length + 1.0 + hb), rel=1e-9)   # 실 걸레받이 뒷면까지
    end = [p for c, p in pieces_of(eng, "B") if c == SKIRT and min(v for v, _ in p.sect) < 0 < max(v for v, _ in p.sect)]
    assert len(end) == 1 and end[0].length == pytest.approx(fr - b)                    # 끝 폐합 벽
    walls = [p for c, p in pieces_of(eng, "A") if c == WALL]
    assert min(dz for p in walls for _, dz in p.sect) == pytest.approx(ft.ffl + H)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    el = next(x for x in f.by_type("IfcCovering") if x.Name == "A_FIN_SKIRT")
    assert el.PredefinedType == "SKIRTINGBOARD" and ifc_world_volume(el) == pytest.approx(e.volume, rel=1e-6)


def test_passage_branch_and_rooms_no_overlap():
    par = PassageSpec(floor=3, path=station_path([(50, None, None), (50, 30, 0), (80, 30, 0)]), name="P", inner_height=H_OK)
    ch = PassageSpec(floor=3, path=station_path([(70, None, None), (70, 40, 0)]), name="C", parent="P", inner_height=H_OK)
    cfg = make_cfg(NO_COLS())
    cfg.passages = [par, ch]
    cfg.finish_settings.enabled = True
    cfg.finish_settings.table = skirted()
    eng = StationCADEngine(cfg)
    fins = [(e.name, p.faces()) for e in eng.passage_finishes.elements for p in e.pieces if e.code != "FRAME"]
    struct = [(e.name, p.faces()) for ps in eng.passages.all_passages() for e in ps.elements for p in e.pieces]
    room = [(e.name, PM.mesh_faces(cfg, p)) for e in eng.finishes.all_elements() for p in e.pieces if e.code != "FRAME"]
    others = fins + struct + room
    box = lambda fs: (np.min([v for f in fs for v in f], axis=0), np.max([v for f in fs for v in f], axis=0))
    bx = [box(fs) for _, fs in others]
    rng = random.Random(4)
    checked = 0
    for name, fs in fins:
        if "SKIRT" not in name:
            continue
        lo, hi = box(fs)
        near = [o for o, (l2, h2) in zip(others, bx) if o[1] is not fs and np.all(l2 <= hi + 0.01) and np.all(h2 >= lo - 0.01)]
        verts = np.unique(np.round(np.array([v for f in fs for v in f]), 9), axis=0)
        for _ in range(60):                                                            # 볼록 조각 안의 점 (꼭짓점 볼록 조합)
            w = np.array([rng.random() ** 2 for _ in verts]) + 1e-6
            q = (w / w.sum()) @ verts
            checked += 1
            hit = next((n2 for n2, f2 in near if _inside(f2, q)), None)
            assert hit is None, (name, hit, q)
    assert checked > 100
    lay = {x.name: x for x in cfg.passage_layouts()}["C"]
    ft = cfg.finish_settings.for_room("통로")
    w = ch.half_in - ft.skirt_span(ft.face)[1]                                         # 부모 걸레받이는 자식 걸레받이 앞면 사이를 비움
    sk = [p for c, p in pieces_of(eng, "P") if c == SKIRT and p.local.get("seg") == 1 and (min(v for v, _ in p.sect) > 0) == (lay.side > 0)]
    assert any(abs(p.a1 - (lay.branch_a - w)) < 1e-9 for p in sk) and any(abs(p.a0 - (lay.branch_a + w)) < 1e-9 for p in sk)


# ===================================================== 출입구
@pytest.mark.parametrize("kw", [{}, dict(open_narrow=0.2, open_wall_t=0.3)])
def test_entrance_skirt(tmp_path, kw):
    cfg = _fin_cfg(**kw)
    cfg.finish_settings.table = skirted(cfg.finish_settings.table)
    eng = StationCADEngine(cfg)
    ent = eng.entrances.entrances[0]
    members = eng.entrances.strip_members(ent)
    sk = [f for f in ent.finishes if f.kind == "SKIRT"]
    assert sk
    rng = random.Random(9)
    boxes = [(n, m.t_range, s) for n, m in members if "_ESC" not in n for s in m.shape.strips]
    for m in sk + [f for f in ent.finishes if f.kind == "WALL"]:
        t0, t1 = m.t_range
        for st in m.shape.strips:
            for _ in range(4):
                u, t = rng.uniform(st.s0, st.s1), rng.uniform(t0, t1)
                if st.zt_at(u) - st.zb_at(u) < 1e-6:
                    continue
                z = rng.uniform(st.zb_at(u), st.zt_at(u))
                for n2, (a0, a1), s2 in boxes:
                    if n2 != m.name and a0 + 1e-9 < t < a1 - 1e-9 and s2.s0 + 1e-9 < u < s2.s1 - 1e-9:
                        assert not (s2.zb_at(u) + 1e-7 < z < s2.zt_at(u) - 1e-7), (m.name, n2, u, t, z)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "e.ifc"))
    by = {e.Name: e for e in f.by_type("IfcCovering")}
    for m in sk:
        assert sum(PM.mesh_volume(q) for q in part_faces(ent.frame, m)) == pytest.approx(m.shape.volume, rel=1e-6)
        assert ifc_world_volume(by[m.name]) == pytest.approx(m.shape.volume, rel=1e-6)
        assert by[m.name].PredefinedType == "SKIRTINGBOARD"
    # 계단 쪽: 디딤판 윗면 ~ 피치선 + h, 승강구 = 윗면 + h (에스컬레이터 쪽은 하부 평탄부만)
    lay = ent.layout
    by_code = {m.code: m for m in sk}
    sides = {c: sum(s.s1 - s.s0 for s in m.shape.strips) for c, m in by_code.items() if c in ("FIN_SKIRT_L", "FIN_SKIRT_R")}
    stair_code = max(sides, key=sides.get)
    assert min(sides.values()) < max(sides.values()) / 3
    last = max(s.s1 for c, m in by_code.items() if c.startswith(stair_code) for s in m.shape.strips)
    end = next(s for c, m in by_code.items() if c.startswith(stair_code) for s in m.shape.strips if s.s1 == last)
    assert end.zt_end == pytest.approx(lay.top_level + H) and end.zb1 == pytest.approx(lay.top_level)
    for m in (x for c, x in by_code.items() if c.startswith(stair_code)):
        for s in m.shape.strips:
            for u in (s.s0 + 1e-4, s.s1 - 1e-4):
                assert s.zt_at(u) - s.zb_at(u) <= H + lay.stair.riser + 1e-3


# ===================================================== 보기 텍스처 · 도면 · 화면 입력
def test_texture_one_image_per_height():
    from exporter.dae_exporter import element_materials, stair_face_frames, tread_uv
    cfg = enc_make()
    cfg.finish_settings.table = skirted(cfg.finish_settings.table)
    eng = StationCADEngine(cfg)
    eng.build_3d_doc()
    frames = stair_face_frames(eng)
    mats = element_materials(eng)
    sk = [e for e in eng.finishes.all_elements() if e.code == "SKIRT"]
    n = 0
    for e in sk:
        for ent in e.source_element:
            assert ent.dxf.layer == "FIN_WALL" and mats[ent.dxf.handle].texture == "Skirting"
            fr = frames.get(ent.dxf.handle)
            if fr is None:
                continue
            pts = np.array([tuple(getattr(ent.dxf, f"vtx{k}")) for k in range(4)])
            uv = tread_uv(fr, pts)
            assert uv[:, 1].min() >= -1e-6 and uv[:, 1].max() <= 1 + 1e-6              # 높이 한 장
            assert uv[:, 1].max() == pytest.approx(1.0, abs=1e-6)
            assert np.ptp(uv[:, 0]) == pytest.approx(np.ptp((pts - fr[1]) @ fr[2]) / 0.8, abs=1e-6)
            n += 1
    assert n > 20


def test_drawings_and_sloped_profile():
    cfg = enc_make()
    cfg.finish_settings.table = skirted(cfg.finish_settings.table)
    eng = StationCADEngine(cfg)
    assert [i for i in eng.finishes.section_items(20.0) if "SKIRT" in i.name]
    low = eng.finishes.plan_items(cfg.station.floor_level(2) + 0.2, 2)
    high = eng.finishes.plan_items(cfg.station.floor_level(2) + 1.5, 2)
    assert [i for i in low if "SKIRT" in i.name] and not [i for i in high if "SKIRT" in i.name and i.u0 < 50]
    p = next(p for e in wall_els(eng) for p in e.pieces if p.ztrap)
    v = PM.profile_view(cfg, p, "PROF_FINISH")
    assert len(v.pts) == 4 and v.pts[0][1] == pytest.approx(PM.z_range_at(cfg, p, PM.s_range(p)[0])[0])


def test_drafts_and_old_project(tmp_path):
    from gui.finish_draft import FinishDrafts, FinishTypeDraft, preview
    from gui.project_file import ProjectState, open_project, save_project
    d = FinishDrafts()
    by = {x.name: x for x in d.items}
    assert by["대합실"].skirt_h == "0.2" and by["화장실"].skirt_h == "0" and by["기계실"].skirt_h == "0"
    assert "걸레받이 흑색 걸레받이 0.2×0.03 (0.01 들어감)" in preview(by["대합실"])
    ft = d.to_settings().table["대합실"]
    assert ft.has_skirt and ft.skirt_recess == pytest.approx(0.01)
    bad = FinishTypeDraft(skirt_h="5")
    with pytest.raises(ValueError, match="걸레받이 높이"):
        bad.to_type("마감")
    st = ProjectState()
    st.finish_drafts = [FinishTypeDraft(name="A", skirt_h="0.15"), FinishTypeDraft(name="B", wall_material="타일")]
    save_project(tmp_path / "a.ssbim", st)
    back = open_project(tmp_path / "a.ssbim").finish_drafts
    assert [x.skirt_h for x in back] == ["0.15", "0"]
    raw = json.loads((tmp_path / "a.ssbim").read_text(encoding="utf-8"))              # 걸레받이 이전 파일: 금속패널 벽만 켜짐

    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if not str(k).startswith("skirt_")}
        return [strip(x) for x in o] if isinstance(o, list) else o
    (tmp_path / "b.ssbim").write_text(json.dumps(strip(raw), ensure_ascii=False), encoding="utf-8")
    assert [x.skirt_h for x in open_project(tmp_path / "b.ssbim").finish_drafts] == ["0.2", "0"]
