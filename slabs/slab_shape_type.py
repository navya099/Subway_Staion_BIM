from enum import Enum


class SlabShapeType(Enum):
    """슬래브 형상 타입"""
    RECTANGLE = 0
    POLYGON = 1
    ETC = -1


class SlabKind(Enum):
    """슬래브 용도 (IFC IfcSlabTypeEnum 매핑: FLOOR→BASESLAB, MID→FLOOR, ROOF→ROOF)"""
    FLOOR = 0   # 바닥 슬래브 (최하층 하부)
    MID = 1     # 중간 슬래브
    ROOF = 2    # 천장 슬래브 (최상층 상부)
