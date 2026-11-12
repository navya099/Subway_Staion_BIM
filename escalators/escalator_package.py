from dataclasses import dataclass, field
from typing import List, Optional

from escalators.escalator_data import EscalatorData


@dataclass
class EscalatorPackage:
    """층별 에스컬레이터 그룹 (level = 시작 층)"""
    package_id: str = ""
    level: str = ""
    escalators: List[EscalatorData] = field(default_factory=list)
    description: str = ""

    def add_escalator(self, esc: EscalatorData):
        self.escalators.append(esc)

    @property
    def total_count(self) -> int:
        return len(self.escalators)

    def get_escalator_by_name(self, name: str) -> Optional[EscalatorData]:
        return next((e for e in self.escalators if e.name == name), None)
