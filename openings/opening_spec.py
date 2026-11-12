import dataclasses

from openings.opening_kind import OpeningKind


@dataclasses.dataclass
class OpeningSpec:
    """슬래브 오프닝 1개의 입력 제원 (항상 직사각형, 정거장 로컬 좌표)
    Attributes:
        kind: 용도 (계단 / 에스컬레이터 / 엘리베이터 / 환기·설비)
        s_start: 내공 시점(s=0, 시점 마감벽 안쪽 면)에서 오프닝 시작까지의 진행방향 거리 (m)
        length: 선형 진행(s) 방향 길이 (m)
        t_center: 오프닝 중심의 선형 직교 방향 위치 (m, 기둥 t_offset 과 같은 좌표, 선형 중심 0)
        width: 선형 직교(t) 방향 폭 (m)
        slabs: 뚫는 슬래브 번호 목록. 0 = 본체 바닥 슬래브, i = i층/i+1층 사이 중간 슬래브, 층수 = 본체 천장 슬래브
        name: 비우면 용도 코드 + 일련번호로 자동 부여 (예: ESC1)
    """
    kind: OpeningKind = OpeningKind.STAIR
    s_start: float = 0.0
    length: float = 1.0
    t_center: float = 0.0
    width: float = 1.0
    slabs: list = dataclasses.field(default_factory=list)
    name: str = ""

    @property
    def s_end(self) -> float:
        return self.s_start + self.length

    @property
    def t_lo(self) -> float:
        return self.t_center - self.width / 2.0

    @property
    def t_hi(self) -> float:
        return self.t_center + self.width / 2.0


def resolve_names(specs: list) -> list[str]:
    """오프닝별 이름 (지정한 이름 우선, 없으면 용도 코드 + 용도별 일련번호). 중복 이름은 오류"""
    counters, names = {}, []
    for sp in specs:
        counters[sp.kind] = counters.get(sp.kind, 0) + 1
        names.append(sp.name.strip() or f"{sp.kind.code}{counters[sp.kind]}")
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"오프닝 이름이 중복됩니다: {', '.join(dup)}")
    return names
