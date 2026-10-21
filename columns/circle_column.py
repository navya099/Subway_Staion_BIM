from dataclasses import dataclass
import math
from columns.column_shape import ColumnShape
from columns.column_shape_type import ColumnShapeType


@dataclass
class CircleColumn(ColumnShape):
    """원기둥 객체 클래스
    Attributes:
        radius: 반지름
        column_type: 기둥 타입
    """
    # 1. 모든 인스턴스가 공유하는 고정값(클래스 변수)임을 명시하거나 default_factory 활용
    column_type: ColumnShapeType = ColumnShapeType.CIRCLE

    # 2. 반지름 속성 (부모 클래스의 필드 순서를 고려해 기본값 지정)
    radius: float = 0.0

    @property
    def half_s(self) -> float:
        return self.radius

    @property
    def half_t(self) -> float:
        return self.radius

    @property
    def volume(self) -> float:
        """원기둥의 부피 계산 (π * r² * h)"""
        # 부모 클래스(ColumnShape)에 height 속성이 정의되어 있다고 가정합니다.
        return math.pi * (self.radius ** 2) * self.height
