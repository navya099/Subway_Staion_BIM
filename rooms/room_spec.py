import dataclasses

# 실 용도 기본 목록 (직접 입력도 가능). 나중에 용도별 기본 마감을 연결한다
ROOM_USES = ["대합실", "승강장층", "복도", "역무실", "기계실", "전기실", "통신실", "공조실", "화장실", "창고", "통로", "기타"]
PLATFORM_USE = "승강장층"
CONCOURSE_USE = "대합실"
DOOR_SIDES = ("+s", "-s", "+t", "-t")     # 문이 있는 실의 변: 종점 쪽 / 시점 쪽 / 왼쪽 / 오른쪽
# 문 종류 → IFC IfcDoor.OperationType
DOOR_KINDS = {"여닫이": "SINGLE_SWING_LEFT", "양개 여닫이": "DOUBLE_DOOR_SINGLE_SWING", "미닫이": "SLIDING_TO_LEFT",
              "방화문": "SINGLE_SWING_LEFT"}
PARTITION = "partition"      # 실 경계 = 칸막이벽 (공통 두께)
SEPARATION = "separation"    # 실 경계 = 구획분리 (두께 0 = 가상 경계선, > 0 = 얇은 실제 벽)
BOUNDARIES = (PARTITION, SEPARATION)


@dataclasses.dataclass
class DoorSpec:
    """실 경계 벽(칸막이벽·두께 있는 구획분리 벽)에 내는 문 1개.
    Attributes:
        side: 실의 어느 변 '+s' | '-s' | '+t' | '-t'
        center: 문 중심 위치 — ±s 변이면 t, ±t 변이면 s (정거장 로컬)
        width / height: 문 폭 / 높이 (개구부 크기, 바닥은 그 벽의 바닥)
        kind: DOOR_KINDS 의 하나 (여닫이 · 양개 여닫이 · 미닫이 · 방화문)
        name: 비우면 실 이름 + _D + 번호
    """
    side: str = "+t"
    center: float = 0.0
    width: float = 0.9
    height: float = 2.1
    kind: str = "여닫이"
    name: str = ""


@dataclasses.dataclass
class RoomSpec:
    """실(구획) 1개 = 한 층의 직사각형 영역 (정거장 로컬 좌표, 칸막이벽 중심선 기준).
    Attributes:
        floor: 층 번호 (1 = 최하층)
        use: 용도 (ROOM_USES 의 하나 또는 직접 입력한 이름)
        s0 / s1: 진행방향 범위 (내공 시점 기준 s, s0 < s1)
        t0 / t1: 직교방향 범위 (t, 왼쪽 +, t0 < t1)
        name: 비우면 용도 + 층 안 일련번호 (예: 역무실1)
        boundary: 경계 종류 — PARTITION(칸막이벽, 공통 두께) | SEPARATION(구획분리)
        sep_t: 구획분리 두께 (m). 0 = 두께 없는 가상 경계선(공간만 나눔), > 0 = 얇은 실제 벽
        doors: 이 실의 변에 내는 문 (DoorSpec). 그 변에 벽이 있어야 함 (본체 벽·가상 경계선은 불가)
    경계 중 본체 벽(내공면)이 아닌 변에는 칸막이벽/구획분리가 중심선에 맞춰 자동으로 선다.
    같은 선에서 겹치면 칸막이벽이 우선 (구획분리끼리는 두꺼운 쪽).
    """
    floor: int = 1
    use: str = "역무실"
    s0: float = 0.0
    s1: float = 10.0
    t0: float = 0.0
    t1: float = 5.0
    name: str = ""
    boundary: str = PARTITION
    sep_t: float = 0.0
    doors: list = dataclasses.field(default_factory=list)        # list[DoorSpec]

    @property
    def rect(self) -> tuple:
        return (self.s0, self.s1, self.t0, self.t1)

    @property
    def area(self) -> float:
        return (self.s1 - self.s0) * (self.t1 - self.t0)


@dataclasses.dataclass
class RoomSettings:
    """실 공통 설정.
    Attributes:
        default_uses: 층 번호 → 기본 실(입력한 실을 뺀 나머지 영역)의 용도. 없는 층은 최하층 = 승강장층, 그 위 = 대합실
        partition_t: 칸막이벽 두께 (m, 조적 기본 0.2)
        partition_material: 칸막이벽 재질 이름 (IFC 재질)
        separation_material: 구획분리 벽(두께 > 0) 재질 이름
    """
    default_uses: dict = dataclasses.field(default_factory=dict)
    partition_t: float = 0.2
    partition_material: str = "Masonry_Block"
    separation_material: str = "Separation_Panel"

    def default_use(self, floor: int) -> str:
        return self.default_uses.get(floor) or (PLATFORM_USE if floor == 1 else CONCOURSE_USE)
