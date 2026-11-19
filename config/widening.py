"""구조물 확폭: 측벽 내공면을 구간만 바깥으로 넓힘 (층별·쪽별).

확폭 1개 = 쪽(+1 = +t 쪽, −1 = −t 쪽) · 적용 층 · 완전 확폭 구간 [s_start, s_end] · 확폭량 d · 양 끝 사선 전이 길이.
  내공면 |t| = W/2 + e(s):  e = 0 (s ≤ s_start − taper_in), 직선 증가, d ([s_start, s_end]), 직선 감소, 0 (s ≥ s_end + taper_out)
  s_start 가 None 이면 정거장 시점(단부 벽 포함)부터, s_end 가 None 이면 종점까지 넓음 (그쪽 전이 없음). 전이 길이 0 = 직각 계단.
벽 바깥면 = 내공면 폴리선을 벽 두께만큼 바깥으로 수직 간격으로 띄운 폴리선 (꺾임점은 연귀) — 사선 벽도 같은 두께.
부재는 s 방향 구간마다 아래·위 경계가 직선인 사다리꼴 (trap = (s0, s1, t0(s0), t1(s0), t0(s1), t1(s1))) 로 나눈다.
"""
import dataclasses
import math
from typing import Optional

_EPS = 1e-9


@dataclasses.dataclass
class WidenSpec:
    """side: +1 = +t 쪽(진행방향 왼쪽) 측벽, −1 = −t 쪽. floors: 적용 층 번호 목록 (비면 모든 층)
    s_start / s_end: 완전 확폭 구간 (정거장 로컬 s, None = 시점·종점 끝까지), amount: 확폭량 (내공면이 바깥으로 이동, m)
    taper_in / taper_out: 시작·끝 사선 전이 길이 (s 방향, None = 확폭량과 같음 = 45°, 0 = 직각 계단)"""
    side: int = 1
    floors: list = dataclasses.field(default_factory=list)
    s_start: Optional[float] = None
    s_end: Optional[float] = None
    amount: float = 1.0
    taper_in: Optional[float] = None
    taper_out: Optional[float] = None
    name: str = ""

    def tapers(self) -> tuple:
        ti = self.amount if self.taper_in is None else self.taper_in
        to = self.amount if self.taper_out is None else self.taper_out
        return (0.0 if self.s_start is None else ti), (0.0 if self.s_end is None else to)

    def applies(self, floor_n: int) -> bool:
        return not self.floors or floor_n in self.floors


def specs_for(cfg, floor_n: int, side: int) -> list:
    return [w for w in getattr(cfg, "widenings", []) if w.side == side and w.applies(floor_n)]


def widened(cfg) -> bool:
    return bool(getattr(cfg, "widenings", []))


def inner_polyline(cfg, floor_n: int, side: int, s_lo: float, s_hi: float) -> list:
    """내공면 |t| 폴리선 [(s, |t|)] (s_lo ~ s_hi). 직각 계단은 같은 s 에 두 점"""
    hw = cfg.station.width / 2.0
    pts = [(s_lo, hw)]
    for w in sorted(specs_for(cfg, floor_n, side), key=lambda w: (-math.inf if w.s_start is None else w.s_start)):
        ti, to = w.tapers()
        a = s_lo if w.s_start is None else w.s_start
        b = s_hi if w.s_end is None else w.s_end
        top = hw + w.amount
        if w.s_start is None:
            pts = [(s_lo, top)]
        else:
            pts += [(a - ti, hw), (a, top)]
        if w.s_end is None:
            pts.append((s_hi, top))
        else:
            pts += [(b, top), (b + to, hw)]
    if pts[-1][0] < s_hi - _EPS:
        pts.append((s_hi, hw))
    return pts


