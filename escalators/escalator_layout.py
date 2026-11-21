"""에스컬레이터 배치 계산 (WP, 스텝 코 선, 구성 부재 띠, 자동 오프닝·피트).

설정(StationProjectConfig)의 선형 접점만 사용하는 순수 계산이라 검증(config.validate)·슬래브·승강장·에스컬레이터 엔진이 공유한다.

진행 좌표 u: 하부 WP = 0, 오르는 방향 +.  s = s_wp + direction * u.  표고는 절대 표고.
스텝 코 선 N(u): u ≤ 0 은 아래층 시작면(바닥 또는 승강장 상면), 0 ~ u_up 은 경사선, u ≥ u_up 은 위층 바닥면.
상부 WP(u_up)는 경사선이 위층 바닥면과 만나는 점 (종단구배 반영).
"""
import math
from dataclasses import dataclass, field
from typing import Optional

from escalators.escalator_spec import HANDRAIL_H, STEP_PLATE_T
from escalators.escalator_type import EscalatorPartKind
from finishes.finish_layout import ceiling_bottom_under
from helper import prism_member as PM
from helper.strip_member import Strip
from openings.opening_kind import OpeningKind
from openings.opening_spec import OpeningSpec
from stairs.stair_layout import base_level

TOL = 1e-9
_MAX_ITER = 500


@dataclass
class EscPartLayout:
    kind: EscalatorPartKind
    side: int
    t_range: tuple
    strips: list


@dataclass
class EscalatorLayout:
    name: str
    spec: object                         # EscalatorSpec
    lower_floor: int
    on_platform: bool
    base_level: float                    # 시작면 높이 (바닥 슬래브 상면 기준: FL 또는 승강장 상면)
    run: float                           # 하부 WP ~ 상부 WP 수평 거리 (u)
    rise: float                          # 하부 WP ~ 상부 WP 실제 표고차
    u_range: tuple                       # 트러스 u 범위 (−lower_ext, run + upper_ext)
    s_range: tuple
    t_range: tuple
    parts: list                          # EscPartLayout
    opening: OpeningSpec                 # 위층 슬래브 오프닝
    pit_opening: Optional[OpeningSpec]   # 아래층 바닥 슬래브 피트 오프닝 (승강장 위면 None)
    platform_hole: Optional[tuple]       # 승강장 위: (이름, s0, s1, t0, t1) 승강장 슬래브 피트 구멍
    steps: list = field(default_factory=list)      # 개별 스텝 StepLayout (escalator_geom) — 위 운행로, 아래에서 위로
    nose: object = None                  # 스텝 코 선 NoseLine (u → 절대 표고) — 스텝 자세·애니메이션

    def s_at(self, u: float) -> float:
        return self.spec.s_wp + self.spec.direction * u

    @property
    def s_wp(self) -> tuple:
        return self.s_at(0.0), self.s_at(self.run)

    def own_opening_names(self) -> set:
        names = {self.opening.name}
        if self.pit_opening:
            names.add(self.pit_opening.name)
        return names


