"""열별 기둥 입력의 화면 비의존 모델 (문자열 초안 → ColumnParameters 변환 + 검증).

UI 위젯은 이 초안 객체만 수정하고, 변환/검증은 tkinter 없이 테스트할 수 있다.
"""
from dataclasses import dataclass, field

from columns.column_params import ColumnParameters, ColumnRowSpec, ColumnSpec, FloorColumnSpec
from columns.column_shape_type import ColumnShapeType

RECT = "사각기둥"
CIRCLE = "원기둥"
SHAPES = [RECT, CIRCLE]


@dataclass
class PatternDraft:
    """열 안에서 순환 반복되는 기둥 규격 1개 (입력창 문자열 그대로 보관)"""
    shape: str = RECT
    width: str = "0.8"       # 사각: 진행방향 폭 (m)
    depth: str = "0.8"       # 사각: 직교방향 두께 (m)
    diameter: str = "1.0"    # 원: 지름 (m)


@dataclass
class RowDraft:
    """기둥 1열 (선형 직교방향 위치 t 에 놓인 기둥 줄)"""
    t_offset: str = "0.0"
    interval: str = "10.0"
    start_offset: str = "1.0"
    patterns: list = field(default_factory=lambda: [PatternDraft()])


@dataclass
class FloorDraft:
    rows: list = field(default_factory=lambda: [RowDraft()])


def level_name(floor_count: int, floor_n: int) -> str:
    """floor_n: 1 = 최하층"""
    return f"B{floor_count - floor_n + 1}F" if floor_count > 1 else f"{floor_n}F"


def _num(text: str, where: str, label: str, positive=False, nonneg=False) -> float:
    try:
        v = float(str(text).strip())
    except ValueError:
        raise ValueError(f"{where}: {label}이(가) 숫자가 아닙니다 ('{text}')") from None
    if positive and v <= 0:
        raise ValueError(f"{where}: {label}은(는) 0보다 커야 합니다 ({v})")
    if nonneg and v < 0:
        raise ValueError(f"{where}: {label}은(는) 0 이상이어야 합니다 ({v})")
    return v


def estimate_count(row: RowDraft, length: float, wall_t: float):
    """현재 정거장 길이 기준 열의 기둥 개수 (입력이 올바르지 않으면 None)"""
    try:
        interval, start = float(row.interval), float(row.start_offset)
    except ValueError:
        return None
    if interval <= 0 or start < 0:
        return None
    span = length - 2 * wall_t - 2 * start
    return int(span / interval + 1e-9) + 1 if span >= 0 else 0


class ColumnDrafts:
    """층별 기둥 입력 초안 (키: 층 번호, 1 = 최하층)"""

    def __init__(self):
        self.floors: dict[int, FloorDraft] = {}

    def ensure_floors(self, count: int) -> bool:
        """층수에 맞게 초안 정리: 기존 층 입력은 유지, 새 층은 기본 1열, 사라진 층은 삭제. 변경 여부 반환"""
        changed = False
        for n in range(1, count + 1):
            if n not in self.floors:
                self.floors[n] = FloorDraft()
                changed = True
        for n in [k for k in self.floors if k > count]:
            del self.floors[n]
            changed = True
        return changed

    def to_params(self, floor_count: int, sync: bool = True) -> ColumnParameters:
        """초안 → ColumnParameters. 잘못된 입력은 어느 층/열/패턴인지 밝혀서 ValueError"""
        self.ensure_floors(floor_count)
        floors = {}
        for n in range(1, floor_count + 1):
            level = level_name(floor_count, n)
            rows = []
            for r, row in enumerate(self.floors[n].rows, start=1):
                where = f"{level} {r}열"
                if not row.patterns:
                    raise ValueError(f"{where}: 기둥 규격(패턴)이 비어 있습니다")
                patterns = []
                for k, pat in enumerate(row.patterns, start=1):
                    w = f"{where} 패턴 {k}"
                    if pat.shape == CIRCLE:
                        d = _num(pat.diameter, w, "지름", positive=True)
                        patterns.append(ColumnSpec(ColumnShapeType.CIRCLE, radius=d / 2.0))
                    else:
                        patterns.append(ColumnSpec(ColumnShapeType.RECTANGLE,
                                                   width=_num(pat.width, w, "폭", positive=True),
                                                   depth=_num(pat.depth, w, "두께", positive=True)))
                rows.append(ColumnRowSpec(
                    t_offset=_num(row.t_offset, where, "t 위치"),
                    interval=_num(row.interval, where, "배치 간격", positive=True),
                    start_offset=_num(row.start_offset, where, "시작 여유", nonneg=True),
                    pattern=patterns))
            if rows:                       # 열이 없는 층은 기둥 없음
                floors[n] = FloorColumnSpec(rows=rows)
        return ColumnParameters(sync_with_platform=sync, floors=floors)
