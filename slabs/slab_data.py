from dataclasses import dataclass, field
from typing import Optional
from bim_data.common_bim_data import CommonBIMData
from slabs.slab_shape import SlabShape
from slabs.slab_shape_type import SlabKind, SlabShapeType


@dataclass
class SlabData(CommonBIMData):
    """
    개별 슬래브 요소 데이터
    Attributes:
        kind: 용도 (바닥/중간/천장)
        shape_type: 모양
        shape: 오프닝을 뚫기 전 슬래브 전체 형상 (SlabShape 상속 클래스)
        slab_no: 슬래브 번호 (0 = 본체 바닥, i = i층/i+1층 사이 중간, 층수 = 본체 천장)
        pieces: 오프닝을 뺀 직사각형 조각 (오프닝이 없으면 빈 목록 = 슬래브 전체가 한 덩어리)
        openings: 이 슬래브를 뚫는 오프닝
    pos_x/pos_y: 슬래브 평면 중심 (s, t), pos_z: 중심 s 위치의 슬래브 하단 표고
    """
    kind: SlabKind = SlabKind.FLOOR
    shape_type: SlabShapeType = SlabShapeType.ETC
    shape: Optional[SlabShape] = None
    slab_no: int = 0
    pieces: list = field(default_factory=list)
    openings: list = field(default_factory=list)

    @property
    def members(self) -> list:
        """작도·내보내기 대상 덩어리: 오프닝이 있으면 조각들, 없으면 슬래브 전체"""
        return self.pieces if self.pieces else [self]

    @property
    def net_volume(self) -> float:
        """오프닝을 뺀 실제 부피"""
        return sum(m.shape.volume for m in self.members if m.shape)
