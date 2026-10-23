"""곡선 선형: 평면(직선 · 원곡선 · 완화곡선) + 종단(구배 · 포물선 종곡선).

- 평면은 '곡률이 거리에 대해 선형으로 변하는 요소'의 연속으로 표현한다.
  직선 (k0 = k1 = 0), 원곡선 (k0 = k1 = ±1/R), 완화곡선/클로소이드 (k0 → k1). 곡률 부호: 좌회전 +.
- 대부분의 입력 방식인 IP(교점) + 곡선반경 + 완화곡선장 으로부터 요소를 만드는 horizontal_from_pi 를 제공한다.
- 종단은 변곡점(PVI: 측점, 표고, 종곡선장) 목록으로 정의하고 종곡선은 포물선이다.
"""
import math
from bisect import bisect_right
from dataclasses import dataclass

from config.alignment import Alignment

# 8점 Gauss-Legendre 적분 (완화곡선 위치 계산용)
_GL = [(-0.9602898564975363, 0.1012285362903763), (-0.7966664774136267, 0.2223810344533745),
       (-0.5255324099163290, 0.3137066458778873), (-0.1834346424956498, 0.3626837833783620),
       (0.1834346424956498, 0.3626837833783620), (0.5255324099163290, 0.3137066458778873),
       (0.7966664774136267, 0.2223810344533745), (0.9602898564975363, 0.1012285362903763)]


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


@dataclass(frozen=True)
class HElement:
    """평면 선형 요소 하나: 길이 length, 시작 곡률 k0 → 끝 곡률 k1 (1/m, 좌회전 +)"""
    length: float
    k0: float = 0.0
    k1: float = 0.0

    def heading_at(self, s: float) -> float:
        """요소 시작 대비 방향 변화 (rad)"""
        return self.k0 * s + (self.k1 - self.k0) * s * s / (2.0 * self.length)

    def curvature_at(self, s: float) -> float:
        return self.k0 + (self.k1 - self.k0) * s / self.length

    def offset_at(self, th0: float, s: float) -> tuple[float, float]:
        """요소 시작점에서 거리 s 만큼 간 점의 변위 (dx, dy). th0 = 요소 시작 방향각"""
        k0, k1 = self.k0, self.k1
        if abs(k1 - k0) < 1e-12:
            if abs(k0) < 1e-12:                                   # 직선
                return s * math.cos(th0), s * math.sin(th0)
            th = th0 + k0 * s                                     # 원곡선 (닫힌 해)
            return (math.sin(th) - math.sin(th0)) / k0, -(math.cos(th) - math.cos(th0)) / k0
        panels = max(1, math.ceil(s / 2.0))                       # 완화곡선: 구간 적분
        dx = dy = 0.0
        for p in range(panels):
            a, b = s * p / panels, s * (p + 1) / panels
            mid, half = (a + b) / 2.0, (b - a) / 2.0
            for x, w in _GL:
                u = mid + half * x
                th = th0 + self.heading_at(u)
                dx += w * half * math.cos(th)
                dy += w * half * math.sin(th)
        return dx, dy


class HorizontalAlignment:
    """평면 선형: 시작점/방향/측점 + 요소 목록"""

    def __init__(self, start_station: float, x0: float, y0: float, theta0: float, elements: list[HElement]):
        if not elements:
            raise ValueError("평면 선형 요소가 비어 있습니다")
        if any(e.length <= 0 for e in elements):
            raise ValueError("평면 선형 요소의 길이는 0보다 커야 합니다")
        self.elements = list(elements)
        self._starts, self._poses = [], []
        sta, x, y, th = start_station, x0, y0, theta0
        for e in self.elements:
            self._starts.append(sta)
            self._poses.append((x, y, th))
            dx, dy = e.offset_at(th, e.length)
            x, y, th = x + dx, y + dy, th + e.heading_at(e.length)
            sta += e.length
        self.start_station, self.end_station = start_station, sta
        self.end_pose = (x, y, th)

    def _locate(self, sta: float):
        i = min(max(bisect_right(self._starts, sta) - 1, 0), len(self.elements) - 1)
        return i, sta - self._starts[i]            # 범위 밖은 첫/끝 요소를 연장 (차분 계산용)

    def point_at(self, sta: float) -> tuple[float, float]:
        i, s = self._locate(sta)
        x, y, th = self._poses[i]
        dx, dy = self.elements[i].offset_at(th, s)
        return x + dx, y + dy

    def azimuth_at(self, sta: float) -> float:
        i, s = self._locate(sta)
        return self._poses[i][2] + self.elements[i].heading_at(s)

    def curvature_at(self, sta: float) -> float:
        i, s = self._locate(sta)
        return self.elements[i].curvature_at(min(max(s, 0.0), self.elements[i].length))

    def breakpoints(self) -> list[float]:
        return self._starts[1:]


