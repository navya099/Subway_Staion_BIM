import dataclasses


@dataclasses.dataclass
class StairSpec:
    """직선 계단 1개의 입력 제원 (정거장 로컬 좌표). 계단은 lower_floor 층에서 바로 위층까지 오른다.

    단수는 목표 단높이 상한(riser_max)으로 자동 결정하고(올림), 실제 단높이 = 실제 표고차 / 단수 로 고르게 맞춘다.
    한 런의 높이가 flight_rise_max 를 넘지 않도록 중간 계단참 개수를 자동으로 정하고, 단수는 런마다 고르게 나눈다.
    계단 맨 위에는 위층 바닥 높이의 디딤판 1개가 포함되고, 그 끝(마지막 챌판 + 단너비)에서 위층 슬래브와 맞닿는다.
    계단이 지나는 중간 슬래브(번호 = lower_floor)에는 머리 높이(headroom)가 부족한 구간부터 그 맞닿는 점까지 오프닝이 자동으로 뚫린다.
    구조(일체형): 디딤판 안쪽 모서리를 잇는 선 / 계단참 상면 아래로 연직 두께가 일정한 띠가 이어지고, 경사부와 계단참의
    상·하면은 같은 위치에서 꺾인다 (계단참 시작 쪽: 마지막 챌판 + 단너비, 끝 쪽: 다음 런 첫 챌판).

    Attributes:
        lower_floor: 계단이 시작되는 층 (1 = 최하층). 1 ~ 층수-1
        s_start: 첫 단(첫 챌판)이 시작되는 진행방향 위치 s (m, 내공 시점 기준)
        direction: 오르는 방향. +1 = 종점 방향(+s), -1 = 시점 방향(−s)
        t_center: 계단 중심의 선형 직교 방향 위치 (m, 선형 중심 0, 진행방향 왼쪽 +. 기둥·오프닝과 같은 좌표)
        width: 계단 폭 (m, t 방향)
        riser_max: 단높이 상한 (m). 단수 = 올림(층간 표고차 / riser_max)
        tread: 단너비 (m, 디딤판 수평 길이)
        flight_rise_max: 한 런(계단참 사이)의 높이 상한 (m)
        landing_len: 중간 계단참 길이 (m, 진행방향, 단너비 이상)
        waist_t: 계단 슬래브(허리) 두께 (m, 경사면에 직각). 구조 띠의 연직 두께 = waist_t / cos(경사각), 계단참도 같은 연직 두께
        headroom: 계단 위 최소 유효 높이 (m). 이보다 낮아지는 구간부터 위층 슬래브를 뚫는다
        name: 비우면 ST + 일련번호
    """
    lower_floor: int = 1
    s_start: float = 0.0
    direction: int = 1
    t_center: float = 0.0
    width: float = 2.0
    riser_max: float = 0.18
    tread: float = 0.30
    flight_rise_max: float = 3.0
    landing_len: float = 1.5
    waist_t: float = 0.2
    headroom: float = 2.1
    name: str = ""

    @property
    def t_lo(self) -> float:
        return self.t_center - self.width / 2.0

    @property
    def t_hi(self) -> float:
        return self.t_center + self.width / 2.0


def resolve_stair_names(specs: list) -> list[str]:
    """계단별 이름 (지정한 이름 우선, 없으면 ST + 일련번호). 중복 이름은 오류"""
    names = [sp.name.strip() or f"ST{i}" for i, sp in enumerate(specs, start=1)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"계단 이름이 중복됩니다: {', '.join(dup)}")
    return names
