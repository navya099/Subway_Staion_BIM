from dataclasses import dataclass, field
from typing import List, Optional

from passages.passage_data import PassageData


@dataclass
class PassagePackage:
    """층별 출구통로 그룹 (level = 통로가 붙는 층)"""
    package_id: str = ""
    level: str = ""
    passages: List[PassageData] = field(default_factory=list)
    description: str = ""

    def add_passage(self, p: PassageData):
        self.passages.append(p)

    @property
    def total_count(self) -> int:
        return len(self.passages)

    def get_passage_by_name(self, name: str) -> Optional[PassageData]:
        return next((p for p in self.passages if p.name == name), None)
