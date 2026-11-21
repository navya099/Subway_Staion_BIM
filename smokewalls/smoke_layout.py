"""제연경계벽 배치: 계단(항상)·ESC(설정) 자동 오프닝마다 입구 쪽 가장자리(오르기 시작하는 쪽, 도착 쪽의 반대) 아래층 천장에서
깊이 depth 만큼 내려온 유리벽 — 오프닝 t 폭 전체, 진행방향 두께 frame_d 를 오프닝 가장자리 바깥(아래층 쪽)에 둠.
위 = 그 자리 아래층 실의 천장판 하면 (천장이 없거나 마감을 끄면 위 슬래브 하면). 조각 (s0, s1, t0, t1, z0, z1) 본체 FL 기준
"""
from config.layout_cache import cached_layout
from dataclasses import dataclass, field

FRAME, GLASS = "FRAME", "GLASS"


@dataclass
class SmokeBarrierLayout:
    name: str                        # SB_{오프닝 이름}
    opening: str
    floor: int                       # 경계벽이 매달린 층 (계단·ESC 시작 층)
    top: float                       # 윗면 (천장판 하면 또는 슬래브 하면, 본체 FL 기준)
    parts: dict = field(default_factory=dict)        # FRAME / GLASS → [조각]


@cached_layout("smokes")
def layout_smoke_barriers(cfg) -> list:
    sb = getattr(cfg, "smoke_settings", None)
    if sb is None or not sb.enabled:
        return []
    from finishes.finish_layout import ceiling_bottom_under
    from rooms.room_layout import ceiling_rel
    st = cfg.station
    items = [(lay, lay.opening, lay.s_at(0.0)) for lay in cfg.stair_layouts()]
    if sb.escalators:
        items += [(lay, lay.opening, lay.s_at(lay.u_range[0])) for lay in cfg.escalator_layouts()]
    out = []
    for lay, op, start in items:
        n = lay.lower_floor
        S0, S1, T0, T1 = op.s_start, op.s_end, op.t_lo, op.t_hi
        # 입구 쪽 가장자리 = 오르기 시작하는 쪽에 가까운 가장자리, 경계벽은 그 바깥(아래층 쪽)
        if abs(start - S0) <= abs(start - S1):
            s0, s1 = S0 - sb.frame_d, S0
        else:
            s0, s1 = S1, S1 + sb.frame_d
        ceil = ceiling_bottom_under(cfg, n, (s0, s1, T0, T1))
        slab = ceiling_rel(st, n)
        top = slab if ceil is None else min(slab, ceil)
        bot = top - sb.depth
        g0, g1 = (s0 + s1) / 2.0 - sb.glass_t / 2.0, (s0 + s1) / 2.0 + sb.glass_t / 2.0
        parts = {FRAME: [(s0, s1, T0, T1, top - sb.frame_h, top), (s0, s1, T0, T1, bot, bot + sb.frame_h)],
                 GLASS: [(g0, g1, T0, T1, bot + sb.frame_h, top - sb.frame_h)]}
        out.append(SmokeBarrierLayout(f"SB_{op.name}", op.name, n, top, parts))
    return out


def check_smoke_barriers(cfg) -> None:
    sb = getattr(cfg, "smoke_settings", None)
    if sb is None or not sb.enabled:
        return
    sb.check()
    layout_smoke_barriers(cfg)
