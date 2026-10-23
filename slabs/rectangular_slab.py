from dataclasses import dataclass
from slabs.slab_shape import SlabShape
from slabs.slab_shape_type import SlabShapeType


@dataclass
class RectangularSlab(SlabShape):
    """사각 슬래브 (종단구배를 따라 기울어진 평행사변형 단면 압출)
    Attributes:
        rise: s 시작점 대비 끝점의 표고 차 (m, 현 기준). 구배가 없으면 0
        curve_factor: 평면 곡선에서 부재 중심선 길이 / 선형(s) 길이 (직선이면 1.0)
    """
    slab_type: SlabShapeType = SlabShapeType.RECTANGLE
    rise: float = 0.0
    curve_factor: float = 1.0

    @property
    def volume(self) -> float:
        """부피 = 길이 * 폭 * 연직 두께 (평행사변형이라 구배와 무관)"""
        return self.length * self.width * self.thickness * self.curve_factor
