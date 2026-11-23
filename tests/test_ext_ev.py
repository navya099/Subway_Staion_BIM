"""외부 엘리베이터 (독립 객체: 출구통로 옆 · 출입구 좌표 · 정거장 좌표, 입체 겹침 검사) 테스트"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ifcopenshell
import ifcopenshell.util.element
import numpy as np
import pytest

from elevators.elevator_spec import ElevatorSpec
from elevators.ext_ev import ExtEvSpec
from elevators.ext_ev_overlap import Convex, overlaps
from engine.cad_engine import StationCADEngine
from gui.ext_ev_draft import LOW_CLOSED, HOST_ENTRANCE, HOST_PASSAGE, HOST_STATION, SIDE_LABELS, ExtEvDraft, ExtEvDrafts
from gui.project_file import ProjectState
from helper import prism_member as PM
from helper.strip_member import part_faces
from test_entrances import FORE, _fin_cfg, cfg_with, ifc_world_volume


def ev_cfg(*evs, base=None):
    cfg = base if base is not None else cfg_with(FORE)
    cfg.ext_evs = list(evs)
    return cfg


def layouts(*evs):
    cfg = ev_cfg(*evs)
    cfg.validate()
    return cfg, cfg.ext_ev_layouts()


def entrance_sig(cfg):
    (lay,) = cfg.entrance_layouts()
    return [(p.code, p.t_range, [(s.s0, s.s1, s.zb0, s.zb1, s.zt, s.zt_end) for s in p.strips]) for p in lay.box_parts]


def in_faces(faces, q):
    for f in faces:
        a, b, c = (np.array(f[i]) for i in range(3))
        if np.dot(np.cross(b - a, c - a), np.array(q) - a) > -1e-7:
            return False
    return True


def _ext_overlaps(frame, parts, n=10):
    import random
    import numpy as np

    def inside(faces, q):
        for f in faces:
            a, b, c = (np.array(f[i]) for i in range(3))
            if np.dot(np.cross(b - a, c - a), np.array(q) - a) > -1e-7:
                return False
        return True
    rng, bad = random.Random(9), []
    for p in parts:
        for _ in range(n):
            if p.strips:
                st = rng.choice(p.strips)
                u, t, z = rng.uniform(st.s0, st.s1), rng.uniform(*p.t_range), rng.uniform(st.zb0, st.zt)
                x, y = frame.to_world(u, t)
            else:
                h = rng.choice(p.pieces)
                pts = [v for f in h.faces() for v in f]
                w = [rng.random() for _ in pts]
                x, y, z = (sum(q[i] * wi for q, wi in zip(pts, w)) / sum(w) for i in range(3))
                dx, dy = x - frame.px, y - frame.py
                u, t = dx * frame.ux + dy * frame.uy, -dx * frame.uy + dy * frame.ux
            for q in parts:
                if q is p:
                    continue
                if any(s2.s0 + 1e-7 < u < s2.s1 - 1e-7 and q.t_range[0] + 1e-7 < t < q.t_range[1] - 1e-7
                       and s2.zb0 + 1e-7 < z < s2.zt - 1e-7 for s2 in q.strips):
                    bad.append((p.code, q.code))
                if any(inside(h.faces(), (x, y, z)) for h in q.pieces):
                    bad.append((p.code, q.code))
    return bad


# ===================================================== 배치 (매뉴얼 치수) — 출입구 좌표
@pytest.mark.parametrize("low_finish", ["closed", "glass"])
@pytest.mark.parametrize("face,u,t", [("+t", 8.0, 6.0), ("-t", 10.0, -6.0), ("+u", 12.0, 6.0), ("-u", 9.0, -6.0)])
def test_layout(face, u, t, low_finish):
    cfg, (x,) = layouts(ExtEvSpec(host="entrance", u=u, t=t, face=face, door_open=1.0, car_at="low", low_finish=low_finish))
    lay = cfg.entrance_layouts()[0]
    G = lay.ground
    assert (x.host, x.host_name, x.name) == ("entrance", "EN1", "OEV1")                       # 이름 비우면 OEV + 순번
    assert x.stops == {1: pytest.approx(lay.z_floor), 2: pytest.approx(G + 0.26)}            # 지하 = 통로 끝 바닥, 지상 = 기단 위
    U0, U1, T0, T1 = x.outer
    assert sorted((U1 - U0, T1 - T0)) == pytest.approx(sorted((3.13, 3.17)))                 # 매뉴얼 3,170 × 3,130
    parts = {}
    for p in x.parts:
        parts.setdefault(p.code, []).append(p)
    (roof,) = parts["ROOF"]
    assert roof.strips[0].zt - G == pytest.approx(0.26 + 5.543)                              # 높이 5,543 (기단 위)
    assert [round(p.strips[0].zb0 - G, 3) for p in parts["CANOPY"]] == [pytest.approx(0.26 + 0.11 + 2.33)]
    ramp = parts["RAMP"][0].pieces[0]
    zs = sorted(q[2] for q in ramp.top)
    assert zs[0] == pytest.approx(G) and zs[-1] == pytest.approx(G + 0.26)                   # 경사로 지상 정지 바닥 → 지표
    rc = [p for p in x.parts if p.kind == "RC_WALL"]
    assert min(p.strips[0].zb0 for p in rc) == pytest.approx(lay.z_floor - 1.7)               # 피트 바닥 ~
    assert max(p.strips[0].zt for p in rc) == pytest.approx(G + 0.26)
    assert len([p for p in x.parts if p.kind == "LANDING_DOOR"]) == 4                         # 지하·지상 두 짝씩
    assert _ext_overlaps(x.frame, x.parts) == []


def test_entrance_and_passage_do_not_change():
    """출입구·통로와 별개: 출입구 좌표로 놓아도 출입구 부재·통로 체적은 그대로, 통로 옆이면 통로 측벽만"""
    base = cfg_with(FORE)
    base.validate()
    v0 = sum(p.volume for p in base.passage_layouts()[0].pieces())
    for spec, dv in ((ExtEvSpec(host="entrance", u=8, t=6, face="+t"), 0.0),
                     (ExtEvSpec(host="passage", along=6.0), 0.6 * 1.1 * 2.2),
                     (ExtEvSpec(host="passage", along=6.0, low_finish="glass"), 0.6 * 2.63 * 2.6),
                     (ExtEvSpec(host="passage", along=13.4), 0.6 * 1.1 * 2.2)):
        cfg, _ = layouts(spec)
        assert entrance_sig(cfg) == entrance_sig(base)
        assert v0 - sum(p.volume for p in cfg.passage_layouts()[0].pieces()) == pytest.approx(dv, abs=1e-9)


# ===================================================== 출력 (3D · IFC · 사인 · 단면)
def test_outputs(tmp_path):
    spec = ExtEvSpec(name="A", host="entrance", u=8, t=6, face="+t", car_at="low", line_name="GTX A")
    eng = StationCADEngine(ev_cfg(spec))
    (x,) = eng.ext_evs.ext_evs
    assert x.car_z == pytest.approx(x.stops[1]) and x.travel[1] - x.travel[0] > 10
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "x.ifc"))
    by = {e.Name: e for e in f.by_type("IfcElement")}
    asm = by["A"]
    assert asm.is_a("IfcElementAssembly") and asm.ObjectType == "ELEVATOR" and "EN1" in asm.Description
    assert ifcopenshell.util.element.get_container(asm).Name == x.level
    assert ifcopenshell.util.element.get_aggregate(asm) is None                              # 출입구 어셈블리와 별개
    car = by["A_CAR"]
    assert len([k for k in ifcopenshell.util.element.get_decomposition(car) if k.is_a("IfcDoor")]) == 2
    for e in x.elements:                                                                     # 체적 공식 = 메쉬 = IFC
        mesh = sum(PM.mesh_volume(q) for q in part_faces(e.frame, e)) + sum(PM.mesh_volume(p.faces()) for p in e.pieces)
        assert mesh == pytest.approx(e.volume, rel=1e-7) and ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=1e-6)
    assert by["A_RAMP"].is_a("IfcRampFlight") and by["A_POST_NN"].is_a("IfcColumn")
    doc = eng.build_3d_doc()
    n = len(list(doc.modelspace().query("3DFACE")))
    assert n > 0 and all(e.source_element for e in x.elements)
    imgs = eng.ext_evs.sign_images()
    assert len([k for k, *_ in imgs if "A_SIGN" in k]) == 3                                    # 문 면 + 양옆 역명 띠
    assert not [k for k, *_ in eng.entrances.sign_images() if "SIGN_P" in k or "SIGN_N" in k]


def test_dae_and_web_viewer_have_signs_and_granite(tmp_path):
    from exporter.dae_exporter import element_materials
    eng = StationCADEngine(ev_cfg(ExtEvSpec(name="A", host="entrance", u=8, t=6, face="+t")))
    eng.build_3d_doc()
    mats = element_materials(eng)
    (x,) = eng.ext_evs.ext_evs
    ramp = next(e for e in x.elements if e.kind == "RAMP")
    assert mats[ramp.source_element[0].dxf.handle].name == "화강석"
    from engine.bim_engine import BIMEngine
    from config.output_config import OutputOptions
    paths = BIMEngine.build(ev_cfg(ExtEvSpec(name="A", host="entrance", u=8, t=6, face="+t")), tmp_path,
                            OutputOptions(dxf3d=True, ifc=False, plan=False, profile=False, section=False, dae=True, web=True))
    assert any(p.endswith(".dae") for p in paths) and any(p.endswith(".html") for p in paths)
    dae = next(p for p in paths if p.endswith(".dae"))
    assert "A_SIGN" in open(dae, encoding="utf-8").read()


def test_section_and_path_profile():
    from engine.path_profile import passage_profile_items
    eng = StationCADEngine(ev_cfg(ExtEvSpec(name="A", host="passage", along=6.0)))
    (x,) = eng.ext_evs.ext_evs
    s0, _ = eng.cfg.to_station(*x.frame.to_world(x.layout.spec.u, x.layout.outer[2] + 0.1))     # EV 통로 쪽 벽을 지나는 측점
    sec = eng.ext_evs.section_items(s0)
    assert any(i.layer == "SEC_CONCRETE" and i.hatch_layer for i in sec) and any(i.layer == "SEC_ELEVATOR" for i in sec)
    its = [i for i in passage_profile_items(eng, "EX1", 3.5) if i.name.startswith("A_")]                  # EV 를 지나는 절단
    assert any(i.layer == "PROF_CONCRETE" for i in its)
    far = [i for i in passage_profile_items(eng, "EX1", -1.0) if i.name.startswith("A_")]                 # 통로 안 절단 → 왼쪽 너머 윤곽
    assert far and not any(i.layer == "PROF_CONCRETE" for i in far)


# ===================================================== 출구통로 옆 박스형 (벽 공유 + 통로 측벽 문 개구부)
def test_beside_passage(tmp_path):
    xs = ExtEvSpec(name="EN1_EV1", host="passage", along=6.0, host_side=1, door_open=1.0, car_at="low")
    cfg = ev_cfg(xs, base=_fin_cfg(**FORE))
    cfg.validate()
    plain = cfg_with(FORE).passage_layouts()[0]
    pl = cfg.passage_layouts()[0]
    seg = pl.segments[0]
    from passages.passage_finish import passage_finish_type
    ffl = passage_finish_type(cfg, pl.spec).ffl
    assert ffl > 0
    # 통로 왼쪽 측벽: 개구부(문 + 문틀 1.1 × 바닥 마감 + 2.2) + 위 인방
    wl = next(e for e in pl.elements if e.code.endswith("WALL_L"))
    wl0 = next(e for e in plain.elements if e.code.endswith("WALL_L"))
    assert sum(p.volume for p in wl0.pieces) - sum(p.volume for p in wl.pieces) == pytest.approx(0.6 * 1.1 * (2.2 + ffl), rel=1e-6)
    assert any(p.local.get("lintel") for p in wl.pieces)
    eng = StationCADEngine(cfg)
    (x,) = eng.ext_evs.ext_evs
    fr = x.frame
    assert (fr.ux, fr.uy) == pytest.approx((seg.ux, seg.uy)) and x.stops[1] == pytest.approx(seg.z + ffl)   # 통로 구간 축 · 통로 바닥 마감면
    U0, U1, T0, T1 = x.layout.outer
    assert T0 == pytest.approx(pl.spec.half_out) and (U0 + U1) / 2 == pytest.approx(6.0)               # 통로 바깥면에 붙음
    # 벽 공유: 통로 쪽(−t) RC 벽은 통로 바닥 하면 ~ 천장 상면 높이에 없음
    nt = [p for p in x.layout.parts if p.code == "RC_WALL_NT"]
    z0, z1 = seg.z - pl.spec.floor_t, seg.z + pl.spec.inner_height + pl.spec.roof_t
    assert nt and all(p.strips[0].zt <= z0 + 1e-9 or p.strips[0].zb0 >= z1 - 1e-9 for p in nt)
    # 지하 승강장 문 = 통로 개구부 자리 (축 6.0 ± 0.45, 열림), 통로 벽 바깥면에 바로 붙음 (사이가 피트 위로 비지 않음)
    low = [e for e in x.elements if e.code.startswith("LDOOR") and "LOW" in e.code]
    assert sorted(e.shape.strips[0].s0 for e in low) == pytest.approx([6.0 - 0.45 - 0.45, 6.0 + 0.45])
    assert all(0.0 <= min(e.t_range) - T0 < 0.05 for e in low)
    # 통로 벽 마감도 문 자리를 비움, 문 위 인방 마감은 있음
    from passages.passage_finish import WALL, layout_passage_finishes
    (pf,), _ = layout_passage_finishes(cfg)
    left = [pc for pc in pf.parts[WALL] if pc.local.get("seg") == 0 and min(v for v, _ in pc.sect) > 0]
    cover = [pc for pc in left if pc.a0 < 6.0 < pc.a1 and min(dz for _, dz in pc.sect) < 1.0 < max(dz for _, dz in pc.sect)]
    assert left and not cover and any(pc.local.get("lintel") and pc.a0 < 6.0 < pc.a1 for pc in left)
    # EV 부재 ↔ 통로 부재·EV 부재끼리 겹침 없음
    assert _ext_overlaps(fr, x.layout.parts) == []
    rng = random.Random(6)
    for e in x.elements:
        for st in e.shape.strips:
            for _ in range(4):
                X, Y = fr.to_world(rng.uniform(st.s0, st.s1), rng.uniform(*e.t_range))
                z = rng.uniform(st.zb0, st.zt)
                assert not any(in_faces(q.faces(), (X, Y, z)) for q in pl.pieces()), e.code
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "h.ifc"))
    by = {e.Name: e for e in f.by_type("IfcElement")}
    for e in x.elements:
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=1e-6)


# ===================================================== 지하 정면 마감 (투시형 / 폐쇄형)
def _passage_overlaps(cfg, x):
    """EV 부재 점이 통로 구조·통로 마감 안에 들어간 것"""
    from passages.passage_finish import CODES, layout_passage_finishes
    (pl,) = cfg.passage_layouts()
    pcs = list(pl.pieces())
    fins = layout_passage_finishes(cfg)[0]
    pcs += [q for f in fins for c in CODES for q in f.parts[c]]
    rng, bad = random.Random(3), []
    for p in x.parts:
        for st in p.strips:
            for _ in range(5):
                X, Y = x.frame.to_world(rng.uniform(st.s0, st.s1), rng.uniform(*p.t_range))
                if any(in_faces(q.faces(), (X, Y, rng.uniform(st.zb0, st.zt))) for q in pcs):
                    bad.append(p.code)
    return bad


@pytest.mark.parametrize("finish_on", [False, True])
@pytest.mark.parametrize("side", [1, -1])
def test_low_front_beside_passage(side, finish_on):
    for low in ("closed", "glass"):
        base = _fin_cfg(**FORE) if finish_on else cfg_with(FORE)
        cfg = ev_cfg(ExtEvSpec(host="passage", along=6.0, host_side=side, low_finish=low, door_open=1.0, car_at="low"), base=base)
        cfg.validate()
        (x,) = cfg.ext_ev_layouts()
        by = {}
        for p in x.parts:
            by.setdefault(p.code, []).append(p)
        assert _ext_overlaps(x.frame, x.parts) == [] and _passage_overlaps(cfg, x) == []
        (pl,) = cfg.passage_layouts()
        z0 = pl.segments[0].z
        assert x.stops[1] >= z0 and ("LOW_FLOOR" in by) == (x.stops[1] > z0 + 1e-9) == finish_on
        assert len(by["LFRAME"]) == 3
        o = side * pl.spec.half_out                                   # 통로 벽 바깥면 = EV 외곽 면
        if low == "closed":
            assert "LCOL_NN" not in by and "LGLASS" not in by
            lo = min(min(abs(v) for v in p.t_range) for p in by["LFRAME"])
            assert lo <= pl.spec.half_in + 1e-9 and max(max(abs(v) for v in p.t_range) for p in by["LFRAME"]) == pytest.approx(abs(o))
        else:
            assert {"LCOL_NN", "LCOL_NP", "LCOL_PN", "LCOL_PP"} <= set(by) and len(by["LINING"]) == 3 and len(by["LGLASS"]) == 4
            assert all(min(abs(v - o) for v in p.t_range) < 1e-9 for p in by["LGLASS"])       # 유리 정면 = 통로 벽 바깥면
            us = [v for p in by["LGLASS"] for v in (p.strips[0].s0, p.strips[0].s1)]
            assert max(us) - min(us) == pytest.approx(3.13 - 0.5)                               # 승강로 내공 폭 전체
            rc = [p for p in x.parts if p.kind == "RC_WALL"]
            for tag in ("PU", "NU", "PT" if side > 0 else "NT"):                                # RC 박스 나머지 세 면은 유지
                (w,) = [p for p in rc if p.code == f"RC_WALL_{tag}"]
                assert w.strips[0].zt - w.strips[0].zb0 == pytest.approx(x.stops[2] - x.stops[1] + 1.7)
            for k in ("NN", "PP"):                                                              # 강관 기둥: 피트 바닥 ~ 지상 정지 바닥
                assert by[f"LCOL_{k}"][0].pieces[0].z_range == pytest.approx((x.stops[1] - 1.7, x.stops[2]))


def test_low_front_volumes_and_materials(tmp_path):
    from exporter.dae_exporter import element_materials
    cfg = ev_cfg(ExtEvSpec(name="A", host="passage", along=6.0, low_finish="glass"), base=_fin_cfg(**FORE))
    eng = StationCADEngine(cfg)
    (x,) = eng.ext_evs.ext_evs
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "g.ifc"))
    by = {e.Name: e for e in f.by_type("IfcElement")}
    for e in x.elements:
        mesh = sum(PM.mesh_volume(q) for q in part_faces(e.frame, e)) + sum(PM.mesh_volume(p.faces()) for p in e.pieces)
        assert mesh == pytest.approx(e.volume, rel=1e-5) and ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=1e-5)
    assert by["A_LCOL_NN"].is_a("IfcColumn") and by["A_LGIRT_PU"].is_a("IfcMember")
    assert any(n.startswith("A_LGLASS") and e.is_a("IfcPlate") for n, e in by.items())
    eng.build_3d_doc()
    mats = element_materials(eng)
    for code, name in (("LFRAME", "스테인리스"), ("LINING", "스테인리스"), ("LDOOR_NT_LOW_N", "스테인리스"), ("LOW_FLOOR", "화강석")):
        e = next(e for e in x.elements if e.code.startswith(code))
        assert mats[e.source_element[0].dxf.handle].name == name
    assert all(f.dxf.layer == "STRUCT_ELEVATOR_GLASS" for e in x.elements if e.code.startswith("LGLASS") for f in e.source_element)


def test_low_front_rules():
    for kw, match in ((dict(low_finish="x"), "지하 마감"), (dict(low_finish="glass", low_row=2.55), "줄눈"),
                      (dict(low_finish="glass", low_open_h=2.0), "보다 낮습니다"), (dict(door_frame_w=0.0), "문틀"),
                      (dict(low_finish="glass", col_d=0.5), "좁습니다"), (dict(low_finish="glass", along=1.2), "측벽 범위")):
        with pytest.raises(ValueError, match=match):
            layouts(ExtEvSpec(**{"host": "passage", "along": 6.0, **kw}))
    cfg = cfg_with(FORE)                                                                       # 통로 천장(헌치 아래)에 맞춰 개구부 높이가 줄어듦
    cfg.passages[0].inner_height = 2.75
    cfg.ext_evs = [ExtEvSpec(host="passage", along=6.0, low_finish="glass")]
    cfg.validate()
    (x,) = cfg.ext_ev_layouts()
    top = max(p.strips[0].zt for p in x.parts if p.code == "LGLASS")
    assert top - x.stops[1] == pytest.approx(2.75 - 0.3)
    cfg.passages[0].inner_height = 2.4
    with pytest.raises(ValueError, match="문 높이 \\+ 문틀"):
        cfg.validate()


# ===================================================== 겹침 검사 (높이까지)
def cube(x0, y0, z0, d=1.0):
    p = [(x0 + i * d, y0 + j * d, z0 + k * d) for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    return Convex("c", [(p[0], p[1], p[3], p[2]), (p[4], p[5], p[7], p[6]), (p[0], p[1], p[5], p[4]), (p[2], p[3], p[7], p[6]),
                        (p[0], p[2], p[6], p[4]), (p[1], p[3], p[7], p[5])])


def test_solid_overlap_is_three_dimensional():
    a = cube(0, 0, 0)
    assert overlaps(a, cube(0.5, 0.5, 0.5)) and overlaps(a, cube(0.2, 0.2, 0.2, 0.3))
    assert not overlaps(a, cube(0.0, 0.0, 1.0)) and not overlaps(a, cube(0.0, 0.0, 5.0))      # 평면은 같아도 위로 맞닿음·떨어짐
    assert not overlaps(a, cube(1.0, 0.0, 0.0))
    tilt = Convex("t", [((1.2, 0, 0.5), (3, -1, 0.5), (3, 1, 0.5)), ((1.2, 0, 0.5), (3, -1, 0.5), (3, 0, 2)),
                        ((1.2, 0, 0.5), (3, 1, 0.5), (3, 0, 2)), ((3, -1, 0.5), (3, 1, 0.5), (3, 0, 2))])
    assert not overlaps(a, tilt)


@pytest.mark.parametrize("along", [10.0, 12.0, 13.4])
def test_surface_parts_may_stand_above_deep_structures(along):
    """지상 기단·경사로가 깊은 출입구 바닥 위에 평면으로 겹쳐도 높이가 다르면 허용"""
    for side in (1, -1):
        for face in ("+u", "-u"):
            layouts(ExtEvSpec(host="passage", along=along, host_side=side, face=face))


def test_real_collisions_are_errors():
    for spec, match in ((ExtEvSpec(host="passage", along=14.0), "출입구 EN1"),                  # 피트·벽이 출입구 박스와 실제로 겹침
                        (ExtEvSpec(host="entrance", u=8, t=0.0, face="+t"), "겹칩니다"),
                        (ExtEvSpec(host="entrance", u=-5, t=0.0, face="+t"), "출구통로 EX1")):
        with pytest.raises(ValueError, match=match):
            layouts(spec)
    ground = cfg_with(FORE).entrances[0].ground_el
    zl = cfg_with(FORE).passage_layouts()[0].vertices[-1].z
    with pytest.raises(ValueError, match="정거장 본체"):
        layouts(ExtEvSpec(host="station", u=30, t=0, low_z=zl, ground_el=ground))
    with pytest.raises(ValueError, match="외부 엘리베이터 OEV1"):
        layouts(ExtEvSpec(host="passage", along=6.0), ExtEvSpec(host="passage", along=8.0))
    layouts(ExtEvSpec(host="passage", along=6.0), ExtEvSpec(host="passage", along=6.0, host_side=-1))     # 양쪽은 안 겹침
    layouts(ExtEvSpec(host="station", u=30, t=25, low_z=zl, ground_el=ground))


# ===================================================== 위치 기준 · 검증
def test_station_host_follows_curved_alignment():
    base = cfg_with(FORE, curved=True)
    zl = base.passage_layouts()[0].vertices[-1].z
    cfg = ev_cfg(ExtEvSpec(host="station", u=20, t=25, face="+t", low_z=zl, ground_el=zl + 15.0), base=base)
    cfg.validate()
    (x,) = cfg.ext_ev_layouts()
    U0, U1, T0, T1 = x.outer
    assert x.frame.to_world((U0 + U1) / 2, (T0 + T1) / 2) == pytest.approx(cfg.to_world(20, 25))
    assert x.ground == pytest.approx(zl + 15.0) and x.stops[1] == pytest.approx(zl)


def test_rules():
    cases = ((ExtEvSpec(host="entrance", u=8, t=6, face="+x"), "문 방향"), (ExtEvSpec(host="entrance", u=8, t=6, car_width=3.0), "카"),
             (ExtEvSpec(host="passage", along=40.0), "경로 길이"), (ExtEvSpec(host="passage", along=0.2), "측벽 범위"),
             (ExtEvSpec(host="passage", along=6.0, host_side=0), "통로 쪽"), (ExtEvSpec(host="passage", host_name="NO", along=6), "'NO'"),
             (ExtEvSpec(host="entrance", host_name="NO", u=8, t=6), "'NO'"), (ExtEvSpec(host="x"), "위치 기준"),
             (ExtEvSpec(host="station", u=30, t=25), "지하 정지 바닥"))
    for spec, match in cases:
        with pytest.raises(ValueError, match=match):
            layouts(spec)
    with pytest.raises(ValueError, match="지표 EL"):
        layouts(ExtEvSpec(host="station", u=30, t=25, low_z=0.0))
    with pytest.raises(ValueError, match="중복"):                                              # 내부 엘리베이터 이름과도 겹치면 안 됨
        cfg = ev_cfg(ExtEvSpec(name="EV1", host="passage", along=6.0))
        cfg.elevators = [ElevatorSpec(lower_floor=1, upper_floor=2, s_center=70, t_center=6.5)]
        cfg.validate()


# ===================================================== 입력 초안 · 옛 프로젝트
def test_draft_to_spec():
    sp = ExtEvDraft(host=HOST_PASSAGE, host_name="EX1", along="6", side=SIDE_LABELS[1]).to_spec("외부 EV", 100.0)
    assert (sp.host, sp.host_name, sp.along, sp.host_side, sp.ground_el, sp.low_z) == ("passage", "EX1", 6.0, -1, None, None)
    sp = ExtEvDraft(host=HOST_ENTRANCE, u="8", t="6", face="+t", low_face="-u", car_at="지하", ground_el="109.3").to_spec("외부 EV", 0)
    assert (sp.host, sp.u, sp.t, sp.face, sp.low_face, sp.car_at, sp.ground_el) == ("entrance", 8.0, 6.0, "+t", "-u", "low", 109.3)
    sp = ExtEvDraft(host=HOST_STATION, sta="130", t="25", low_z="3").to_spec("외부 EV", 100.0)
    assert (sp.host, sp.u, sp.t, sp.low_z, sp.low_face) == ("station", 30.0, 25.0, 3.0, None)
    assert sp.low_finish == "glass"                                                            # 화면 기본 = 투시형 (모델 기본 폐쇄형)
    assert ExtEvDraft(low_finish=LOW_CLOSED).to_spec("x", 0).low_finish == "closed" == ExtEvSpec().low_finish
    for bad in (dict(along="x"), dict(low_finish="?"), dict(along="-1"), dict(sign_bg="red"), dict(face="+x"), dict(host="?"), dict(door_open="-1")):
        with pytest.raises(ValueError, match="외부 엘리베이터 1"):
            d = ExtEvDrafts()
            d.items.append(ExtEvDraft(**bad))
            d.to_specs(0.0)


def test_old_project_entrance_evs_become_independent():
    d = ProjectState().to_dict()
    d.pop("ext_ev_drafts")
    d["entrance_drafts"] = [{"name": "", "passage": "EX1", "ground_el": "109.3", "line_name": "GTX A", "ev_on": True, "ev_u": "8", "ev_t": "6",
                             "ev_face": "+t", "ev_low_face": "(지상과 같음)", "ev_low_z": "", "ev_car_at": "지하", "ev_door_open": "0.5"},
                            {"name": "B", "passage": "EX2", "ev_on": False},
                            {"name": "C", "passage": "EX3", "ev_on": True, "ev_host": "출구통로 옆", "ev_along": "6", "ev_side": "오른쪽 (−)"}]
    st = ProjectState.from_dict(d)
    a, c = st.ext_ev_drafts
    assert (a.name, a.host, a.host_name, a.u, a.t, a.face, a.car_at, a.ground_el, a.line_name) == \
        ("EN1_EV1", HOST_ENTRANCE, "EN1", "8", "6", "+t", "지하", "109.3", "GTX A")
    assert (c.name, c.host, c.host_name, c.along, c.side) == ("C_EV1", HOST_PASSAGE, "EX3", "6", "오른쪽 (−)")
    assert a.to_spec("x", 0).door_open == 0.5 and c.to_spec("x", 0).host_side == -1
    st2 = ProjectState.from_dict(st.to_dict())                                                 # 다시 저장·열기 (두 번 옮기지 않음)
    assert st2.ext_ev_drafts == st.ext_ev_drafts
