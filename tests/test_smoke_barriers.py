"""계단·ESC 입구 천장 제연경계벽: 위치(입구 쪽 가장자리), 높이(천장 아래 깊이), 오프닝 연장·머리 높이, 간섭, 체적·IFC, 재질, 초안"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.shape
import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from escalators.escalator_spec import EscalatorSpec
from helper import prism_member as PM
from smokewalls.smoke_layout import FRAME, GLASS, layout_smoke_barriers
from smokewalls.smoke_spec import SmokeBarrierSettings
from test_stair_enclosure import hits_members, make

ESC = EscalatorSpec(lower_floor=2, s_wp=100.0, direction=1, t_center=-6.0, truss_depth=0.35, name="ES")


def make_sb(curved=False, **spec):
    if curved:
        from stairs.stair_spec import StairSpec
        from test_finishes import cfg_with
        cfg = cfg_with(curved=True, no_cols=True, stairs=[StairSpec(lower_floor=2, s_start=80.0, t_center=-6.0, name="ST")])
    else:
        cfg = make(escs=[ESC], **spec)
    cfg.smoke_settings = SmokeBarrierSettings(enabled=True)
    return cfg


def box(cfg, p):
    z0 = PM.z_off(cfg, p)
    return (*PM.s_range(p), *PM.t_range(p), z0, z0 + p.shape.height)


def test_disabled_by_default():
    cfg = make(escs=[ESC])
    assert layout_smoke_barriers(cfg) == [] and StationCADEngine(cfg).smokes.barriers == []


def test_entry_edge_depth_and_opening_extended():
    off = make(escs=[ESC])
    StationCADEngine(off)
    before = {o.name: (o.s_start, o.s_end) for o in off.all_openings()}
    cfg = make_sb()
    eng = StationCADEngine(cfg)
    sb = cfg.smoke_settings
    ops = {o.name: o for o in eng.cfg.all_openings()}
    for name in ("ST", "ES"):
        assert ops[name].s_start < before[name][0] - 0.1 and ops[name].s_end == pytest.approx(before[name][1])
    lays = {l.opening: l for l in layout_smoke_barriers(eng.cfg)}
    assert set(lays) == {"ST", "ES"} and all(l.floor == 2 for l in lays.values())
    st = lays["ST"]
    op = ops["ST"]
    frames = st.parts[FRAME]
    assert all(f[1] == pytest.approx(op.s_start) and f[0] == pytest.approx(op.s_start - sb.frame_d) for f in frames)   # 입구 가장자리 바깥
    assert all(f[2] == pytest.approx(op.t_lo) and f[3] == pytest.approx(op.t_hi) for f in frames)                   # 오프닝 폭 전체
    assert max(f[5] for f in frames) == pytest.approx(st.top) and min(f[4] for f in frames) == pytest.approx(st.top - sb.depth)
    room = next(r for r in eng.finishes.rooms if r.floor == 2 and r.room == "ENC_ST")
    assert st.top == pytest.approx(room.ceiling_rel)                                                              # 천장판 하면에서
    down = make_sb(direction=-1, s_start=73.0)
    StationCADEngine(down)
    lay = next(l for l in layout_smoke_barriers(down) if l.opening == "ST")
    o = next(o for o in down.all_openings() if o.name == "ST")
    assert lay.parts[FRAME][0][0] == pytest.approx(o.s_end)                                                       # −s 로 오르면 +s 가장자리


def test_headroom_and_no_clash():
    cfg = make_sb()
    eng = StationCADEngine(cfg)
    for b in eng.smokes.barriers:
        for e in b.parts:
            for p in e.pieces:
                assert hits_members(eng.cfg, box(eng.cfg, p)) is None, e.name
    lay = eng.cfg.stair_layouts()[0]
    b = eng.smokes.barriers[0]
    bottom = min(box(eng.cfg, p)[4] for p in b.part(FRAME).pieces)
    s = sum(PM.s_range(b.part(FRAME).pieces[0])) / 2
    surf = [z for p in lay.parts for ua, ub, z in p.surfaces if min(lay.s_at(ua), lay.s_at(ub)) <= s <= max(lay.s_at(ua), lay.s_at(ub))]
    assert surf and eng.cfg.lv(s) - eng.cfg.station.offset + bottom - max(surf) >= lay.spec.headroom - 1e-6


@pytest.mark.parametrize("curved", [False, True])
def test_volume_mesh_and_ifc(tmp_path, curved):
    cfg = make_sb(curved=curved)
    eng = StationCADEngine(cfg)
    eng.build_3d_doc()
    rel = 1e-4 if curved else 1e-9
    for e in eng.smokes.elements:
        faces = [f.dxf for f in e.source_element]
        o = np.array(faces[0].vtx0, dtype=float)
        v = 0.0
        for d in faces:
            p = [np.array(d.get(f"vtx{i}"), dtype=float) - o for i in range(4)]
            v += np.dot(p[0], np.cross(p[1], p[2])) / 6.0
            if np.linalg.norm(p[3] - p[2]) > 1e-12:
                v += np.dot(p[0], np.cross(p[2], p[3])) / 6.0
        assert v == pytest.approx(e.volume, rel=rel, abs=1e-9)
        assert {f.dxf.layer for f in e.source_element} == {"STRUCT_SMOKE_GLASS" if e.code == GLASS else "STRUCT_SMOKE"}
    f = ifcopenshell.open(eng.generate_ifc(str(tmp_path / "s.ifc")))
    walls = [w for w in f.by_type("IfcCurtainWall") if w.ObjectType == "SMOKE_BARRIER"]
    assert {w.Name for w in walls} == {b.name for b in eng.smokes.barriers}
    s = ifcopenshell.geom.settings()
    s.set(s.USE_WORLD_COORDS, True)
    want = {e.name: e.volume for e in eng.smokes.elements}
    for rel_ in f.by_type("IfcRelAggregates"):
        if rel_.RelatingObject.is_a("IfcCurtainWall"):
            for el in rel_.RelatedObjects:
                vol = ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(s, el).geometry)
                assert vol == pytest.approx(want[el.Name], rel=rel, abs=1e-8)


def test_glass_color_and_escalator_option():
    from exporter.web_viewer import build_web_data
    cfg = make_sb()
    cfg.smoke_settings.glass_rgb = (0, 0, 255)
    cfg.smoke_settings.escalators = False
    eng = StationCADEngine(cfg)
    assert [b.opening for b in eng.smokes.barriers] == ["ST"]
    data, _ = build_web_data(eng)
    glass = [c for c in data["chunks"] if c["layer"] == "STRUCT_SMOKE_GLASS"]
    assert glass and glass[0]["color"] == [0.0, 0.0, 1.0] and glass[0]["material"] == "제연 유리"


@pytest.mark.parametrize("kw, msg", [(dict(depth=0), "깊이"), (dict(depth=0.12), "너무 작습니다"),
                                     (dict(glass_t=0.1), "프레임 두께"), (dict(glass_rgb=(1, 2)), "R, G, B")])
def test_invalid_settings(kw, msg):
    with pytest.raises(ValueError, match=msg):
        SmokeBarrierSettings(enabled=True, **kw).check()


def test_draft_and_project_round_trip():
    from gui.project_file import ProjectState
    from gui.smoke_draft import SmokeDraft, preview
    d = SmokeDraft()
    assert d.to_settings().depth == 0.6 and "0.6m" in preview(d)
    d.glass_rgb = "x"
    with pytest.raises(ValueError, match="제연경계벽: 유리 색"):
        d.to_settings()
    d.enabled = False
    assert not d.to_settings().enabled and "없음" in preview(d)
    st = ProjectState()
    st.smoke_draft = SmokeDraft(depth="0.8", escalators=False)
    assert ProjectState.from_dict(st.to_dict()).smoke_draft == st.smoke_draft
    old = st.to_dict()
    del old["smoke_draft"]
    assert ProjectState.from_dict(old).smoke_draft == SmokeDraft()
