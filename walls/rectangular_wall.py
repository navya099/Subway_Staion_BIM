from dataclasses import dataclass
from walls.wall_shape import WallShape
from walls.wall_shape_type import WallShapeType


@dataclass
class RectangularWall(WallShape):
    """사각벽체 객체 클래스 (종단구배를 따라 기울어진 평행사변형 단면 압출)
    Attributes:
        rise: s 시작점 대비 끝점의 표고 차 (m). 구배가 없으면 0
    """

    wall_type: WallShapeType = WallShapeType.RECTANGLE
    rise: float = 0.0

    @property
    def volume(self) -> float:
        """부피 = 길이 * 폭 * 연직 높이 (평행사변형이라 구배와 무관)"""
        return self.width * self.length * self.height
