"""에스컬레이터 배치 계산 (WP, 스텝 코 선, 구성 부재 띠, 자동 오프닝·피트).

설정(StationProjectConfig)의 선형 접점만 사용하는 순수 계산이라 검증(config.validate)·슬래브·승강장·에스컬레이터 엔진이 공유한다.

진행 좌표 u: 하부 WP = 0, 오르는 방향 +.  s = s_wp + direction * u.  표고는 절대 표고.
스텝 코 선 N(u): u ≤ 0 은 아래층 시작면(바닥 또는 승강장 상면), 0 ~ u_up 은 경사선, u ≥ u_up 은 위층 바닥면.
상부 WP(u_up)는 경사선이 위층 바닥면과 만나는 점 (종단구배 반영).
"""
import math
from dataclasses import dataclass, field
from typing import Optional

from escalators.escalator_spec import DECK_T, HANDRAIL_H, HANDRAIL_W, STEP_PLATE_T
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
    detail = steps_range is not None                   # 정거장 상세 형상 (출입구는 예전 형상)
    # 난간·데크·스커트·핸드레일 구간: 상세면 스텝 구간 양끝 너머 newel_ext (끝은 뉴얼 반원), 아니면 스텝 구간
    rail_lo, rail_hi = (step_lo - spec.newel_ext, step_hi + spec.newel_ext) if detail else (step_lo, step_hi)
    pts = {u_lo, u_hi, step_lo, step_hi, rail_lo, rail_hi, 0.0, run, *(x for x in extra_us if u_lo < x < u_hi)}
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
    if not detail:
        part_defs.append((EscalatorPartKind.STEPS, 0, t_steps))
    for side in (1, -1):
        if detail:
            dt = spec.detail_t(side)
            part_defs += [(EscalatorPartKind.SKIRT, side, dt["SKIRT"]), (EscalatorPartKind.INNER_DECK, side, dt["INNER_DECK"]),
                          (EscalatorPartKind.BALUSTRADE, side, dt["GLASS"]), (EscalatorPartKind.OUTER_DECK, side, dt["OUTER_DECK"])]
            gc = sum(dt["GLASS"]) / 2.0                    # 핸드레일은 유리 위 가운데
            part_defs.append((EscalatorPartKind.HANDRAIL, side, (gc - HANDRAIL_W / 2.0, gc + HANDRAIL_W / 2.0)))
        else:
            part_defs.append((EscalatorPartKind.BALUSTRADE, side, spec.balustrade_t(side)))
            part_defs.append((EscalatorPartKind.HANDRAIL, side, spec.handrail_t(side)))
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
        else:                                          # 스텝 밖: 트러스 상면 = 바닥면 (덮개판)
            ttop = bot = (na, nb)
        if rail_lo < m < rail_hi:
            for side in (1, -1):
                rail_bot = (na + hh - HANDRAIL_H, nb + hh - HANDRAIL_H)
                if detail:                                 # 스커트(트러스 상면 ~ 데크 하면) · 데크 · 유리(데크 위 ~ 핸드레일 아래)
                    kh, dk = spec.skirt_height, DECK_T
                    deck_b, deck_t = (na + kh, nb + kh), (na + kh + dk, nb + kh + dk)
                    add((EscalatorPartKind.SKIRT, side), a, b, bot, deck_b)
                    add((EscalatorPartKind.INNER_DECK, side), a, b, deck_b, deck_t)
                    add((EscalatorPartKind.OUTER_DECK, side), a, b, deck_b, deck_t)
                    add((EscalatorPartKind.BALUSTRADE, side), a, b, deck_t, rail_bot)
                else:
                    add((EscalatorPartKind.BALUSTRADE, side), a, b, (na, nb), rail_bot)
                add((EscalatorPartKind.HANDRAIL, side), a, b, rail_bot, (na + hh, nb + hh))
        add((EscalatorPartKind.TRUSS, 0), a, b, (na - depth, nb - depth), ttop)
        truss_top[(a, b)] = ttop

    if detail:                                         # 끝 뉴얼: 핸드레일이 바깥쪽 반원으로 돌아 내려감 (세로 띠로 근사)
        for side in (1, -1):
            for u_end, sgn in ((rail_lo, -1), (rail_hi, 1)):
                for ua, ub, zb, zt in newel_slices(u_end, sgn, nose(u_end) + hh, spec.newel_radius):
                    add((EscalatorPartKind.HANDRAIL, side), ua, ub, zb, zt)
                for ua, ub, zb, zt in newel_glass(u_end, sgn, nose(u_end) + hh, spec.newel_radius):
                    add((EscalatorPartKind.BALUSTRADE, side), ua, ub, zb, zt)    # 뉴얼 안쪽 반원 유리
    parts = [EscPartLayout(kind, side, t_of[(kind, side)], sorted(strips[(kind, side)], key=lambda s: s.s0))
             for kind, side, _ in part_defs]
    return parts, truss_top, us


