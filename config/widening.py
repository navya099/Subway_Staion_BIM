"""구조물 확폭: 측벽 내공면을 구간만 바깥으로 넓힘 (층별·쪽별).

확폭 1개 = 쪽(+1 = +t 쪽, −1 = −t 쪽) · 적용 층 · 완전 확폭 구간 [s_start, s_end] · 확폭량 d · 양 끝 사선 전이 길이.
  내공면 |t| = W/2 + e(s):  e = 0 (s ≤ s_start − taper_in), 직선 증가, d ([s_start, s_end]), 직선 감소, 0 (s ≥ s_end + taper_out)
  s_start 가 None 이면 정거장 시점(단부 벽 포함)부터, s_end 가 None 이면 종점까지 넓음 (그쪽 전이 없음). 전이 길이 0 = 직각 계단.
벽 바깥면 = 내공면 폴리선을 벽 두께만큼 바깥으로 수직 간격으로 띄운 폴리선 (꺾임점은 연귀) — 사선 벽도 같은 두께.
종류(kind): CLEAR = 내공 확폭(위 설명, 내공면이 이동) | WALL = 벽체 두께 증가 (내공면 그대로, 벽 바깥면만 확폭량만큼
  바깥으로 — 바깥면 |t| = W/2 + 벽 두께 + e(s), 전이부는 바깥면만 사선). WALL 은 측벽·단부 벽·바닥/천장 슬래브 외곽·
  위층이 두꺼워질 때의 중간 슬래브 받침만 바뀌고 내공(승강장·실·마감 등)은 그대로.
부재는 s 방향 구간마다 아래·위 경계가 직선인 사다리꼴 (trap = (s0, s1, t0(s0), t1(s0), t0(s1), t1(s1))) 로 나눈다.
"""
import dataclasses
import math
from typing import Optional

_EPS = 1e-9
CLEAR, WALL = "clear", "wall"
KINDS = (CLEAR, WALL)


@dataclasses.dataclass
class WidenSpec:
    """side: +1 = +t 쪽(진행방향 왼쪽) 측벽, −1 = −t 쪽. floors: 적용 층 번호 목록 (비면 모든 층)
    s_start / s_end: 완전 확폭 구간 (정거장 로컬 s, None = 시점·종점 끝까지), amount: 확폭량 (내공면이 바깥으로 이동, m)
    taper_in / taper_out: 시작·끝 사선 전이 길이 (s 방향, None = 확폭량과 같음 = 45°, 0 = 직각 계단)
    kind: CLEAR(내공 확폭) | WALL(벽체 두께 증가 — 내공면 고정, 바깥면만)"""
    side: int = 1
    floors: list = dataclasses.field(default_factory=list)
    s_start: Optional[float] = None
    s_end: Optional[float] = None
    amount: float = 1.0
    taper_in: Optional[float] = None
    taper_out: Optional[float] = None
    name: str = ""
    kind: str = CLEAR

    def tapers(self) -> tuple:
        ti = self.amount if self.taper_in is None else self.taper_in
        to = self.amount if self.taper_out is None else self.taper_out
        return (0.0 if self.s_start is None else ti), (0.0 if self.s_end is None else to)

    def applies(self, floor_n: int) -> bool:
        return not self.floors or floor_n in self.floors


def specs_for(cfg, floor_n: int, side: int, kind: Optional[str] = None) -> list:
    """그 층·쪽에 적용되는 확폭 (kind 를 주면 그 종류만)"""
    return [w for w in getattr(cfg, "widenings", []) if w.side == side and w.applies(floor_n)
            and (kind is None or w.kind == kind)]


def widened(cfg) -> bool:
    return bool(getattr(cfg, "widenings", []))


def inner_polyline(cfg, floor_n: int, side: int, s_lo: float, s_hi: float) -> list:
    """내공면 |t| 폴리선 [(s, |t|)] (s_lo ~ s_hi, 내공 확폭만). 직각 계단은 같은 s 에 두 점"""
    return _profile(specs_for(cfg, floor_n, side, CLEAR), cfg.station.width / 2.0, s_lo, s_hi)