def offset_polyline(pts: list, d: float) -> list:
    """폴리선 [(s, t)] 을 +t 바깥쪽으로 수직 간격 d 만큼 띄운 폴리선 (꺾임점 연귀, 평행한 이웃 구간은 한 점)"""
    segs = []
    for (s0, t0), (s1, t1) in zip(pts, pts[1:]):
        L = math.hypot(s1 - s0, t1 - t0)
        if L < _EPS:
            continue
        us, ut = (s1 - s0) / L, (t1 - t0) / L
        ns, nt = -ut, us                                    # 폴리선을 s 증가 방향으로 따라갈 때 왼쪽 = 바깥 (내공은 오른쪽)
        segs.append(((s0 + ns * d, t0 + nt * d), (us, ut)))
    out = [segs[0][0]]
    for (p, u), (q, v) in zip(segs, segs[1:]):
        cross = u[0] * v[1] - u[1] * v[0]
        if abs(cross) < _EPS:
            continue
        k = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / cross
        out.append((p[0] + u[0] * k, p[1] + u[1] * k))
    (p, u) = segs[-1]
    L = math.hypot(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
    out.append((p[0] + u[0] * L, p[1] + u[1] * L))
    return out


def _value(poly: list, sa: float, sb: float) -> tuple:
    """폴리선이 [sa, sb] 에서 직선일 때 (t(sa), t(sb)) — 그 구간을 덮는 (s 길이 > 0) 구간을 찾음"""
    for (s0, t0), (s1, t1) in zip(poly, poly[1:]):
        if s1 - s0 > _EPS and s0 <= sa + 1e-7 and sb <= s1 + 1e-7:
            k = (t1 - t0) / (s1 - s0)
            return t0 + k * (sa - s0), t0 + k * (sb - s0)
    raise ValueError(f"확폭: 폴리선이 s {sa:.3f} ~ {sb:.3f} 를 덮지 않습니다")


def band(lower: list, upper: list, s_lo: float, s_hi: float) -> list:
    """아래·위 폴리선 사이 띠 → 사다리꼴 [(s0, s1, lo0, hi0, lo1, hi1)] (위가 아래보다 높은 곳만, 교차점에서 나눔)"""
    cuts = sorted({s for s, _ in lower + upper if s_lo - _EPS <= s <= s_hi + _EPS} | {s_lo, s_hi})
    cuts = [c for c in cuts if s_lo - _EPS <= c <= s_hi + _EPS]
    out = []
    for sa, sb in zip(cuts, cuts[1:]):
        if sb - sa < 1e-7:
            continue
        la, lb = _value(lower, sa, sb)
        ha, hb = _value(upper, sa, sb)
        da, db = ha - la, hb - lb
        if da < -1e-9 and db > 1e-9 or da > 1e-9 and db < -1e-9:       # 교차: 두 조각
            sx = sa + (sb - sa) * da / (da - db)
            lx = la + (lb - la) * (sx - sa) / (sb - sa)
            parts = [(sa, sx, la, ha, lx, lx), (sx, sb, lx, lx, lb, hb)]
        else:
            parts = [(sa, sb, la, ha, lb, hb)]
        for s0, s1, l0, h0, l1, h1 in parts:
            if h0 - l0 > 1e-9 or h1 - l1 > 1e-9:
                out.append((s0, s1, l0, max(h0, l0), l1, max(h1, l1)))
    return out


def side_wall_traps(cfg, floor_n: int, side: int) -> list:
    """측벽(s 0 ~ L) 사다리꼴 [(s0, s1, |t|내0, |t|외0, |t|내1, |t|외1)] — 내공면 ~ 바깥면 (|t| 기준)"""
    st = cfg.station
    L, wt = st.length, st.wall_t_at(floor_n)
    pad = st.max_wall_t + 1.0
    inner = inner_polyline(cfg, floor_n, side, -pad, L + pad)
    outer = offset_polyline(inner, wt)
    return band(inner, outer, 0.0, L)


def outer_at(cfg, floor_n: int, side: int, s: float) -> float:
    """바깥면 |t| (s 에서, 직각 계단이면 큰 쪽)"""
    st = cfg.station
    pad = st.max_wall_t + 1.0
    outer = offset_polyline(inner_polyline(cfg, floor_n, side, -pad, st.length + pad), st.wall_t_at(floor_n))
    vals = [t for (s0, t0), (s1, t1) in zip(outer, outer[1:])
            for t in ([t0 + (t1 - t0) * (s - s0) / (s1 - s0)] if s1 - s0 > _EPS and s0 - 1e-7 <= s <= s1 + 1e-7 else [])]
    return max(vals)


def inner_at(cfg, floor_n: int, side: int, s: float) -> float:
    """내공면 |t| (s 에서, 직각 계단이면 큰 쪽)"""
    st = cfg.station
    pad = st.max_wall_t + 1.0
    inner = inner_polyline(cfg, floor_n, side, -pad, st.length + pad)
    vals = [t for (s0, t0), (s1, t1) in zip(inner, inner[1:])
            for t in ([t0 + (t1 - t0) * (s - s0) / (s1 - s0)] if s1 - s0 > _EPS and s0 - 1e-7 <= s <= s1 + 1e-7 else [])]
    return max(vals)


def check_widenings(cfg):
    """확폭 입력 검사 (ValueError)"""
    st = cfg.station
    L = st.length
    for k, w in enumerate(getattr(cfg, "widenings", []), start=1):
        where = f"확폭 {k}" + (f"({w.name})" if w.name else "")
        if w.side not in (1, -1):
            raise ValueError(f"{where}: 쪽은 +1(+t) 또는 −1(−t) 이어야 합니다 ({w.side!r})")
        bad = [n for n in w.floors if not (isinstance(n, int) and 1 <= n <= st.floors)]
        if bad:
            raise ValueError(f"{where}: 층 번호가 범위(1~{st.floors}) 밖입니다 ({bad})")
        if not (isinstance(w.amount, (int, float)) and math.isfinite(w.amount) and w.amount > 0):
            raise ValueError(f"{where}: 확폭량은 0보다 커야 합니다 ({w.amount})")
        ti, to = w.tapers()
        for label, v in (("시작 전이 길이", ti), ("끝 전이 길이", to)):
            if not (math.isfinite(v) and v >= 0):
                raise ValueError(f"{where}: {label}은(는) 0 이상이어야 합니다 ({v})")
        a = 0.0 if w.s_start is None else w.s_start
        b = L if w.s_end is None else w.s_end
        if b - a < 1e-6:
            raise ValueError(f"{where}: 확폭 구간 끝이 시작보다 뒤여야 합니다 (s {a:g} ~ {b:g})")
        if w.s_start is not None and w.s_start - ti < -1e-6:
            raise ValueError(f"{where}: 시작 전이부(s {w.s_start - ti:.3f})가 내공 시점(0) 앞입니다 — 시작을 비우면 시점부터 넓음")
        if w.s_end is not None and w.s_end + to > L + 1e-6:
            raise ValueError(f"{where}: 끝 전이부(s {w.s_end + to:.3f})가 내공 종점({L:g}) 뒤입니다 — 끝을 비우면 종점까지 넓음")
    for n in range(1, st.floors + 1):
        for side in (1, -1):
            spans = []
            for w in specs_for(cfg, n, side):
                ti, to = w.tapers()
                a = -math.inf if w.s_start is None else w.s_start - ti
                b = math.inf if w.s_end is None else w.s_end + to
                spans.append((a, b, w))
            spans.sort(key=lambda x: x[0])
            for (a0, b0, w0), (a1, b1, w1) in zip(spans, spans[1:]):
                if a1 < b0 - 1e-6:
                    raise ValueError(f"확폭: {st.level_name(n)} {'+t' if side > 0 else '−t'} 쪽 확폭 구간(전이 포함)이 서로 겹칩니다")


def _mirror(poly: list) -> list:
    return [(s, -t) for s, t in poly]


def _poly(cfg, floor_n: int, side: int, outer: bool) -> list:
    st = cfg.station
    pad = st.max_wall_t + 1.0
    inner = inner_polyline(cfg, floor_n, side, -pad, st.length + pad)
    return offset_polyline(inner, st.wall_t_at(floor_n)) if outer else inner


def outline_traps(cfg, floor_n: int, s_lo: float, s_hi: float, outer: bool = True) -> list:
    """층 floor_n 의 바깥면(outer) 또는 내공면 사이 영역 사다리꼴 [(s0, s1, t0@s0, t1@s0, t0@s1, t1@s1)]"""
    lo = _mirror(_poly(cfg, floor_n, -1, outer))
    hi = _poly(cfg, floor_n, 1, outer)
    return [(s0, s1, l0, h0, l1, h1) for s0, s1, l0, h0, l1, h1 in band(lo, hi, s_lo, s_hi)]


def mid_slab_traps(cfg, below: int) -> list:
    """중간 슬래브(below 층과 그 위층 사이) 영역: 아래층 내공(확폭 포켓의 천장 포함) + 위층이 더 넓은 확폭 구간에서
    아래층 바깥면 ~ 위층 바깥면 (위층 확폭 벽을 받침). 아래층 벽은 슬래브를 지나 올라가므로 그 자리는 뺌"""
    st = cfg.station
    L = st.length
    out = outline_traps(cfg, below, 0.0, L, outer=False)
    up = below + 1
    for side in (1, -1):
        spans = []
        for w in specs_for(cfg, up, side):
            ti, to = w.tapers()
            pad = 2.0 * st.wall_t_at(up) + 1e-6
            a = 0.0 if w.s_start is None else max(0.0, w.s_start - ti - pad)
            b = L if w.s_end is None else min(L, w.s_end + to + pad)
            spans.append((a, b))
        lo_poly, hi_poly = _poly(cfg, below, side, True), _poly(cfg, up, side, True)
        for a, b in spans:
            for s0, s1, l0, h0, l1, h1 in band(lo_poly, hi_poly, a, b):
                out.append((s0, s1, l0, h0, l1, h1) if side > 0 else (s0, s1, -h0, -l0, -h1, -l1))
    return out