def escalator_part_strips(spec, nose, e0: float, run: float, s_at, curve_factor, extra_us=(), steps_range=None):
    """에스컬레이터 부재 띠 (정거장·출입구 공통 핵심 기하).
    nose(u): 스텝 코 선 절대 표고, e0 = 하부 WP 표고, run = WP 간 수평 거리, s_at(u): 진행 좌표 → 부재 s 좌표,
    curve_factor(sa, sb, t_center): 띠 체적 보정. t 범위는 spec(t_center, 폭)으로 정한다.
    extra_us: 더 자를 u (곡선 전이부 표본), steps_range: (lo, hi) 를 주면 스텝은 개별 객체(escalator_geom)로 따로 만들고
    여기서는 스텝 띠를 만들지 않음 — 그 범위가 스텝 구간(트러스 상면 = 코 선 − 단높이 − 판 두께, 난간·핸드레일)
    반환: (부재 목록 EscPartLayout, 구간별 트러스 상면 {(ua, ub): (z_a, z_b)}, 구간 경계 u 목록)"""
    r, dep, depth = spec.riser, spec.step_depth, spec.truss_depth
    u_lo, u_hi = -spec.lower_ext, run + spec.upper_ext
    step_lo, step_hi = steps_range or (-spec.lower_flat_steps * dep, run + spec.upper_flat_steps * dep)
    pts = {u_lo, u_hi, step_lo, step_hi, 0.0, run, *(x for x in extra_us if u_lo < x < u_hi)}
    j = 1
    while j * dep < run - TOL:                         # 경사 스텝 경계
        pts.add(j * dep)
        j += 1
    us = []
    for x in sorted(pts):
        if not us or x - us[-1] > TOL:
            us.append(x)

    tc = spec.t_center
    t_truss = (spec.t_lo, spec.t_hi)
    t_steps = (tc - spec.step_width / 2.0, tc + spec.step_width / 2.0)
    part_defs = [(EscalatorPartKind.TRUSS, 0, t_truss)]
    if steps_range is None:
        part_defs.append((EscalatorPartKind.STEPS, 0, t_steps))
    for side in (1, -1):
        part_defs += [(EscalatorPartKind.BALUSTRADE, side, spec.balustrade_t(side)),
                      (EscalatorPartKind.HANDRAIL, side, spec.handrail_t(side))]
    strips = {(kind, side): [] for kind, side, _ in part_defs}
    t_of = {(kind, side): t for kind, side, t in part_defs}

    def add(key, ua, ub, zb, zt):
        """u 구간 [ua, ub] 의 띠 (zb, zt = (u=ua 값, u=ub 값))"""
        sa, sb = s_at(ua), s_at(ub)
        (zba, zbb), (zta, ztb) = zb, zt
        if sa > sb:
            sa, sb, zba, zbb, zta, ztb = sb, sa, zbb, zba, ztb, zta
        t0, t1 = t_of[key]
        strips[key].append(Strip(sa, sb, zba, zbb, zta, curve_factor=curve_factor(sa, sb, (t0 + t1) / 2.0), zt1=ztb))

    hh, plate = spec.handrail_height, r + STEP_PLATE_T
    truss_top = {}
    for a, b in zip(us, us[1:]):
        m = (a + b) / 2.0
        na, nb = nose(a), nose(b)
        in_steps = step_lo < m < step_hi
        if in_steps:
            bot = (na - plate, nb - plate)
            if steps_range is None:
                if 0.0 < m < run:                      # 경사 스텝: 디딤판 상면 수평, 앞 코가 경사선 위
                    tread = e0 + math.floor(m / dep + TOL) * r
                    top = (tread, tread)
                else:                                  # 평탄 스텝: 바닥면을 따름
                    top = (na, nb)
                add((EscalatorPartKind.STEPS, 0), a, b, bot, top)
            ttop = bot
            for side in (1, -1):
                rail_bot = (na + hh - HANDRAIL_H, nb + hh - HANDRAIL_H)
                add((EscalatorPartKind.BALUSTRADE, side), a, b, (na, nb), rail_bot)
                add((EscalatorPartKind.HANDRAIL, side), a, b, rail_bot, (na + hh, nb + hh))
        else:                                          # 스텝 밖: 트러스 상면 = 바닥면 (덮개판)
            ttop = (na, nb)
        add((EscalatorPartKind.TRUSS, 0), a, b, (na - depth, nb - depth), ttop)
        truss_top[(a, b)] = ttop

    parts = [EscPartLayout(kind, side, t_of[(kind, side)], sorted(strips[(kind, side)], key=lambda s: s.s0))
             for kind, side, _ in part_defs]
    return parts, truss_top, us


def _crossing(a, b, fa, fb):
    """[a, b] 에서 f 가 부호를 바꾸면 선형 보간한 0 점"""
    return a + (b - a) * fa / (fa - fb)


