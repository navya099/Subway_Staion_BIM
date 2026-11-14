"""출입구 입력의 화면 비의존 모델 (문자열 초안 → EntranceSpec 변환 + 검증)"""
from dataclasses import dataclass

from entrances.entrance_spec import EntranceSpec
from gui.column_draft import _num

_SPEC = EntranceSpec()              # 초기값은 모델 기본값이 단일 출처

SIDE_LEFT = "왼쪽 (+t)"
SIDE_RIGHT = "오른쪽 (−t)"
SIDES = [SIDE_LEFT, SIDE_RIGHT]
_SIDE = {SIDE_LEFT: 1, SIDE_RIGHT: -1}

# (속성, 라벨, 양수만 / 0 이상) — 숫자 입력칸
NUM_FIELDS = [("ground_el", "지표 EL", None), ("stair_width", "계단 폭", "pos"), ("partition_t", "칸막이벽", "pos"),
              ("escalator_zone", "ESC 구역 폭", "pos"), ("wall_t", "벽·슬래브 두께", "pos"), ("haunch_w", "헌치 폭", "nonneg"),
              ("haunch_h", "헌치 높이", "nonneg"), ("lower_margin", "하부 여유", "nonneg"), ("top_margin", "상부 여유", "nonneg"),
              ("parapet", "파라펫", "nonneg"), ("riser_max", "단높이 상한", "pos"), ("tread", "단너비", "pos"),
              ("flight_rise_max", "런 높이 상한", "pos"), ("landing_len", "계단참 길이", "pos"),
              ("stair_slab_t", "계단 슬래브", "pos"), ("stair_headroom", "계단 머리 높이", "pos")]


@dataclass
class EntranceDraft:
    """출입구 1개 (입력창 문자열 그대로 보관). stair_offset 이 비어 있으면 계단 시작 위치 자동"""
    name: str = ""
    passage: str = "EX1"
    escalator: bool = True
    side: str = SIDE_LEFT
    ground_el: str = "0"
    stair_width: str = f"{_SPEC.stair_width:g}"
    partition_t: str = f"{_SPEC.partition_t:g}"
    escalator_zone: str = f"{_SPEC.escalator_zone:g}"
    wall_t: str = f"{_SPEC.wall_t:g}"
    haunch_w: str = f"{_SPEC.haunch_w:g}"
    haunch_h: str = f"{_SPEC.haunch_h:g}"
    lower_margin: str = f"{_SPEC.lower_margin:g}"
    top_margin: str = f"{_SPEC.top_margin:g}"
    parapet: str = f"{_SPEC.parapet:g}"
    riser_max: str = f"{_SPEC.riser_max:g}"
    tread: str = f"{_SPEC.tread:g}"
    flight_rise_max: str = f"{_SPEC.flight_rise_max:g}"
    landing_len: str = f"{_SPEC.landing_len:g}"
    stair_slab_t: str = f"{_SPEC.stair_slab_t:g}"
    stair_headroom: str = f"{_SPEC.stair_headroom:g}"
    stair_offset: str = ""

    def to_spec(self, where: str) -> EntranceSpec:
        if self.side not in _SIDE:
            raise ValueError(f"{where}: 에스컬레이터 쪽이 올바르지 않습니다 ('{self.side}')")
        if not self.passage.strip():
            raise ValueError(f"{where}: 이어 붙일 출구통로 이름을 입력하세요")
        vals = {}
        for attr, label, rule in NUM_FIELDS:
            vals[attr] = _num(getattr(self, attr), where, label, positive=rule == "pos", nonneg=rule == "nonneg")
        offset = None if not str(self.stair_offset).strip() else _num(self.stair_offset, where, "계단 시작 조정")
        return EntranceSpec(passage=self.passage.strip(), escalator=bool(self.escalator), escalator_side=_SIDE[self.side],
                            stair_offset=offset, name=self.name.strip(), **vals)


class EntranceDrafts:
    """출입구 입력 초안 목록"""

    def __init__(self):
        self.items: list[EntranceDraft] = []

    def to_specs(self) -> list[EntranceSpec]:
        return [it.to_spec(self.where(i, it)) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: EntranceDraft) -> str:
        return f"출입구 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")


def preview(it: EntranceDraft) -> str:
    """입력 중 미리보기: 내공 폭 구성 (높이·길이는 통로 끝 표고가 정해지는 출력 시 계산)"""
    try:
        sp = it.to_spec("")
    except ValueError:
        return "→ 입력값을 확인하세요"
    if sp.escalator:
        side = "왼쪽" if sp.escalator_side > 0 else "오른쪽"
        parts = f"계단 {sp.stair_width:g} + 칸막이 {sp.partition_t:g} + 에스컬레이터 {sp.escalator_zone:g} ({side})"
    else:
        parts = f"계단 {sp.stair_width:g}"
    return (f"→ 내공 폭 {sp.inner_width:g}m = {parts}\n"
            f"   통로 {sp.passage} 끝에서 지표 EL {sp.ground_el:g} 까지 자동 계산"
            + ("" if sp.stair_offset is None else f", 계단 시작 조정 {sp.stair_offset:g}m"))
