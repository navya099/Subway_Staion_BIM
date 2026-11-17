"""점자블록 입력: 공통 설정(블록 크기·자동 경고블록 위치) + 유도블록 경로.

- 점형(경고) 블록: 승강장 연단, 계단·에스컬레이터 시작·끝 앞, 엘리베이터 문 앞 (자동), 유도 경로의 시작·끝·꺾임 점
- 선형(유도) 블록: 유도 경로 (정거장 로컬 (s, t) 꼭짓점, 선분은 s 또는 t 방향만)
기본값은 일반값 예시이며 점자블록 탭에서 고친다 (실무 기준이 있으면 그 값으로).
"""
import dataclasses
from typing import Optional

WARNING = "warning"              # 점형 (경고)
GUIDE = "guide"                  # 선형 (유도)
KIND_LABEL = {WARNING: "점형", GUIDE: "선형"}


@dataclasses.dataclass
class TactilePathSpec:
    """유도블록 경로 1개. points = [(s, t)] 정거장 로컬 (블록 중심선), 선분은 s 방향(t 같음) 또는 t 방향(s 같음).
    width = 블록 띠 폭 (None = 공통 블록 크기). 시작·끝·꺾임 점은 점형(폭 × 폭), 그 사이는 선형"""
    floor: int = 1
    points: list = dataclasses.field(default_factory=list)
    width: Optional[float] = None
    name: str = ""


@dataclasses.dataclass
class TactileSettings:
    """점자블록 공통 설정. enabled: 생성 여부 (모델 기본은 끔 — 기존 출력 유지, GUI 는 켬)
    size: 블록 한 장 크기 (m, 정사각형 — 텍스처 반복 크기·유도 경로 기본 폭)
    block_t: 바닥 마감이 없는 곳에 놓는 블록 두께 (구조 바닥 위로 올라옴). 바닥 마감이 있으면 그 마감재를 대체 (같은 높이·두께)
    edge: 승강장 연단 경고블록 (최하층, 선로 쪽 끝단에서 edge_offset 떨어져 폭 edge_width, 승강장 전 길이)
    stair / escalator / elevator: 시작·끝(엘리베이터는 정지층 문) 앞 경고블록, *_clear = 계단 첫 챌판·트러스 끝·승강로 바깥면에서
    떨어진 거리, *_depth = 띠 깊이(진행방향). 계단·에스컬레이터 폭 = 계단 폭·트러스 외폭, 엘리베이터 폭 = 문 폭 + 2 × 블록 크기
    paths: 유도블록 경로 TactilePathSpec 목록"""
    enabled: bool = False
    size: float = 0.3
    block_t: float = 0.03
    edge: bool = True
    edge_offset: float = 0.6
    edge_width: float = 0.6
    stair: bool = True
    stair_clear: float = 0.3
    stair_depth: float = 0.6
    escalator: bool = True
    esc_clear: float = 0.3
    esc_depth: float = 0.6
    elevator: bool = True
    ev_clear: float = 0.3
    ev_depth: float = 0.6
    paths: list = dataclasses.field(default_factory=list)
