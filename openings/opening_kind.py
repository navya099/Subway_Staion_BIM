from enum import Enum


class OpeningKind(Enum):
    """슬래브 오프닝 용도 (값 = (코드, 한글명))"""
    STAIR = ("STAIR", "계단")
    ESCALATOR = ("ESC", "에스컬레이터")
    ELEVATOR = ("ELEV", "엘리베이터")
    VENT = ("VENT", "환기·설비")

    @property
    def code(self) -> str:
        return self.value[0]

    @property
    def label(self) -> str:
        return self.value[1]