def layout_escalator(cfg, spec, name: str) -> EscalatorLayout:
    """에스컬레이터 1대의 배치 (spec 의 기본 범위 검사는 escalator_check.check_escalator_spec 이 먼저 한다)"""
    st = cfg.station
    k, d = spec.lower_floor, spec.direction
    z_base, on_platform = base_level(cfg, spec, name, "에스컬레이터")
    z_top = st.floor_level(k + 1)
    tan, depth = spec.tan, spec.truss_depth
    tc, t_truss = spec.t_center, (spec.t_lo, spec.t_hi)

    def s_at(u):
        return spec.s_wp + d * u

    def elev(u, z_rel):
        return cfg.lv(s_at(u)) - st.offset + z_rel

    e0 = elev(0.0, z_base)
    run = (z_top - z_base) / tan                      # 상부 WP: 경사선이 위층 바닥면(구배 반영)과 만나는 점
    for _ in range(_MAX_ITER):
        nxt = (elev(run, z_top) - e0) / tan
        if abs(nxt - run) < 1e-12:
            break
        run = nxt
    else:
        raise ValueError(f"에스컬레이터 {name}: 상부 WP 계산이 수렴하지 않습니다 (종단구배를 확인하세요)")
    if run <= 0:
        raise ValueError(f"에스컬레이터 {name}: 위층 바닥이 시작면보다 낮습니다")
    e1 = elev(run, z_top)

    from escalators.escalator_geom import NoseLine, layout_steps, step_range
    nose = NoseLine(e0, run, tan, lambda u: elev(u, z_base), lambda u: elev(u, z_top),
                    spec.lower_radius, spec.upper_radius)          # 스텝 코 선 (곡선 전이부)
    u_lo, u_hi = -spec.lower_ext, run + spec.upper_ext
    s_lo_st, s_hi_st, _ = step_range(spec, nose)
    if s_lo_st < u_lo - 1e-6 or s_hi_st > u_hi + 1e-6:
        raise ValueError(f"에스컬레이터 {name}: 스텝(평탄 스텝 + 곡선 전이부)이 트러스보다 깁니다 "
                         f"(하부/상부 연장 {spec.lower_ext:g}/{spec.upper_ext:g} 을 늘리거나 평탄 스텝 수·반경을 줄이세요)")
    steps = layout_steps(spec, nose)
    parts, truss_top, us = escalator_part_strips(
        spec, nose, e0, run, s_at, lambda sa, sb, tc: PM.curve_factor(cfg, sa, sb, tc),
        extra_us=nose.breakpoints(), steps_range=(s_lo_st, s_hi_st))

    # 위층 슬래브(번호 k) 오프닝: 트러스가 슬래브를 지나는 구간 + 스텝 코 선 위 머리 높이 부족 구간 → 트러스 상단 끝까지
    # 머리 높이는 아래층(k) 천장 마감이 슬래브 하면보다 낮으면 천장판 하면 기준 (오프닝이 그만큼 길어짐)
    z_sb, z_st = z_top - st.mid_t, z_top
    ceil = ceiling_bottom_under(cfg, k, (*sorted((s_at(u_lo), s_at(u_hi))), *t_truss))
    z_head = z_sb if ceil is None else min(z_sb, ceil)
    from smokewalls.smoke_spec import head_drop
    sb = getattr(cfg, "smoke_settings", None)
    if sb is None or sb.escalators:
        z_head -= head_drop(cfg)                         # 입구 천장 제연경계벽 아래에서도 머리 높이 확보
    u_open = u_hi
    for (a, b), ttop in truss_top.items():
        for x, tt in ((a, ttop[0]), (b, ttop[1])):
            through = tt > elev(x, z_sb) + 1e-9 and nose(x) - depth < elev(x, z_st) - 1e-9
            low = elev(x, z_head) - nose(x) < spec.headroom - 1e-9
            if x >= 0.0 and (through or low):
                u_open = min(u_open, a)
    s_lo, s_hi = sorted((s_at(u_open), s_at(u_hi)))
    from finishes.finish_clear import shaft_opening_t
    o_lo, o_hi, _ = shaft_opening_t(cfg, k, s_lo, s_hi, tc - spec.truss_width / 2.0, tc + spec.truss_width / 2.0)
    o_lo = min(o_lo, tc - spec.truss_width / 2.0 - spec.side_clear)
    o_hi = max(o_hi, tc + spec.truss_width / 2.0 + spec.side_clear)
    opening = OpeningSpec(kind=OpeningKind.ESCALATOR, s_start=s_lo, length=s_hi - s_lo, t_center=(o_lo + o_hi) / 2.0,
                          width=o_hi - o_lo, slabs=[k], name=name)

    # 하부 피트: 트러스 하면이 시작면 아래인 구간 (트러스 하단 끝 ~ 하면이 시작면 위로 올라오는 점)
    u_pit = u_lo
    for a, b in zip(us, us[1:]):
        fa, fb = nose(a) - depth - elev(a, z_base), nose(b) - depth - elev(b, z_base)
        if fa < -1e-9:
            u_pit = b if fb < -1e-9 else _crossing(a, b, fa, fb)
        if fb >= -1e-9:
            break
    p_lo, p_hi = sorted((s_at(u_lo), s_at(u_pit)))
    pit_opening = platform_hole = None
    if on_platform:
        if z_base - depth < -1e-9:
            raise ValueError(f"에스컬레이터 {name}: 트러스 높이({depth:g}m)가 승강장 상면 높이({z_base:g}m)보다 커서 "
                             "피트가 바닥 슬래브에 닿습니다")
        platform_hole = (f"{name}_PIT", p_lo, p_hi, *t_truss)
    else:
        slab_no = k - 1
        thick = st.floor_t if slab_no == 0 else st.mid_t
        if depth > thick + 1e-9:
            raise ValueError(f"에스컬레이터 {name}: 피트 깊이(트러스 높이 {depth:g}m)가 아래 슬래브 두께({thick:g}m)보다 깊습니다 "
                             "(바닥을 내린 피트 구조는 아직 지원하지 않습니다)")
        pit_opening = OpeningSpec(kind=OpeningKind.ESCALATOR, s_start=p_lo, length=p_hi - p_lo, t_center=tc,
                                  width=spec.truss_width, slabs=[slab_no], name=f"{name}_PIT")
    return EscalatorLayout(name=name, spec=spec, lower_floor=k, on_platform=on_platform, base_level=z_base, run=run,
                           rise=e1 - e0, u_range=(u_lo, u_hi), s_range=tuple(sorted((s_at(u_lo), s_at(u_hi)))),
                           t_range=t_truss, parts=parts, opening=opening, pit_opening=pit_opening,
                           platform_hole=platform_hole, steps=steps, nose=nose)

