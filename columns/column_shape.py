from abc import abstractmethod, ABC
from dataclasses import dataclass
from columns.column_shape_type import ColumnShapeType

@dataclass
class ColumnShape(ABC):
    """
    공통 추상 기둥 형상 데이터
    Attributes:
        column_type: 객체 모양 타입(원기둥, 사각기둥)
        height: 기둥 높이
    """
    column_type: ColumnShapeType = ColumnShapeType.ETC
    height: float = 0.0

    @property
    @abstractmethod
    def half_s(self) -> float:
        """선형 진행 방향 반폭 (m)"""

    @property
    @abstractmethod
    def half_t(self) -> float:
        """선형 직교 방향 반폭 (m)"""

    @property
    @abstractmethod
    def volume(self) -> float:
        """기둥의 부피를 계산하는 추상 프로퍼티 (자식 클래스에서 반드시 구현해야 함)"""
        pass
