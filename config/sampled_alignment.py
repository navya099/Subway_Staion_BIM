"""좌표 목록(x, y, z)으로 정의된 선형. Bentley / Civil 3D 등 다른 프로그램에서 설계해 일정 간격으로 내보낸 선형용.

- 입력점을 이웃 점들의 국소 2차 회귀로 평활한 뒤 에르미트 보간한다. 좌표가 mm~cm 단위로 반올림돼 있어도
  방향(방위각)과 곡률, 구배에 잡음이 증폭되지 않으며, 잡음이 없는 좌표는 사실상 그대로(0.1mm 이내) 통과한다.
- 입력 좌표와 평활 곡선의 최대 차이는 `max_shift` 로 알 수 있고, 크면 경고한다.
- 측점은 평면 좌표 간 거리의 누적값 (선형 측점 = 평면 연장 규약)에 시작 측점을 더해 계산한다.
"""
import bisect
import math

from config.alignment import Alignment


def _wrap(d: float) -> float:
    return (d + math.pi) % (2.0 * math.pi) - math.pi


class SampledAlignment(Alignment):
    """x, y, z 좌표열 + 시작 측점으로 정의한 선형

    Attributes:
        smooth_m: 접선 평활 구간의 반폭 (m). 0 이면 평활 없이 인접 점의 중심 차분을 쓴다
        warnings: 입력 점검 중 발견한 주의 사항 (중복점 제거, 점 간격 등)
    """
    MAX_TURN = math.radians(30.0)     # 인접한 현 사이의 허용 방향 변화. 이보다 꺾이면 곡선 샘플링 좌표가 아니라고 봄
    MAX_GRADE = 0.5                   # 허용 구배 500‰. 이보다 급하면 단위/열 순서 오류로 봄
    SPARSE_SPACING = 10.0             # 이보다 점 간격이 크면 곡선 정확도가 낮다고 경고

    def __init__(self, xs, ys, zs, start_station: float = 0.0, smooth_m: float = 5.0, warnings=None, name: str = ""):
        self.warnings: list[str] = list(warnings or [])
        self.name = name
        if not (len(xs) == len(ys) == len(zs)):
            raise ValueError("x, y, z 좌표 개수가 다릅니다")
        if not all(math.isfinite(v) for v in (*xs, *ys, *zs, start_station, smooth_m)):
            raise ValueError("좌표에 유한하지 않은 숫자가 있습니다")
        if smooth_m < 0:
            raise ValueError("평활 구간은 0 이상이어야 합니다")
        self.smooth_m = float(smooth_m)

        # 평면 좌표가 같은 연속 중복점 제거 (측점이 늘지 않는 점)
        px, py, pz, dup = [xs[0]], [ys[0]], [zs[0]], 0
        for x, y, z in zip(xs[1:], ys[1:], zs[1:]):
            if math.hypot(x - px[-1], y - py[-1]) < 1e-6:
                dup += 1
                continue
            px.append(float(x)); py.append(float(y)); pz.append(float(z))
        if dup:
            self.warnings.append(f"평면 좌표가 같은 중복 점 {dup}개를 제거했습니다")
        n = len(px)
        if n < 3:
            raise ValueError(f"선형 좌표가 3점 이상 필요합니다 (중복 제거 후 {n}점)")
        self.x, self.y, self.z = px, py, pz

        # 누적 평면 거리
        self._sd = [0.0]
        for i in range(1, n):
            self._sd.append(self._sd[-1] + math.hypot(px[i] - px[i - 1], py[i] - py[i - 1]))
        self._start = float(start_station)
        self._check_shape()
        self._tx, self._ty, self._gz = self._fit()

    # ------------------------------------------------------------------ 입력 점검
    def _check_shape(self):
        sd, n = self._sd, len(self.x)
        for i in range(1, n - 1):
            a = math.atan2(self.y[i] - self.y[i - 1], self.x[i] - self.x[i - 1])
            b = math.atan2(self.y[i + 1] - self.y[i], self.x[i + 1] - self.x[i])
            turn = abs(_wrap(b - a))
            if turn > self.MAX_TURN:
                raise ValueError(
                    f"{i + 1}번째 점(x={self.x[i]:.3f}, y={self.y[i]:.3f})에서 진행 방향이 {math.degrees(turn):.0f}° 꺾입니다. "
                    "곡선 구간을 촘촘히 샘플링한 좌표가 아니거나(교점만 나열한 경우 등) 점 순서가 잘못되었을 수 있습니다")
        for i in range(1, n):
            h = sd[i] - sd[i - 1]
            g = abs(self.z[i] - self.z[i - 1]) / h
            if g > self.MAX_GRADE:
                raise ValueError(f"{i + 1}번째 점 부근 구배가 {g * 1000:.0f}‰ 입니다. 표고 단위나 열 순서(x, y, z)를 확인하세요")
        spacing = max(sd[i] - sd[i - 1] for i in range(1, n))
        if spacing > self.SPARSE_SPACING:
            self.warnings.append(f"점 간격이 최대 {spacing:.1f}m 입니다. 곡선 구간 정확도를 위해 1~5m 간격 좌표를 권장합니다")

    # ------------------------------------------------------------------ 국소 2차 회귀 평활
    def _fit(self):
        """각 점에서 반경 smooth_m 안의 점들에 2차 다항식을 최소제곱으로 맞춰 평활 위치, 단위 접선, 구배, 곡률을 구함"""
        sd, n = self._sd, len(self.x)
        sx, sy, sz, tx, ty, gz, kap = ([0.0] * n for _ in range(7))
        shift = sumsq = 0.0
        for i in range(n):
            lo = hi = i
            while lo > 0 and sd[i] - sd[lo - 1] <= self.smooth_m:
                lo -= 1
            while hi < n - 1 and sd[hi + 1] - sd[i] <= self.smooth_m:
                hi += 1
            while hi - lo + 1 < 3:                      # 최소 3점 (양 끝이나 성긴 좌표)
                if lo > 0:
                    lo -= 1
                if hi - lo + 1 < 3 and hi < n - 1:
                    hi += 1
            idx = range(lo, hi + 1)
            scale = max(abs(sd[j] - sd[i]) for j in idx)
            u = [(sd[j] - sd[i]) / scale for j in idx]
            S = [sum(v ** k for v in u) for k in range(5)]
            M = [[S[0], S[1], S[2]], [S[1], S[2], S[3]], [S[2], S[3], S[4]]]
            det = self._det3(M)

            def fit(vals):
                T = [sum(vals[j] * v ** k for j, v in zip(idx, u)) for k in range(3)]
                co = []
                for c in range(3):                     # 크래머 공식
                    Mc = [row[:] for row in M]
                    for r in range(3):
                        Mc[r][c] = T[r]
                    co.append(self._det3(Mc) / det)
                return co[0], co[1] / scale, 2.0 * co[2] / scale ** 2     # 값, 1차 도함수, 2차 도함수 (s 에 대해)
            (x0, x1, x2), (y0, y1, y2), (z0, z1, _) = fit(self.x), fit(self.y), fit(self.z)
            speed = math.hypot(x1, y1)
            sx[i], sy[i], sz[i] = x0, y0, z0
            tx[i], ty[i], gz[i] = x1 / speed, y1 / speed, z1
            kap[i] = (x1 * y2 - y1 * x2) / speed ** 3
            d = math.hypot(x0 - self.x[i], y0 - self.y[i], z0 - self.z[i])
            shift, sumsq = max(shift, d), sumsq + d * d
        self.raw_x, self.raw_y, self.raw_z = self.x, self.y, self.z
        self.x, self.y, self.z = sx, sy, sz
        self.max_shift = shift
        self.noise_rms = math.sqrt(sumsq / n)
        if shift > 0.05:
            self.warnings.append(f"입력 좌표가 평활 곡선에서 최대 {shift * 100:.1f}cm 벗어납니다. 좌표 잡음이 크거나 급한 꺾임이 있을 수 있습니다")
        elif self.noise_rms > 0.002 and self.smooth_m < 8.0:
            self.warnings.append(f"좌표 잡음(RMS {self.noise_rms * 1000:.1f}mm)이 큽니다. 좌표 소수점이 cm 단위로 거친 파일이면 "
                                 "평활 구간을 8~12m 로 늘리면 방향·곡률이 더 매끈해집니다")
        self._kappa = kap
        return tx, ty, gz

    @staticmethod
    def _det3(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

    # ------------------------------------------------------------------ Alignment 인터페이스
    @property
    def start_station(self) -> float:
        return self._start

    @property
    def end_station(self) -> float:
        return self._start + self._sd[-1]

    @property
    def point_count(self) -> int:
        return len(self.x)

    @property
    def max_spacing(self) -> float:
        return max(b - a for a, b in zip(self._sd, self._sd[1:]))

    def _locate(self, station):
        """(구간 번호, 구간 내 매개변수 t, 구간 길이 h). 범위 밖이면 구간 번호가 -1(시작 앞) / n-1(끝 뒤)"""
        s = station - self._start
        if s <= 0.0:
            return -1, s, 0.0
        if s >= self._sd[-1]:
            return len(self.x) - 1, s - self._sd[-1], 0.0
        i = min(bisect.bisect_right(self._sd, s) - 1, len(self.x) - 2)
        h = self._sd[i + 1] - self._sd[i]
        return i, (s - self._sd[i]) / h, h

    @staticmethod
    def _basis(t):
        t2, t3 = t * t, t * t * t
        return (2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t, -2 * t3 + 3 * t2, t3 - t2)

    @staticmethod
    def _dbasis(t):
        t2 = t * t
        return (6 * t2 - 6 * t, 3 * t2 - 4 * t + 1, -6 * t2 + 6 * t, 3 * t2 - 2 * t)

    def point_at(self, station):
        i, t, h = self._locate(station)
        if i == -1:
            return self.x[0] + self._tx[0] * t, self.y[0] + self._ty[0] * t
        if i == len(self.x) - 1:
            return self.x[i] + self._tx[i] * t, self.y[i] + self._ty[i] * t
        b = self._basis(t)
        return tuple(b[0] * v[i] + b[1] * h * m[i] + b[2] * v[i + 1] + b[3] * h * m[i + 1]
                     for v, m in ((self.x, self._tx), (self.y, self._ty)))

    def azimuth_at(self, station):
        i, t, h = self._locate(station)
        if i == -1:
            return math.atan2(self._ty[0], self._tx[0])
        if i == len(self.x) - 1:
            return math.atan2(self._ty[i], self._tx[i])
        d = self._dbasis(t)
        dx = (d[0] * self.x[i] + d[2] * self.x[i + 1]) / h + d[1] * self._tx[i] + d[3] * self._tx[i + 1]
        dy = (d[0] * self.y[i] + d[2] * self.y[i + 1]) / h + d[1] * self._ty[i] + d[3] * self._ty[i + 1]
        return math.atan2(dy, dx)

    def elevation_at(self, station):
        i, t, h = self._locate(station)
        if i == -1:
            return self.z[0] + self._gz[0] * t
        if i == len(self.x) - 1:
            return self.z[i] + self._gz[i] * t
        b = self._basis(t)
        return b[0] * self.z[i] + b[1] * h * self._gz[i] + b[2] * self.z[i + 1] + b[3] * h * self._gz[i + 1]

    def grade_at(self, station, h=0.01):
        i, t, hh = self._locate(station)
        if i == -1:
            return self._gz[0]
        if i == len(self.x) - 1:
            return self._gz[i]
        d = self._dbasis(t)
        return (d[0] * self.z[i] + d[2] * self.z[i + 1]) / hh + d[1] * self._gz[i] + d[3] * self._gz[i + 1]

    def curvature_at(self, station, h=0.01):
        """평면 곡률 (1/m, 좌회전 +): 각 점의 2차 회귀 곡률을 측점 사이에서 선형 보간"""
        i, t, _ = self._locate(station)
        if i == -1:
            return self._kappa[0]
        if i == len(self.x) - 1:
            return self._kappa[i]
        return (1.0 - t) * self._kappa[i] + t * self._kappa[i + 1]

    def validate(self):
        if not (math.isfinite(self.start_station) and self.end_station > self.start_station):
            raise ValueError("선형 연장이 0 이하입니다")
