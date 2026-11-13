"""세계 좌표에서 곧게 뻗은 압출 부재 조각 (출구통로 등 선형을 따르지 않는 박스 구조물).

조각 1개 = 연직 단면 다각형(사각형 또는 헌치 삼각형)을 수평 축 u 방향으로 a0 ~ a1 만큼 편 각기둥.
축을 따라 기준 표고가 z(a) = z0 + slope·(a − a0) 로 변하고(구배), 단면은 연직면에서 그대로라 체적 = 단면적 × 수평 길이.
단면 좌표 (v, dz): v = 축의 왼쪽 수직 방향(u 를 +90° 돌린 방향) 거리, dz = 기준 표고에서의 높이.
IFC 에서는 연직 단면을 (0, slope, 1) 방향으로 민 IfcExtrudedAreaSolid 하나로 정확히 표현된다.
"""
import math
from dataclasses import dataclass, field

from helper import prism_member as PM


def polygon_area(pts) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


@dataclass
class BoxPiece:
    """곧은 압출 조각
    Attributes:
        ox, oy: 축 원점(a=0, v=0)의 세계 평면 좌표
        ux, uy: 축 방향 단위벡터 (세계 평면)
        a0, a1: 축 구간 (a0 < a1)
        sect: 단면 다각형 [(v, dz)] (볼록)
        z0: a0 에서의 기준 표고 (절대)
        slope: 축 방향 구배 (dz/da)
        local: 2D 도면용 부재 좌표 정보 (축 이름, 단면의 부재 좌표) — 소유 엔진이 해석
    """
    ox: float
    oy: float
    ux: float
    uy: float
    a0: float
    a1: float
    sect: list
    z0: float
    slope: float = 0.0
    local: dict = field(default_factory=dict)

    @property
    def vx(self) -> float:
        return -self.uy

    @property
    def vy(self) -> float:
        return self.ux

    @property
    def length(self) -> float:
        return self.a1 - self.a0

    def z_ref(self, a: float) -> float:
        return self.z0 + self.slope * (a - self.a0)

    def point(self, a: float, v: float, dz: float) -> tuple[float, float, float]:
        return (self.ox + a * self.ux + v * self.vx, self.oy + a * self.uy + v * self.vy, self.z_ref(a) + dz)

    @property
    def area(self) -> float:
        return abs(polygon_area(self.sect))

    @property
    def volume(self) -> float:
        return self.area * self.length

    @property
    def z_range(self) -> tuple[float, float]:
        dzs = [d for _, d in self.sect]
        zs = [self.z_ref(a) + d for a in (self.a0, self.a1) for d in dzs]
        return min(zs), max(zs)

    def footprint(self) -> list[tuple[float, float]]:
        """평면 외곽 (세계 좌표, 사각형)"""
        vs = [v for v, _ in self.sect]
        v0, v1 = min(vs), max(vs)
        return [self.point(a, v, 0.0)[:2] for a, v in ((self.a0, v0), (self.a1, v0), (self.a1, v1), (self.a0, v1))]

    def faces(self) -> list[tuple]:
        """닫힌 면 집합 (바깥 방향): 축 방향 측면(평행사변형) + 양 끝 단면"""
        r0 = [self.point(self.a0, v, dz) for v, dz in self.sect]
        r1 = [self.point(self.a1, v, dz) for v, dz in self.sect]
        n = len(r0)
        ref = PM._mean(r0 + r1)
        out = [_outward(r0[i], r0[(i + 1) % n], r1[(i + 1) % n], r1[i], ref=ref) for i in range(n)]
        out.append(_outward(*r0, ref=ref))
        out.append(_outward(*r1, ref=ref))
        return out


def _outward(*poly, ref):
    """볼록 다각형(3·4각형) 면의 법선이 ref(부재 안쪽 점)에서 멀어지도록 꼭짓점 순서를 맞춤"""
    nrm = PM._cross(PM._sub(poly[1], poly[0]), PM._sub(poly[-1], poly[0]))
    d = PM._sub(PM._mean(list(poly)), ref)
    return tuple(poly) if sum(nrm[i] * d[i] for i in range(3)) >= 0 else tuple(reversed(poly))


def footprints_overlap(p: list, q: list, tol: float = 1e-6) -> bool:
    """두 볼록 다각형(평면)이 면적을 가지고 겹치는가 (분리축 정리, 맞닿음은 겹침 아님)"""
    for poly in (p, q):
        for i in range(len(poly)):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % len(poly)]
            nx, ny = y1 - y0, x0 - x1
            ln = math.hypot(nx, ny)
            if ln < 1e-12:
                continue
            nx, ny = nx / ln, ny / ln
            pa = [nx * x + ny * y for x, y in p]
            qa = [nx * x + ny * y for x, y in q]
            if max(pa) <= min(qa) + tol or max(qa) <= min(pa) + tol:
                return False
    return True
