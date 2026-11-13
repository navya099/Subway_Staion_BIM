import dataclasses
from typing import Optional

STATION = "station"     # 선형 상대 좌표: (s, t) — s = 내공 시점 기준 진행방향 거리, t = 선형 중심에서 왼쪽 +
WORLD = "world"         # 절대 좌표: (X, Y) — 선형과 같은 평면 좌표계(WCS)
MODES = (STATION, WORLD)


@dataclasses.dataclass
class PathVertex:
    """통로 경로(중심선 폴리선)의 꼭짓점 1개. 꼭짓점마다 좌표 방식을 따로 정할 수 있다.

    Attributes:
        mode: STATION (선형 상대) 또는 WORLD (절대)
        x, y: STATION 이면 (s, t), WORLD 이면 (X, Y)
        z: 통로 바닥 상면 높이. STATION 이면 접합부(첫 꼭짓점) FL 기준 상대 높이, WORLD 이면 절대 표고(EL).
           첫 꼭짓점은 비우면(None) 접합부 FL 이고, 값을 주면 그 FL 과 같아야 한다.
    """
    mode: str = STATION
    x: float = 0.0
    y: float = 0.0
    z: Optional[float] = None


@dataclasses.dataclass
class PassageSpec:
    """출구통로 1개의 입력 제원. 경로(중심선 폴리선)를 따라가는 박스 구조물.

    - 첫 꼭짓점 = 본체 측벽 접합점: floor 층 외벽 바깥면 위에 있어야 하고, 첫 구간은 본체에 직각으로 나가야 한다.
      그 층 측벽에는 통로 내공 크기의 오프닝이 뚫리고, 첫 꼭짓점의 바닥 높이는 그 층 FL 이다.
    - 꼭짓점 사이는 직선(평면) + 바닥 높이 직선 보간: 높이가 같으면 수평, 다르면 경사.
      평면에서 일직선인 꼭짓점을 넣으면 경사가 바뀌는 점(경사 시작·끝)이 된다.
    - 평면에서 꺾이는 꼭짓점은 임의 각도(연귀 접합)이고, 그 앞뒤 구간은 수평이어야 한다 (꺾임부 수평참).
    - 단면은 내공 기준: 내공 폭 × 내공 높이 + 벽·바닥·천장 두께. 상·하부 헌치는 각각 천장·바닥 슬래브에 포함. 끝단은 개방.

    Attributes:
        floor: 통로가 붙는 층 (1 = 최하층)
        path: PathVertex 목록 (2개 이상)
        inner_width / inner_height: 내공 폭 / 높이 (m)
        wall_t / floor_t / roof_t: 벽 / 바닥 슬래브 / 천장 슬래브 두께 (m)
        top_haunch_w / top_haunch_h: 상부 헌치 수평 / 연직 크기 (m, 0 이면 없음)
        bottom_haunch_w / bottom_haunch_h: 하부 헌치 수평 / 연직 크기 (m, 0 이면 없음)
        name: 비우면 EX + 일련번호
    """
    floor: int = 1
    path: list = dataclasses.field(default_factory=list)
    inner_width: float = 4.0
    inner_height: float = 3.0
    wall_t: float = 0.6
    floor_t: float = 0.6
    roof_t: float = 0.6
    top_haunch_w: float = 0.3
    top_haunch_h: float = 0.3
    bottom_haunch_w: float = 0.0
    bottom_haunch_h: float = 0.0
    name: str = ""

    @property
    def half_in(self) -> float:
        return self.inner_width / 2.0

    @property
    def half_out(self) -> float:
        return self.inner_width / 2.0 + self.wall_t


def station_path(points: list) -> list:
    """[(s, t, z|None), ...] → 선형 상대 좌표 꼭짓점 목록 (테스트·코드 입력용)"""
    return [PathVertex(STATION, s, t, z) for s, t, z in points]


def world_path(points: list) -> list:
    """[(X, Y, EL|None), ...] → 절대 좌표 꼭짓점 목록"""
    return [PathVertex(WORLD, x, y, z) for x, y, z in points]


def resolve_passage_names(specs: list) -> list[str]:
    """통로별 이름 (지정한 이름 우선, 없으면 EX + 일련번호). 중복 이름은 오류"""
    names = [sp.name.strip() or f"EX{i}" for i, sp in enumerate(specs, start=1)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"출구통로 이름이 중복됩니다: {', '.join(dup)}")
    return names
