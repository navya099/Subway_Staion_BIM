from dataclasses import dataclass, field
from typing import Optional
from bim_data.common_bim_data import CommonBIMData
from platforms.platform_shape import PlatformShape
from platforms.platform_type import PlatformPart, PlatformSide


@dataclass
class PlatformData(CommonBIMData):
    """
    개별 승강장 요소 데이터
    Attributes:
        part: 구성 부재 (슬래브 / 지지벽체)
        side: 좌/우 (상대식)
        shape: 실제 형상 객체 (PlatformShape 상속 클래스). 구멍을 뚫기 전 전체
        pieces: 구멍(에스컬레이터 피트)을 뺀 직사각형 조각 (구멍이 없으면 빈 목록)
        openings: 이 승강장 슬래브의 구멍 (OpeningData)
    pos_x/pos_y: 승강장 평면 중심 (s, t), pos_z: 중심 s 위치의 승강장 슬래브 하단 표고
    """
    part: PlatformPart = PlatformPart.SLAB
    side: PlatformSide = PlatformSide.LEFT
    shape: Optional[PlatformShape] = None
    pieces: list = field(default_factory=list)
    openings: list = field(default_factory=list)

    @property
    def members(self) -> list:
        """작도·내보내기 대상 덩어리: 구멍이 있으면 조각들, 없으면 전체"""
        return self.pieces if self.pieces else [self]

    @property
    def net_volume(self) -> float:
        return sum(m.shape.volume for m in self.members if m.shape)
