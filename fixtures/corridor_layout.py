"""출구통로·출입구 천장의 조명·디퓨저 배치 (실과 같은 기구·간격 — 마감 종류의 light_s·light_t·diff_gap).

좌표 = 통로 구간(또는 출입구 경사 천장의 곧은 한 구간)의 축 방향 실제 길이 × 폭 방향 v(중심선 0, 왼쪽 +). 천장판 격자 0.6 은 축 방향으로
구간 시작, 폭 방향으로 중심선이 칸 가운데 (좌우 대칭). 조명 긴 방향 = 통로 방향 (사용자 지정), 경사 천장은 천장판을 따라 기울여 매입 —
천장이 꺾이는 선에는 걸치지 않음 (곧은 구간마다 따로 배치).
기구 자리 = (종류, a0, a1, v0, v1, 깊이) — a 는 수평 거리(구간 틀 좌표).
"""
import math

from fixtures.fixture_layout import DEPTH, layout_fixtures
from helper.box_piece import BoxPiece
from helper.strip_member import Strip

_EPS = 1e-6
_MIN = 1e-9


def mitre_region(end: float, tp: float, ke: float, half: float) -> list:
    """구간 천장 평면 (a, v): tp·v ≤ a ≤ end + ke·v, |v| ≤ half → 사다리꼴 조각 (a0, a1, 하한·상한 @ 양 끝)"""
    def span(a):
        lo, hi = -half, half
        for k, b in ((tp, a), (-ke, end - a)):                          # k·v ≤ b
            if k > 1e-12:
                hi = min(hi, b / k)
            elif k < -1e-12:
                lo = max(lo, b / k)
            elif b < -1e-12:
                return None
        return (lo, hi) if hi >= lo - 1e-12 else None
    cuts = {tp * half, -tp * half, end + ke * half, end - ke * half}
    if abs(tp - ke) > 1e-12:                                            # 양 끝 선이 만나는 곳
        v = end / (tp - ke)
        if abs(v) < half:
            cuts.add(tp * v)
    cs = sorted(cuts)
    out = []
    for a, b in zip(cs, cs[1:]):
        if b - a < 1e-6:
            continue
        p, q = span(a + 1e-12), span(b - 1e-12)
        if p and q and max(p[1] - p[0], q[1] - q[0]) > 1e-6:
            out.append((a, b, *p, *q))
    return out


def place(ft, region: list, k: float = 1.0, base: float = 0.0, diffusers: bool = True) -> list:
    """천장 평면 조각(수평 a, v) → [(종류, a0, a1, v0, v1)]. k = cos(경사각): 축 방향은 실제 길이로 배치하고 수평 거리로
    되돌림, base = 천장판 격자의 축 방향 원점"""
    import dataclasses
    if not diffusers:
        ft = dataclasses.replace(ft, diff_gap=0.0)
    if not region:
        return []
    real = [((p[0] - base) / k, (p[1] - base) / k, *p[2:]) for p in region]
    lights, diffs = layout_fixtures(ft, real, [], centered=True)
    return [(kind, base + r[0] * k, base + r[1] * k, r[2], r[3]) for kind, rs in (("LIGHT", lights), ("DIFFUSER", diffs)) for r in rs]


# ====================================================================== 출구통로
def passage_fixtures(ft, seg, c_half: float, end: float, ke: float, room_above) -> list:
    """통로 구간의 기구 [(종류, a0, a1, v0, v1, 깊이)]. room_above(v) = 천장판 하면에서 그 자리 구조 천장 하면까지 높이"""
    k = 1.0 / math.sqrt(1.0 + seg.slope ** 2)
    return [(*f, min(DEPTH[f[0]], room_above(max(abs(f[3]), abs(f[4])))))
            for f in place(ft, mitre_region(end, seg.tp, ke, c_half), k)]


def cut_boxes(pieces: list, seg_index: int, holes: list) -> list:
    """BoxPiece(사각 단면) 들에서 같은 구간(local['seg'])의 기구 자리 (a0, a1, v0, v1) 를 뺌"""
    out = []
    for p in pieces:
        vs = [v for v, _ in p.sect]
        v0, v1 = min(vs), max(vs)
        reach = max(abs(p.ks), abs(p.ke)) * max(abs(v0), abs(v1))
        near = [] if p.local.get("seg") != seg_index else [
            h for h in holes if min(h[3], v1) - max(h[2], v0) > _EPS and min(h[1], p.a1 + reach) - max(h[0], p.a0 - reach) > _EPS
            and not (p.ks == p.ke == 0.0 and not min(h[1], p.a1) - max(h[0], p.a0) > _EPS)]
        if not near:
            out.append(p)
            continue
        d0, d1 = min(d for _, d in p.sect), max(d for _, d in p.sect)
        for b0, b1, hs in bands(v0, v1, near):
            a, ks = p.a0, p.ks
            for h0, h1 in [x[:2] for x in hs] + [(None, None)]:
                e, ke = (p.a1, p.ke) if h0 is None else (h0, 0.0)
                lo, hi = max(a + ks * b for b in (b0, b1)), min(e + ke * b for b in (b0, b1))
                if not hs or hi - lo > _MIN:
                    out.append(BoxPiece(p.ox, p.oy, p.ux, p.uy, a, e, [(b0, d0), (b1, d0), (b1, d1), (b0, d1)], p.z_ref(a), p.slope, ks, ke, dict(p.local)))
                if h0 is not None:
                    a, ks = (h1, 0.0) if h1 > a else (a, ks)
    return out


