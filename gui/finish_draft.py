"""마감표 입력의 화면 비의존 모델 (문자열 초안 → FinishSettings 변환 + 검증)"""
from dataclasses import dataclass

from finishes.finish_spec import (FILL_MORTAR, FILL_VOID, STEP_CONCRETE, STEP_PLATE, STEP_SOLID, FinishSettings, FinishType,
                                  StairFinish, default_finishes)
from gui.column_draft import _num

FILL_LABELS = {"몰탈 채움": FILL_MORTAR, "빈 공간(액세스 플로어)": FILL_VOID}
FILL_OF = {v: k for k, v in FILL_LABELS.items()}
FRAME_LABELS = {"M바": "M", "T바": "T"}
FRAME_OF = {v: k for k, v in FRAME_LABELS.items()}
BY_USE = "(용도 기준)"            # 실 마감 덮어쓰기 콤보의 '덮어쓰지 않음'

# (속성, 라벨, 규칙) 숫자 칸
NUM_FIELDS = [("ffl", "바닥 마감 높이", "nonneg"), ("floor_t", "바닥 마감재 두께", "nonneg"), ("wall_t", "벽 마감 두께", "nonneg"),
              ("ceiling_h", "천장 높이", "pos"), ("board_t", "천장판 두께", "pos"), ("bar_spacing", "바 간격", "pos"),
              ("carrier_spacing", "캐링 간격", "pos")]
TEXT_FIELDS = [("floor_material", "바닥 재질"), ("wall_material", "벽 재질"), ("ceiling_material", "천장 재질")]
FACE_FIELD = ("wall_face", "벽 마감면 거리")    # 구조체 면 → 마감 표면 (비우면 = 벽 마감 두께, 이격 없음)


@dataclass
class FinishTypeDraft:
    """마감 종류 1개 (입력창 문자열). 바·캐링 채널 단면 치수는 모델 기본값을 그대로 씀"""
    name: str = "새 마감"
    ffl: str = "0.1"
    floor_t: str = "0.03"
    fill: str = "몰탈 채움"
    floor_material: str = "화강석"
    wall_t: str = "0.05"
    wall_material: str = "금속패널"
    wall_face: str = ""                 # 구조체 면 → 벽 마감 표면 거리 (비우면 마감 두께와 같음 = 이격 없음)
    ceiling: bool = True
    ceiling_h: str = "3"
    board_t: str = "0.01"
    ceiling_material: str = "알루미늄 천장판"
    frame: str = "M바"
    bar_spacing: str = "0.6"
    carrier_spacing: str = "0.9"

    @classmethod
    def from_type(cls, ft: FinishType) -> "FinishTypeDraft":
        g = lambda v: f"{v:g}"
        return cls(name=ft.name, ffl=g(ft.ffl), floor_t=g(ft.floor_t), fill=FILL_OF.get(ft.floor_fill, "몰탈 채움"),
                   floor_material=ft.floor_material, wall_t=g(ft.wall_t), wall_material=ft.wall_material,
                   wall_face="" if ft.wall_face is None else g(ft.wall_face), ceiling=ft.ceiling,
                   ceiling_h=g(ft.ceiling_h), board_t=g(ft.board_t), ceiling_material=ft.ceiling_material,
                   frame=FRAME_OF.get(ft.frame, "M바"), bar_spacing=g(ft.bar_spacing), carrier_spacing=g(ft.carrier_spacing))

    def to_type(self, where: str) -> FinishType:
        name = str(self.name).strip()
        if not name:
            raise ValueError(f"{where}: 마감 종류 이름을 입력하세요")
        if self.fill not in FILL_LABELS:
            raise ValueError(f"{where}: 바닥 채움이 올바르지 않습니다 ('{self.fill}')")
        if self.frame not in FRAME_LABELS:
            raise ValueError(f"{where}: 천장틀이 올바르지 않습니다 ('{self.frame}')")
        vals = {}
        for attr, label, rule in NUM_FIELDS:
            if attr in ("ceiling_h", "board_t", "bar_spacing", "carrier_spacing") and not self.ceiling:
                continue                                       # 천장이 없으면 천장 입력은 검사하지 않음
            vals[attr] = _num(getattr(self, attr), where, label, positive=rule == "pos", nonneg=rule == "nonneg")
        texts = {attr: str(getattr(self, attr)).strip() for attr, _ in TEXT_FIELDS}
        face = None
        if str(self.wall_face).strip():
            face = _num(self.wall_face, where, FACE_FIELD[1], nonneg=True)
            if face < vals["wall_t"] - 1e-9:
                raise ValueError(f"{where}: 벽 마감면 거리({face:g})가 벽 마감 두께({vals['wall_t']:g})보다 작습니다 "
                                 "(구조체 면 → 마감 표면 거리 ≥ 마감재 두께)")
        return FinishType(name=name, floor_fill=FILL_LABELS[self.fill], ceiling=bool(self.ceiling),
                          frame=FRAME_LABELS[self.frame], wall_face=face, **vals, **texts)