def _profile(specs: list, hw: float, s_lo: float, s_hi: float) -> list:
    """기준 |t| = hw 에 확폭 specs 의 e(s) 를 더한 폴리선 (구간은 서로 겹치지 않음 — check_widenings)"""
    pts = [(s_lo, hw)]
    for w in sorted(specs, key=lambda w: (-math.inf if w.s_start is None else w.s_start)):
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


def _envelope(p: list, q: list, s_lo: float, s_hi: float) -> list:
    """두 폴리선 중 큰 쪽(위 포락선) 폴리선 — 교차점에서 꺾고, 직각 계단(같은 s 두 점)은 그대로"""
    cuts = sorted({s for s, _ in p + q if s_lo - _EPS <= s <= s_hi + _EPS} | {s_lo, s_hi})
    out = []
    for sa, sb in zip(cuts, cuts[1:]):
        if sb - sa < 1e-7:
            continue
        pa, pb = _value(p, sa, sb)
        qa, qb = _value(q, sa, sb)
        da, db = pa - qa, pb - qb
        seg = [(sa, max(pa, qa))]
        if da < -1e-9 and db > 1e-9 or da > 1e-9 and db < -1e-9:
            sx = sa + (sb - sa) * da / (da - db)
            seg.append((sx, pa + (pb - pa) * (sx - sa) / (sb - sa)))
        seg.append((sb, max(pb, qb)))
        for pt in seg:
            if not out or abs(out[-1][0] - pt[0]) > 1e-9 or abs(out[-1][1] - pt[1]) > 1e-9:
                out.append(pt)
    return out


def outer_polyline(cfg, floor_n: int, side: int, s_lo: float, s_hi: float) -> list:
    """벽 바깥면 |t| 폴리선: 내공면을 벽 두께만큼 띄운 선 + 벽체 두께 증가(WALL) 확폭 (둘 중 바깥)"""
    st = cfg.station
    wt = st.wall_t_at(floor_n)
    outer = offset_polyline(inner_polyline(cfg, floor_n, side, s_lo, s_hi), wt)
    thick = specs_for(cfg, floor_n, side, WALL)
    if not thick:
        return outer
    return _envelope(outer, _profile(thick, st.width / 2.0 + wt, s_lo, s_hi), s_lo, s_hi)


def side_wall_traps(cfg, floor_n: int, side: int) -> list:
    """측벽(s 0 ~ L) 사다리꼴 [(s0, s1, |t|내0, |t|외0, |t|내1, |t|외1)] — 내공면 ~ 바깥면 (|t| 기준)"""
    st = cfg.station
    L = st.length
    pad = st.max_wall_t + 1.0
    inner = inner_polyline(cfg, floor_n, side, -pad, L + pad)
    return band(inner, outer_polyline(cfg, floor_n, side, -pad, L + pad), 0.0, L)


def outer_at(cfg, floor_n: int, side: int, s: float) -> float:
    """바깥면 |t| (s 에서, 직각 계단이면 큰 쪽)"""
    st = cfg.station
    pad = st.max_wall_t + 1.0
    outer = outer_polyline(cfg, floor_n, side, -pad, st.length + pad)
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
        if w.kind not in KINDS:
            raise ValueError(f"{where}: 종류는 {CLEAR}(내공 확폭) 또는 {WALL}(벽체 두께 증가) 이어야 합니다 ({w.kind!r})")
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
    if outer:
        return outer_polyline(cfg, floor_n, side, -pad, st.length + pad)
    return inner_polyline(cfg, floor_n, side, -pad, st.length + pad)


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


# ---------------------------------------------------------------- 2단계: 넓어진 내공 (실·마감·검사)
def has_pockets(cfg, floor_n: Optional[int] = None) -> bool:
    """내공 확폭(CLEAR)이 있나 (floor_n 을 주면 그 층에)"""
    ws = [w for w in getattr(cfg, "widenings", []) if w.kind == CLEAR]
    return bool(ws) if floor_n is None else any(w.applies(floor_n) for w in ws)


