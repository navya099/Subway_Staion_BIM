"""선형(Alignment) 인터페이스.

엔진·내보내기는 선형을 이 인터페이스로만 접근한다. 측점(STA) 하나를 주면 평면 좌표, 진행 방향, 표고, 구배를 돌려준다.
직선 + 일정 구배 구현(AlignmentConfig, HeadingAlignment)이 있고, 곡선/종곡선 선형은 이 인터페이스를 구현해 추가한다.
"""
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AlignmentFrame:
    """측점 하나에서의 선형 상태

    Attributes:
        station: 절대 측점 (m)
        x, y: 선형 중심의 WCS 평면 좌표
        z: 선형 표고
        theta: 진행 방향각 (rad, +X 기준 반시계 = atan2 규약). 직교(t) 방향은 진행 방향의 왼쪽(+90°)
        grade: 종단 구배 (m/m, 상향 +)
    """
    station: float
    x: float
    y: float
    z: float
    theta: float
    grade: float


class Alignment(ABC):
    """선형 인터페이스: 측점 → 좌표 / 방향 / 표고"""

    @property
    @abstractmethod
    def start_station(self) -> float:
        """선형이 정의된 시작 측점"""

    @property
    @abstractmethod
    def end_station(self) -> float:
        """선형이 정의된 끝 측점"""

    @abstractmethod
    def point_at(self, station: float) -> tuple[float, float]:
        """측점의 WCS 평면 좌표 (x, y)"""

    @abstractmethod
    def azimuth_at(self, station: float) -> float:
        """측점의 진행 방향각 (rad, +X 기준 반시계)"""

    @abstractmethod
    def elevation_at(self, station: float) -> float:
        """측점의 선형 표고"""

    @property
    def is_straight(self) -> bool:
        """평면 직선 + 일정 구배인가. True 이면 정거장 부재를 단일 강체 변환으로 배치할 수 있다.
        곡선/종곡선 선형은 False 로 두며, 부재를 측점 구간별로 나누는 배치 단계가 필요하다."""
        return False

    def grade_at(self, station: float, h: float = 0.01) -> float:
        """측점의 종단 구배 (m/m). 기본 구현은 표고의 중심 차분이며, 구현체가 해석해를 알면 재정의"""
        return (self.elevation_at(station + h) - self.elevation_at(station - h)) / (2.0 * h)

    def frame_at(self, station: float) -> AlignmentFrame:
        x, y = self.point_at(station)
        return AlignmentFrame(station, x, y, self.elevation_at(station), self.azimuth_at(station),
                              self.grade_at(station))

    def polyline_stations(self, step: float = 5.0) -> list[float]:
        """선형을 折線으로 그리기 위한 측점 목록. 직선은 양 끝점만, 그 외는 step 간격"""
        a, b = self.start_station, self.end_station
        if self.is_straight:
            return [a, b]
        n = max(1, math.ceil((b - a) / step))
        return [a + (b - a) * i / n for i in range(n + 1)]

    def validate(self):
        """선형 제원 검사 (구현체가 재정의)"""


@dataclass
class HeadingAlignment(Alignment):
    """시점 좌표 + 방향각 + 구배 + 연장으로 정의한 직선 선형 (BP/EP 좌표 대신 방향으로 입력할 때)

    Attributes:
        bp_station: 시점 측점
        bp_x, bp_y, bp_z: 시점의 좌표/표고
        heading_deg: 진행 방향각 (도, +X 기준 반시계)
        grade_permil: 종단 구배 (‰, 상향 +)
        length: 선형 연장 (m)
    """
    bp_station: float = 0.0
    bp_x: float = 0.0
    bp_y: float = 0.0
    bp_z: float = 0.0
    heading_deg: float = 0.0
    grade_permil: float = 0.0
    length: float = 100.0

    @property
    def start_station(self) -> float:
        return self.bp_station

    @property
    def end_station(self) -> float:
        return self.bp_station + self.length

    @property
    def is_straight(self) -> bool:
        return True

    def point_at(self, station):
        d, th = station - self.bp_station, math.radians(self.heading_deg)
        return self.bp_x + d * math.cos(th), self.bp_y + d * math.sin(th)

    def azimuth_at(self, station):
        return math.radians(self.heading_deg)

    def elevation_at(self, station):
        return self.bp_z + self.grade_permil / 1000.0 * (station - self.bp_station)

    def grade_at(self, station, h=0.01):
        return self.grade_permil / 1000.0

    def validate(self):
        vals = (self.bp_station, self.bp_x, self.bp_y, self.bp_z, self.heading_deg, self.grade_permil, self.length)
        if not all(math.isfinite(v) for v in vals):
            raise ValueError("선형 제원에 유한하지 않은 숫자가 있습니다")
        if self.length <= 0:
            raise ValueError("선형 연장은 0보다 커야 합니다")
