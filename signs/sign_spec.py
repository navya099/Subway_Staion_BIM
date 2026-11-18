"""역명판·안내사인 입력.

- StationInfo: 이 역의 이름(한글·영문·한자·일문)·역번호·노선색 + 양쪽(+s / −s 방향) 이웃 역
  (승강장마다 열차 진행방향이 달라 '다음 역'은 그 선로의 진행방향 쪽 이웃 역)
- 역명판: 승강장 뒤 본체 측벽(승강장 쪽 면, 마감이 있으면 마감 표면)에 일정 간격, 이미지 = 역명판 스타일(nameplate.py)
- 안내사인(천장 매달림): 대합실의 '타는 곳'(승강장으로 내려가는 계단·에스컬레이터 입구 위), '출구'(출구통로 입구 앞)
기본 치수·색은 일반값 예시이며 15.사인 탭에서 고친다.
"""
import dataclasses


@dataclasses.dataclass
class StationRef:
    """이웃 역 (비우면 없음 — 종착역)"""
    kname: str = ""
    ename: str = ""
    cname: str = ""
    no: str = ""


@dataclasses.dataclass
class StationInfo:
    kname: str = "정거장"
    ename: str = "Station"
    cname: str = ""
    jname: str = ""
    no: str = ""
    rgb: str = "#0052A4"                     # 노선색
    plus: StationRef = dataclasses.field(default_factory=StationRef)    # +s 방향(종점 쪽) 이웃 역
    minus: StationRef = dataclasses.field(default_factory=StationRef)   # −s 방향(시점 쪽) 이웃 역


@dataclasses.dataclass
class ExitInfo:
    """출구 안내: passage = 출구통로 이름, number = 출구 번호(비우면 통로 순번), destinations = 목적지 (줄바꿈 구분)"""
    passage: str = ""
    number: str = ""
    destinations: str = ""


@dataclasses.dataclass
class SignSettings:
    """enabled: 생성 여부 (모델 기본 끔, GUI 는 켬)
    style: 역명판 스타일 이름 (nameplate.STYLES), plate_interval: 역명판 간격 (m, 승강장 가운데 기준 대칭),
    plate_bottom: 역명판 하단 높이 (승강장 바닥 마감면 기준), plate_h: 역명판 높이 (폭 = 이미지 비율), plate_t: 두께
    boarding: 타는 곳 사인, dest_l / dest_r: 왼쪽(+t) / 오른쪽(−t) 선로 '방면' 문구
    exits: 출구 사인, exit_info: 출구통로별 출구 번호·목적지 (없는 통로는 순번)
    hang_bottom: 매달림 사인 하단 높이 (그 층 바닥 마감면 기준), hang_w / hang_h / hang_t: 매달림 사인 크기,
    hang_offset: 계단·에스컬레이터 도착 끝 / 측벽 면에서 사인까지 거리"""
    enabled: bool = False
    station: StationInfo = dataclasses.field(default_factory=StationInfo)
    style: str = "seoul"
    plate_interval: float = 40.0
    plate_bottom: float = 2.0
    plate_h: float = 0.8
    plate_t: float = 0.05
    boarding: bool = True
    dest_l: str = ""
    dest_r: str = ""
    exits: bool = True
    exit_info: list = dataclasses.field(default_factory=list)
    hang_bottom: float = 2.5
    hang_w: float = 2.4
    hang_h: float = 0.45
    hang_t: float = 0.1
    hang_offset: float = 1.5
