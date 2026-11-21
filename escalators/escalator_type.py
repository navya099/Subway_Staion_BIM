from enum import Enum


class EscalatorPartKind(Enum):
    """에스컬레이터 구성 부재 (값 = IFC ObjectType 코드)"""
    TRUSS = "TRUSS"              # 트러스 외형 (상·하부 수평부 + 경사부)
    STEPS = "STEPS"              # 스텝 (평탄 스텝 + 경사 스텝)
    BALUSTRADE = "BALUSTRADE"    # 난간 패널 (좌/우)
    HANDRAIL = "HANDRAIL"        # 핸드레일 (좌/우)
    SKIRT = "SKIRT"              # 스커트 패널 (스텝 양옆, 좌/우) — 상세 2단계
    INNER_DECK = "INNER_DECK"    # 안쪽 데크 (스커트 위 ~ 유리, 좌/우)
    OUTER_DECK = "OUTER_DECK"    # 바깥 데크 (유리 ~ 트러스 바깥, 좌/우)
