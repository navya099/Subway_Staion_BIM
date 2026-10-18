from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class BaseShape(ABC):
    """
    모든 BIM 부재 형상의 최상위 추상 클래스
    """
    @property
    @abstractmethod
    def volume(self) -> float:
        """모든 3D 부재는 자신의 부피(m³)를 계산하여 반환해야 함"""
        pass