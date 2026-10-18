from dataclasses import dataclass
from walls.wall_shape import WallShape
from walls.wall_shape_type import WallShapeType


@dataclass
class RectangularWall(WallShape):
    """사각벽체 객체 클래스
    """

    wall_type: WallShapeType = WallShapeType.RECTANGLE

    @property
    def volume(self) -> float:
        """사각벽체의 부피 계산 (width * length * height)"""
        return self.width * self.length * self.height