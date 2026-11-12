from dataclasses import dataclass, field
from typing import List, Optional

from stairs.stair_data import StairData


@dataclass
class StairPackage:
    """층별 계단 그룹 (level = 계단이 시작되는 층)"""
    package_id: str = ""
    level: str = ""
    stairs: List[StairData] = field(default_factory=list)
    description: str = ""

    def add_stair(self, stair: StairData):
        self.stairs.append(stair)

    @property
    def total_count(self) -> int:
        return len(self.stairs)

    @property
    def total_volume(self) -> float:
        return sum(s.volume for s in self.stairs)

    def get_stair_by_name(self, name: str) -> Optional[StairData]:
        return next((s for s in self.stairs if s.name == name), None)
