import dataclasses
import math

@dataclasses.dataclass
class StationParameters:
    """정거장 제원 및 선형 파라미터 데이터 클래스"""
    length: float = 200.0          # L (m)
    width: float = 20.0            # W (m)
    base_level: float = 123.45     # 시점 표고 (m)
    slope_permil: float = 3    # 종단구배 (‰)
    offset: float = 0.0           # 선형~바닥 상단 오프셋 (m)
    height: float = 12.0           # 내부 높이 H (m)
    floors: int = 3                # 층수
    wall_t: float = 1           # 외벽 두께 (m)
    floor_t: float = 1.2          # 바닥 슬래브 두께 (m)
    slab_t: float = 0.4            # 천장/중간 슬래브 두께 (m)
    interval: float = 20.0         # 단면 추출 간격 (m)

    def calc_align_lv(self, x: float) -> float:
        """체인점(X)에서의 선형 절대 표고 계산"""
        return self.base_level + (self.slope_permil / 1000.0) * x


# DXF 레이어 스타일 정의
LAYER_DEFINITIONS = {
    "ALIGNMENT_CL": {"color": 1},  # 적색
    "STRUCT_WALL": {"color": 3},    # 녹색
    "STRUCT_SLAB": {"color": 5},    # 파란색
    "STRUCT_PLATFORM": {"color": 2}, # 승강장 레이어 (황색)
    "SEC_OUTLINE": {"color": 7},    # 흰색
    "SEC_CONCRETE": {"color": 4},   # 청색
    "SEC_PLATFORM": {"color": 2},    # 단면 승강장
    "SEC_CENTER": {"color": 1},     # 적색
    "SEC_TEXT": {"color": 2},       # 황색
    "SEC_HATCH": {"color": 8},      # 회색
    "PLAN_OUTLINE": {"color": 7},
    "PLAN_CENTER": {"color": 1},
    "PLAN_TEXT": {"color": 2},
    "PLAN_SECTION_LINE": {"color": 3},
    "PROF_CONCRETE": {"color": 4},
    "PROF_CENTER": {"color": 1},
    "PROF_TEXT": {"color": 2},
    "PROF_HATCH": {"color": 8},
    "STRUCT_COLUMN": {"color": 3}

}