from dataclasses import dataclass
import math


@dataclass
class AlignmentConfig:
    """선형 파라미터 데이터 클래스
        Attributes:
            bp_station: 선형 시작 측점
            bp_x: 시작 x좌표
            bp_y: 시작 y좌표
            bp_z: 시작 z좌표
            ep_x: 끝 x좌표
            ep_y: 끝 y좌표
            ep_z: 끝 z좌표
    """
    bp_station: float = 0.0
    bp_x: float = 286.4826         # 샘플 선형 (GUI 초기값도 동일)
    bp_y: float = -85.3896
    bp_z: float = 123.45
    ep_x: float = 575.9987
    ep_y: float = 437.4075
    ep_z: float = 134.45

    def validate(self):
        vals = (self.bp_station, self.bp_x, self.bp_y, self.bp_z, self.ep_x, self.ep_y, self.ep_z)
        if not all(math.isfinite(v) for v in vals):
            raise ValueError("선형 제원에 유한하지 않은 숫자가 있습니다")
        if self.length <= 0:
            raise ValueError("선형 시작점(BP)과 끝점(EP)의 평면 좌표가 같습니다. 선형 방향을 정할 수 없어요")

    @property
    def length(self) -> float:
        """선형의 수평 총 연장 (m) 계산"""
        dx = self.ep_x - self.bp_x
        dy = self.ep_y - self.bp_y
        return math.hypot(dx, dy)

    @property
    def theta(self):
        """선형 방위각(theta) 계산"""
        dx = self.ep_x - self.bp_x
        dy = self.ep_y - self.bp_y

        return math.atan2(dy, dx)  # 라디안 방위각

    @property
    def slope(self) -> float:
        """선형 구배 (‰, 퍼밀) 계산
           - (종점 표고 - 시점 표고) / 수평 연장 * 1000
        """
        l = self.length
        if l == 0.0:
            return 0.0
        return ((self.ep_z - self.bp_z) / l) * 1000.0

    @property
    def slope_permil(self) -> float:
        return self.slope

    def origin_at(self, station: float) -> tuple[float, float]:
        """선형 위 특정 (절대) 측점의 WCS 평면 좌표"""
        d = station - self.bp_station
        th = self.theta
        return self.bp_x + d * math.cos(th), self.bp_y + d * math.sin(th)

    def calc_align_lv(self, station: float) -> float:
        """특정 측점(STA)에서의 선형 절대 표고(Z) 계산 (직선 구배 가정)"""
        l = self.length
        if l == 0.0:
            return self.bp_z

        # BP로부터의 거리 계산
        dist_from_bp = station - self.bp_station

        # 선형 구배를 반영한 표고 선형 보간
        # 표고 = 시점 표고 + (구배(‰) / 1000) * 거리
        return self.bp_z + (self.slope / 1000.0) * dist_from_bp