def bands(lo: float, hi: float, holes: list) -> list:
    """[lo, hi] 를 구멍(a0, a1, v0, v1)의 v 경계로 나눈 띠 [(v0, v1, 그 띠의 구멍 a 순서)] — 구멍 구성이 같은 이웃 띠는 합침"""
    cuts = sorted({lo, hi, *(x for h in holes for x in (h[2], h[3]) if lo + _EPS < x < hi - _EPS)})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        m = (a + b) / 2.0
        hs = sorted((h for h in holes if h[2] < m < h[3]), key=lambda h: h[0])
        if out and out[-1][2] == hs:
            out[-1] = (out[-1][0], b, hs)
        else:
            out.append((a, b, hs))
    return out


# ====================================================================== 출입구 (경사 천장)
def straight_runs(segs: list, lo: float, hi: float) -> list:
    """꺾은선 (u0, u1, z0, z1) 들을 [lo, hi] 로 자르고 한 직선으로 이어지는 것끼리 합침"""
    out = []
    for u0, u1, z0, z1 in segs:
        a, b = max(u0, lo), min(u1, hi)
        if b - a <= _EPS:
            continue
        m = (z1 - z0) / (u1 - u0)
        za, zb = z0 + m * (a - u0), z0 + m * (b - u0)
        if out:
            p0, p1, q0, q1, pm = out[-1]
            if abs(p1 - a) < 1e-6 and abs(q1 - za) < 1e-6 and abs(pm - m) < 1e-9:
                out[-1] = (p0, b, q0, zb, pm)
                continue
        out.append((a, b, za, zb, m))
    return out


def entrance_fixtures(ft, segs: list, lo: float, hi: float, half: float, room_above) -> list:
    """출입구 천장 조명 [(종류, u0, u1, t0, t1, 깊이, u0 의 천장판 하면 표고, 기울기)] — 곧은 구간마다, 조명만 (사용자 지정)"""
    out = []
    for a, b, za, _, m in straight_runs(segs, lo, hi):
        k = 1.0 / math.sqrt(1.0 + m * m)
        for f in place(ft, [(a, b, -half, half, -half, half)], k, a, diffusers=False):
            out.append((*f, min(DEPTH[f[0]], room_above(max(abs(f[3]), abs(f[4])))), za + m * (f[1] - a), m))
    return out


def cut_strips(parts: list, holes: list) -> list:
    """출입구 마감 부재 (코드, 종류, 재질, t 범위, 띠) 중 천장판·천장틀에서 구멍 (u0, u1, t0, t1) 을 뺌 — t 띠마다 부재 하나 (둘째부터 _B{k})"""
    out = []
    for part in parts:
        code, kind, mat, (t0, t1), strips = part
        lo, hi = min(s.s0 for s in strips), max(s.s1 for s in strips)
        near = [h for h in holes if kind in ("CEILING", "FRAME") and min(h[3], t1) - max(h[2], t0) > _EPS and min(h[1], hi) - max(h[0], lo) > _EPS]
        if not near:
            out.append(part)
            continue
        n = 0
        for b0, b1, hs in bands(t0, t1, near):
            new = [q for s in strips for q in _minus(s, hs)]
            if new:
                n += 1
                out.append((code if n == 1 else f"{code}_B{n}", kind, mat, (b0, b1), new))
    return out


def _minus(s: Strip, holes: list) -> list:
    """띠 s 에서 u 구간들을 뺀 나머지"""
    out, a = [], s.s0
    for h in [x for x in holes if min(x[1], s.s1) - max(x[0], s.s0) > _EPS] + [None]:
        b = s.s1 if h is None else h[0]
        if b - a > _MIN:
            zt = s.zt_at(b)
            out.append(Strip(a, b, s.zb_at(a), s.zb_at(b), s.zt_at(a), s.curve_factor, None if abs(zt - s.zt_at(a)) < 1e-12 else zt))
        if h is not None:
            a = max(a, h[1])
    return out
