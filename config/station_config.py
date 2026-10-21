import dataclasses
import math


def _positive(value, label):
    if not value > 0:          # NaN 도 걸러냄
        raise ValueError(f"{label}은(는) 0보다 커야 합니다 ({value})")


@dataclasses.dataclass
class StationParameters:
    """정거장 제원 데이터 클래스 (GUI 초기값도 이 기본값을 그대로 사용)
    Attributes:
        start_station: 정거장 시작 측점
        length: 길이 (m)
        width: 폭 (m)
        offset: FL과 바닥 슬래브 OFFSET
        height: 내부 높이 H (m)
        floors: 층수
        wall_t: 외벽 두께 (m)
        floor_t: 바닥 슬래브 두께 (m)
        slab_t: 천장/중간 슬래브 두께 (m)
        sta_tick: 평면도 측점 표기 간격 (m)
    """
    start_station: float = 0.0
    length: float = 200.0          # L (m)
    width: float = 20.0            # W (m)
    offset: float = 0.0            # 선형~바닥 상단 오프셋 (m)
    height: float = 12.0           # 내부 높이 H (m)
    floors: int = 2                # 층수
    wall_t: float = 1.0            # 외벽 두께 (m)
    floor_t: float = 1.2           # 바닥 슬래브 두께 (m)
    slab_t: float = 1.0            # 천장/중간 슬래브 두께 (m)
    sta_tick: float = 20.0         # 평면도 측점 표기 간격 (m)

    def validate(self):
        """제원이 물리적으로 말이 되는지 검사 (잘못되면 어떤 값인지 밝혀 ValueError)"""
        for label, v in (("정거장 길이", self.length), ("정거장 폭", self.width), ("정거장 총 높이", self.height),
                         ("외벽 두께", self.wall_t), ("바닥 슬래브 두께", self.floor_t),
                         ("천장/중간 슬래브 두께", self.slab_t), ("측점 표기 간격", self.sta_tick)):
            _positive(v, label)
        if int(self.floors) != self.floors or self.floors < 1:
            raise ValueError(f"층수는 1 이상의 정수여야 합니다 ({self.floors})")
        if not (math.isfinite(self.start_station) and math.isfinite(self.offset)):
            raise ValueError("시작 측점/오프셋이 유한한 숫자가 아닙니다")
        if 2 * self.wall_t >= min(self.width, self.length):
            raise ValueError(f"외벽 두께({self.wall_t}m)의 2배가 정거장 폭({self.width}m) 또는 길이({self.length}m) 이상입니다")
        if self.height / self.floors <= self.slab_t:
            raise ValueError(f"층 높이({self.height / self.floors:.2f}m)가 천장/중간 슬래브 두께({self.slab_t}m) 이하입니다. "
                             "총 높이/층수/슬래브 두께를 확인하세요")
