"""직사각형 영역에서 직사각형 구멍들을 뺀 나머지를 서로 겹치지 않는 직사각형 조각으로 분해한다.

모든 좌표는 (s0, s1, t0, t1). 구멍은 영역 안에 있어야 하며 서로 겹치지 않는다고 가정한다 (검증은 호출 쪽 책임).
"""

TOL = 1e-9


def subtract_rects(region, holes):
    """region - ∪holes → 조각 목록. 구멍이 없으면 [region]. 같은 폭으로 이어지는 s 띠는 하나로 합친다"""
    S0, S1, T0, T1 = region
    holes = [h for h in holes if h[1] - h[0] > TOL and h[3] - h[2] > TOL]
    if not holes:
        return [tuple(region)]
    s_cuts = sorted({S0, S1, *(min(max(v, S0), S1) for h in holes for v in h[:2])})
    strips = []                                    # [(s0, s1, [(t0, t1), ...])]
    for a, b in zip(s_cuts, s_cuts[1:]):
        if b - a <= TOL:
            continue
        mid = (a + b) / 2.0
        blocked = sorted((max(h[2], T0), min(h[3], T1)) for h in holes if h[0] < mid < h[1])
        free, cur = [], T0
        for lo, hi in blocked:
            if lo - cur > TOL:
                free.append((cur, lo))
            cur = max(cur, hi)
        if T1 - cur > TOL:
            free.append((cur, T1))
        strips.append((a, b, free))
    merged = []                                    # 인접한 띠 중 t 구간이 같은 것은 s 방향으로 합침
    for a, b, free in strips:
        if merged and len(merged[-1][2]) == len(free) and all(
                abs(p[0] - q[0]) < TOL and abs(p[1] - q[1]) < TOL for p, q in zip(merged[-1][2], free)):
            merged[-1] = (merged[-1][0], b, merged[-1][2])
        else:
            merged.append((a, b, free))
    return [(a, b, lo, hi) for a, b, free in merged for lo, hi in free]


def subtract_intervals(lo, hi, holes):
    """1D: [lo, hi] - ∪holes(lo, hi 쌍) → 구간 목록 (2D 단면 작도용)"""
    out, cur = [], lo
    for a, b in sorted((max(h[0], lo), min(h[1], hi)) for h in holes):
        if a - cur > TOL:
            out.append((cur, a))
        cur = max(cur, b)
    if hi - cur > TOL:
        out.append((cur, hi))
    return out


def overlap_area(a, b):
    """두 직사각형 (s0, s1, t0, t1) 의 겹침 면적"""
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[2], b[2]))
