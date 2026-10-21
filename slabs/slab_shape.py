from abc import abstractmethod, ABC
from dataclasses import dataclass
from slabs.slab_shape_type import SlabShapeType


@dataclass
class SlabShape(ABC):
    """
    공통 추상 슬래브 형상 데이터 (선형 로컬 좌표: s = 진행방향, t = 직교방향)
    Attributes:
        slab_type: 객체 모양 타입
        length: 선형 진행(s) 방향 수평 길이 (m)
        width: 선형 직교(t) 방향 폭 (m)
        thickness: 연직 두께 (m)
    """
    slab_type: SlabShapeType = SlabShapeType.ETC
    length: float = 0.0
    width: float = 0.0
    thickness: float = 0.0

    @property
    @abstractmethod
    def volume(self) -> float:
        """슬래브 부피 (자식 클래스에서 구현)"""
        pass
