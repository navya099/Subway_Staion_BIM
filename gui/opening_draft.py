"""슬래브 오프닝 입력의 화면 비의존 모델 (문자열 초안 → OpeningSpec 변환 + 검증)"""
from dataclasses import dataclass, field

from gui.column_draft import _num, level_name
from openings.opening_kind import OpeningKind
from openings.opening_spec import OpeningSpec

_SLAB_KINDS = [k for k in OpeningKind if k not in (OpeningKind.PASSAGE, OpeningKind.VENT_DUCT)]   # 측벽 오프닝은 출구통로·환기구가 자동으로 만듦
KIND_LABELS = [k.label for k in _SLAB_KINDS]
_BY_LABEL = {k.label: k for k in _SLAB_KINDS}


def slab_choice_label(floor_count: int, slab_no: int) -> str:
    """슬래브 선택 체크박스 이름: 바닥 / B3F~B2F(중간) / 천장"""
    if slab_no == 0:
        return "본체 바닥"
    if slab_no == floor_count:
        return "본체 천장"
    return f"{level_name(floor_count, slab_no)}/{level_name(floor_count, slab_no + 1)} 중간"


@dataclass
class OpeningDraft:
    """오프닝 1개 (입력창 문자열 그대로 보관)
    sta_start: 오프닝 시작 측점 (절대 STA, m) - 정거장 시작 측점을 빼서 내공 시점 기준 s 로 변환한다
    t_center : 선형 중심선 기준 직교 위치 (m, 기둥 t 위치와 같은 좌표)"""
    kind: str = OpeningKind.STAIR.label
    name: str = ""
    sta_start: str = "0"
    length: str = "10"
    t_center: str = "0"
    width: str = "3"
    slabs: set = field(default_factory=lambda: {1})


class OpeningDrafts:
    """오프닝 입력 초안 목록"""

    def __init__(self):
        self.items: list[OpeningDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 줄어 없어진 슬래브 번호를 선택에서 뺌. 변경 여부 반환"""
        changed = False
        for it in self.items:
            gone = {n for n in it.slabs if n > floor_count}
            if gone:
                it.slabs -= gone
                changed = True
        return changed

    def to_specs(self, floor_count: int, start_station: float) -> list[OpeningSpec]:
        """초안 → OpeningSpec 목록. 잘못된 입력은 몇 번째 오프닝인지 밝혀서 ValueError"""
        specs = []
        for i, it in enumerate(self.items, start=1):
            where = f"오프닝 {i}" + (f"({it.name.strip()})" if it.name.strip() else f"({it.kind})")
            if it.kind not in _BY_LABEL:
                raise ValueError(f"{where}: 용도가 올바르지 않습니다 ('{it.kind}')")
            sta = _num(it.sta_start, where, "시작 측점")
            specs.append(OpeningSpec(
                kind=_BY_LABEL[it.kind],
                s_start=sta - start_station,
                length=_num(it.length, where, "길이", positive=True),
                t_center=_num(it.t_center, where, "t 위치"),
                width=_num(it.width, where, "폭", positive=True),
                slabs=sorted(n for n in it.slabs if n <= floor_count),
                name=it.name.strip()))
        return specs
