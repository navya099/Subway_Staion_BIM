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
    "PLAN_BEYOND": {"color": 8},         # 평면도 본체 외곽(지상 평면)·절단면 위 지붕 윤곽
    "PROF_OUTER": {"color": 140},        # 종단면도에 투영한 본체 밖 구조물 (출구통로·출입구·외부 EV·환기구)
    "PLAN_PASSAGE": {"color": 140},      # 평면도 출구통로 벽
    "STRUCT_ENTRANCE": {"color": 170},   # 출입구 (박스·계단·에스컬레이터)
    "STRUCT_ELEVATOR_FRAME": {"color": 251},  # 투시형 엘리베이터 강관 기둥·가로재·금속 패널 띠
    "STRUCT_ELEVATOR_GLASS": {"color": 131},  # 투시형 엘리베이터 승강로 유리
    "STRUCT_CANOPY": {"color": 251},     # 출입구 캐노피 철골
    "STRUCT_CANOPY_GLASS": {"color": 131},   # 출입구 캐노피 유리
    "STRUCT_ELEVATOR": {"color": 150},   # 엘리베이터 승강로 (콘크리트)
    "STRUCT_ELEVATOR_CAR": {"color": 5},  # 엘리베이터 카
    "PLAN_ELEVATOR": {"color": 150},     # 평면도 엘리베이터 (승강로·X 표시·카)
    "SEC_ELEVATOR": {"color": 5},        # 단면도 엘리베이터 카
    "STRUCT_PARTITION": {"color": 52},   # 실 경계 칸막이벽
    "SEC_PARTITION": {"color": 52},      # 횡단면도 칸막이벽
    "PROF_PARTITION": {"color": 52},     # 종단면도 칸막이벽
    "PLAN_PARTITION": {"color": 52},     # 평면도 칸막이벽
    "PLAN_ROOM": {"color": 3},
    "FIN_FLOOR": {"color": 33},          # 바닥 마감재·채움
    "FIN_WALL": {"color": 43},           # 벽·기둥·승강로 마감
    "FIN_CEILING": {"color": 151},       # 천장판
    "FIN_FRAME": {"color": 8},           # 천장틀 (M/T바, 캐링 채널)
    "FIN_STAIR": {"color": 34},          # 계단 마감 (계단석 판석·통석·채움·논슬립·옆면)
    "STRUCT_SIGN": {"color": 8},         # 사인 본체 (역명판·매달림 사인)
    "STRUCT_SIGN_FACE": {"color": 5},    # 사인 이미지 면
    "SEC_SIGN": {"color": 5},            # 횡단·종단면도 사인
    "PLAN_SIGN": {"color": 5},           # 평면도 사인 + 문구
    "STRUCT_PSD": {"color": 252},        # 스크린도어 프레임·POST·구동부
    "STRUCT_PSD_GLASS": {"color": 151},  # 스크린도어 유리
    "SEC_PSD": {"color": 252},           # 횡단·종단면도 스크린도어
    "PLAN_PSD": {"color": 252},          # 평면도 스크린도어
    "STRUCT_RAILING": {"color": 254},    # 오프닝 유리난간 경계석·POST·레일
    "STRUCT_RAILING_GLASS": {"color": 131},   # 오프닝 유리난간 유리
    "SEC_RAILING": {"color": 254},       # 횡단·종단면도 유리난간
    "PLAN_RAILING": {"color": 254},      # 평면도 유리난간 (제연경계벽도)
    "STRUCT_ESC_GLASS": {"color": 131},  # 에스컬레이터 유리 난간 (상세)
    "STRUCT_SMOKE": {"color": 8},        # 제연경계벽 프레임
    "STRUCT_SMOKE_GLASS": {"color": 131},     # 제연경계벽 유리
    "FIN_TACTILE": {"color": 2},         # 점자블록 (점형·선형)
    "SEC_TACTILE": {"color": 2},         # 횡단·종단면도 점자블록
    "PLAN_TACTILE": {"color": 2},        # 평면도 점자블록
    "SEC_FINISH": {"color": 43},         # 횡단면도 마감
    "PROF_FINISH": {"color": 43},        # 종단면도 마감
    "PLAN_FINISH": {"color": 43},        # 평면도 벽·기둥 마감
    "STRUCT_DOOR": {"color": 6},         # 문틀·문짝
    "STRUCT_DOOR_GLASS": {"color": 4},   # 자동문 유리
    "PLAN_DOOR": {"color": 6},           # 평면도 문 기호 (열린 문짝 + 호)
    "SEC_DOOR": {"color": 6},            # 횡단면도 문짝
    "PROF_DOOR": {"color": 6},           # 종단면도 문짝
    "STRUCT_SEPARATION": {"color": 1},   # 구획분리 벽 (두께 > 0)
    "PLAN_SEPARATION": {"color": 1},     # 평면도 구획분리 (벽 윤곽 / 가상 경계선)           # 평면도 실 영역·실 이름
    "STRUCT_VENT": {"color": 130},       # 환기구 콘크리트 (덕트·수직구)
    "STRUCT_GRILL": {"color": 9},        # 환기구 금속 그릴
    "PLAN_VENT": {"color": 130},         # 평면도 환기구 벽
    "SEC_GRILL": {"color": 9},           # 횡단면도 그릴 절단면

}