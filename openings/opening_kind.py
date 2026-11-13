from enum import Enum


class OpeningKind(Enum):
    """슬래브 오프닝 용도 (값 = (코드, 한글명))"""
    STAIR = ("STAIR", "계단")
    ESCALATOR = ("ESC", "에스컬레이터")
    ELEVATOR = ("ELEV", "엘리베이터")
    VENT = ("VENT", "환기·설비")
    PASSAGE = ("PASSAGE", "출구통로")       # 본체 측벽 오프닝 (출구통로 접합부, 직접 입력 대상 아님)

    @property
    def code(self) -> str:
        return self.value[0]

    @property
    def label(self) -> str:
        return self.value[1]
