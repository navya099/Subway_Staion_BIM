from dataclasses import dataclass
from columns.column_shape import ColumnShape
from columns.column_shape_type import ColumnShapeType

@dataclass
class RectangularColumn(ColumnShape):
    """사각기둥 객체 클래스
    Attributes:
        column_type: 객체타입
        width: 선형 진행 방향 폭
        depth: 선형 직교 방향 두께
    """

    column_type: ColumnShapeType = ColumnShapeType.RECTANGLE
    width: float = 0.0   # 선형 진행 방향 폭
    depth: float = 0.0   # 선형 직교 방향 두께

    @property
    def half_s(self) -> float:
        return self.width / 2.0

    @property
    def half_t(self) -> float:
        return self.depth / 2.0

    @property
    def volume(self) -> float:
        """사각기둥의 부피 계산 (width * depth * height)"""
        return self.width * self.depth * self.height