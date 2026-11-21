"""계단 마감 (구조 경사 슬래브 + 계단석): 디딤판 높이(마감면 기준), 방식별 부재 겹침·빈틈, 옆면, 체적 교차 검증, 초안·프로젝트 파일"""
import os, sys
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.shape
import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from finishes.finish_spec import STEP_CONCRETE, STEP_PLATE, STEP_SOLID, StairFinish
from helper.strip_member import part_faces
from stairs.stair_spec import StairSpec
from test_finishes import cfg_with

ST = dict(lower_floor=2, s_start=60.0, direction=1, t_center=-6.0, width=2.0, name="ST")


def make(method=STEP_PLATE, curved=False, **spec):
    cfg = cfg_with(curved=curved, no_cols=True, stairs=[StairSpec(**{**ST, **spec})])
    cfg.finish_settings.stair.method = method
    return cfg


def walk_surfaces(lay):
    """걷는 면 [(s0, s1, 표고)] — 디딤판·계단참 + 위층 도착 디딤판 (마지막 챌판 ~ 슬래브와 맞닿는 점)"""
    out = [(min(lay.s_at(a), lay.s_at(b)), max(lay.s_at(a), lay.s_at(b)), z) for p in lay.parts for a, b, z in p.surfaces]
    top = max(z for _, _, z in out) + lay.riser
    out.append((*sorted((lay.s_at(lay.run), lay.s_at(lay.length))), top))
    return sorted(out)


def boxes(lay):
    out = [(st, *p.t_range, "S") for p in lay.parts for st in p.strips]
    return out + [(st, *f.t_range, f.code) for f in lay.finish for st in f.strips]


def mesh_volume(faces):
    v = 0.0
    o = np.array(faces[0][0], dtype=float)              # 큰 세계 좌표의 자리수 손실 방지
    for f in faces:
        p = [np.array(x, dtype=float) - o for x in f]
        for i in range(1, len(p) - 1):
            v += np.dot(p[0], np.cross(p[i], p[i + 1])) / 6.0
    return v


# ===================================================== 높이·구조
def test_disabled_keeps_monolithic_stair():
    on, off = make(), make()
    off.finish_settings.stair.enabled = False
    a, b = on.stair_layouts()[0], off.stair_layouts()[0]
    assert b.finish == [] and b.finish_base is None and a.finish
    off2 = make()
    off2.finish_settings.enabled = False                          # 마감 전체를 끄면 계단 마감도 없음
    c = off2.stair_layouts()[0]
    assert c.finish == [] and [len(p.strips) for p in c.parts] == [len(p.strips) for p in b.parts]


def test_treads_follow_finished_floor_levels():
    cfg = make()
    st = cfg.station
    lay = cfg.stair_layouts()[0]
    ffl = cfg.finish_settings.table["기본"].ffl
    assert lay.finish_base == pytest.approx(st.floor_level(2) + ffl) and lay.base_level == pytest.approx(st.floor_level(2))
    e0 = cfg.lv(60.0) - st.offset + lay.finish_base
    surfs = walk_surfaces(lay)
    for m, (_, _, z) in enumerate(surfs[:5], start=1):           # 디딤판 = 아래층 마감면 + m × 단높이
        assert z == pytest.approx(e0 + m * lay.riser)
    s_end = lay.s_at(lay.length)                                   # 위층 도착 = 위층 바닥 마감면
    assert surfs[-1][2] == pytest.approx(cfg.lv(s_end) - st.offset + st.floor_level(3) + ffl, abs=1e-9)
    # 같은 계단을 마감 없이 = 구조 FL 기준 → 첫 디딤판이 ffl 만큼 낮음
    off = make()
    off.finish_settings.stair.enabled = False
    lo = off.stair_layouts()[0]
    z_off = min(z for p in lo.parts for a, b, z in p.surfaces)
    assert min(z for _, _, z in surfs) > z_off


