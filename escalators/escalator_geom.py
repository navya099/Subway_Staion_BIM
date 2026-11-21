"""에스컬레이터 상세 기하 (1단계): 곡선 전이부가 있는 스텝 코 선 + 스텝 개별 형상·자세.

진행 좌표 u (하부 WP = 0, 오르는 방향 +), 표고 z 는 절대 표고.
- 스텝 코 선 N(u): 아래층 바닥면 → 하부 곡선 전이(반경 lower_radius, 오목) → 경사선 → 상부 곡선 전이(upper_radius, 볼록)
  → 위층 바닥면. 전이부는 WP 에서 만나는 두 직선(바닥면은 WP 에서의 기울기로 근사 — 종단구배)에 접하는 원호 (필렛).
- 스텝: 위 운행로만. 스텝 k 의 코(앞 = 아래쪽 끝) u_k = 첫 스텝 + k · 스텝 깊이(수평) — 코는 늘 N 위, 디딤판은 수평.
  애니메이션은 모든 스텝의 u 를 같은 만큼 옮기면 됨(`step_pose`). 형상 = 디딤판 판(두께 STEP_PLATE_T) + 앞 챌판 판
  (두께 STEP_RISER_T, 바로 아래 스텝 디딤판 높이 ~ 디딤판 하면) — 이웃 스텝과 겹치지 않음.
"""
import math
from dataclasses import dataclass, field

from escalators.escalator_spec import STEP_PLATE_T, STEP_RISER_T

TOL = 1e-9
ARC_STEP = 0.05          # 곡선 전이부 표본 간격 (u, m) — 띠 부재(트러스·난간)가 전이부를 따르는 정밀도


@dataclass
class NoseLine:
    """스텝 코 선 N(u). floor_lo(u) / floor_hi(u): 아래층·위층 바닥면 절대 표고 함수"""
    e0: float                     # 하부 WP 표고
    run: float                    # WP 간 수평 거리
    tan: float                    # 경사 tan
    floor_lo: object
    floor_hi: object
    r_lo: float = 0.0             # 하부 전이 반경 (0 = 꺾임)
    r_hi: float = 0.0             # 상부 전이 반경
    arcs: list = field(default_factory=list)      # [(u_a, u_b, 중심 u, 중심 z, 반경, 볼록(+1)/오목(−1))]

    def __post_init__(self):
        th = math.atan(self.tan)
        self.arcs = []
        if self.r_lo > TOL:
            g = math.atan(self._slope(self.floor_lo, 0.0))
            d = th - g
            tl = self.r_lo * math.tan(d / 2.0)
            ua, ub = -tl * math.cos(g), tl * math.cos(th)
            bx, bz = ub, self.e0 + ub * self.tan
            cx, cz = bx - self.r_lo * math.sin(th), bz + self.r_lo * math.cos(th)   # 중심은 위쪽 (오목)
            self.arcs.append((ua, ub, cx, cz, self.r_lo, -1))
        if self.r_hi > TOL:
            g = math.atan(self._slope(self.floor_hi, self.run))
            d = th - g
            tl = self.r_hi * math.tan(d / 2.0)
            uc, ud = self.run - tl * math.cos(th), self.run + tl * math.cos(g)
            bx, bz = uc, self.e0 + uc * self.tan
            cx, cz = bx + self.r_hi * math.sin(th), bz - self.r_hi * math.cos(th)   # 중심은 아래쪽 (볼록)
            self.arcs.append((uc, ud, cx, cz, self.r_hi, 1))
        if len(self.arcs) == 2 and self.arcs[0][1] > self.arcs[1][0] + TOL:
            raise ValueError("에스컬레이터 곡선 전이부(하부·상부 반경)가 경사부보다 길어 서로 겹칩니다 (반경을 줄이세요)")

    @staticmethod
    def _slope(f, u, h=0.5):
        return (f(u + h) - f(u - h)) / (2.0 * h)

    def __call__(self, u: float) -> float:
        for ua, ub, cx, cz, r, sign in self.arcs:
            if ua <= u <= ub:
                return cz + sign * math.sqrt(max(r * r - (u - cx) ** 2, 0.0))
        lo = self.arcs[0][0] if self.arcs and self.arcs[0][5] < 0 else 0.0
        hi = self.arcs[-1][1] if self.arcs and self.arcs[-1][5] > 0 else self.run
        if u <= lo:
            return self.floor_lo(u)
        if u >= hi:
            return self.floor_hi(u)
        return self.e0 + u * self.tan

    @property
    def u_flat_lo(self) -> float:
        """아래층 평탄부 끝 (하부 전이 시작, 전이가 없으면 하부 WP)"""
        return self.arcs[0][0] if self.arcs and self.arcs[0][5] < 0 else 0.0

    @property
    def u_flat_hi(self) -> float:
        """위층 평탄부 시작 (상부 전이 끝, 없으면 상부 WP)"""
        return self.arcs[-1][1] if self.arcs and self.arcs[-1][5] > 0 else self.run

    def breakpoints(self) -> list:
        """띠 부재가 꺾이는 u (WP, 전이부 표본)"""
        pts = {0.0, self.run}
        for ua, ub, *_ in self.arcs:
            n = max(2, int(math.ceil((ub - ua) / ARC_STEP)))
            pts |= {ua + (ub - ua) * i / n for i in range(n + 1)}
        return sorted(pts)


@dataclass
class StepLayout:
    """스텝 1개: index(아래에서 0), u = 코 위치(진행 좌표), z = 디딤판 윗면, rise = 바로 아래 스텝 디딤판과의 높이차,
    pieces = [(ua, ub, zb, zt)] 진행 좌표 사각형 (디딤판 판, 챌판 판)"""
    index: int
    u: float
    z: float
    rise: float
    pieces: list


def step_range(spec, nose: NoseLine) -> tuple:
    """스텝이 놓이는 u 범위 [첫 스텝 코, 마지막 스텝 디딤판 끝] — 평탄 스텝 수만큼 평탄부로 나감"""
    dep = spec.step_depth
    lo = nose.u_flat_lo - spec.lower_flat_steps * dep
    n = int(math.floor((nose.u_flat_hi + spec.upper_flat_steps * dep - lo) / dep + 1e-9))
    return lo, lo + n * dep, n


def step_pose(nose: NoseLine, u: float, dep: float) -> tuple:
    """코가 u 에 있는 스텝의 (디딤판 윗면, 아래 스텝과의 높이차) — 애니메이션 자세 함수"""
    z = nose(u)
    return z, max(0.0, z - nose(u - dep))


def step_pieces(u: float, z: float, rise: float, dep: float) -> list:
    """스텝 형상 (진행 좌표 사각형): 디딤판 판 [u, u + dep] × [z − 판 두께, z], 챌판 판 [u, u + 챌판 두께] × [z − rise, z − 판 두께]"""
    out = [(u, u + dep, z - STEP_PLATE_T, z)]
    if rise - STEP_PLATE_T > 1e-6:
        out.append((u, u + STEP_RISER_T, z - rise, z - STEP_PLATE_T))
    return out


def layout_steps(spec, nose: NoseLine) -> list:
    lo, hi, n = step_range(spec, nose)
    dep = spec.step_depth
    out = []
    for k in range(n):
        u = lo + k * dep
        z, rise = step_pose(nose, u, dep)
        if k == 0:
            rise = 0.0
        out.append(StepLayout(k, u, z, rise, step_pieces(u, z, rise, dep)))
    return out
