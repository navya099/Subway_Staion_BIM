"""s 방향 띠(strip)를 이어 붙인 부재의 공통 기하 (계단 · 에스컬레이터).

띠 1개 = s0 ~ s1 구간에서 하면(zb0 → zb1)과 상면(zt → zt_end)이 각각 직선인 단면을 t 방향 폭만큼 편 각기둥.
표고는 절대 표고. 부재 = 띠들을 s 순서로 맞닿게 이은 것 (띠끼리 겹치지 않음).
직선 선형이면 띠는 6면 각기둥, 곡선이면 표본 측점마다 단면을 이은 스윕이고 기울어진 상·하면은 중심점 4분할 삼각형으로 작도한다.
"""
from dataclasses import dataclass, field
from typing import Optional

from helper import prism_member as PM
from shapes.base_shape import BaseShape


@dataclass
class Strip:
    """띠 1개. zt1 을 비우면 상면 수평 (zt). curve_factor = 곡선 체적 보정 (직선 1.0)"""
    s0: float
    s1: float
    zb0: float
    zb1: float
    zt: float
    curve_factor: float = 1.0
    zt1: Optional[float] = None

    @property
    def zt_end(self) -> float:
        return self.zt if self.zt1 is None else self.zt1

    def _lerp(self, a: float, b: float, s: float) -> float:
        if self.s1 - self.s0 <= 0:
            return a
        return a + (b - a) * (s - self.s0) / (self.s1 - self.s0)

    def zb_at(self, s: float) -> float:
        return self._lerp(self.zb0, self.zb1, s)

    def zt_at(self, s: float) -> float:
        return self._lerp(self.zt, self.zt_end, s)

    @property
    def area(self) -> float:
        """s–z 단면적"""
        return (self.s1 - self.s0) * (self.zt + self.zt_end - self.zb0 - self.zb1) / 2.0


@dataclass
class StripShape(BaseShape):
    """띠들을 s 순서로 이은 단면을 t 방향 width 만큼 편 부재 형상
    Attributes:
        strips: s 오름차순, 서로 맞닿고 겹치지 않음
        width: t 방향 폭 (m)
    """
    strips: list = field(default_factory=list)
    width: float = 0.0

    @property
    def length(self) -> float:
        return self.strips[-1].s1 - self.strips[0].s0 if self.strips else 0.0

    @property
    def volume(self) -> float:
        return sum(st.area * self.width * st.curve_factor for st in self.strips)

    def profile_points(self) -> list[tuple[float, float]]:
        """(s, z) 단면 외곽 다각형 (반시계): 하면을 s 증가 방향으로, 상면을 s 감소 방향으로"""
        bottom, top = [], []
        for st in self.strips:
            bottom += [(st.s0, st.zb0), (st.s1, st.zb1)]
            top += [(st.s0, st.zt), (st.s1, st.zt_end)]
        pts = bottom + list(reversed(top))
        out = []
        for p in pts:                                      # 연속 중복점 제거
            if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
                out.append(p)
        if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
            out.pop()
        return out


def strip_rings(cfg, strip: Strip, t0: float, t1: float) -> list:
    """띠 1개의 표본 측점별 단면 링 [t0 하단, t1 하단, t1 상단, t0 상단] (WCS)"""
    out = []
    for s in cfg.sample_s(strip.s0, strip.s1):
        zb, zt = strip.zb_at(s), strip.zt_at(s)
        (xa, ya), (xb, yb) = cfg.to_world(s, t0), cfg.to_world(s, t1)
        out.append([(xa, ya, zb), (xb, yb, zb), (xb, yb, zt), (xa, ya, zt)])
    return out


def _fan(q):
    c = tuple(sum(p[i] for p in q) / 4.0 for i in range(3))
    return [(q[i], q[(i + 1) % 4], c) for i in range(4)]


def strip_faces(cfg, strip: Strip, t0: float, t1: float) -> list[tuple]:
    """띠 1개의 닫힌 면 집합 (바깥 방향). 직선은 6면 각기둥.
    곡선에서 기울어진 상·하면은 양 끝 단면(방사 방향 선)이 평행하지 않아 비틀린 사각형이 되므로, 중심점을 둔 삼각형 4개로 나눠
    대각선 한쪽으로 자를 때 생기는 체적 편차를 없앤다 (측면은 연직이라 평면)"""
    rs = strip_rings(cfg, strip, t0, t1)
    quads = PM.sweep_quads(rs)
    if min(strip.zt - strip.zb0, strip.zt_end - strip.zb1) < 1e-9:
        return _degenerate_faces(rs)                  # 한쪽 끝 높이 0 (삼각 단면 띠)
    if cfg.align.is_straight:
        return quads
    twisted = set()
    if abs(strip.zb1 - strip.zb0) > 1e-12:
        twisted |= {frozenset((r0[0], r1[0], r1[1], r0[1])) for r0, r1 in zip(rs, rs[1:])}
    if abs(strip.zt_end - strip.zt) > 1e-12:
        twisted |= {frozenset((r0[3], r0[2], r1[2], r1[3])) for r0, r1 in zip(rs, rs[1:])}
    if not twisted:
        return quads
    out = []
    for q in quads:
        out.extend(_fan(q) if frozenset(q) in twisted else [q])
    return out


def _degenerate_faces(rs) -> list[tuple]:
    """한쪽 끝의 높이가 0 인 띠(칸막이벽이 계단 슬래브 아래로 사라지는 점 등): 겹친 꼭짓점을 지운 면(삼각형 포함)을
    부재 안쪽 점 기준으로 바깥 방향으로 맞춤. 면이 퇴화하면 사각형 법선이 0 이 되어 방향 판정이 틀리므로 따로 처리"""
    raw = []
    for r0, r1 in zip(rs, rs[1:]):
        raw += [(r0[0], r1[0], r1[1], r0[1]), (r0[3], r0[2], r1[2], r1[3]), (r0[0], r0[3], r1[3], r1[0]), (r0[1], r1[1], r1[2], r0[2])]
    raw += [tuple(rs[0]), tuple(rs[-1])]
    pts = {p for f in raw for p in f}
    ref = PM._mean(list(pts))
    out = []
    for f in raw:
        poly = []
        for p in f:
            if not poly or max(abs(p[i] - poly[-1][i]) for i in range(3)) > 1e-12:
                poly.append(p)
        if len(poly) > 1 and max(abs(poly[0][i] - poly[-1][i]) for i in range(3)) <= 1e-12:
            poly.pop()
        if len(poly) < 3:
            continue
        n = PM._cross(PM._sub(poly[1], poly[0]), PM._sub(poly[-1], poly[0]))
        if sum(c * c for c in n) < 1e-24:
            continue
        d = PM._sub(PM._mean(poly), ref)
        out.append(tuple(poly) if sum(n[i] * d[i] for i in range(3)) >= 0 else tuple(reversed(poly)))
    return out


def part_faces(cfg, part) -> list[list[tuple]]:
    """부재(part.t_range, part.shape.strips)의 띠마다 닫힌 면 집합 (면은 사각형 또는 삼각형)"""
    t0, t1 = part.t_range
    return [strip_faces(cfg, st, t0, t1) for st in part.shape.strips]


def section_spans(part, sta: float):
    """측점 sta 의 횡단면이 자르는 띠의 (t0, t1, zb, zt) 목록 (띠는 [s0, s1) 반열린 구간)"""
    t0, t1 = part.t_range
    return [(t0, t1, st.zb_at(sta), st.zt_at(sta)) for st in part.shape.strips if st.s0 - 1e-9 <= sta < st.s1 - 1e-9]
