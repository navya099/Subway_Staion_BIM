"""스크린도어(PSD): 열차 문마다 유닛 + POST + 구동부 + 채움 패널 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ifcopenshell
import ifcopenshell.util.element
import pytest

from engine.cad_engine import StationCADEngine
from gui.project_file import ProjectState
from gui.psd_draft import PsdDraft, preview
from helper import prism_member as PM
from helper.strip_member import _fan
from psds.psd_layout import DOOR, EMERGENCY, FILL, FIXED, HEADER, POST, layout_psds
from psds.psd_spec import PsdSettings
from test_finishes import ifc_world_volume
from test_tactile import cfg_t
from trains.train_spec import CarDoor, TrainSettings, TrainStop, make_train

# cfg_t: 내공 198 × 18, 선로 t = ±2.2, 승강장 끝단 |t| = 3.9 (상면 1.3), 기본 열차 8량 × 20m 문 4개 (문 간격 5.0)


def cfg_psd(finishes=False, curved=False, train=None, stops=None, **ps):
    cfg = cfg_t(finishes=finishes, curved=curved)
    kw = {} if stops is None else {"stops": stops}
    cfg.train_settings = TrainSettings(enabled=True, train=train or make_train(), **kw)
    cfg.psd_settings = PsdSettings(enabled=True, **ps)
    return cfg


def parts(cfg, track="R"):
    return next(r for r in layout_psds(cfg) if r.track == track).parts


def by_name(ps):
    return {p.name: p for p in ps}


# ===================================================== 배치
def test_disabled_by_default():
    cfg = cfg_t()
    assert cfg.psd_settings.enabled is False and layout_psds(cfg) == []
    assert StationCADEngine(cfg).psds.elements == []


def test_units_at_train_doors_with_shared_posts():
    cfg = cfg_psd()
    ps = parts(cfg)
    count = lambda k: sum(1 for p in ps if p.kind == k)
    assert (count(DOOR), count(FIXED), count(EMERGENCY), count(HEADER), count(POST), count(FILL)) == (64, 32, 32, 32, 33, 0)
    u = by_name(ps)
    # R 선로 1-1 문 중심 176.5: 고정부 | 가동문 | 가동문 | 고정부, PSD 중심선 t = −(3.9 + 0.3)
    s = lambda name: (u[name].pieces[0][0], u[name].pieces[1][1])            # 왼쪽 기둥 시작 ~ 오른쪽 기둥 끝
    assert s("PSD_R_1-1_FIX_N") == pytest.approx((174.1, 175.45)) and s("PSD_R_1-1_DOOR_N") == pytest.approx((175.45, 176.5))
    assert s("PSD_R_1-1_DOOR_P") == pytest.approx((176.5, 177.55)) and s("PSD_R_1-1_FIX_P") == pytest.approx((177.55, 178.9))
    assert u["PSD_R_1-1_FIX_P"].kind == EMERGENCY and u["PSD_R_1-1_FIX_N"].kind == FIXED
    glass = u["PSD_R_1-1_DOOR_N"].pieces[4]
    assert glass[2:4] == pytest.approx((-4.204, -4.196)) and u["PSD_R_1-1_DOOR_N"].glass == [False] * 4 + [True]
    assert glass[4:] == pytest.approx((1.3 + 0.1, 1.3 + 2.0 - 0.05))                   # 하부 레일 위 ~ 위 프레임 아래
    assert u["PSD_R_1-1_HEADER"].pieces[0] == pytest.approx((174.1, 178.9, -4.375, -4.025, 3.3, 3.7))
    posts = sorted(p.pieces[0][0] for p in ps if p.kind == POST)
    assert posts[0] == pytest.approx(18.9) and posts[-1] == pytest.approx(178.9)
    assert all(b - a == pytest.approx(5.0) for a, b in zip(posts, posts[1:]))           # 유닛 4.8 + POST 0.2
    assert all(p.pieces[0][4:] == pytest.approx((1.3, 3.7)) for p in ps if p.kind == POST)
    # L 선로는 +t 쪽
    assert parts(cfg, "L")[0].pieces[0][2] > 4.0


def test_base_on_floor_finish_and_emergency_side():
    u = by_name(parts(cfg_psd(finishes=True, emergency="-s")))
    assert u["PSD_R_1-1_DOOR_N"].pieces[0][4] == pytest.approx(1.4)                     # 승강장 상면 + 마감 0.1
    assert u["PSD_R_1-1_FIX_N"].kind == EMERGENCY and u["PSD_R_1-1_FIX_P"].kind == FIXED
    assert not [p for p in parts(cfg_psd(emergency="")) if p.kind == EMERGENCY]


def test_fill_panels_between_spread_units():
    # 차량 21m: 연결부 문 간격 6.0 → POST 사이 0.8 → 채움 1장, 23m → 2.8 → 1.3 × 2장 + 사이 POST (차량 3량 = 연결부 2곳)
    for length, n_fill, w in ((21.0, 1, 0.8), (23.0, 2, 1.3)):
        tr = make_train(3, length, [CarDoor(2.5), CarDoor(7.5), CarDoor(12.5), CarDoor(17.5)])
        ps = parts(cfg_psd(train=tr, stops=[TrainStop("R", 1)]))
        fills = [p for p in ps if p.kind == FILL]
        assert len(fills) == 2 * n_fill
        assert all(p.pieces[1][1] - p.pieces[0][0] == pytest.approx(w) for p in fills)
        assert len([p for p in ps if p.kind == HEADER]) == 12 + 2 * n_fill
        assert len([p for p in ps if p.kind == POST]) == 3 * 5 + 2 * (n_fill - 1)            # 차량마다 5 + 채움 사이


@pytest.mark.parametrize("kw, msg", [
    (dict(train=make_train(8, 16.0, [CarDoor(2.0), CarDoor(6.0), CarDoor(10.0), CarDoor(14.0)])), "겹칩니다"),
    (dict(train=make_train(8, 19.6, [CarDoor(2.45), CarDoor(7.35), CarDoor(12.25), CarDoor(17.15)])), "POST 가 일부"),
    (dict(frame_w=0.6), "프레임 폭"),
    (dict(door_h=10.0), "천장"),
    (dict(edge_offset=6.0), "승강장 폭"),
    (dict(edge_offset=0.05), "승강장 폭"),
    (dict(emergency="x"), "비상문"),
    (dict(glass_t=0.1), "유리 두께"),
    (dict(post_w=0.0), "POST 폭"),
    (dict(train=make_train(3, 23.0, [CarDoor(2.5), CarDoor(7.5), CarDoor(12.5), CarDoor(20.25)])), "너무 좁습니다"),
])
def test_invalid(kw, msg):
    with pytest.raises(ValueError, match=msg):
        cfg_psd(**kw).validate()


def test_requires_train_and_platform():
    cfg = cfg_psd()
    cfg.train_settings = TrainSettings(enabled=False)
    with pytest.raises(ValueError, match="열차"):
        cfg.validate()
    cfg = cfg_psd()
    cfg.platform.plat_thick = 0.0
    with pytest.raises(ValueError, match="승강장이 없습니다"):
        cfg.validate()


# ===================================================== 체적 · IFC · 도면 · DAE
@pytest.mark.parametrize("curved", [False, True])
def test_volume_formula_mesh_and_ifc_agree(tmp_path, curved):
    cfg = cfg_psd(finishes=True, curved=curved, stops=[TrainStop("R", 1)])
    eng = StationCADEngine(cfg)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    by = {e.Name: e for e in f.by_type("IfcProduct") if e.Name}
    tol = 1e-4 if curved else 1e-7
    for e in eng.psds.elements[:40] + eng.psds.elements[-5:]:
        quads = [q for p in e.pieces for q in PM.sweep_quads(PM.rings(eng.cfg, p))]
        if curved:
            quads = [t for q in quads for t in _fan(q)]
        assert PM.mesh_volume(quads) == pytest.approx(e.volume, rel=tol), e.name
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=tol), e.name


def test_ifc_entities_and_assembly(tmp_path):
    eng = StationCADEngine(cfg_psd())
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "p.ifc"))
    asms = [a for a in f.by_type("IfcElementAssembly") if a.ObjectType == "PLATFORM_SCREEN_DOOR"]
    assert sorted(a.Name for a in asms) == ["PSD_L", "PSD_R"]
    assert all(a.ContainedInStructure[0].RelatingStructure.Name == "B3F" for a in asms)
    by = {e.Name: e for e in f.by_type("IfcProduct") if e.Name}
    d = by["PSD_R_1-1_DOOR_N"]
    assert d.is_a("IfcDoor") and d.OperationType == "SLIDING_TO_LEFT" and d.OverallWidth == pytest.approx(1.05)
    assert by["PSD_R_1-1_DOOR_P"].OperationType == "SLIDING_TO_RIGHT"
    assert by["PSD_R_1-1_FIX_P"].is_a("IfcDoor") and by["PSD_R_1-1_FIX_N"].is_a("IfcPlate")
    assert by["PSD_R_P1"].is_a("IfcColumn") and by["PSD_R_1-1_HEADER"].is_a("IfcMember")
    assert ifcopenshell.util.element.get_material(d).Name == "PSD 강화유리 THK8"
    assert len(asms[0].IsDecomposedBy[0].RelatedObjects) == len([e for e in eng.psds.elements if e.track == asms[0].Name[-1]])


def test_drawings_and_dae_glass(tmp_path):
    eng = StationCADEngine(cfg_psd(stops=[TrainStop("R", 1)]))
    sec = eng.psds.section_items(176.0)                                      # 1-1 가동문(−s 짝) 가운데: 아래 레일·유리·위 레일·구동부
    fl = eng.cfg.lv(176.0) - eng.cfg.station.offset
    assert sorted(round(it.vb0 - fl, 3) for it in sec) == [1.3, 1.4, 3.25, 3.3]
    assert eng.psds.plan_items(3.3, floor=2) == []
    plan = eng.psds.plan_items(1.3 + 1.0, floor=1)
    assert len(plan) == 64 * 3 + 32 * 2 * 3 + 33                               # 패널마다 양옆 기둥 + 유리, POST
    assert eng.psds.profile_items(-4.2) and not eng.psds.profile_items(0.0)
    doc = eng.build_3d_doc()
    assert len(doc.modelspace().query('3DFACE[layer=="STRUCT_PSD_GLASS"]')) == 6 * 128
    eng.generate_dae(tmp_path / "m.dae", texture_dir=tmp_path)
    xml = (tmp_path / "m.dae").read_text(encoding="utf-8")
    assert "PSD 유리" in eng.dae_result.materials and "<transparency><float>0.300</float></transparency>" in xml


# ===================================================== 입력 초안 · 프로젝트 파일
def test_draft_and_project_roundtrip():
    d = PsdDraft()
    assert d.enabled is True and d.emergency == "+s 쪽"
    d.fixed_w, d.emergency = "1.3", "없음"
    ps = d.to_settings()
    assert ps.enabled and ps.fixed_w == 1.3 and ps.emergency == "" and ps.unit_w == pytest.approx(4.7)
    assert "유닛 4.7m" in preview(d)
    d.door_h = "x"
    with pytest.raises(ValueError, match="문 높이"):
        d.to_settings()
    d.enabled = False
    assert d.to_settings().enabled is False and "없음" in preview(d)
    st = ProjectState()
    st.psd_draft.edge_offset = "0.4"
    assert ProjectState.from_dict(st.to_dict()).psd_draft == st.psd_draft
    old = st.to_dict()
    del old["psd_draft"]
    assert ProjectState.from_dict(old).psd_draft == PsdDraft()


def test_end_unit_clipped_at_clear_length():
    # 열차 후미가 내공 시점(s = 0)에 붙음: 끝 유닛 POST [−0.1, 0.1] → [0, 0.1]
    cfg = cfg_psd(stops=[TrainStop("R", 1, 160.0)])
    cfg.validate()
    ps = parts(cfg)
    lo = min(pc[0] for p in ps for pc in p.pieces)
    assert lo == pytest.approx(0.0)
    p1 = next(p for p in ps if p.kind == POST and p.pieces[0][0] < 0.5)
    assert p1.pieces[0][:2] == pytest.approx((0.0, 0.1))
