"""사다리꼴 영역 연산 (정거장 로컬 평면 (s, t)).

영역 = 사다리꼴 조각 목록. 조각 p = (s0, s1, lo0, hi0, lo1, hi1): s0 ~ s1 구간에서 아래 경계 t = lo(s), 위 경계 t = hi(s) 가
각각 직선 (lo0/hi0 @ s0, lo1/hi1 @ s1). 직사각형은 lo0 = lo1, hi0 = hi1.
구조물 확폭(내공면이 비스듬한 전이부)의 실·마감 영역에 쓴다. 불 연산은 s 를 모든 조각 경계·선 교차점에서 잘라
가늘고 긴 띠마다 선들의 순서가 바뀌지 않게 한 뒤 구간 연산으로 푼다 (정확).
"""
import math

EPS = 1e-7
BIG = 1e6


def rect(s0, s1, t0, t1) -> tuple:
    return (s0, s1, t0, t1, t0, t1)


def from_rects(rects) -> list:
    return [rect(*r[:4]) for r in rects]


def is_rect(p) -> bool:
    return abs(p[2] - p[4]) < 1e-9 and abs(p[3] - p[5]) < 1e-9


def bbox(p) -> tuple:
    """(s0, s1, t 최소, t 최대)"""
    return p[0], p[1], min(p[2], p[4]), max(p[3], p[5])


def trap_of(p):
    """RoomPiece/SlabPiece 용 trap (t0, t1 @ s0, t0, t1 @ s1) — 직사각형이면 None"""
    return None if is_rect(p) else (p[2], p[3], p[4], p[5])


def at(p, s) -> tuple:
    """s 에서의 (lo, hi)"""
    s0, s1 = p[0], p[1]
    k = 0.0 if s1 - s0 < 1e-12 else (s - s0) / (s1 - s0)
    return p[2] + (p[4] - p[2]) * k, p[3] + (p[5] - p[3]) * k


def area(ps) -> float:
    return sum((p[1] - p[0]) * ((p[3] - p[2]) + (p[5] - p[4])) / 2.0 for p in ps)


def contains(ps, s, t, tol=1e-6) -> bool:
    for p in ps:
        if p[0] - tol <= s <= p[1] + tol:
            lo, hi = at(p, min(max(s, p[0]), p[1]))
            if lo - tol <= t <= hi + tol:
                return True
    return False


def _cuts(ps):
    vals = sorted(v for p in ps for v in (p[0], p[1]))
    out = []
    for v in vals:
        if not out or v - out[-1] > EPS:
            out.append(v)
    return out


def _intervals(ps, a, b):
    """[a, b] 를 덮는 조각들의 (lo@a, lo@b, hi@a, hi@b)"""
    out = []
    for p in ps:
        if p[0] <= a + EPS and b <= p[1] + EPS:
            la, ha = at(p, a)
            lb, hb = at(p, b)
            out.append((la, lb, ha, hb))
    return out


def combine(A, B, op) -> list:
    """op(A 안, B 안) 이 참인 영역 (조각 목록)"""
    out = []
    cuts = _cuts(list(A) + list(B))
    for a, b in zip(cuts, cuts[1:]):
        if b - a < EPS:
            continue
        ia, ib = _intervals(A, a, b), _intervals(B, a, b)
        if not ia and not ib:
            continue
        lines = [(x[0], x[1]) for x in ia + ib] + [(x[2], x[3]) for x in ia + ib]
        sub = {a, b}
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                d0 = lines[i][0] - lines[j][0]
                d1 = lines[i][1] - lines[j][1]
                if (d0 < -EPS and d1 > EPS) or (d0 > EPS and d1 < -EPS):
                    sub.add(a + (b - a) * d0 / (d0 - d1))
        sub = sorted(sub)
        for c, d in zip(sub, sub[1:]):
            if d - c < EPS:
                continue
            val = lambda ln, s: ln[0] + (ln[1] - ln[0]) * (s - a) / (b - a)
            m = (c + d) / 2.0
            ends = sorted({(round(val(ln, m), 9), val(ln, c), val(ln, d)) for ln in lines})
            uniq = []
            for e in ends:
                if not uniq or e[0] - uniq[-1][0] > 1e-8:
                    uniq.append(e)
            fa = [(val((x[0], x[1]), m), val((x[2], x[3]), m)) for x in ia]
            fb = [(val((x[0], x[1]), m), val((x[2], x[3]), m)) for x in ib]
            cur = None
            for e0, e1 in zip(uniq, uniq[1:]):
                t = (e0[0] + e1[0]) / 2.0
                if op(any(lo < t < hi for lo, hi in fa), any(lo < t < hi for lo, hi in fb)):
                    if cur is not None and abs(cur[3] - e0[1]) < 1e-9 and abs(cur[5] - e0[2]) < 1e-9:
                        cur[3], cur[5] = e1[1], e1[2]
                    else:
                        cur = [c, d, e0[1], e1[1], e0[2], e1[2]]
                        out.append(cur)
                else:
                    cur = None
    return merge([tuple(p) for p in out if (p[3] - p[2]) > 1e-9 or (p[5] - p[4]) > 1e-9])