def test_structure_is_smooth_slab_below_steps():
    cfg = make()
    lay = cfg.stair_layouts()[0]
    fin = cfg.finish_settings.stair
    strips = sorted((st for p in lay.parts for st in p.strips), key=lambda s: s.s0)
    for a, b in zip(strips, strips[1:]):                            # 상·하면이 이어짐 (계단 모양 없음)
        assert b.s0 == pytest.approx(a.s1, abs=1e-9)
        assert b.zt == pytest.approx(a.zt_end, abs=1e-9) and b.zb0 == pytest.approx(a.zb1, abs=1e-9)
    # 계단참 구조 상면 = 계단참 마감면 − 받침 두께
    land = next(p for p in lay.parts if p.kind.value == "LANDING")
    z_land = land.surfaces[0][2]
    assert land.strips[-1].zt_end == pytest.approx(z_land - fin.depth)


@pytest.mark.parametrize("method", [STEP_PLATE, STEP_SOLID, STEP_CONCRETE])
def test_pieces_fill_without_overlap_or_gap(method):
    cfg = make(method)
    lay = cfg.stair_layouts()[0]
    codes = {f.code for f in lay.finish}
    want = {STEP_PLATE: {"TREAD", "RISER", "FILL", "NOSING", "SIDE"},
            STEP_SOLID: {"TREAD", "RISER", "STONE", "FILL", "NOSING", "SIDE"},       # 통석도 계단참은 판석
            STEP_CONCRETE: {"FILL", "NOSING", "SIDE"}}[method]
    assert codes == want
    bx = boxes(lay)
    surf = walk_surfaces(lay)
    s0, s1 = lay.s_range
    t0, t1 = lay.t_range
    rnd = random.Random(7)
    for _ in range(3000):
        s, t = rnd.uniform(s0, s1), rnd.uniform(t0, t1)
        hits = [b for b in bx if b[0].s0 <= s < b[0].s1 and b[1] <= t < b[2] and b[0].zt_at(s) - b[0].zb_at(s) > 1e-12]
        assert hits
        tops = [b[0].zt_at(s) for b in hits]
        z_walk = next(z for a, b, z in surf if a <= s < b)
        assert max(tops) == pytest.approx(z_walk, abs=1e-9)                 # 맨 위 = 걷는 면
        tot = sum(b[0].zt_at(s) - b[0].zb_at(s) for b in hits)
        span = max(tops) - min(b[0].zb_at(s) for b in hits)
        assert tot == pytest.approx(span, abs=1e-9)                         # 겹침도 빈틈도 없음


def test_plate_and_nosing_dimensions():
    cfg = make()
    fin = cfg.finish_settings.stair
    lay = cfg.stair_layouts()[0]
    by = {}
    for f in lay.finish:
        by.setdefault(f.code, []).append(f)
    nos = by["NOSING"][0]
    assert nos.t_range == pytest.approx((-7 + fin.side_t + fin.nosing_end, -5 - fin.side_t - fin.nosing_end))
    assert all(st.zt - st.zb0 == pytest.approx(fin.nosing_t) for st in nos.strips)
    # 논슬립은 앞에 챌판이 있는 칸마다 (디딤판 + 계단참 + 위층 도착) = 전체 챌판 수, 앞 코에서 nosing_w
    fronts = sorted({round(a, 9) for a, _, _ in walk_surfaces(lay)})
    covered = [x for x in fronts if any(abs(st.s0 - x) < 1e-9 for st in nos.strips)]
    assert len(covered) == lay.n_risers
    assert all(x - 1e-9 <= st.s0 and st.s1 <= x + fin.nosing_w + 1e-9 for st in nos.strips
               for x in [max(f for f in fronts if f <= st.s0 + 1e-9)])
    tread = next(f for f in by["TREAD"] if f.t_range[1] - f.t_range[0] > 1.0)
    assert all(st.zt - st.zb0 in (pytest.approx(fin.tread_t), pytest.approx(fin.tread_t - fin.nosing_t)) for st in tread.strips)
    assert all(st.s1 - st.s0 <= fin.riser_t + 1e-9 for f in by["RISER"] for st in f.strips)


