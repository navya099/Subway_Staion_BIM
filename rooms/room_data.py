from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData


@dataclass
class RoomBox:
    """실 · 칸막이벽 조각의 형상: (s 길이) × (t 폭) × (연직 높이), 하면은 선형 종단을 따름 (helper.prism_member 규약)"""
    length: float = 0.0
    width: float = 0.0
    height: float = 0.0
    rise: float = 0.0                # 조각 양 끝 선형 표고차 (직선 IFC 압출용)
    curve_factor: float = 1.0

    @property
    def vertical(self) -> float:
        return self.height

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height * self.curve_factor


@dataclass
class RoomPiece:
    """각기둥 조각 1개 (pos_x/pos_y = s/t 중심, pos_z = pos_x 에서의 하면 절대 표고)"""
    name: str = ""
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    shape: RoomBox = field(default_factory=RoomBox)


@dataclass
class RoomData(CommonBIMData):
    """실(공간) 1개. IFC: IfcSpace (LongName = 용도). level = 층 이름
    Attributes:
        use: 용도, floor: 층 번호, is_default: 그 층의 기본 실(입력 실을 뺀 나머지)인가
        pieces: RoomPiece 목록 (바닥 ~ 위 슬래브 하면, 기본 실은 여러 조각)
    """
    use: str = ""
    floor: int = 1
    is_default: bool = False
    pieces: list = field(default_factory=list)

    @property
    def area(self) -> float:
        return sum(p.shape.length * p.shape.width * p.shape.curve_factor for p in self.pieces)

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.pieces)


@dataclass
class PartitionData(CommonBIMData):
    """칸막이벽 또는 구획분리 벽(두께 > 0) 1개 (실 경계의 한 직선). IFC: IfcWall(PARTITIONING)
    Attributes:
        floor: 층 번호, axis: 's' = s 방향으로 뻗음(t 일정), 't' = t 방향으로 뻗음
        kind: 'partition' (칸막이벽) | 'separation' (구획분리 벽), thickness: 두께
        pieces: RoomPiece 목록 (승강장 위·아래로 높이가 달라지면 나뉨)
    """
    floor: int = 1
    axis: str = "s"
    kind: str = "partition"
    thickness: float = 0.0
    pieces: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.pieces)


@dataclass
class SeparationLineData(CommonBIMData):
    """두께 없는 구획분리 경계선 (공간만 나눔). IFC: IfcVirtualElement (바닥 높이의 선)
    Attributes:
        floor: 층 번호, axis: 's' | 't', rect: (s0, s1, t0, t1) 한 방향 폭 0, z_rel: 층 FL (FL 기준)
    """
    floor: int = 1
    axis: str = "s"
    rect: tuple = (0.0, 0.0, 0.0, 0.0)
    z_rel: float = 0.0


@dataclass
class DoorData(CommonBIMData):
    """문 1개. IFC: IfcOpeningElement(벽 개구부, IfcRelVoidsElement → 벽) + IfcDoor(닫힌 문짝, IfcRelFillsElement → 개구부)
    Attributes:
        room / wall: 문을 정의한 실 이름 / 개구부가 난 벽 이름
        floor, side: 층 번호, 실의 변 (열림 방향 = 실 안쪽)
        kind / operation: 문 종류 (여닫이·양개 여닫이·미닫이·방화문) / IFC OperationType
        width / height: 개구부 폭 / 높이
        opening / leaf: RoomPiece (개구부 상자 = 벽 두께 전체, 문짝 = 두께 0.05)
        wall_t: 벽 두께
    """
    room: str = ""
    wall: str = ""
    floor: int = 1
    side: str = "+t"
    kind: str = "여닫이"
    operation: str = "SINGLE_SWING_LEFT"
    width: float = 0.9
    height: float = 2.1
    wall_t: float = 0.2
    opening: object = None
    leaf: object = None
