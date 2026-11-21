import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.layout_cache import ATTR, cached_layout
from engine.cad_engine import StationCADEngine
from stairs.stair_check import layout_stairs
from stairs.stair_spec import StairSpec
from test_curved import NO_COLS
from test_patch import make_cfg


def test_layouts_cached_after_validate_and_cleared_on_field_swap():
    """검증 뒤 같은 배치는 한 번만 계산 (같은 객체), 입력 필드를 바꿔 끼우면 다시 계산, validate 중 오류면 캐시 꺼짐"""
    cfg = make_cfg(NO_COLS())
    cfg.stairs = [StairSpec(lower_floor=1, s_start=60.0, t_center=-6.0, width=2.0)]
    StationCADEngine(cfg)
    assert getattr(cfg, ATTR) is not None
    a = layout_stairs(cfg)
    assert layout_stairs(cfg) is a and cfg.stair_layouts() is a
    cfg.stairs = [StairSpec(lower_floor=1, s_start=80.0, t_center=-6.0, width=2.0)]      # 바꿔 끼움 → 다시 계산
    b = layout_stairs(cfg)
    assert b is not a and b[0].spec.s_start == 80.0
    cfg.stairs = [StairSpec(lower_floor=1, s_start=80.0, t_center=-6.0, width=-1.0)]
    try:
        cfg.validate()
    except ValueError:
        pass
    assert getattr(cfg, ATTR) is None                                    # 검증 실패 → 캐시 없음 (매번 계산)


def test_cached_layout_without_cache_and_unhashable_args():
    calls = []

    @cached_layout("t")
    def f(cfg, x=None):
        calls.append(x)
        return [x]

    class C:
        pass
    c = C()
    f(c); f(c)
    assert len(calls) == 2                                               # 캐시가 없으면 매번
    setattr(c, ATTR, {})
    f(c, 1); f(c, 1); f(c, [1]); f(c, [1])
    assert calls[2:] == [1, [1], [1]]                                    # 해시 가능한 인자만 캐시
