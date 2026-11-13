from enum import Enum


class EscalatorPartKind(Enum):
    """에스컬레이터 구성 부재 (값 = IFC ObjectType 코드)"""
    TRUSS = "TRUSS"              # 트러스 외형 (상·하부 수평부 + 경사부)
    STEPS = "STEPS"              # 스텝 (평탄 스텝 + 경사 스텝)
    BALUSTRADE = "BALUSTRADE"    # 난간 패널 (좌/우)
    HANDRAIL = "HANDRAIL"        # 핸드레일 (좌/우)
