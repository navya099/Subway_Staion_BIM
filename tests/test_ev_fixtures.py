"""엘리베이터 호출 버튼 판·층 표시기, 금속 보기 재질, 웹 뷰어 애니메이션 자료 (카 이동·문 열림) 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ifcopenshell
import numpy as np
import pytest

from elevators import hall_fixture as HF
from elevators.elevator_engine import ev_part_faces
from elevators.elevator_spec import ElevatorSpec
from elevators.elevator_type import ElevatorPartKind as K
from elevators.ext_ev import ExtEvSpec
from engine.cad_engine import StationCADEngine
from exporter import ev_anim
from exporter.dae_exporter import element_materials, frame_uv
from exporter.web_viewer import build_web_data
from gui.elevator_draft import ElevatorDraft
from gui.ext_ev_draft import ExtEvDraft
from helper import prism_member as PM
from helper.strip_member import part_faces
from test_entrances import FORE, _fin_cfg, cfg_with, ifc_world_volume
from test_ext_ev import _ext_overlaps

GLASS = dict(shaft="glass", inner_s=3.0, inner_t=3.0, overhead=2.6, door_floors=["-s", "-s", "+t"], s_center=80.0, t_center=6.5)
RC = dict(shaft="rc", door_side="-s", overhead=2.8, s_center=95.0, t_center=-6.0)


def make(ev=(), ext=(), fin=True, curved=False):
    cfg = _fin_cfg(**FORE) if fin else cfg_with(FORE, curved=curved)
    cfg.elevators = [ElevatorSpec(lower_floor=1, upper_floor=3, **{"fixtures": True, **kw}) for kw in ev]
    cfg.ext_evs = [ExtEvSpec(host="passage", along=6.0, **{"fixtures": True, **kw}) for kw in ext]
    cfg.validate()
    return cfg


# ===================================================== 배치
@pytest.mark.parametrize("kw", [GLASS, RC, dict(RC, through=True)])
def test_internal_fixtures(kw):
    cfg = make([kw])
    (lay,) = cfg.elevator_layouts()
    fx = [p for p in lay.parts if p.kind in (K.CALL_PANEL, K.CALL_BUTTON, K.INDICATOR)]
    doors = {n: lay.spec.doors_at(n) for n in (1, 2, 3)}
    n_doors = sum(len(v) for v in doors.values())
    by = lambda k: [p for p in fx if p.kind == k]
    assert len(by(K.CALL_PANEL)) == len(by(K.INDICATOR)) == n_doors
    ups = [p for p in by(K.CALL_BUTTON) if p.code.startswith("CALLU")]
    dns = [p for p in by(K.CALL_BUTTON) if p.code.startswith("CALLD")]
    assert {p.stop for p in ups} == {1, 2} and {p.stop for p in dns} == {2, 3}                 # 최하층 위만 · 최상층 아래만
    S0, S1, T0, T1 = lay.spec.outer_rect()
    for p in fx:
        head, axis, sign = HF.parse_code(p.code)
        assert (axis, sign) in doors[p.stop]
        rng = p.s_range if axis == "s" else p.t_range
        outer = {("s", 1): S1, ("s", -1): S0, ("t", 1): T1, ("t", -1): T0}[(axis, sign)]
        inner_side = min(rng) if sign > 0 else max(rng)
        depth = sign * (inner_side - outer)                                                   # 붙은 면: 투시형 = 유리 바깥면, RC = 마감 표면
        want = (HF.PANEL_T if head in ("CALLU", "CALLD") else 0.0) + (0.0 if kw is GLASS else 0.15)
        assert depth == pytest.approx(want, abs=1e-9)
    st = cfg.station
    for p in by(K.CALL_PANEL):                                                                 # 문을 보는 사람의 오른쪽
        _, axis, sign = HF.parse_code(p.code)
        tan = p.t_range if axis == "s" else p.s_range
        mid = lay.spec.t_center if axis == "s" else lay.spec.s_center
        assert ((sum(tan) / 2.0 - mid) > 0) == (HF.right_sign(axis, sign) > 0)
        assert p.z_range[0] - lay.stops[p.stop] == pytest.approx(HF.PANEL_Z - HF.PANEL_H / 2.0)
    assert st.floors == 3


@pytest.mark.parametrize("low", ["glass", "closed"])
@pytest.mark.parametrize("face", ["+u", "-u", "+t", "-t"])
def test_external_fixtures_do_not_overlap(low, face):
    cfg = make(ext=[dict(low_finish=low, face=face, host_side=1 if face != "-t" else -1)])
    (x,) = cfg.ext_ev_layouts()
    fx = [p for p in x.parts if p.kind in ("CALL_PANEL", "CALL_BUTTON", "INDICATOR")]
    assert sorted(p.code.split("_")[0] for p in fx) == ["CALLD", "CALLP", "CALLP", "CALLU", "IND", "IND"]
    assert {p.code[-3:] for p in fx if p.code.startswith("CALLU")} == {"LOW"} and _ext_overlaps(x.frame, x.parts) == []


def test_fixtures_default_off_in_model_on_in_gui():
    cfg = make([dict(RC, fixtures=False)], [dict(fixtures=False)])
    assert not [p for p in cfg.elevator_layouts()[0].parts if p.kind == K.INDICATOR]
    assert not [p for p in cfg.ext_ev_layouts()[0].parts if p.kind == "INDICATOR"]
    assert not ElevatorSpec().fixtures and not ExtEvSpec().fixtures and ElevatorDraft().fixtures and ExtEvDraft().fixtures
    assert ElevatorDraft().to_spec("x", 0).fixtures and not ExtEvDraft(fixtures=False).to_spec("x", 0).fixtures


# ===================================================== 출력
def test_ifc_classes_and_volumes(tmp_path):
    eng = StationCADEngine(make([GLASS], [dict(low_finish="glass")]))
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "f.ifc"))
    by = {e.Name: e for e in f.by_type("IfcElement")}
    assert by["EV1_CALLU_NS_B3F"].is_a("IfcSwitchingDevice") and by["EV1_IND_PT_B1F"].is_a("IfcUnitaryControlElement")
    assert by["OEV1_CALLP_NT_LOW"].is_a("IfcUnitaryControlElement") and by["OEV1_IND_PS_GND"].PredefinedType == "INDICATORPANEL"
    for e in eng.elevators.elevators[0].elements:
        if e.kind in (K.CALL_PANEL, K.CALL_BUTTON, K.INDICATOR):
            mesh = sum(PM.mesh_volume(ev_part_faces(eng.cfg, p)) for p in e.parts)
            assert mesh == pytest.approx(e.volume, rel=1e-4) and ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=1e-4)
    for e in eng.ext_evs.ext_evs[0].elements:
        if e.kind in ("CALL_PANEL", "CALL_BUTTON", "INDICATOR"):
            assert sum(PM.mesh_volume(q) for q in part_faces(e.frame, e)) == pytest.approx(e.volume, rel=1e-4)


def test_face_images_map_to_front_face():
    """버튼·표시기 앞면: uv (0,0) = 왼쪽 아래, 오른쪽 × 위 = 바깥 법선"""
    eng = StationCADEngine(make([GLASS], [dict(low_finish="closed")]))
    eng.build_3d_doc()
    imgs = eng.elevators.sign_images() + [s for s in eng.ext_evs.sign_images() if "IND" in s[0] or "CALL" in s[0]]
    assert len(imgs) == 3 + 4 + 2 + 2
    for name, img, frame, faces in imgs:
        o, r, u, w, h, _ = frame
        pts = np.array([tuple(v) for f in faces for v in (f.dxf.vtx0, f.dxf.vtx1, f.dxf.vtx2, f.dxf.vtx3)])
        uv = frame_uv(frame, (pts - np.array([0.0, 0.0, 0.0]))[None, :, :], np.zeros(3))[0]
        assert uv.min() == pytest.approx(0.0, abs=1e-6) and uv.max() == pytest.approx(1.0, abs=1e-6)
        n = np.cross(r, u)                                                                     # 바깥 법선: 앞면이 부재 중심보다 바깥
        assert (np.array(o) - pts.mean(axis=0)) @ n > 0
        assert img.size[0] > 60
    assert HF.fixture_image("CALLP_PT_B1F", "B1F") is None
    a, b = HF.render_indicator("B1F"), HF.render_indicator("B1F", HF.DIR_UP)
    assert np.abs(np.asarray(a, int) - np.asarray(b, int)).sum() > 0
    edge = np.asarray(a)[:, :6].astype(int)
    assert edge.max() < 120                                                                    # 글자가 테두리 밖으로 잘리지 않음


def test_metal_materials():
    eng = StationCADEngine(make([GLASS], [dict(low_finish="glass")]))
    eng.build_3d_doc()
    mats = element_materials(eng)
    name = lambda e: mats[e.source_element[0].dxf.handle].name
    for e in eng.elevators.elevators[0].elements:
        if e.kind in (K.LANDING_DOOR, K.DOOR_FRAME, K.CAR_DOOR, K.CALL_PANEL):
            assert name(e) == "스테인리스 헤어라인"
        elif e.kind in (K.COLUMN, K.GIRT):
            assert name(e) == "강관 도장"
    for e in eng.ext_evs.ext_evs[0].elements:
        if e.kind == "COLUMN":
            assert name(e) == "강관 도장"
    from exporter.render_material import find_image
    assert find_image("stainless_hairline") is not None


# ===================================================== 웹 뷰어 자료
@pytest.mark.parametrize("curved", [False, True])
def test_animation_vectors_match_geometry(curved):
    """문짝 이동(d) = 열림 1 로 다시 만든 형상의 실제 이동, 카 = 연직 이동 (독립 검증)"""
    ev, ext = [dict(GLASS, car_floor=2), dict(RC, car_floor=2)], [dict(low_finish="glass", car_at="low")]
    closed = StationCADEngine(make(ev, ext, fin=not curved, curved=curved))
    opened = StationCADEngine(make([dict(k, door_open=1.0) for k in ev], [dict(k, door_open=1.0) for k in ext], fin=not curved, curved=curved))
    closed.build_3d_doc()
    evs, tags = ev_anim.build(closed, (0.0, 0.0, 0.0))

    def center(eng, e):
        fs = [f for p in e.parts for f in ev_part_faces(eng.cfg, p)] if hasattr(e, "parts") else e.faces()
        return np.mean([p for f in fs for p in f], axis=0)
    seen = 0
    for k, (a, b) in enumerate(list(zip(closed.elevators.elevators, opened.elevators.elevators))
                               + list(zip(closed.ext_evs.ext_evs, opened.ext_evs.ext_evs))):
        eb = {e.name: e for e in b.elements}
        at = min(range(len(evs[k]["stops"])), key=lambda i: abs(evs[k]["stops"][i]["z"] - evs[k]["z"]))
        for e in a.elements:
            tag = tags.get(e.source_element[0].dxf.handle) if e.source_element else None
            if not tag or "d" not in evs[k]["parts"].get(tag, {}):
                continue
            p = evs[k]["parts"][tag]
            move = center(opened, eb[e.name]) - center(closed, e)
            if p["role"] == "landing" and p["stop"] != at:
                assert np.abs(move).max() < 1e-9                                               # 다른 층 문은 안 열림
                continue
            assert move == pytest.approx(p["d"], abs=5e-3 if curved else 1e-6), tag
            seen += 1
    assert seen == 6 + 4 + 6                                          # 카 문짝 + 선 층 승강장 문짝


def test_animation_tags_and_buttons():
    eng = StationCADEngine(make([GLASS, RC], [dict(low_finish="closed")]))
    data, _ = build_web_data(eng)
    evs = data["evs"]
    assert [e["name"] for e in evs] == ["EV1", "EV2", "OEV1"]
    assert [s["label"] for s in evs[0]["stops"]] == ["B3F", "B2F", "B1F"] and [s["label"] for s in evs[2]["stops"]] == ["B1F", "1F"]
    assert [s["faces"] for s in evs[0]["stops"]] == [["NS"], ["NS"], ["PT"]]                    # 층별 문 면
    zs = [s["z"] + data["origin"][2] for s in evs[0]["stops"]]
    assert zs == pytest.approx([eng.elevators.elevators[0].stops[n] for n in (1, 2, 3)], abs=1e-4)
    names = {e["name"] for e in data["elements"]}
    for e in evs:
        assert set(e["buttons"]) <= names and all(0 <= i < len(e["stops"]) and d in ("up", "down") for i, d in e["buttons"].values())
    assert evs[0]["buttons"]["EV1_CALLU_NS_B3F"] == [0, "up"]
    used = {c["anim"] for c in data["chunks"] if c.get("anim")}
    assert used == {t for e in evs for t in e["parts"]}                                       # 태그마다 메쉬가 있음
    for c in data["chunks"]:                                                                  # 움직이지 않는 부재에는 태그 없음
        assert not c.get("anim") or c["layer"] in ("STRUCT_ELEVATOR_CAR", "STRUCT_ELEVATOR_GLASS", "STRUCT_ELEVATOR_FRAME")
    for lb in ("B3F", "B2F", "B1F", "1F"):
        for d in ("", "up", "down"):
            assert HF.indicator_key(lb, d) in data["images"]


def test_no_elevators_no_animation():
    data, _ = build_web_data(StationCADEngine(cfg_with(FORE)))
    assert data["evs"] == [] and not [c for c in data["chunks"] if c.get("anim")]


# ===================================================== RC 승강로 벽 마감의 문 자리 (이격 마감)
@pytest.mark.parametrize("through", [False, True])
def test_wall_finish_leaves_door_openings(through):
    """벽 마감이 벽면에서 이격(금속패널 0.15)된 RC 승강로: 마감이 문을 막지 않음 (예전엔 이격이 있으면 문 자리를 비우지 않았음)"""
    cfg = make([dict(RC, through=through)])
    eng = StationCADEngine(cfg)
    (lay,) = cfg.elevator_layouts()
    S0, S1, T0, T1 = lay.spec.outer_rect()
    st = cfg.station
    pcs = [q for r in eng.finishes.rooms for e in r.elements for q in e.pieces if q.shape.height > 1.0]   # 벽·승강로 마감
    for n in (1, 2, 3):
        for s in [S0 - 0.15 + 0.001] + ([S1 + 0.15 - 0.001] if through else []):
            z = lay.stops[n] + 1.0
            hit = lambda t: [q for q in pcs if PM.s_range(q)[0] - 2e-2 < s < PM.s_range(q)[1] + 2e-2 and PM.t_range(q)[0] < t < PM.t_range(q)[1]
                             and q.pos_z < z < q.pos_z + q.shape.height]
            assert not hit(lay.spec.t_center), n                                               # 문 가운데
            assert hit(T1 - 0.3), n                                                            # 문 옆에는 마감이 있음
    assert st.floors == 3
