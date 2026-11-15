"""건축 마감 제원: 용도별 마감표 (바닥·벽·천장·천장틀). 실은 용도로 마감을 찾고, 실마다 다른 마감 종류로 덮어쓸 수 있다.

기본값은 실무 일반값을 따른 예시이며 마감 탭에서 고친다 (실무 마감표가 있으면 그 값으로).
"""
import dataclasses

FILL_MORTAR = "mortar"           # 바닥 마감재 아래를 몰탈로 채움
FILL_VOID = "void"               # 바닥 마감재 아래가 빈 공간 (액세스 플로어)
FILLS = (FILL_MORTAR, FILL_VOID)
FRAME_M = "M"                    # M바 (경량 천장틀, 숨김형)
FRAME_T = "T"                    # T바 (노출형 그리드)
FRAMES = (FRAME_M, FRAME_T)
FALLBACK = "기본"                # 마감표에 없는 용도가 쓰는 마감 종류


@dataclasses.dataclass
class FinishType:
    """마감 종류 1개 (보통 실 용도 이름과 같음).
    바닥: ffl = 마감 높이 (구조 바닥 상면 → 마감면, 0 이면 바닥 마감 없음), floor_t = 마감재 두께 (마감면에서 아래로),
          floor_fill = 그 아래 (FILL_MORTAR 몰탈 채움 | FILL_VOID 빈 공간 = 액세스 플로어)
    벽: wall_t = 마감 두께 (0 = 면처리, 형상 없음), 마감면 ~ 천장(없으면 위 슬래브 하면)
    천장: ceiling = 천장 있음, ceiling_h = 바닥 마감면에서 천장판 하면까지, board_t = 천장판 두께,
          frame = M | T, bar_spacing = 천장틀 바(M/T) 간격 (t 방향으로 뻗은 바를 s 방향으로 배열),
          carrier_spacing = 캐링 채널 간격 (s 방향으로 뻗은 바를 t 방향으로 배열), bar 단면 = 폭 bar_w × 높이 bar_h,
          캐링 채널 단면 = carrier_w × carrier_h (바 위)
    """
    name: str = FALLBACK
    ffl: float = 0.1
    floor_t: float = 0.03
    floor_fill: str = FILL_MORTAR
    floor_material: str = "석재"
    wall_t: float = 0.05
    wall_material: str = "패널"
    ceiling: bool = True
    ceiling_h: float = 3.0
    board_t: float = 0.01
    ceiling_material: str = "알루미늄 천장판"
    frame: str = FRAME_M
    bar_spacing: float = 0.6
    carrier_spacing: float = 0.9
    bar_w: float = 0.025
    bar_h: float = 0.025
    carrier_w: float = 0.012
    carrier_h: float = 0.038

    @property
    def frame_depth(self) -> float:
        """천장판 상면 위 천장틀 높이 (바 + 캐링 채널)"""
        return self.bar_h + self.carrier_h


def default_finishes() -> dict:
    """용도별 기본 마감표 (이름 → FinishType). 기계·전기·공조실은 콘크리트 면처리 + 천장 없음, 통신실은 액세스 플로어"""
    concrete = dict(ffl=0.0, floor_t=0.0, floor_material="콘크리트 면처리", wall_t=0.0, wall_material="콘크리트 면처리",
                    ceiling=False)
    table = [
        FinishType("대합실"),
        FinishType("승강장층"),
        FinishType("복도"),
        FinishType("역무실", floor_material="타일", wall_t=0.05, ceiling_h=2.7),
        FinishType("기계실", **concrete),
        FinishType("전기실", **concrete),
        FinishType("공조실", **concrete),
        FinishType("통신실", ffl=0.45, floor_t=0.035, floor_fill=FILL_VOID, floor_material="액세스 플로어",
                   wall_t=0.0, wall_material="콘크리트 면처리", ceiling_h=2.7),
        FinishType("화장실", floor_material="타일", wall_t=0.03, wall_material="타일", ceiling_h=2.7,
                   ceiling_material="방수 천장판"),
        FinishType("창고", floor_material="타일", wall_t=0.0, wall_material="콘크리트 면처리", ceiling=False),
        FinishType("통로"),
        FinishType("기타"),
        FinishType(FALLBACK),
    ]
    return {f.name: f for f in table}


@dataclasses.dataclass
class FinishSettings:
    """마감 공통 설정. enabled: 마감 생성 여부 (모델 기본은 끔 — 기존 출력 유지, GUI 는 켬)
    table: 마감 종류 이름 → FinishType (용도 이름과 같은 종류를 그 용도에 씀, 없으면 '기본')"""
    enabled: bool = False
    table: dict = dataclasses.field(default_factory=default_finishes)

    def for_room(self, use: str, override: str = "") -> FinishType:
        key = (override or "").strip() or use.strip()
        if key in self.table:
            return self.table[key]
        if (override or "").strip():
            raise ValueError(f"마감 종류 '{override}' 이(가) 마감표에 없습니다")
        return self.table.get(FALLBACK) or FinishType()
