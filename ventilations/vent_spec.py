import dataclasses
from typing import Optional


@dataclasses.dataclass
class VentSpec:
    """환기구 1개의 입력 제원. 출구통로와 같은 경로(중심선 폴리선) 입력에 연속박스(n련) 단면, 수직구, 끝 그릴.

    - 경로·접합부 규칙은 출구통로와 같다: 첫 꼭짓점 = floor 층 외벽 바깥면 위 접합점, 첫 구간은 본체에 직각,
      꼭짓점 높이(z) = 덕트 바닥 상면(첫 꼭짓점은 비우면 FL). 평면 꺾임은 임의 각도 연귀, 그 앞뒤는 수평.
      본체 측벽에는 칸마다 칸 크기의 오프닝이 뚫린다 (중벽 자리는 벽이 남음).
    - **수직 구간**: 평면 위치가 같고 높이만 다른 연속 두 꼭짓점 (위로만). 아래 덕트는 끝을 막고(끝 벽)
      천장 슬래브에 칸마다 구멍을 내어 그 위에 수직구를 세운다. 수직구 평면 = 아래 덕트 방향으로 깊이 shaft_depth,
      덕트와 같은 칸·중벽 배치, 수직 꼭짓점이 수직구 내공 중심. 수직구 위로 덕트가 이어지면(경로 중간)
      위 덕트는 아래 덕트와 평면에서 같은 선(같은 방향 또는 반대 방향)이어야 하고, 시작을 막고 바닥 슬래브에 구멍을 낸다.
      수직 구간 앞뒤 덕트 구간은 수평이어야 한다. 위 덕트의 바닥 높이 = 수직 구간 끝 꼭짓점 높이.
    - **그릴**(금속): 경로 마지막 끝면, 칸마다 1개 (테두리 + 일정 간격 살). 마지막이 수직구면 상단 수평 그릴
      (윗면 = 마지막 꼭짓점 높이), 덕트면 끝 단면의 연직 그릴(덕트 끝은 막지 않음).

    Attributes:
        floor: 환기구가 붙는 층 (1 = 최하층)
        path: passages.passage_spec.PathVertex 목록 (2개 이상, 출구통로와 같은 형식)
        cells: 련 수 (칸 개수, 1 이상. 실무 4~6련)
        cell_width / cell_height: 칸 내공 폭 / 높이 (m, 모든 칸 같음)
        wall_t / mid_wall_t: 바깥 벽 / 칸 사이 중벽 두께 (m). 수직구의 앞·뒤 벽도 wall_t
        floor_t / roof_t: 바닥 / 천장 슬래브 두께 (m)
        haunch_w / haunch_h: 칸마다 상부 헌치 수평 / 연직 크기 (m, 0 이면 없음)
        shaft_depth: 수직구 칸 내공 깊이 (아래 덕트 방향, m). None 이면 cell_height (덕트 단면을 눕힌 크기)
        grill_t / grill_frame / grill_bar / grill_gap: 그릴 두께, 테두리 폭, 살 폭, 살 사이 간격 (m)
        name: 비우면 VS + 일련번호
    """
    floor: int = 1
    path: list = dataclasses.field(default_factory=list)
    cells: int = 4
    cell_width: float = 2.5
    cell_height: float = 3.0
    wall_t: float = 0.6
    mid_wall_t: float = 0.4
    floor_t: float = 0.6
    roof_t: float = 0.6
    haunch_w: float = 0.3
    haunch_h: float = 0.3
    shaft_depth: Optional[float] = None
    grill_t: float = 0.1
    grill_frame: float = 0.1
    grill_bar: float = 0.03
    grill_gap: float = 0.1
    name: str = ""

    @property
    def inner_width(self) -> float:
        """연속박스 내공 전체 폭 = 칸 폭 × 련 수 + 중벽 × (련 수 − 1)"""
        return self.cells * self.cell_width + (self.cells - 1) * self.mid_wall_t

    @property
    def half_in(self) -> float:
        return self.inner_width / 2.0

    @property
    def half_out(self) -> float:
        return self.half_in + self.wall_t

    @property
    def depth(self) -> float:
        return self.cell_height if self.shaft_depth is None else self.shaft_depth

    def cell_ranges(self) -> list:
        """칸별 v 구간 (v = 진행방향 왼쪽 +, 오른쪽(−v) 칸부터)"""
        a, step = self.half_in, self.cell_width + self.mid_wall_t
        return [(-a + k * step, -a + k * step + self.cell_width) for k in range(self.cells)]

    def mid_ranges(self) -> list:
        """중벽별 v 구간"""
        return [(hi, hi + self.mid_wall_t) for _, hi in self.cell_ranges()[:-1]]

    def solid_ranges(self) -> list:
        """벽이 있는 v 구간 (바깥 벽 + 중벽) — 수직구 아래·위 슬래브에서 구멍 사이에 남는 띠"""
        a, b = self.half_in, self.half_out
        return [(-b, -a)] + self.mid_ranges() + [(a, b)]


def resolve_vent_names(specs: list) -> list[str]:
    """환기구별 이름 (지정한 이름 우선, 없으면 VS + 일련번호). 중복 이름은 오류"""
    names = [sp.name.strip() or f"VS{i}" for i, sp in enumerate(specs, start=1)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"환기구 이름이 중복됩니다: {', '.join(dup)}")
    return names
