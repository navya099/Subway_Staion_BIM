"""
캐드 관련 속성 config
레이어, 색상 등
"""

# DXF 레이어 스타일 정의
LAYER_DEFINITIONS = {
    "ALIGNMENT_CL": {"color": 1},  # 적색
    "STRUCT_WALL": {"color": 3},    # 녹색
    "STRUCT_SLAB": {"color": 5},    # 파란색
    "STRUCT_PLATFORM": {"color": 2}, # 승강장 레이어 (황색)
    "SEC_OUTLINE": {"color": 7},    # 흰색
    "SEC_CONCRETE": {"color": 4},   # 청색
    "SEC_PLATFORM": {"color": 2},    # 단면 승강장
    "SEC_CENTER": {"color": 1},     # 적색
    "SEC_TEXT": {"color": 2},       # 황색
    "SEC_HATCH": {"color": 8},      # 회색
    "PLAN_OUTLINE": {"color": 7},
    "PLAN_CENTER": {"color": 1},
    "PLAN_TEXT": {"color": 2},
    "PLAN_SECTION_LINE": {"color": 3},
    "PROF_CONCRETE": {"color": 4},
    "PROF_CENTER": {"color": 1},
    "PROF_TEXT": {"color": 2},
    "PROF_HATCH": {"color": 8},
    "STRUCT_COLUMN": {"color": 3},
    "SEC_BEYOND": {"color": 8},     # 횡단면도의 절단되지 않고 보이는 부재 (기둥)
    "PROF_BEYOND": {"color": 8},    # 종단면도의 절단되지 않고 보이는 부재 (승강장, 측면 기둥, 측면 계단)
    "STRUCT_STAIR": {"color": 6},   # 계단 (자홍색)
    "PLAN_STAIR": {"color": 6},     # 평면도 계단 디딤판·계단참
    "STRUCT_ESCALATOR": {"color": 30},   # 에스컬레이터 (주황)
    "SEC_ESCALATOR": {"color": 30},      # 횡단면도 에스컬레이터 절단면
    "PROF_ESCALATOR": {"color": 30},     # 종단면도 에스컬레이터 절단면
    "PLAN_ESCALATOR": {"color": 30},     # 평면도 에스컬레이터
    "STRUCT_PASSAGE": {"color": 140},    # 출구통로 (하늘색)
    "PLAN_PASSAGE": {"color": 140},      # 평면도 출구통로 벽
    "STRUCT_ENTRANCE": {"color": 170},   # 출입구 (박스·계단·에스컬레이터)

}