NEWEL_SLICES = 12          # 뉴얼 반원을 나누는 세로 띠 수


def _newel_ds(r_out: float) -> list:
    """뉴얼 반원 세로 띠 분할점 (중심에서 거리): 바깥 반경 기준 cos 간격 + 안쪽 반경 — 핸드레일·유리가 함께 씀"""
    r_in = r_out - HANDRAIL_H
    cuts = {r_out * math.sin(math.pi / 2.0 * i / NEWEL_SLICES) for i in range(NEWEL_SLICES + 1)} | {r_in}
    return sorted(d for d in cuts if 0.0 <= d <= r_out)


def newel_slices(u_end: float, sgn: int, z_top: float, r_out: float) -> list:
    """끝 뉴얼 핸드레일: 핸드레일 끝(u_end, 윗면 z_top)에서 바깥쪽(sgn) 반원으로 돌아 내려가는 고리 (단면 = 핸드레일 높이).
    중심 (u_end, z_top − r_out), 바깥 반경 r_out, 안쪽 반경 r_out − HANDRAIL_H. 세로 띠 [(ua, ub, (zb_a, zb_b), (zt_a, zt_b))] —
    안쪽 반경 안은 위·아래 두 띠, 밖은 한 띠 (띠 끝 높이는 반원 위의 점, 사이는 직선)"""
    r_in = r_out - HANDRAIL_H
    zc = z_top - r_out
    f = lambda r, d: math.sqrt(max(r * r - d * d, 0.0))
    ds = _newel_ds(r_out)
    out = []
    for d0, d1 in zip(ds, ds[1:]):
        if d1 - d0 < 1e-9:
            continue
        if d1 <= r_in + 1e-12:
            bands = [((zc + f(r_in, d0), zc + f(r_in, d1)), (zc + f(r_out, d0), zc + f(r_out, d1))),
                     ((zc - f(r_out, d0), zc - f(r_out, d1)), (zc - f(r_in, d0), zc - f(r_in, d1)))]
        else:
            bands = [((zc - f(r_out, d0), zc - f(r_out, d1)), (zc + f(r_out, d0), zc + f(r_out, d1)))]
        ua, ub = u_end + sgn * d0, u_end + sgn * d1
        for zb, zt in bands:
            if sgn > 0:
                out.append((ua, ub, zb, zt))
            else:                                       # u 가 줄어드는 쪽: 띠 끝 순서 맞춤
                out.append((ub, ua, (zb[1], zb[0]), (zt[1], zt[0])))
    return out


def newel_glass(u_end: float, sgn: int, z_top: float, r_out: float) -> list:
    """뉴얼 안쪽 반원 유리 (핸드레일 고리 안쪽 반경 안을 채움, 실무 사진처럼 유리가 뉴얼을 따라 둥글게) — 세로 띠"""
    r_in = r_out - HANDRAIL_H
    zc = z_top - r_out
    f = lambda d: math.sqrt(max(r_in * r_in - d * d, 0.0))
    ds = [d for d in _newel_ds(r_out) if d <= r_in + 1e-12]      # 핸드레일 고리와 같은 분할점 (원호 근사가 서로 맞음)
    out = []
    for d0, d1 in zip(ds, ds[1:]):
        if d1 - d0 < 1e-9:
            continue
        zb, zt = (zc - f(d0), zc - f(d1)), (zc + f(d0), zc + f(d1))
        ua, ub = u_end + sgn * d0, u_end + sgn * d1
        out.append((ua, ub, zb, zt) if sgn > 0 else (ub, ua, (zb[1], zb[0]), (zt[1], zt[0])))
    return out


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
    reach = spec.newel_ext + spec.newel_radius                        # 뉴얼까지 트러스 안
    if s_lo_st - reach < u_lo - 1e-6 or s_hi_st + reach > u_hi + 1e-6:
        raise ValueError(f"에스컬레이터 {name}: 스텝(평탄 스텝 + 곡선 전이부)과 끝 뉴얼이 트러스보다 깁니다 "
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

