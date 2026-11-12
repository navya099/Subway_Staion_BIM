"""직선 계단의 배치 계산 (단수, 런/계단참 분할, 단면 띠, 자동 오프닝).

설정(StationProjectConfig)의 선형 접점(lv, curvature 등)만 사용하는 순수 계산이라, 검증 단계(config.validate)와
엔진(StairEngine · SlabEngine) 이 같은 결과를 공유한다 (단일 데이터 원천).

진행 좌표 u: 첫 챌판 = 0, 오르는 방향 +.  s = s_start + direction * u.
표고는 절대 표고. 디딤판·계단참 상면은 수평이고, 실제 단높이 = (위층 바닥 표고(도착점) − 시작면 표고(첫 챌판)) / 단수 로
종단구배까지 반영해 모든 단이 같다.
"""
import math
from dataclasses import dataclass, field

from helper import prism_member as PM
from openings.opening_kind import OpeningKind
from openings.opening_spec import OpeningSpec
from stairs.stair_shape import StairStrip
from stairs.stair_type import StairPartKind

TOL = 1e-9
_MAX_ITER = 500


@dataclass
class PartLayout:
    kind: StairPartKind
    strips: list                     # StairStrip, s 오름차순
    n_risers: int = 0
    surfaces: list = field(default_factory=list)   # 걷는 면 [(u0, u1, 상면 표고)] (디딤판 / 계단참)


@dataclass
class StairLayout:
    name: str
    spec: object                     # StairSpec (입력)
    lower_floor: int
    on_platform: bool
    base_level: float                # 시작면 높이 (바닥 슬래브 상면 기준: FL 또는 승강장 상면)
    n_risers: int
    riser: float
    flight_risers: list              # 런별 챌판 수
    run: float                       # 첫 챌판 ~ 위층 도착 지점 수평 거리 (u)
    s_range: tuple
    t_range: tuple
    parts: list                      # PartLayout (아래 → 위)
    opening: OpeningSpec

    @property
    def landings(self) -> int:
        return len(self.flight_risers) - 1

    def s_at(self, u: float) -> float:
        """진행 좌표 u (첫 챌판 = 0) → 정거장 로컬 s"""
        return self.spec.s_start + self.spec.direction * u


def riser_count(height: float, riser_max: float) -> int:
    """단높이 상한을 넘지 않는 최소 단수"""
    return max(1, math.ceil(height / riser_max - 1e-9))


