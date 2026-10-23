from dataclasses import dataclass
from walls.wall_shape import WallShape
from walls.wall_shape_type import WallShapeType


@dataclass
class RectangularWall(WallShape):
    """사각벽체 객체 클래스 (종단구배를 따라 기울어진 평행사변형 단면 압출)
    Attributes:
        rise: s 시작점 대비 끝점의 표고 차 (m, 현 기준). 구배가 없으면 0
        curve_factor: 평면 곡선에서 부재 중심선 길이 / 선형(s) 길이. 직선이면 1.0 (정거장 중심선에서 t 만큼 떨어진 부재는
                      곡선 안쪽에서 짧고 바깥쪽에서 길어 체적이 달라짐)
    """

    wall_type: WallShapeType = WallShapeType.RECTANGLE
    rise: float = 0.0
    curve_factor: float = 1.0

    @property
    def volume(self) -> float:
        """부피 = 길이 * 폭 * 연직 높이 * 곡선 보정 (평행사변형이라 구배와 무관)"""
        return self.width * self.length * self.height * self.curve_factor
