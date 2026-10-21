from dataclasses import dataclass, field
from typing import List, Optional
from slabs.slab_data import SlabData


@dataclass
class SlabPackage:
    """
    층별 슬래브 그룹 데이터 패키지
    Attributes:
        package_id: 패키지 ID (예: "PKG_B1F_SLABS")
        level: 소속 층 (슬래브 상면이 속한 층. 바닥=최하층, 중간=위층, 천장=최상층)
        slabs: 패키지에 포함된 슬래브 데이터 리스트
    """
    package_id: str = ""
    level: str = ""
    slabs: List[SlabData] = field(default_factory=list)
    description: str = ""

    def add_slab(self, slab: SlabData):
        self.slabs.append(slab)

    @property
    def total_count(self) -> int:
        return len(self.slabs)

    @property
    def total_volume(self) -> float:
        return sum(s.shape.volume for s in self.slabs if s.shape)

    def get_slab_by_name(self, name: str) -> Optional[SlabData]:
        return next((s for s in self.slabs if s.name == name), None)
