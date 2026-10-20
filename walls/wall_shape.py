from abc import abstractmethod, ABC
from dataclasses import dataclass
from walls.wall_shape_type import WallShapeType


@dataclass
class WallShape(ABC):
    """
    공통 추상 벽체 형상 데이터 (선형 로컬 좌표: s = 진행방향, t = 직교방향)
    Attributes:
        wall_type: 객체 모양 타입
        length: 선형 진행(s) 방향 수평 길이 (m)
        width: 선형 직교(t) 방향 치수 (m)  (측벽은 두께, 마감벽은 정거장 폭)
        height: 연직 높이 (m)
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
