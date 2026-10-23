from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PlatformShape(ABC):
    """
    공통 추상 승강장 형상 데이터 (선형 로컬 좌표: s = 진행방향, t = 직교방향)
    Attributes:
        length: 선형 진행(s) 방향 수평 길이 (m)
        width: 선형 직교(t) 방향 폭 (m)
        thickness: 연직 치수 (m) (슬래브는 두께, 지지벽체는 높이)
    """
    length: float = 0.0
    width: float = 0.0
    thickness: float = 0.0

    @property
    def vertical(self) -> float:
        """연직 치수 (슬래브는 두께, 지지벽체는 높이)"""
        return self.thickness

    @property
    @abstractmethod
    def volume(self) -> float:
        """승강장 부피 (자식 클래스에서 구현)"""
        pass