def merge(ps) -> list:
    """s 방향으로 이어지는 같은 직선 조각을 합침 (s, t 순 정렬)"""
    ps = sorted(ps, key=lambda p: (p[0], p[2] + p[4]))
    out = []
    for p in ps:
        for i, q in enumerate(out):
            if abs(q[1] - p[0]) < EPS and abs(q[4] - p[2]) < 1e-8 and abs(q[5] - p[3]) < 1e-8:
                L0, L1 = q[1] - q[0], p[1] - p[0]
                same = lambda a0, a1, b0, b1: abs((a1 - a0) / L0 - (b1 - b0) / L1) < 1e-9
                if same(q[2], q[4], p[2], p[4]) and same(q[3], q[5], p[3], p[5]):
                    out[i] = (q[0], p[1], q[2], q[3], p[4], p[5])
                    break
        else:
            out.append(p)
    return sorted(out, key=lambda p: (p[0], p[2] + p[4]))


def subtract(A, B) -> list:
    return combine(A, B, lambda x, y: x and not y) if B else merge(list(A))


def intersect(A, B) -> list:
    return combine(A, B, lambda x, y: x and y)


def union(A, B=()) -> list:
    return combine(A, B, lambda x, y: x or y)


def touch(p, q) -> bool:
    """두 조각이 변을 길이 > 0 만큼 공유하나 (꼭짓점만 닿으면 아님)"""
    a, b = max(p[0], q[0]), min(p[1], q[1])
    if b - a > EPS:                                           # s 가 겹침: 아래·위 경계가 맞닿음
        m = (a + b) / 2.0
        (pl, ph), (ql, qh) = at(p, m), at(q, m)
        return abs(ph - ql) < 1e-6 or abs(qh - pl) < 1e-6 or (min(ph, qh) - max(pl, ql) > 1e-6)
    for x, y in ((p, q), (q, p)):                             # s 끝이 맞닿음
        if abs(x[1] - y[0]) < 1e-6:
            (xl, xh), (yl, yh) = at(x, x[1]), at(y, y[0])
            if min(xh, yh) - max(xl, yl) > 1e-6:
                return True
    return False


def groups(ps) -> list:
    """맞닿은 조각끼리 묶음 (가장 작은 s 순)"""
    n = len(ps)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if touch(ps[i], ps[j]):
                parent[find(i)] = find(j)
    gs = {}
    for i, p in enumerate(ps):
        gs.setdefault(find(i), []).append(p)
    return sorted(gs.values(), key=lambda g: (min(p[0] for p in g), min(min(p[2], p[4]) for p in g)))


def boundary(ps) -> list:
    """영역의 바깥 경계 선분 [((s, t), (s, t), 안쪽 법선 (ns, nt))] — 같은 영역 조각끼리 맞닿은 부분은 뺌"""
    segs = []
    for p in ps:
        s0, s1, l0, h0, l1, h1 = p
        cand = [((s0, l0), (s1, l1), "lo"), ((s0, h0), (s1, h1), "hi"), ((s0, l0), (s0, h0), "s0"), ((s1, l1), (s1, h1), "s1")]
        for a, b, kind in cand:
            if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9:
                continue
            for u0, u1 in _uncovered(p, kind, ps):
                pa = (a[0] + (b[0] - a[0]) * u0, a[1] + (b[1] - a[1]) * u0)
                pb = (a[0] + (b[0] - a[0]) * u1, a[1] + (b[1] - a[1]) * u1)
                dx, dy = pb[0] - pa[0], pb[1] - pa[1]
                L = math.hypot(dx, dy)
                n = {"lo": (-dy / L, dx / L), "hi": (dy / L, -dx / L), "s0": (1.0, 0.0), "s1": (-1.0, 0.0)}[kind]
                if kind in ("lo", "hi") and abs(dx) < 1e-12:
                    continue
                segs.append((pa, pb, n))
    return segs


def _uncovered(p, kind, ps):
    """조각 p 의 변(kind) 중 다른 조각이 덮지 않은 매개변수 구간 [(u0, u1)] (0 ~ 1)"""
    s0, s1 = p[0], p[1]
    cover = []
    for q in ps:
        if q is p:
            continue
        if kind in ("lo", "hi"):
            a, b = max(s0, q[0]), min(s1, q[1])
            if b - a < EPS:
                continue
            line = (lambda s: at(p, s)[0]) if kind == "lo" else (lambda s: at(p, s)[1])
            other = (lambda s: at(q, s)[1]) if kind == "lo" else (lambda s: at(q, s)[0])
            if abs(line(a) - other(a)) < 1e-6 and abs(line(b) - other(b)) < 1e-6:
                cover.append(((a - s0) / (s1 - s0), (b - s0) / (s1 - s0)))
        else:
            s = s0 if kind == "s0" else s1
            qs = q[1] if kind == "s0" else q[0]
            if abs(qs - s) > 1e-6:
                continue
            lo, hi = at(p, s)
            if hi - lo < 1e-12:
                continue
            ql, qh = at(q, qs)
            a, b = max(lo, ql), min(hi, qh)
            if b - a > 1e-9:
                cover.append(((a - lo) / (hi - lo), (b - lo) / (hi - lo)))
    out, cur = [], 0.0
    for a, b in sorted(cover):
        if a > cur + 1e-9:
            out.append((cur, a))
        cur = max(cur, b)
    if cur < 1.0 - 1e-9:
        out.append((cur, 1.0))
    return out
