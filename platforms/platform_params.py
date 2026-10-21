import dataclasses

from platforms.platform_type import PlatformType


@dataclasses.dataclass
class PlatformParameters:
    """승강장 파라메터 (GUI 초기값도 이 기본값을 그대로 사용)
    Attributes:
        track_spacing: 선로 간격 D (m) [하선: -D/2, 상선: +D/2]
        plat_offset: 선로 중심 ~ 승강장 끝단 거리 (m)
        plat_thick: 승강장 슬래브 두께 (m, 표준 200mm). 0이면 승강장 없음
        plat_height: 바닥 상단 기준 승강장 슬래브 하면 높이 (m) = 지지벽체 높이
        plat_type: 승강장 타입 (NORMAL = 상대식, ISLAND = 섬식(미지원))
        support_t: 승강장 지지벽체 두께 (m). ㅠ형 구조의 다리 두께이며 슬래브 양 끝(선로측/벽체측)에 맞춰 배치. 0이면 지지벽체 없음
    """
    track_spacing: float = 4.4
    plat_offset: float = 1.7
    plat_thick: float = 0.2
    plat_height: float = 1.1
    plat_type: PlatformType = PlatformType.NORMAL
    support_t: float = 0.3

    def validate(self):
        for label, v in (("선로 간격", self.track_spacing), ("승강장 끝단 거리", self.plat_offset),
                         ("승강장 슬래브 두께", self.plat_thick), ("승강장 높이", self.plat_height),
                         ("지지벽체 두께", self.support_t)):
            if not v >= 0:
                raise ValueError(f"{label}은(는) 0 이상이어야 합니다 ({v})")
        if not isinstance(self.plat_type, PlatformType):
            raise ValueError(f"승강장 타입이 올바르지 않습니다 ({self.plat_type!r})")