def clear_traps(cfg, floor_n: int) -> list:
    """층 floor_n 의 넓어진 내공 영역 (s 0 ~ L) — 사다리꼴 조각 (helper.trap_region 형식)"""
    from helper import trap_region as T
    return T.merge(outline_traps(cfg, floor_n, 0.0, cfg.station.length, outer=False))


def inner_min(cfg, floor_n: int, side: int, s0: float, s1: float) -> float:
    """s0 ~ s1 에서 내공면 |t| 의 최솟값 (그 구간 어디서나 닿는 |t|)"""
    return inner_range(cfg, floor_n, side, s0, s1)[0]


def inner_range(cfg, floor_n: int, side: int, s0: float, s1: float) -> tuple:
    """s0 ~ s1 에서 내공면 |t| 의 (최솟값, 최댓값) — 같으면 그 구간 내공면이 곧음"""
    st = cfg.station
    pad = st.max_wall_t + 1.0
    poly = inner_polyline(cfg, floor_n, side, -pad, st.length + pad)
    vals = []
    for (a, ta), (b, tb) in zip(poly, poly[1:]):
        if b - a < _EPS:
            if s0 + 1e-7 < a < s1 - 1e-7:
                vals += [ta, tb]
            continue
        lo, hi = max(a, s0), min(b, s1)
        if hi - lo < -1e-9:
            continue
        f = lambda s: ta + (tb - ta) * (s - a) / (b - a)
        vals += [f(lo), f(hi)]
    return (min(vals), max(vals)) if vals else (st.width / 2.0, st.width / 2.0)


def clear_contains_rect(cfg, floor_n: int, rect, tol: float = 1e-6) -> bool:
    """사각형 (s0, s1, t0, t1) 이 그 층 넓어진 내공 안인가"""
    s0, s1, t0, t1 = rect[:4]
    L = cfg.station.length
    if s0 < -tol or s1 > L + tol:
        return False
    return t1 <= inner_min(cfg, floor_n, 1, s0, s1) + tol and -t0 <= inner_min(cfg, floor_n, -1, s0, s1) + tol


def on_inner_face(cfg, floor_n: int, a: tuple, b: tuple, tol: float = 1e-6) -> bool:
    """선분 a–b (정거장 로컬 (s, t)) 가 그 층 내공면(확폭 포함) 위인가 — 단부 내공면(s = 0, L)도 포함"""
    L = cfg.station.length
    if abs(a[0] - b[0]) < tol and (abs(a[0]) < tol or abs(a[0] - L) < tol):
        return True
    st = cfg.station
    pad = st.max_wall_t + 1.0
    for p in (a, b, ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)):
        side = 1 if p[1] > 0 else -1
        poly = inner_polyline(cfg, floor_n, side, -pad, st.length + pad)
        if not _on_poly(poly, p[0], abs(p[1]), tol):
            return False
    return True


def _on_poly(poly, s, t, tol):
    for (a, ta), (b, tb) in zip(poly, poly[1:]):
        if b - a < _EPS:
            if abs(s - a) < tol and min(ta, tb) - tol <= t <= max(ta, tb) + tol:
                return True
            continue
        if a - tol <= s <= b + tol and abs(ta + (tb - ta) * (min(max(s, a), b) - a) / (b - a) - t) < tol:
            return True
    return False


def platform_ranges(cfg) -> list:
    """최하층 좌·우 승강장 슬래브 t 범위 (platform.slab_t_ranges 를 내공 확폭만큼 벽 쪽으로 넓힘 — 가장 넓은 곳 기준,
    s 별 정확한 범위는 내공(clear_traps)으로 자름)"""
    st, pl = cfg.station, cfg.platform
    out = []
    for (t0, t1), side in zip(pl.slab_t_ranges(st.width), (-1, 1)):
        ext = max((w.amount for w in specs_for(cfg, 1, side, CLEAR)), default=0.0)
        out.append((t0 - ext, t1) if side < 0 else (t0, t1 + ext))
    return out
