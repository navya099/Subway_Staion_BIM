"""이슈 #32 근본 원인: 계단·ESC 와 본체 벽 마감 표면 간섭 검사 + t 기준점(중심·변·벽 마감면) + 벽 판단 기준"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from engine.cad_engine import StationCADEngine
from escalators.escalator_spec import EscalatorSpec
from finishes.finish_clear import resolve_t_ref, wall_surface
from finishes.finish_spec import default_finishes
from stairs.stair_spec import StairSpec
from test_finishes import cfg_with


def cfg_of(stairs=(), escs=(), table=None, finish=True):
    cfg = cfg_with(no_cols=True, stairs=list(stairs), escalators=list(escs), table=table)
    cfg.finish_settings.enabled = finish
    return cfg


def big_face():
    t = default_finishes()
    for ft in t.values():
        if ft.wall_t > 0:
            ft.wall_face = 0.5                                     # 실무 샘플: 본체 벽 이격 큼
    return t


def test_wall_surface_and_edge_refs():
    cfg = cfg_of(table=big_face())
    assert wall_surface(cfg, 2, 1, 50, 70) == pytest.approx(9.0 - 0.5)
    sp = StairSpec(lower_floor=2, s_start=60.0, t_ref="+t", t_center=-5.0, width=2.0)
    assert resolve_t_ref(cfg, sp, 2.0) == pytest.approx(-6.0)        # 왼쪽 변 = −5 → 중심 −6
    sp = StairSpec(lower_floor=2, s_start=60.0, t_ref="-t", t_center=-7.0, width=2.0)
    assert resolve_t_ref(cfg, sp, 2.0) == pytest.approx(-6.0)
    sp = StairSpec(lower_floor=2, s_start=60.0, t_ref="wall+t", t_center=0.2, width=2.0)
    assert resolve_t_ref(cfg, sp, 2.0) == pytest.approx(8.5 - 0.2 - 1.0)
    with pytest.raises(ValueError, match="이격"):
        resolve_t_ref(cfg, StairSpec(lower_floor=2, t_ref="wall-t", t_center=-0.1), 2.0)
    with pytest.raises(ValueError, match="t 기준"):
        resolve_t_ref(cfg, StairSpec(lower_floor=2, t_ref="xx"), 2.0)


def test_sample_like_stair_rejected_then_wall_ref_ok():
    """실무 샘플처럼 벽 마감면 0.5 인데 계단을 t 6.6 ~ 10.0(벽 쪽) 근처에 두면 마감 안으로 들어가 오류"""
    bad = cfg_of([StairSpec(lower_floor=2, s_start=60.0, t_center=7.9, width=2.0, name="ST")], table=big_face())
    with pytest.raises(ValueError, match=r"왼쪽\(\+t\) 본체 벽 마감 표면.*0\.40m 들어갑니다"):
        StationCADEngine(bad)
    ok = cfg_of([StairSpec(lower_floor=2, s_start=60.0, t_ref="wall+t", t_center=0.0, width=2.0, name="ST")],
                table=big_face())
    StationCADEngine(ok)
    assert ok.stair_layouts()[0].t_range == pytest.approx((6.5, 8.5))
    off = cfg_of([StairSpec(lower_floor=2, s_start=60.0, t_center=7.9, width=2.0, name="ST")], table=big_face(), finish=False)
    StationCADEngine(off)                                            # 마감을 끄면 검사 안 함 (벽 마감 없음)


def test_escalator_clearance_and_wall_ref():
    esc = EscalatorSpec(lower_floor=2, s_wp=100.0, direction=1, t_center=8.0, truss_depth=0.35, name="ES")
    with pytest.raises(ValueError, match="에스컬레이터 ES.*들어갑니다"):
        StationCADEngine(cfg_of(escs=[esc], table=big_face()))
    esc2 = EscalatorSpec(lower_floor=2, s_wp=100.0, direction=1, t_ref="wall+t", t_center=0.0, truss_depth=0.35, name="ES")
    cfg = cfg_of(escs=[esc2], table=big_face())
    StationCADEngine(cfg)
    lay = cfg.escalator_layouts()[0]
    assert lay.t_range[1] == pytest.approx(8.5) and lay.t_range[1] - lay.t_range[0] == pytest.approx(esc2.truss_width)


def test_enclosure_treats_finish_surface_as_wall():
    """벽 마감 표면에 붙인 계단: 계단실이 그 쪽에 칸막이벽을 세우지 않고(마감 이격 안에 벽이 서던 문제) 본체 벽으로 봄"""
    from rooms.room_check import layout_rooms
    from stairs.stair_enclosure import EnclosureSettings
    cfg = cfg_of([StairSpec(lower_floor=2, s_start=60.0, t_ref="wall+t", t_center=0.0, width=2.0, name="ST")],
                 table=big_face())
    cfg.enclosure_settings = EnclosureSettings(enabled=True)
    eng = StationCADEngine(cfg)
    room = next(r for r in eng.cfg.rooms if r.name == "ENC_ST")
    assert room.t1 == pytest.approx(9.0)                             # 본체 벽(내공면)까지
    walls = [p for pw in layout_rooms(eng.cfg)[1].partitions if pw.axis == "s" for p in pw.pieces]
    assert not [p for p in walls if p[2] > 8.0]                       # 마감 이격 안에 칸막이벽 없음


def test_drafts_t_ref():
    from gui.escalator_draft import EscalatorDraft
    from gui.stair_draft import StairDraft, preview
    d = StairDraft(t_ref="왼쪽 벽 마감면", t_center="0.1")
    sp = d.to_spec("계단 1", 0.0)
    assert sp.t_ref == "wall+t" and sp.t_center == 0.1
    assert "왼쪽 벽 마감면에서 0.1 띄움" in preview(d, 6.0, 0.0)
    d.t_center = "-0.1"
    with pytest.raises(ValueError, match="벽 마감면 이격"):
        d.to_spec("계단 1", 0.0)
    d = StairDraft(t_ref="오른쪽 변(−t)", t_center="-7")
    assert "t -7 ~ -4.5" in preview(d, 6.0, 0.0)                     # 폭 2.5
    e = EscalatorDraft(t_ref="오른쪽 벽 마감면", t_center="0")
    assert e.to_spec("ESC 1", 0.0).t_ref == "wall-t"
    with pytest.raises(ValueError, match="t 기준"):
        StairDraft(t_ref="??").to_spec("계단 1", 0.0)