STEP_LABELS = {"판석 + 몰탈 채움": STEP_PLATE, "통석 + 깔 몰탈": STEP_SOLID, "콘크리트 계단": STEP_CONCRETE}
STEP_OF = {v: k for k, v in STEP_LABELS.items()}
# 계단 마감 숫자 칸 (속성, 라벨)
STAIR_NUM_FIELDS = [("depth", "받침 두께"), ("tread_t", "디딤판 두께"), ("riser_t", "챌판 두께"), ("bed", "깔 몰탈"),
                    ("side_t", "옆면 두께"), ("nosing_w", "논슬립 폭"), ("nosing_t", "논슬립 깊이"), ("nosing_end", "논슬립 끝 여유")]
STAIR_TEXT_FIELDS = [("material", "계단석 재질"), ("fill_material", "채움 재질"), ("side_material", "옆면 재질"),
                     ("nosing_material", "논슬립 재질")]


@dataclass
class StairFinishDraft:
    """계단 마감 입력 (문자열). 마감을 켜고 enabled 일 때 계단 = 매끈한 경사 슬래브 + 계단석"""
    enabled: bool = True
    method: str = "판석 + 몰탈 채움"
    material: str = "화강석"
    fill_material: str = "몰탈"
    depth: str = "0.1"
    tread_t: str = "0.03"
    riser_t: str = "0.02"
    bed: str = "0.03"
    nosing: bool = True
    nosing_w: str = "0.05"
    nosing_t: str = "0.005"
    nosing_end: str = "0.05"
    nosing_material: str = "논슬립"
    side_t: str = "0.02"
    side_material: str = "화강석"

    def to_finish(self) -> StairFinish:
        where = "계단 마감"
        if not self.enabled:                             # 끈 계단 마감은 입력을 검사하지 않음
            return StairFinish(enabled=False)
        if self.method not in STEP_LABELS:
            raise ValueError(f"{where}: 방식이 올바르지 않습니다 ('{self.method}')")
        vals = {a: _num(getattr(self, a), where, lb, nonneg=True) for a, lb in STAIR_NUM_FIELDS}
        texts = {a: str(getattr(self, a)).strip() for a, _ in STAIR_TEXT_FIELDS}
        fin = StairFinish(enabled=bool(self.enabled), method=STEP_LABELS[self.method], nosing=bool(self.nosing),
                          **vals, **texts)
        if fin.enabled:
            try:
                fin.check()
            except ValueError as e:
                raise ValueError(f"{where}: {e}") from None
        return fin


def stair_preview(d: StairFinishDraft) -> str:
    if not d.enabled:
        return "→ 계단 마감 없음 (일체형 콘크리트 계단)"
    try:
        f = d.to_finish()
    except ValueError:
        return "→ 입력값을 확인하세요"
    body = {STEP_PLATE: f"{f.material} 디딤판 {f.tread_t:g}·챌판 {f.riser_t:g} + {f.fill_material} 채움",
            STEP_SOLID: f"{f.material} 통석 + {f.fill_material} {f.bed:g}",
            STEP_CONCRETE: "콘크리트 스텝"}[f.method]
    extra = (f" · 논슬립 {f.nosing_w:g}×{f.nosing_t:g}" if f.nosing else "") +         (f" · 노출 옆면 {f.side_material} {f.side_t:g}" if f.side_t > 0 else "")
    return f"→ 구조 슬래브 + {body} (받침 {f.depth:g}){extra}. 디딤판 높이 = 아래·위층 바닥 마감면 기준"


def default_drafts() -> list:
    return [FinishTypeDraft.from_type(ft) for ft in default_finishes().values()]


class FinishDrafts:
    """마감표 입력 초안 (마감 생성 여부 + 마감 종류 목록)"""

    def __init__(self):
        self.enabled = True                 # GUI 는 기본으로 마감을 생성
        self.items: list[FinishTypeDraft] = default_drafts()
        self.stair = StairFinishDraft()

    def names(self) -> list[str]:
        return [str(it.name).strip() for it in self.items if str(it.name).strip()]

    def to_settings(self) -> FinishSettings:
        table = {}
        for i, it in enumerate(self.items):
            ft = it.to_type(f"마감 {i + 1}({str(it.name).strip() or '?'})")
            if ft.name in table:
                raise ValueError(f"마감 종류 이름이 중복됩니다: {ft.name}")
            table[ft.name] = ft
        return FinishSettings(enabled=bool(self.enabled), table=table, stair=self.stair.to_finish())


def preview(it: FinishTypeDraft) -> str:
    try:
        ft = it.to_type("")
    except ValueError:
        return "→ 입력값을 확인하세요"
    floor = "바닥 마감 없음" if ft.ffl == 0 else f"바닥 FL+{ft.ffl:g} ({ft.floor_material} {ft.floor_t:g}, " \
        f"{'몰탈 채움' if ft.floor_fill == FILL_MORTAR else '빈 공간'})"
    wall = f"벽 {ft.wall_material}" + (f" {ft.wall_t:g}" if ft.wall_t > 0 else " (형상 없음)")
    if ft.wall_t > 0 and ft.wall_gap > 1e-9:
        wall += f" (구조면→표면 {ft.face:g}, 이격 {ft.wall_gap:g})"
    ceil = f"천장 마감면+{ft.ceiling_h:g} ({ft.ceiling_material}, {ft.frame}바 {ft.bar_spacing:g})" if ft.ceiling else "천장 없음"
    return f"→ {floor} · {wall} · {ceil}"

