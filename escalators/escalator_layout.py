"""에스컬레이터 배치 계산 (WP, 스텝 코 선, 구성 부재 띠, 자동 오프닝·피트).

설정(StationProjectConfig)의 선형 접점만 사용하는 순수 계산이라 검증(config.validate)·슬래브·승강장·에스컬레이터 엔진이 공유한다.

진행 좌표 u: 하부 WP = 0, 오르는 방향 +.  s = s_wp + direction * u.  표고는 절대 표고.
스텝 코 선 N(u): u ≤ 0 은 아래층 시작면(바닥 또는 승강장 상면), 0 ~ u_up 은 경사선, u ≥ u_up 은 위층 바닥면.
상부 WP(u_up)는 경사선이 위층 바닥면과 만나는 점 (종단구배 반영).
"""
import math
from dataclasses import dataclass
from typing import Optional

from escalators.escalator_spec import HANDRAIL_H, STEP_PLATE_T
from escalators.escalator_type import EscalatorPartKind
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


def _crossing(a, b, fa, fb):
    """[a, b] 에서 f 가 부호를 바꾸면 선형 보간한 0 점"""
    return a + (b - a) * fa / (fa - fb)


def layout_escalator(cfg, spec, name: str) -> EscalatorLayout:
    """에스컬레이터 1대의 배치 (spec 의 기본 범위 검사는 escalator_check.check_escalator_spec 이 먼저 한다)"""
    st = cfg.station
    k, d = spec.lower_floor, spec.direction
    z_base, on_platform = base_level(cfg, spec, name, "에스컬레이터")
    z_top = st.floor_level(k + 1)
    tan, r, dep, depth = spec.tan, spec.riser, spec.step_depth, spec.truss_depth

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

    def nose(u):
        """스텝 코 선"""
        if u <= 0.0:
            return elev(u, z_base)
        if u >= run:
            return elev(u, z_top)
        return e0 + u * tan

    u_lo, u_hi = -spec.lower_ext, run + spec.upper_ext
    step_lo, step_hi = -spec.lower_flat_steps * dep, run + spec.upper_flat_steps * dep
    pts = {u_lo, u_hi, step_lo, step_hi, 0.0, run}
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
    part_defs = [(EscalatorPartKind.TRUSS, 0, t_truss), (EscalatorPartKind.STEPS, 0, t_steps)]
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
        strips[key].append(Strip(sa, sb, zba, zbb, zta, curve_factor=PM.curve_factor(cfg, sa, sb, (t0 + t1) / 2.0), zt1=ztb))

    hh, plate = spec.handrail_height, r + STEP_PLATE_T
    truss_top = {}                                     # 오프닝 판정용: 구간별 (트러스 상면 a, b)
    for a, b in zip(us, us[1:]):
        m = (a + b) / 2.0
        na, nb = nose(a), nose(b)
        in_steps = step_lo < m < step_hi
        if in_steps:
            if 0.0 < m < run:                          # 경사 스텝: 디딤판 상면 수평, 앞 코가 경사선 위
                tread = e0 + math.floor(m / dep + TOL) * r
                top = (tread, tread)
            else:                                      # 평탄 스텝: 바닥면을 따름
                top = (na, nb)
            bot = (na - plate, nb - plate)
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

    # 위층 슬래브(번호 k) 오프닝: 트러스가 슬래브를 지나는 구간 + 스텝 코 선 위 머리 높이 부족 구간 → 트러스 상단 끝까지
    z_sb, z_st = z_top - st.mid_t, z_top
    u_open = u_hi
    for (a, b), ttop in truss_top.items():
        for x, tt in ((a, ttop[0]), (b, ttop[1])):
            through = tt > elev(x, z_sb) + 1e-9 and nose(x) - depth < elev(x, z_st) - 1e-9
            low = elev(x, z_sb) - nose(x) < spec.headroom - 1e-9
            if x >= 0.0 and (through or low):
                u_open = min(u_open, a)
    s_lo, s_hi = sorted((s_at(u_open), s_at(u_hi)))
    opening = OpeningSpec(kind=OpeningKind.ESCALATOR, s_start=s_lo, length=s_hi - s_lo, t_center=tc,
                          width=spec.truss_width, slabs=[k], name=name)

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
                           platform_hole=platform_hole)

