import dataclasses
import math


def _positive(value, label):
    if not value > 0:          # NaN 도 걸러냄
        raise ValueError(f"{label}은(는) 0보다 커야 합니다 ({value})")


@dataclasses.dataclass
class StationParameters:
    """정거장 제원 데이터 클래스 (GUI 초기값도 이 기본값을 그대로 사용)

    높이 기준: 본체 바닥 슬래브 상면 = 0. 층 높이는 '그 층 바닥 슬래브 상면 ~ 바로 위 슬래브 상면' (최상층은 천장 슬래브 상면까지)이고,
    층 높이의 합이 정거장 총 높이(바닥 슬래브 상면 ~ 천장 슬래브 상면)다. 각 층의 내공 높이 = 층 높이 − 위쪽 슬래브 두께.

    Attributes:
        start_station: 정거장 시작 측점
        length: 길이 (m)
        width: 폭 (m)
        offset: FL과 바닥 슬래브 OFFSET
        floor_heights: 층별 높이 (m), 최하층부터. 층수 = 개수
        wall_t: 외벽 두께 (m)
        floor_t: 본체 바닥 슬래브 두께 (m) (최하층 아래)
        mid_t: 중간층 바닥 슬래브 두께 (m) (층 사이의 슬래브, 층수 2 이상일 때)
        roof_t: 본체 천장 슬래브 두께 (m) (최상층 위)
        sta_tick: 평면도 측점 표기 간격 (m)
    """
    start_station: float = 0.0
    length: float = 200.0          # L (m)
    width: float = 20.0            # W (m)
    offset: float = 0.0            # 선형~바닥 상단 오프셋 (m)
    floor_heights: list = dataclasses.field(default_factory=lambda: [6.0, 6.0])   # 층별 높이 (m), 최하층부터
    wall_t: float = 1.0            # 외벽 두께 (m)
    floor_t: float = 1.2           # 본체 바닥 슬래브 두께 (m)
    mid_t: float = 1.0             # 중간층 바닥 슬래브 두께 (m)
    roof_t: float = 1.0            # 본체 천장 슬래브 두께 (m)
    sta_tick: float = 20.0         # 평면도 측점 표기 간격 (m)

    # ---------- 층 구성 (모든 엔진/내보내기가 이 메서드로만 높이를 계산한다) ----------
    @property
    def floors(self) -> int:
        return len(self.floor_heights)

    @property
    def height(self) -> float:
        """정거장 총 높이 H = 층 높이의 합 (본체 바닥 슬래브 상면 ~ 천장 슬래브 상면)"""
        return float(sum(self.floor_heights))

    def level_name(self, floor_n: int) -> str:
        """floor_n: 1 = 최하층"""
        return f"B{self.floors - floor_n + 1}F" if self.floors > 1 else f"{floor_n}F"

    def floor_level(self, floor_n: int) -> float:
        """층 floor_n 의 바닥 슬래브 상면 높이 (본체 바닥 슬래브 상면 = 0). floor_n = floors + 1 이면 천장 슬래브 상면 (= 총 높이)"""
        return float(sum(self.floor_heights[:floor_n - 1]))

    def slab_above_t(self, floor_n: int) -> float:
        """층 floor_n 바로 위 슬래브 두께 (최상층은 천장 슬래브)"""
        return self.mid_t if floor_n < self.floors else self.roof_t

    def clear_height(self, floor_n: int) -> float:
        """층 floor_n 의 내공 높이 = 층 높이 − 위쪽 슬래브 두께"""
        return self.floor_heights[floor_n - 1] - self.slab_above_t(floor_n)

    def validate(self):
        """제원이 물리적으로 말이 되는지 검사 (잘못되면 어떤 값인지 밝혀 ValueError)"""
        for label, v in (("정거장 길이", self.length), ("정거장 폭", self.width),
                         ("외벽 두께", self.wall_t), ("본체 바닥 슬래브 두께", self.floor_t),
                         ("중간층 바닥 슬래브 두께", self.mid_t), ("본체 천장 슬래브 두께", self.roof_t),
                         ("측점 표기 간격", self.sta_tick)):
            _positive(v, label)
        if not isinstance(self.floor_heights, (list, tuple)) or len(self.floor_heights) < 1:
            raise ValueError("층별 높이가 비어 있습니다. 층수는 1 이상이어야 합니다")
        for n, h in enumerate(self.floor_heights, start=1):
            _positive(h, f"{self.level_name(n)} 층 높이")
        if not (math.isfinite(self.start_station) and math.isfinite(self.offset)):
            raise ValueError("시작 측점/오프셋이 유한한 숫자가 아닙니다")
        if 2 * self.wall_t >= min(self.width, self.length):
            raise ValueError(f"외벽 두께({self.wall_t}m)의 2배가 정거장 폭({self.width}m) 또는 길이({self.length}m) 이상입니다")
        for n in range(1, self.floors + 1):
            if self.clear_height(n) <= 0:
                kind = "천장" if n == self.floors else "중간층 바닥"
                raise ValueError(f"{self.level_name(n)} 층 높이({self.floor_heights[n - 1]:g}m)가 위쪽 {kind} 슬래브 두께"
                                 f"({self.slab_above_t(n):g}m) 이하입니다. 층 높이나 슬래브 두께를 확인하세요")