def test_side_finish_only_on_exposed_side():
    lay = make(t_center=-8.0).stair_layouts()[0]                  # t −9 ~ −7: −t 쪽은 본체 벽 내공면에 붙음
    sides = [f for f in lay.finish if f.code == "SIDE"]
    assert len(sides) == 1 and sides[0].t_range == pytest.approx((-7.02, -7.0))
    assert all(p.t_range == pytest.approx((-9.0, -7.0)) for p in lay.parts)            # 구조는 계단 폭 전체 (옆면 콘크리트 노출)
    fill = next(f for f in lay.finish if f.code == "FILL")
    assert fill.t_range == pytest.approx((-9.0, -7.02))                                 # 스텝만 옆면 마감만큼 좁음
    # 옆면 마감은 구조 상면 위(스텝 높이)만: 하면이 구조 상면보다 낮은 곳 없음
    struct = [st for p in lay.parts for st in p.strips]
    for st in sides[0].strips:
        s = (st.s0 + st.s1) / 2.0
        top = max((x.zt_at(s) for x in struct if x.s0 <= s < x.s1), default=None)
        if top is not None:
            assert st.zb_at(s) >= top - 1e-9
    lay2 = make().stair_layouts()[0]                               # 가운데 계단: 양쪽
    assert sorted(f.t_range for f in lay2.finish if f.code == "SIDE") == [pytest.approx((-7.0, -6.98)), pytest.approx((-5.02, -5.0))]
    cfg = make()
    cfg.finish_settings.stair.side_t = 0.0
    lay3 = cfg.stair_layouts()[0]
    assert not any(f.code == "SIDE" for f in lay3.finish) and lay3.parts[0].t_range == pytest.approx((-7.0, -5.0))


def test_invalid_stair_finish():
    for kw, msg in [(dict(method="x"), "방식"), (dict(depth=0.0), "받침"), (dict(depth=0.02), "디딤판 두께"),
                    (dict(method=STEP_SOLID, depth=0.02), "깔 몰탈"), (dict(tread_t=-0.1), "0 이상")]:
        with pytest.raises(ValueError, match=msg):
            StairFinish(**kw).check()
    cfg = make()
    cfg.finish_settings.stair.side_t = 0.98
    with pytest.raises(ValueError, match="옆면"):
        StationCADEngine(cfg)


# ===================================================== 체적·출력
@pytest.mark.parametrize("curved", [False, True])
def test_volume_strip_mesh_and_ifc_agree(tmp_path, curved):
    kw = dict(s_start=60.0) if not curved else dict(s_start=80.0)
    cfg = make(curved=curved, **kw)
    eng = StationCADEngine(cfg)
    eng.build_3d_doc()
    stair = eng.stairs.all_stairs()[0]
    rel = 1e-4 if curved else 1e-9
    for fe in stair.finishes:
        assert fe.source_element and all(e.dxf.layer == "FIN_STAIR" for e in fe.source_element)
        mesh = mesh_volume([f for q in part_faces(cfg, fe) for f in q])
        assert mesh == pytest.approx(fe.volume, rel=rel, abs=1e-9)
    path = eng.generate_ifc(str(tmp_path / "s.ifc"))
    f = ifcopenshell.open(path)
    s = ifcopenshell.geom.settings()
    s.set(s.USE_WORLD_COORDS, True)
    covers = {c.Name: c for c in f.by_type("IfcCovering") if c.Name.startswith("ST_FIN_")}
    assert set(covers) == {fe.name for fe in stair.finishes}
    for fe in stair.finishes:
        v = ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(s, covers[fe.name]).geometry)
        assert v == pytest.approx(fe.volume, rel=rel, abs=1e-8)
    rel_cov = f.by_type("IfcRelCoversBldgElements")
    assert len(rel_cov) == 1 and rel_cov[0].RelatingBuildingElement.Name == "ST" and len(rel_cov[0].RelatedCoverings) == len(covers)


