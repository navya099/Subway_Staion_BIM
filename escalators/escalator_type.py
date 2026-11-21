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
    FLOOR_PLATE = "FLOOR_PLATE"  # 승강구 바닥판 (스커트 안쪽, 상·하부) — 상세 4단계
    COMB = "COMB"                # 콤플레이트 (첫·끝 스텝 앞, 스커트 안쪽)
    OUTER_PLATE = "OUTER_PLATE"  # 승강구 바깥 덮개판 (스커트 바깥 ~ 트러스 바깥, 난간 끝 너머, 좌/우)
    NEWEL_BASE = "NEWEL_BASE"    # 뉴얼 받침 (핸드레일 고리 띠: 데크 높이 ~ 고리 아래 끝을 넘지 않게 둥글게 내려감, 좌/우)
    NEWEL_END_IN = "NEWEL_END_IN"    # 데크 끝 마무리 (스커트 안쪽 면 ~ 핸드레일 띠, 데크 높이에서 바닥까지 1/4 타원, 좌/우)
    NEWEL_END_OUT = "NEWEL_END_OUT"  # 데크 끝 마무리 (핸드레일 띠 ~ 트러스 바깥, 좌/우)
    CLAD_SIDE = "CLAD_SIDE"      # 트러스 옆 외장 패널 (좌/우)
    CLAD_BOTTOM = "CLAD_BOTTOM"  # 트러스 아래 외장 패널
