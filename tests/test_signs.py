"""역명판·안내사인(타는 곳·출구): 이미지 생성, 배치, BIM·IFC·DAE 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xml.etree.ElementTree as ET

import ifcopenshell
import ifcopenshell.util.element
import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from escalators.escalator_spec import EscalatorSpec
from finishes.finish_spec import FinishSettings
from gui.project_file import ProjectState
from gui.sign_draft import ExitDraft, SignDraft, preview
from helper import prism_member as PM
from passages.passage_spec import STATION, PassageSpec, PathVertex
from signs.nameplate import STYLES, NameplateInput, render_boarding, render_exit, render_nameplate
from signs.sign_layout import BOARDING, EXIT, NAMEPLATE, layout_signs
from signs.sign_spec import ExitInfo, SignSettings, StationInfo, StationRef
from stairs.stair_spec import StairSpec
from test_curved import NO_COLS
from test_finishes import ifc_world_volume
from test_patch import make_cfg

# make_cfg: 3개 층 각 6m, 내공 198 × 18, 승강장 t ±3.9 ~ ±9 (상면 1.3)
INFO = StationInfo(kname="검단3동", ename="Geomdan 3-dong", cname="黔丹3洞", no="215", rgb="#0090D2",
                   plus=StationRef("아라", "Ara"), minus=StationRef("검단오류", "Geomdan-oryu"))


def cfg_s(finishes=True, **kw):
    cfg = make_cfg(NO_COLS())
    cfg.finish_settings = FinishSettings(enabled=finishes)
    cfg.sign_settings = SignSettings(enabled=True, station=INFO, dest_l="인천대입구 방면", dest_r="검단호수공원 방면", **kw)
    return cfg


def by_kind(cfg, kind):
    return [p for p in layout_signs(cfg) if p.kind == kind]


# ===================================================== 이미지
@pytest.mark.parametrize("style", sorted(STYLES))
def test_nameplate_styles_render(style):
    inp = NameplateInput(kname="검단3동", ename="Geomdan 3-dong", cname="黔丹3洞", jname="コムダン", no="215",
                         prev=StationRef("검단오류", "Geomdan-oryu"), next=StationRef("아라", "Ara"))
    img = render_nameplate(style, inp)
    assert img.width > img.height > 100
    alone = render_nameplate(style, NameplateInput(kname="역"))                  # 이웃 역 없음 → 아래 띠 없음 (더 낮음)
    assert alone.height < img.height
    with pytest.raises(ValueError, match="스타일"):
        render_nameplate("없음", inp)


def test_guide_sign_images_keep_aspect():
    for img in (render_boarding(2.4, 0.45, "아무개 방면"), render_exit(2.4, 0.45, "3", "가\n나\n다\n라")):
        assert img.width / img.height == pytest.approx(2.4 / 0.45, rel=0.01)


# ===================================================== 배치
def test_nameplates_on_both_platform_walls():
    cfg = cfg_s()
    nps = by_kind(cfg, NAMEPLATE)
    for side, tag in ((1, "L"), (-1, "R")):
        ps = [p for p in nps if p.name.startswith(f"NP_{tag}_")]
        assert [p.s for p in ps] == pytest.approx([19.0, 59.0, 99.0, 139.0, 179.0])         # 가운데 99 기준 40m 간격
        assert all(p.t == pytest.approx(side * (9.0 - 0.15)) for p in ps)                   # 측벽 금속패널 표면 (0.15)
        assert all(p.normal == (0.0, -float(side)) and p.mounted for p in ps)
        assert all(p.z0 == pytest.approx(1.3 + 0.1 + 2.0) and p.height == 0.8 for p in ps)
        assert ps[0].content["right_plus"] is (side > 0)                                    # +t 벽을 보면 오른쪽 = +s
    assert by_kind(cfg_s(finishes=False), NAMEPLATE)[0].t == pytest.approx(9.0)            # 마감 없음 = 내공면
    body, face = nps[0].boxes()
    assert body[2:4] == pytest.approx((8.8, 8.85)) and face[2:4] == pytest.approx((8.798, 8.8))   # 판 + 승강장 쪽 이미지 면


def test_nameplate_skips_wall_opening_and_neighbors_follow_view():
    cfg = cfg_s(plate_bottom=0.5)
    cfg.passages = [PassageSpec(floor=1, path=[PathVertex(STATION, 99.0, None, None), PathVertex(STATION, 99.0, -20.0, 0.0)],
                                name="EX1")]
    rs = [p.s for p in by_kind(cfg, NAMEPLATE) if p.name.startswith("NP_R_")]
    assert 99.0 not in rs and len(rs) == 4
    from signs.sign_layout import nameplate_input
    ss = cfg.sign_settings
    assert nameplate_input(ss, True).next.kname == "아라" and nameplate_input(ss, False).next.kname == "검단오류"


def test_boarding_signs_above_stairs_and_escalators_to_platform():
    cfg = cfg_s()
    cfg.stairs = [StairSpec(lower_floor=1, s_start=40.0, direction=1, t_center=6.5, width=2.0, name="ST1"),
                  StairSpec(lower_floor=2, s_start=60.0, direction=1, t_center=0.0, width=2.0, name="ST2")]
    cfg.escalators = [EscalatorSpec(lower_floor=1, s_wp=150.0, direction=-1, t_center=-6.5, name="ES1")]
    bd = {p.name: p for p in by_kind(cfg, BOARDING)}
    assert set(bd) == {"BD_ST1", "BD_ES1"}                                                   # 2층 → 3층 계단은 아님
    st = cfg.stair_layouts()[0]
    p = bd["BD_ST1"]
    assert (p.floor, p.s, p.t, p.normal) == (2, pytest.approx(st.s_at(st.length + 1.5)), 6.5, (1.0, 0.0))
    assert p.content["dest"] == "인천대입구 방면" and p.z0 == pytest.approx(6.0 + 0.1 + 2.5)
    es = cfg.escalator_layouts()[0]
    q = bd["BD_ES1"]
    assert q.s == pytest.approx(es.s_at(es.u_range[1] + 1.5)) and q.normal == (-1.0, 0.0)
    assert q.content["dest"] == "검단호수공원 방면"
    assert not by_kind(cfg_s(boarding=False), BOARDING)


def test_exit_signs_in_front_of_passages():
    cfg = cfg_s(exit_info=[ExitInfo("EXB", "7", "가\n나")])
    cfg.passages = [PassageSpec(floor=3, path=[PathVertex(STATION, 50.0, None, None), PathVertex(STATION, 50.0, 20.0, 0.0)],
                                name="EXA"),
                    PassageSpec(floor=3, path=[PathVertex(STATION, 120.0, None, None), PathVertex(STATION, 120.0, -20.0, 0.0)],
                                name="EXB")]
    ex = {p.name: p for p in by_kind(cfg, EXIT)}
    a, b = ex["EX_EXA"], ex["EX_EXB"]
    assert (a.floor, a.s, a.t, a.normal, a.content["number"]) == (3, 50.0, pytest.approx(9.0 - 1.5), (0.0, -1.0), "1")
    assert (b.t, b.normal, b.content["number"], b.content["destinations"]) == (pytest.approx(-7.5), (0.0, 1.0), "7", "가\n나")


@pytest.mark.parametrize("kw, msg", [
    (dict(style="없음"), "스타일"), (dict(plate_h=0.0), "역명판 높이"), (dict(hang_bottom=-1.0), "하단 높이"),
    (dict(plate_bottom=4.0), "천장"), (dict(hang_w=0.0), "매달림 사인 폭"),
])
def test_invalid(kw, msg):
    cfg = cfg_s(**kw)
    with pytest.raises(ValueError, match=msg):
        cfg.validate()


def test_hanging_sign_below_ceiling():
    cfg = cfg_s(hang_bottom=2.8)                                       # 대합실 천장판 FL+0.1+3.0, 사인 높이 0.45 → 넘음
    cfg.stairs = [StairSpec(lower_floor=1, s_start=40.0, direction=1, t_center=6.5, width=2.0, name="ST1")]
    with pytest.raises(ValueError, match="BD_ST1.*천장"):
        cfg.validate()


# ===================================================== BIM · IFC · 도면 · DAE
def full_cfg():
    cfg = cfg_s()
    cfg.stairs = [StairSpec(lower_floor=1, s_start=40.0, direction=1, t_center=6.5, width=2.0, name="ST1")]
    cfg.passages = [PassageSpec(floor=3, path=[PathVertex(STATION, 50.0, None, None), PathVertex(STATION, 50.0, 20.0, 0.0)],
                                name="EXA")]
    return cfg


def test_engine_ifc_and_drawings(tmp_path):
    eng = StationCADEngine(full_cfg())
    names = [e.name for e in eng.signs.elements]
    assert len(names) == 12 and "BD_ST1" in names and "EX_EXA" in names
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "s.ifc"))
    by = {e.Name: e for e in f.by_type("IfcBuildingElementProxy")}
    for e in eng.signs.elements:
        el = by[e.name]
        assert el.ObjectType == "SIGNAGE" and el.ContainedInStructure[0].RelatingStructure.Name == e.level
        assert ifc_world_volume(el) == pytest.approx(e.volume, rel=1e-7)
        quads = [q for p in e.pieces for q in PM.sweep_quads(PM.rings(eng.cfg, p))]
        assert PM.mesh_volume(quads) == pytest.approx(e.volume, rel=1e-7)
    ps = ifcopenshell.util.element.get_psets(by["EX_EXA"])["SSBIM_Sign"]
    assert ps["Kind"] == "출구 안내" and ps["Text"].startswith("출구 1")
    assert by["NP_L_1"].Description == "검단3동 Geomdan 3-dong"
    plan = eng.signs.plan_items(2.0, floor=1)
    assert len(plan) == 20 and any(it.label and it.label[0].startswith("검단3동") for it in plan)
    assert [it.name for it in eng.signs.plan_items(2.0, floor=2) if not it.label] == ["BD_ST1"]
    assert eng.signs.section_items(99.0) and eng.signs.profile_items(8.82)
    doc = eng.build_3d_doc()
    assert len(doc.modelspace().query('3DFACE[layer=="STRUCT_SIGN_FACE"]')) == 12 * 6


def test_dae_sign_images_fit_face(tmp_path):
    eng = StationCADEngine(full_cfg())
    path = eng.generate_dae(tmp_path / "m.dae", texture_dir=tmp_path / "none")
    signs = sorted(os.listdir(tmp_path / "textures"))
    assert signs == [f"sign_{k:03d}.png" for k in range(1, 13)]
    assert {f"사인 {e.name}" for e in eng.signs.elements} <= set(eng.dae_result.textured)
    # 이미지 면 앞면 네 모서리 → 텍스처 (0~1, 0~1): 보는 사람 기준 왼쪽 아래 = (0, 0)
    root = ET.parse(path).getroot()
    ns = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
    mats = {m.get("id"): m.get("name") for m in root.iterfind(".//c:material", ns)}
    g = next(g for g in root.iterfind(".//c:geometry", ns) if mats[g.find(".//c:triangles", ns).get("material")] == "사인 NP_L_1")
    arr = {a.get("id"): np.array(a.text.split(), dtype=float) for a in g.iterfind(".//c:float_array", ns)}
    uv = next(v for k, v in arr.items() if k.endswith("uv-array")).reshape(-1, 2)
    pos = next(v for k, v in arr.items() if k.endswith("pos-array")).reshape(-1, 3)
    e = next(e for e in eng.signs.elements if e.name == "NP_L_1")
    o, u, v, w, h, k = eng.signs.uv_frame(e)
    assert k == pytest.approx(eng.cfg.grade_permil(e.placement.s) / 1000.0, rel=1e-3)        # +t 벽 오른쪽 = +s
    front = np.abs(uv[:, 0] - 0.5) <= 0.5 + 1e-6
    assert uv[:, 0].min() == pytest.approx(0.0, abs=1e-3) and uv[:, 0].max() == pytest.approx(1.0, abs=1e-3)
    assert uv[:, 1].min() == pytest.approx(0.0, abs=1e-3) and uv[:, 1].max() == pytest.approx(1.0, abs=1e-3)
    assert front.all() and pos.shape[0] == uv.shape[0]
    th = eng.cfg.theta_at(e.placement.s)
    assert u[0] * np.cos(th) + u[1] * np.sin(th) == pytest.approx(1.0)                     # 오른쪽 = 선형 진행방향 (+s)


# ===================================================== 입력 초안 · 프로젝트 파일
def test_draft_settings_preview_and_project():
    d = SignDraft()
    assert d.enabled is True and d.style == "서울 지하철형"
    d.kname, d.plus_kname, d.minus_no, d.style = "검단3동", "아라", "214", "코레일형"
    d.exits = [ExitDraft("EX1", "3", "가 / 나 /  ")]
    ss = d.to_settings()
    assert ss.style == "korail" and ss.station.plus.kname == "아라" and ss.station.minus.no == "214"
    assert ss.exit_info == [ExitInfo("EX1", "3", "가\n나")]
    assert "출구 1곳" in preview(d)
    d.plate_h = "x"
    with pytest.raises(ValueError, match="판 높이"):
        d.to_settings()
    d.enabled = False
    assert d.to_settings().enabled is False and "없음" in preview(d)
    st = ProjectState()
    st.sign_draft.kname, st.sign_draft.exits = "역", [ExitDraft("EX2", "5", "가")]
    back = ProjectState.from_dict(st.to_dict())
    assert back.sign_draft == st.sign_draft and isinstance(back.sign_draft.exits[0], ExitDraft)
    old = st.to_dict()
    del old["sign_draft"]
    assert ProjectState.from_dict(old).sign_draft == SignDraft()
