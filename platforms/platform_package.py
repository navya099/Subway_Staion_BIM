from dataclasses import dataclass, field
from typing import List, Optional
from platforms.platform_data import PlatformData


@dataclass
class PlatformPackage:
    """
    층별 승강장 그룹 데이터 패키지
    Attributes:
        package_id: 패키지 ID (예: "PKG_B3F_PLATFORMS")
        level: 소속 층 (승강장이 놓인 최하층)
        platforms: 승강장 부재(슬래브 + 지지벽체) 데이터 리스트
    """
    package_id: str = ""
    level: str = ""
    platforms: List[PlatformData] = field(default_factory=list)
    description: str = ""

    def add_platform(self, platform: PlatformData):
        self.platforms.append(platform)

    @property
    def total_count(self) -> int:
        return len(self.platforms)

    @property
    def total_volume(self) -> float:
        return sum(p.shape.volume for p in self.platforms if p.shape)

    def get_platform_by_name(self, name: str) -> Optional[PlatformData]:
        return next((p for p in self.platforms if p.name == name), None)