def test_drawings_and_viewer_materials(tmp_path):
    from exporter.web_viewer import build_web_data
    eng = StationCADEngine(make())
    stair = eng.stairs.all_stairs()[0]
    sta = (stair.s_range[0] + stair.s_range[1]) / 2.0
    assert any(it.layer == "SEC_FINISH" and it.name.startswith("ST_FIN_") for it in eng.stairs.section_items(sta))
    assert any(it.layer == "PROF_FINISH" for it in eng.stairs.profile_items(t_cut=-6.0))
    assert not any(it.layer == "PROF_FINISH" for it in eng.stairs.profile_items(t_cut=0.0))
    data, _ = build_web_data(eng)
    mats = {c["material"] for c in data["chunks"] if c["layer"] == "FIN_STAIR"}
    assert {"화강석", "논슬립", "몰탈"} <= mats
    assert any(e["name"].startswith("ST_FIN_NOSING") and e["material"] == "논슬립" for e in data["elements"])


def test_floor_finish_contact_includes_step_fill():
    """계단 마감 채움이 아래층 바닥 마감 자리를 차지하므로 그 구간은 바닥 마감에서 빠짐 (겹침 없음)"""
    eng = StationCADEngine(make())
    lay = eng.cfg.stair_layouts()[0]
    room = next(r for r in eng.finishes.rooms if r.floor == 2)
    ftop = room.finish.ffl
    s_first = lay.s_range[0]
    for p in room.element("FLOOR").pieces + room.element("FILL").pieces:
        s0 = p.pos_x - p.shape.length / 2
        s1 = p.pos_x + p.shape.length / 2
        t0, t1 = p.pos_y - p.shape.width / 2, p.pos_y + p.shape.width / 2
        if t1 > -7 + 1e-6 and t0 < -5 - 1e-6:
            assert not (s0 < s_first + 0.05 and s1 > s_first + 1e-6), (s0, s1, ftop)


# ===================================================== 초안·프로젝트 파일
def test_stair_finish_draft_and_project_roundtrip():
    from gui.finish_draft import FinishDrafts, StairFinishDraft, stair_preview
    from gui.project_file import ProjectState
    d = FinishDrafts()
    fs = d.to_settings()
    assert fs.stair.method == STEP_PLATE and fs.stair_finish() is not None
    d.stair.method = "통석 + 깔 몰탈"
    d.stair.side_t = "0"
    assert d.to_settings().stair.method == STEP_SOLID and "통석" in stair_preview(d.stair)
    d.stair.depth = "abc"
    with pytest.raises(ValueError, match="계단 마감"):
        d.to_settings()
    assert "입력값" in stair_preview(d.stair)
    d.stair.enabled = False
    assert d.to_settings().stair_finish() is None and "일체형" in stair_preview(d.stair)
    st = ProjectState()
    st.stair_finish_draft = StairFinishDraft(method="콘크리트 계단", depth="0.12", nosing=False)
    back = ProjectState.from_dict(st.to_dict())
    assert back.stair_finish_draft == st.stair_finish_draft
    old = st.to_dict()
    del old["stair_finish_draft"]                                   # 옛 파일 → 기본 (사용)
    assert ProjectState.from_dict(old).stair_finish_draft == StairFinishDraft()


def test_platform_stair_starts_on_platform_finish():
    """최하층 승강장 위 계단: 시작면 = 승강장 상면, 디딤판 기준 = 승강장 상면 + 그 실 마감 높이"""
    cfg = make(lower_floor=1)
    lay = cfg.stair_layouts()[0]
    ffl = cfg.finish_settings.table["기본"].ffl
    assert lay.on_platform and lay.base_level == pytest.approx(cfg.platform.top_level)
    assert lay.finish_base == pytest.approx(cfg.platform.top_level + ffl)
    eng = StationCADEngine(cfg)
    assert eng.stairs.all_stairs()[0].finishes