def horizontal_from_pi(start_station: float, points: list, radii: list, spirals: list | None = None) -> HorizontalAlignment:
    """IP(교점) 방식 입력 → 평면 선형. 첫 점이 시점, 마지막 점이 종점, 사이 점이 교점(IP).

    points:  [(x, y), ...] 시점, IP들, 종점
    radii:   IP별 원곡선 반경 (IP 개수와 같음)
    spirals: IP별 완화곡선 길이 (생략하면 0 = 완화곡선 없는 단곡선)
    """
    n = len(points)
    if n < 2:
        raise ValueError("점이 2개 이상 필요합니다")
    ips = n - 2
    spirals = list(spirals) if spirals is not None else [0.0] * ips
    if len(radii) != ips or len(spirals) != ips:
        raise ValueError(f"교점이 {ips}개이므로 곡선반경/완화곡선장도 {ips}개여야 합니다 (반경 {len(radii)}, 완화곡선 {len(spirals)})")

    seg_len, seg_th = [], []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if math.hypot(x1 - x0, y1 - y0) < 1e-9:
            raise ValueError("연속한 두 점의 위치가 같습니다")
        seg_len.append(math.hypot(x1 - x0, y1 - y0))
        seg_th.append(math.atan2(y1 - y0, x1 - x0))

    curves = {}                                   # 교점 j(1..n-2) → (접선장 T, 요소 목록)
    for j in range(1, n - 1):
        delta = _wrap(seg_th[j] - seg_th[j - 1])
        R, Ls = float(radii[j - 1]), float(spirals[j - 1])
        if abs(delta) < 1e-9:                     # 일직선 위의 교점: 곡선 없음
            curves[j] = (0.0, [])
            continue
        if R <= 0 or Ls < 0:
            raise ValueError(f"교점 {j}: 곡선반경은 0보다 크고 완화곡선장은 0 이상이어야 합니다 (R={R}, Ls={Ls})")
        sign, d = (1.0 if delta > 0 else -1.0), abs(delta)
        ths = Ls / (2.0 * R)                      # 완화곡선 전체 방향 변화
        if d < 2.0 * ths - 1e-12:
            raise ValueError(f"교점 {j}: 편각({math.degrees(d):.2f}°)이 완화곡선 2개의 방향 변화({math.degrees(2 * ths):.2f}°)보다 작습니다")
        if Ls > 0:
            xs, ys = HElement(Ls, 0.0, 1.0 / R).offset_at(0.0, Ls)
            p, kk = ys - R * (1.0 - math.cos(ths)), xs - R * math.sin(ths)
        else:
            p = kk = 0.0
        T = (R + p) * math.tan(d / 2.0) + kk
        Lc = R * (d - 2.0 * ths)
        k = sign / R
        els = []
        if Ls > 0:
            els.append(HElement(Ls, 0.0, k))
        if Lc > 1e-9:
            els.append(HElement(Lc, k, k))
        if Ls > 0:
            els.append(HElement(Ls, k, 0.0))
        curves[j] = (T, els)

    elements = []
    for i in range(n - 1):
        t_start = curves[i][0] if i >= 1 else 0.0
        t_end = curves[i + 1][0] if i + 1 <= n - 2 else 0.0
        line = seg_len[i] - t_start - t_end
        if line < -1e-9:
            raise ValueError(f"구간 {i + 1}: 인접한 두 곡선의 접선장 합({t_start + t_end:.2f}m)이 직선 길이({seg_len[i]:.2f}m)보다 커서 곡선이 겹칩니다")
        if line > 1e-9:
            elements.append(HElement(line))
        if i + 1 <= n - 2:
            elements.extend(curves[i + 1][1])
    return HorizontalAlignment(start_station, points[0][0], points[0][1], seg_th[0], elements)


