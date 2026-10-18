from dataclasses import dataclass, field
from typing import List, Optional
from walls.wall_data import WallData


@dataclass
class WallPackage:
    """
    층별/구역별 벽 요소 그룹 데이터 패키지
    Attributes:
        package_id: 패키지/그룹 ID (예: "PKG_B1F_COLUMNS")
        level: 소속 층 (예: "B1F", "B2F")
        walls: 패키지에 포함된 벽체 데이터 리스트
        description: 그룹 설명
    """
    package_id: str = ""
    level: str = ""
    walls: List[WallData] = field(default_factory=list)
    description: str = ""

    def add_wall(self, wall: WallData):
        """패키지에 벽체 객체 추가"""
        self.walls.append(wall)

    @property
    def total_count(self) -> int:
        """패키지 내 전체 벽체 개수"""
        return len(self.walls)

    @property
    def total_volume(self) -> float:
        """
        패키지 내 모든 벽체의 총 콘크리트 체적(m³) 산출
        (각 WallData의 shape.volume 연산 활용)
        """
        total = 0.0
        for w in self.walls:
            if w.shape and hasattr(w.shape, 'volume'):
                total += w.shape.volume
        return total

    def get_column_by_name(self, name: str) -> Optional[WallData]:
        """이름으로 개별 벽체 검색"""
        for w in self.walls:
            if w.name == name:
                return w
        return None