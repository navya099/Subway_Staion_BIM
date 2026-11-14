"""세계 좌표에서 곧게 뻗은 압출 부재 조각 (출구통로 등 선형을 따르지 않는 박스 구조물).

조각 1개 = 연직 단면 다각형(사각형 또는 헌치 삼각형)을 수평 축 u 방향으로 편 각기둥.
- 축을 따라 기준 표고가 z(a) = z0 + slope·(a − a0) 로 변하고(구배), 단면은 연직면에서 그대로다.
- 단면 좌표 (v, dz): v = 축의 왼쪽 수직 방향(u 를 +90° 돌린 방향) 거리, dz = 기준 표고에서의 높이.
- 양 끝은 비스듬히 잘릴 수 있다 (꺾임부 연귀 접합): 단면의 v 위치마다 축 구간이
  a_s(v) = a0 + ks·v  ~  a_e(v) = a1 + ke·v  (ks = ke = 0 이면 직각 끝).
  모든 면이 평면이라 볼록 다면체이고, 체적 = 단면적 × (a1 − a0 + (ke − ks)·v_도심).
IFC: 직각 끝이면 IfcExtrudedAreaSolid 하나(압출 방향 (0, 구배, 1)), 비스듬한 끝이면 면 집합으로 정확히 표현한다.
"""
import math
from dataclasses import dataclass, field

from helper import prism_member as PM


def polygon_area(pts) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def polygon_centroid(pts) -> tuple[float, float]:
    a = polygon_area(pts)
    cx = sum((p[0] + q[0]) * (p[0] * q[1] - q[0] * p[1]) for p, q in zip(pts, pts[1:] + pts[:1])) / (6.0 * a)
    cy = sum((p[1] + q[1]) * (p[0] * q[1] - q[0] * p[1]) for p, q in zip(pts, pts[1:] + pts[:1])) / (6.0 * a)
    return cx, cy


@dataclass
class BoxPiece:
    """곧은 압출 조각
    Attributes:
        ox, oy: 축 원점(a=0, v=0)의 세계 평면 좌표
        ux, uy: 축 방향 단위벡터 (세계 평면)
        a0, a1: 축 구간 (v=0 에서, a0 < a1)
        sect: 단면 다각형 [(v, dz)] (볼록)
        z0: a0 에서의 기준 표고 (절대)
        slope: 축 방향 구배 (dz/da)
        ks, ke: 시작·끝 단면의 비스듬함 (a_s(v) = a0 + ks·v, a_e(v) = a1 + ke·v)
        local: 소유 엔진이 쓰는 부가 정보
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
    ks: float = 0.0
    ke: float = 0.0
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

    @property
    def skewed(self) -> bool:
        return abs(self.ks) > 1e-12 or abs(self.ke) > 1e-12

    def a_start(self, v: float) -> float:
        return self.a0 + self.ks * v

    def a_end(self, v: float) -> float:
        return self.a1 + self.ke * v

    def z_ref(self, a: float) -> float:
        return self.z0 + self.slope * (a - self.a0)

    def point(self, a: float, v: float, dz: float) -> tuple[float, float, float]:
        return (self.ox + a * self.ux + v * self.vx, self.oy + a * self.uy + v * self.vy, self.z_ref(a) + dz)

    @property
    def area(self) -> float:
        return abs(polygon_area(self.sect))

    @property
    def volume(self) -> float:
        vc = polygon_centroid(self.sect)[0]
        return self.area * (self.length + (self.ke - self.ks) * vc)

    def rings(self):
        """(시작 단면, 끝 단면) 꼭짓점 목록 (세계 3D)"""
        r0 = [self.point(self.a_start(v), v, dz) for v, dz in self.sect]
        r1 = [self.point(self.a_end(v), v, dz) for v, dz in self.sect]
        return r0, r1

    @property
    def z_range(self) -> tuple[float, float]:
        r0, r1 = self.rings()
        zs = [p[2] for p in r0 + r1]
        return min(zs), max(zs)

    def footprint(self) -> list[tuple[float, float]]:
        """평면 외곽 (세계 좌표, 사각형 또는 사다리꼴)"""
        vs = [v for v, _ in self.sect]
        v0, v1 = min(vs), max(vs)
        return [self.point(a, v, 0.0)[:2] for a, v in ((self.a_start(v0), v0), (self.a_end(v0), v0),
                                                       (self.a_end(v1), v1), (self.a_start(v1), v1))]

    def faces(self) -> list[tuple]:
        """닫힌 면 집합 (바깥 방향): 축 방향 측면 + 양 끝 단면 (모두 평면)"""
        r0, r1 = self.rings()
        n = len(r0)
        ref = PM._mean(r0 + r1)
        out = [_outward(r0[i], r0[(i + 1) % n], r1[(i + 1) % n], r1[i], ref=ref) for i in range(n)]
        out.append(_outward(*r0, ref=ref))
        out.append(_outward(*r1, ref=ref))
        return out

    def cut_by_plane(self, px: float, py: float, nx: float, ny: float):
        """연직 평면(점 (px, py), 수평 법선 (nx, ny))과의 단면 다각형 → [(w, z)] 또는 None.
        w = 평면 위 수평 좌표 (법선을 +90° 돌린 방향, 즉 (−ny, nx) 방향 거리)"""
        return cut_faces_by_plane(self.faces(), px, py, nx, ny)


def cut_faces_by_plane(faces, px: float, py: float, nx: float, ny: float):
    """볼록 다면체(면 목록)를 연직 평면으로 자른 단면 다각형 [(w, z)] 또는 None (w 는 BoxPiece.cut_by_plane 과 같음)"""
    pts = []
    for f in faces:
        for i in range(len(f)):
            p, q = f[i], f[(i + 1) % len(f)]
            dp = (p[0] - px) * nx + (p[1] - py) * ny
            dq = (q[0] - px) * nx + (q[1] - py) * ny
            if abs(dp) < 1e-12:
                pts.append(p)
            if dp * dq < 0:
                t = dp / (dp - dq)
                pts.append(tuple(p[k] + (q[k] - p[k]) * t for k in range(3)))
    wz = [(-(p[0] - px) * ny + (p[1] - py) * nx, p[2]) for p in pts]
    hull = _convex_hull(wz)
    if len(hull) < 3 or abs(polygon_area(hull)) < 1e-9:
        return None
    return hull


def _outward(*poly, ref):
    """볼록 다각형(3·4각형) 면의 법선이 ref(부재 안쪽 점)에서 멀어지도록 꼭짓점 순서를 맞춤"""
    nrm = PM._cross(PM._sub(poly[1], poly[0]), PM._sub(poly[-1], poly[0]))
    d = PM._sub(PM._mean(list(poly)), ref)
    return tuple(poly) if sum(nrm[i] * d[i] for i in range(3)) >= 0 else tuple(reversed(poly))


def _convex_hull(pts):
    """2D 볼록 껍질 (반시계, 중복 제거)"""
    uniq = sorted({(round(x, 9), round(y, 9)) for x, y in pts})
    if len(uniq) < 3:
        return uniq

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in uniq:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(uniq):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


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