class VerticalProfile:
    """종단 선형: 변곡점(PVI) 목록과 포물선 종곡선"""

    def __init__(self, pvis: list):
        """pvis: [(측점, 표고, 종곡선장), ...]  첫/끝 점의 종곡선장은 0"""
        if len(pvis) < 2:
            raise ValueError("종단 변곡점(PVI)이 2개 이상 필요합니다")
        self.sta = [float(p[0]) for p in pvis]
        self.z = [float(p[1]) for p in pvis]
        self.vc = [float(p[2]) if len(p) > 2 else 0.0 for p in pvis]
        if any(b <= a for a, b in zip(self.sta, self.sta[1:])):
            raise ValueError("종단 변곡점의 측점은 증가해야 합니다")
        if self.vc[0] != 0 or self.vc[-1] != 0:
            raise ValueError("첫/끝 변곡점의 종곡선장은 0이어야 합니다")
        if any(v < 0 for v in self.vc):
            raise ValueError("종곡선장은 0 이상이어야 합니다")
        self.g = [(self.z[i + 1] - self.z[i]) / (self.sta[i + 1] - self.sta[i]) for i in range(len(pvis) - 1)]
        for i in range(1, len(pvis) - 1):             # 종곡선이 서로, 그리고 끝점과 겹치지 않는지
            lo, hi = self.sta[i] - self.vc[i] / 2, self.sta[i] + self.vc[i] / 2
            prev_hi = self.sta[i - 1] + self.vc[i - 1] / 2
            next_lo = self.sta[i + 1] - self.vc[i + 1] / 2
            if lo < prev_hi - 1e-9 or hi > next_lo + 1e-9:
                raise ValueError(f"변곡점 {i + 1}: 종곡선이 인접한 종곡선/구간과 겹칩니다")
        self.start_station, self.end_station = self.sta[0], self.sta[-1]

    def _curve_at(self, sta: float):
        for i in range(1, len(self.sta) - 1):
            if self.vc[i] > 0 and self.sta[i] - self.vc[i] / 2 <= sta <= self.sta[i] + self.vc[i] / 2:
                return i
        return None

    def elevation_at(self, sta: float) -> float:
        i = self._curve_at(sta)
        if i is not None:
            L, g1, g2 = self.vc[i], self.g[i - 1], self.g[i]
            x = sta - (self.sta[i] - L / 2)
            return self.z[i] - g1 * L / 2 + g1 * x + (g2 - g1) * x * x / (2.0 * L)
        k = min(max(bisect_right(self.sta, sta) - 1, 0), len(self.g) - 1)   # 범위 밖은 첫/끝 구배로 연장
        return self.z[k] + self.g[k] * (sta - self.sta[k])

    def grade_at(self, sta: float) -> float:
        i = self._curve_at(sta)
        if i is not None:
            L, g1, g2 = self.vc[i], self.g[i - 1], self.g[i]
            return g1 + (g2 - g1) * (sta - (self.sta[i] - L / 2)) / L
        return self.g[min(max(bisect_right(self.sta, sta) - 1, 0), len(self.g) - 1)]

    def breakpoints(self) -> list[float]:
        pts = []
        for i in range(1, len(self.sta) - 1):
            pts.extend([self.sta[i] - self.vc[i] / 2, self.sta[i] + self.vc[i] / 2] if self.vc[i] > 0 else [self.sta[i]])
        return pts


class CurvedAlignment(Alignment):
    """평면(HorizontalAlignment) + 종단(VerticalProfile) 으로 정의한 일반 선형"""

    def __init__(self, horizontal: HorizontalAlignment, vertical: VerticalProfile):
        self.horizontal, self.vertical = horizontal, vertical

    @property
    def start_station(self) -> float:
        return max(self.horizontal.start_station, self.vertical.start_station)

    @property
    def end_station(self) -> float:
        return min(self.horizontal.end_station, self.vertical.end_station)

    def point_at(self, station):
        return self.horizontal.point_at(station)

    def azimuth_at(self, station):
        return self.horizontal.azimuth_at(station)

    def curvature_at(self, station, h=0.01):
        return self.horizontal.curvature_at(station)

    def elevation_at(self, station):
        return self.vertical.elevation_at(station)

    def grade_at(self, station, h=0.01):
        return self.vertical.grade_at(station)

    def breakpoints(self):
        return sorted(set(self.horizontal.breakpoints()) | set(self.vertical.breakpoints()))

    def validate(self):
        if self.end_station - self.start_station <= 0:
            raise ValueError("평면 선형과 종단 선형의 측점 범위가 겹치지 않습니다")
