from dataclasses import dataclass
from platforms.platform_shape import PlatformShape


@dataclass
class RectangularPlatform(PlatformShape):
    """사각 승강장 슬래브 (종단구배를 따라 기울어진 평행사변형 단면 압출)
    Attributes:
        rise: s 시작점 대비 끝점의 표고 차 (m). 구배가 없으면 0
    """
    rise: float = 0.0

    @property
    def volume(self) -> float:
        """부피 = 길이 * 폭 * 연직 두께 (평행사변형이라 구배와 무관)"""
        return self.length * self.width * self.thickness
