from abc import abstractmethod, ABC
from dataclasses import dataclass
from columns.column_shape_type import ColumnShapeType
from walls.wall_shape_type import WallShapeType


@dataclass
class WallShape(ABC):
    """
    공통 추상 기둥 형상 데이터
    Attributes:
        wall_type: 객체 모양 타입
        width: 벽체 폭
        height: 벽체 높이
        length: 벽체 길이
    """
    wall_type: WallShapeType = WallShapeType.ETC
    width: float = 0.0
    height: float = 0.0
    length: float = 0.0

    @property
    @abstractmethod
    def volume(self) -> float:
        """벽체의 부피를 계산하는 추상 프로퍼티 (자식 클래스에서 반드시 구현해야 함)"""
        pass
