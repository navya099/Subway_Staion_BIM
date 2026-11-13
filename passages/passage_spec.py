import dataclasses


@dataclasses.dataclass
class PassageSpec:
    """출구통로 1개의 입력 제원. 본체 측벽에서 선형에 직각으로 나가는 직선 박스(첫 구간)와,
    필요하면 꺾임점에서 선형 접선 방향(+s/−s)으로 꺾이는 두 번째 직선 박스로 이루어진다 (L자).

    - 단면은 내공 기준: 내공 폭 × 내공 높이 + 벽·바닥·천장 두께. 상·하부 헌치는 각각 천장·바닥 슬래브에 포함
    - 첫 구간은 floor 층 외벽 바깥면(중심 STA s_center)에서 시작하고, 그 층 측벽에는 통로 내공 크기의 오프닝이 뚫린다
    - 통로 바닥 상면 = 그 층 FL (측벽 접합부), 구배(‰)로 끝까지 오르내림. 꺾임부(모서리 사각형)는 수평
    - 길이는 통로 중심선 기준: 첫 구간 = 외벽 바깥면 ~ 꺾임점(두 중심선의 교점), 두 번째 구간 = 꺾임점 ~ 끝. 끝단은 개방

    Attributes:
        floor: 통로가 붙는 층 (1 = 최하층)
        side: +1 = t 큰 쪽(진행방향 왼쪽), -1 = t 작은 쪽
        s_center: 통로 중심의 진행방향 위치 s (m, 내공 시점 기준)
        inner_width / inner_height: 내공 폭 / 높이 (m)
        wall_t / floor_t / roof_t: 벽 / 바닥 슬래브 / 천장 슬래브 두께 (m)
        top_haunch_w / top_haunch_h: 상부 헌치 수평 / 연직 크기 (m, 0 이면 없음)
        bottom_haunch_w / bottom_haunch_h: 하부 헌치 수평 / 연직 크기 (m, 0 이면 없음)
        length1: 첫 구간 길이 (m), length2: 꺾임 후 길이 (m, 0 이면 꺾임 없음)
        turn: 꺾이는 방향 +1 = 종점 방향(+s), -1 = 시점 방향(−s)
        grade_permil: 통로 구배 (‰, + 면 본체에서 멀어질수록 오름)
        name: 비우면 EX + 일련번호
    """
    floor: int = 1
    side: int = 1
    s_center: float = 0.0
    inner_width: float = 4.0
    inner_height: float = 3.0
    wall_t: float = 0.6
    floor_t: float = 0.6
    roof_t: float = 0.6
    top_haunch_w: float = 0.3
    top_haunch_h: float = 0.3
    bottom_haunch_w: float = 0.0
    bottom_haunch_h: float = 0.0
    length1: float = 15.0
    length2: float = 0.0
    turn: int = 1
    grade_permil: float = 0.0
    name: str = ""

    @property
    def half_in(self) -> float:
        return self.inner_width / 2.0

    @property
    def half_out(self) -> float:
        return self.inner_width / 2.0 + self.wall_t

    @property
    def bent(self) -> bool:
        return self.length2 > 0


def resolve_passage_names(specs: list) -> list[str]:
    """통로별 이름 (지정한 이름 우선, 없으면 EX + 일련번호). 중복 이름은 오류"""
    names = [sp.name.strip() or f"EX{i}" for i, sp in enumerate(specs, start=1)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"출구통로 이름이 중복됩니다: {', '.join(dup)}")
    return names