def split_flights(n_risers: int, riser: float, flight_rise_max: float) -> list[int]:
    """n 단을 런 높이 상한 이하가 되는 가장 적은 수의 런으로 고르게 나눔 (앞쪽 런이 1단 많을 수 있음). 런마다 2단 이상"""
    for f in range(1, max(1, n_risers // 2) + 1):
        base, extra = divmod(n_risers, f)
        counts = [base + 1] * extra + [base] * (f - extra)
        if max(counts) * riser <= flight_rise_max + 1e-9:
            return counts
    raise ValueError(f"런 높이 상한({flight_rise_max:g}m)이 단높이({riser:.3f}m)에 비해 너무 작아 계단을 나눌 수 없습니다")


def run_length(counts: list[int], tread: float, landing_len: float) -> float:
    """런별 디딤판(챌판 − 1) 길이 + 중간 계단참 길이"""
    return sum(c - 1 for c in counts) * tread + (len(counts) - 1) * landing_len


def plan_risers(height: float, spec, rise_of_run=None):
    """(단수, 실제 단높이, 런별 단수, 수평 길이). rise_of_run(run) = 그 수평 길이일 때 실제 표고차 (없으면 height 고정).
    단높이가 상한을 넘으면 단수를 하나씩 늘린다"""
    rise_of_run = rise_of_run or (lambda run: height)
    n = riser_count(height, spec.riser_max)
    for _ in range(_MAX_ITER):
        r = height / n
        for _ in range(_MAX_ITER):
            counts = split_flights(n, r, spec.flight_rise_max)
            run = run_length(counts, spec.tread, spec.landing_len)
            r_new = rise_of_run(run) / n
            if abs(r_new - r) < 1e-12:
                break
            r = r_new
        else:
            raise ValueError("계단 단높이 계산이 수렴하지 않습니다 (종단구배를 확인하세요)")
        if r <= 0:
            raise ValueError("계단의 위층 도착 표고가 시작 표고보다 낮습니다 (종단구배를 확인하세요)")
        if r <= spec.riser_max + 1e-9:
            return n, r, counts, run
        n += 1
    raise ValueError("계단 단수를 정할 수 없습니다")


def base_level(cfg, spec, name: str) -> tuple[float, bool]:
    """계단 시작면 높이 (바닥 슬래브 상면 기준)와 승강장 위 여부.
    최하층에서 계단 폭이 승강장 슬래브 안에 완전히 들어가면 승강장 상면에서 시작, 걸치면 오류"""
    st, pl = cfg.station, cfg.platform
    if spec.lower_floor == 1 and pl.exists:
        for t0, t1 in pl.slab_t_ranges(st.width):
            inside = t0 - 1e-6 <= spec.t_lo and spec.t_hi <= t1 + 1e-6
            overlap = min(t1, spec.t_hi) - max(t0, spec.t_lo) > 1e-6
            if inside:
                return pl.top_level, True
            if overlap:
                raise ValueError(f"계단 {name}: t {spec.t_lo:g} ~ {spec.t_hi:g} 이(가) 승강장 슬래브(t {t0:g} ~ {t1:g})에 "
                                 "걸쳐 있습니다. 승강장 안에 완전히 넣거나 승강장 밖으로 옮기세요")
    return st.floor_level(spec.lower_floor), False


def layout_stair(cfg, spec, name: str) -> StairLayout:
    """계단 1개의 배치 (spec 의 기본 범위 검사는 stair_check.check_stair_spec 이 먼저 한다)"""
    st = cfg.station
    k, d, g, w = spec.lower_floor, spec.direction, spec.tread, spec.waist_t
    z_base, on_platform = base_level(cfg, spec, name)
    z_top = st.floor_level(k + 1)

    def s_at(u):
        return spec.s_start + d * u

    def elev(u, z_rel):
        return cfg.lv(s_at(u)) - st.offset + z_rel

    e_base = elev(0.0, z_base)
    n, r, counts, run = plan_risers(z_top - z_base, spec, lambda run: elev(run, z_top) - e_base)
    slope = r / g
    waist_v = w * math.sqrt(1.0 + slope * slope)       # 허리 슬래브 연직 두께 = 두께 / cos(경사각)
    t0, t1 = spec.t_lo, spec.t_hi
    tc = spec.t_center

    def to_strip(ua, ub, zba, zbb, zt):
        sa, sb = s_at(ua), s_at(ub)
        if sa > sb:
            sa, sb, zba, zbb = sb, sa, zbb, zba
        return StairStrip(sa, sb, zba, zbb, zt, curve_factor=PM.curve_factor(cfg, sa, sb, tc))

    parts, u, j0 = [], 0.0, 0
    for i, c in enumerate(counts):
        u_start, e_start = u, e_base + j0 * r
        if i == 0:                                       # 첫 런은 시작면(바닥 또는 승강장 상면) 위에 놓임
            def clip(x):
                return elev(x, z_base)
        else:                                            # 계단참 하면에서 이어짐
            def clip(x, e=e_start):
                return e - w

        def soffit(x, u0=u_start, e0=e_start):
            return e0 + (x - u0) * slope - waist_v

        def bottom(x):
            return max(clip(x), soffit(x))

        strips, surfaces = [], []
        for m in range(1, c):
            ua, ub = u_start + (m - 1) * g, u_start + m * g
            zt = e_start + m * r
            surfaces.append((ua, ub, zt))
            cuts = [ua]
            fa, fb = soffit(ua) - clip(ua), soffit(ub) - clip(ub)
            if fa * fb < 0:                              # 허리 하면이 시작면과 만나는 점에서 띠를 나눔
                cuts.append(ua + (ub - ua) * fa / (fa - fb))
            cuts.append(ub)
            for a, b in zip(cuts, cuts[1:]):
                if b - a > TOL:
                    strips.append(to_strip(a, b, bottom(a), bottom(b), zt))
        strips.sort(key=lambda s: s.s0)
        parts.append(PartLayout(StairPartKind.FLIGHT, strips, n_risers=c, surfaces=surfaces))
        u = u_start + (c - 1) * g
        j0 += c
        if i < len(counts) - 1:
            top = e_base + j0 * r
            parts.append(PartLayout(StairPartKind.LANDING, [to_strip(u, u + spec.landing_len, top - w, top - w, top)],
                                    surfaces=[(u, u + spec.landing_len, top)]))
            u += spec.landing_len

    # 자동 오프닝: 위층 슬래브(번호 k) 하면까지의 유효 높이가 headroom 보다 낮아지는 첫 걷는 면부터 도착 지점까지
    z_slab_bot = z_top - st.mid_t
    u_open = run
    for p in parts:
        for ua, ub, zt in p.surfaces:
            if min(elev(ua, z_slab_bot), elev(ub, z_slab_bot)) - zt < spec.headroom - 1e-9:
                u_open = min(u_open, ua)
    s_lo, s_hi = sorted((s_at(u_open), s_at(run)))
    opening = OpeningSpec(kind=OpeningKind.STAIR, s_start=s_lo, length=s_hi - s_lo, t_center=tc, width=spec.width,
                          slabs=[k], name=name)
    return StairLayout(name=name, spec=spec, lower_floor=k, on_platform=on_platform, base_level=z_base, n_risers=n, riser=r,
                       flight_risers=counts, run=run, s_range=tuple(sorted((s_at(0.0), s_at(run)))),
                       t_range=(t0, t1), parts=parts, opening=opening)
