import dataclasses
import math


DEFAULT_WALL_T = 1.0           # 외벽 두께 기본값 (m)


def _positive(value, label):
    if not value > 0:          # NaN 도 걸러냄
        raise ValueError(f"{label}은(는) 0보다 커야 합니다 ({value})")


@dataclasses.dataclass
class StationParameters:
    """정거장 제원 데이터 클래스 (GUI 초기값도 이 기본값을 그대로 사용)

    높이 기준: 본체 바닥 슬래브 상면 = 0. 층 높이는 '그 층 바닥 슬래브 상면 ~ 바로 위 슬래브 상면' (최상층은 천장 슬래브 상면까지)이고,
    층 높이의 합이 정거장 총 높이(바닥 슬래브 상면 ~ 천장 슬래브 상면)다. 각 층의 내공 높이 = 층 높이 − 위쪽 슬래브 두께.
    길이 L · 폭 W 는 벽체 **안쪽 면 사이(내공)** 치수이고 모든 층에서 고정이다 (s ∈ [0, L], t ∈ [−W/2, W/2] 이 내공 영역).
    외벽 두께는 층마다 다를 수 있으며, 벽은 내공 영역 바깥쪽으로 붙는다: 층 n 의 외곽 = 내공 + 양쪽 wall_t[n] 이라
    바깥면이 층마다 계단식으로 달라진다 (안쪽 면은 변하지 않음). 마감벽도 같은 두께로 s < 0 과 s > L 쪽에 붙는다.
    각 층의 외벽은 그 층의 층 높이 구간을 차지하며(최상층은 천장 슬래브 하면까지), 중간층 바닥 슬래브는 내공 영역 전체를 덮는다.
    본체 바닥 슬래브는 최하층 외곽, 본체 천장 슬래브는 최상층 외곽과 같은 범위다.

    Attributes:
        start_station: 정거장 시작 측점
        length: 내공 길이 (m): 시·종점 마감벽 안쪽 면 사이
        width: 내공 폭 (m): 좌·우 외벽 안쪽 면 사이
        offset: FL과 바닥 슬래브 OFFSET
        floor_heights: 층별 높이 (m), 최하층부터. 층수 = 개수
        wall_ts: 층별 외벽 두께 (m), 최하층부터 (측벽과 시·종점 마감벽에 같이 적용). 비워 두면 모든 층 DEFAULT_WALL_T
        floor_t: 본체 바닥 슬래브 두께 (m) (최하층 아래)
        mid_t: 중간층 바닥 슬래브 두께 (m) (층 사이의 슬래브, 층수 2 이상일 때)
        roof_t: 본체 천장 슬래브 두께 (m) (최상층 위)
        sta_tick: 평면도 측점 표기 간격 (m)
    """
    start_station: float = 0.0
    length: float = 200.0          # L (m) 내공 길이
    width: float = 18.0            # W (m) 내공 폭
    offset: float = 0.0            # 선형~바닥 상단 오프셋 (m)
    floor_heights: list = dataclasses.field(default_factory=lambda: [6.0, 6.0])   # 층별 높이 (m), 최하층부터
    wall_ts: list = dataclasses.field(default_factory=list)   # 층별 외벽 두께 (m), 최하층부터
    floor_t: float = 1.2           # 본체 바닥 슬래브 두께 (m)
    mid_t: float = 1.0             # 중간층 바닥 슬래브 두께 (m)
    roof_t: float = 1.0            # 본체 천장 슬래브 두께 (m)
    sta_tick: float = 20.0         # 평면도 측점 표기 간격 (m)

    def __post_init__(self):
        if not self.wall_ts:                    # 층별 외벽 두께를 주지 않으면 모든 층 기본 두께
            self.wall_ts = [DEFAULT_WALL_T] * len(self.floor_heights)

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

    def wall_t_at(self, floor_n: int) -> float:
        """층 floor_n 의 외벽 두께 (floor_n: 1 = 최하층)"""
        return self.wall_ts[floor_n - 1]

    @property
    def max_wall_t(self) -> float:
        return max(self.wall_ts)

    def outer_width(self, floor_n: int) -> float:
        """층 floor_n 의 외곽 폭 = 내공 폭 + 양쪽 외벽 두께"""
        return self.width + 2.0 * self.wall_t_at(floor_n)

    def outer_length(self, floor_n: int) -> float:
        """층 floor_n 의 외곽 길이 = 내공 길이 + 양쪽 마감벽 두께"""
        return self.length + 2.0 * self.wall_t_at(floor_n)

    def slab_above_t(self, floor_n: int) -> float:
        """층 floor_n 바로 위 슬래브 두께 (최상층은 천장 슬래브)"""
        return self.mid_t if floor_n < self.floors else self.roof_t

    def clear_height(self, floor_n: int) -> float:
        """층 floor_n 의 내공 높이 = 층 높이 − 위쪽 슬래브 두께"""
        return self.floor_heights[floor_n - 1] - self.slab_above_t(floor_n)

    def validate(self):
        """제원이 물리적으로 말이 되는지 검사 (잘못되면 어떤 값인지 밝혀 ValueError)"""
        for label, v in (("정거장 내공 길이", self.length), ("정거장 내공 폭", self.width),
                         ("본체 바닥 슬래브 두께", self.floor_t),
                         ("중간층 바닥 슬래브 두께", self.mid_t), ("본체 천장 슬래브 두께", self.roof_t),
                         ("측점 표기 간격", self.sta_tick)):
            _positive(v, label)
        if not isinstance(self.floor_heights, (list, tuple)) or len(self.floor_heights) < 1:
            raise ValueError("층별 높이가 비어 있습니다. 층수는 1 이상이어야 합니다")
        for n, h in enumerate(self.floor_heights, start=1):
            _positive(h, f"{self.level_name(n)} 층 높이")
        if not (math.isfinite(self.start_station) and math.isfinite(self.offset)):
            raise ValueError("시작 측점/오프셋이 유한한 숫자가 아닙니다")
        if len(self.wall_ts) != len(self.floor_heights):
            raise ValueError(f"층별 외벽 두께 개수({len(self.wall_ts)})가 층수({self.floors})와 다릅니다")
        for n, wt in enumerate(self.wall_ts, start=1):
            _positive(wt, f"{self.level_name(n)} 외벽 두께")
        for n in range(1, self.floors + 1):
            if self.clear_height(n) <= 0:
                kind = "천장" if n == self.floors else "중간층 바닥"
                raise ValueError(f"{self.level_name(n)} 층 높이({self.floor_heights[n - 1]:g}m)가 위쪽 {kind} 슬래브 두께"
                                 f"({self.slab_above_t(n):g}m) 이하입니다. 층 높이나 슬래브 두께를 확인하세요")
