"""배치 객체(비품) 입력의 화면 비의존 모델 (문자열 초안 → PropSpec 변환 + 검증).

비품 하나 = 종류·층·STA·t·앞면 방향 + 종류별 치수·문구(prop_kinds 등록부가 단일 출처). 숫자 칸을 비우면 종류 기본값.
"""
from dataclasses import dataclass, field

from gui.column_draft import _num
from gui.pick_fill import num
from props.prop_kinds import INT, KINDS, TEXT, WALL
from props.prop_spec import PropSpec, resolve_prop_names

KIND_CODES = list(KINDS)
KIND_LABELS = [KINDS[c].label for c in KIND_CODES]
ANGLES = ["0 (종점 쪽 +s)", "90 (왼쪽 +t)", "180 (시점 쪽 −s)", "270 (오른쪽 −t)"]      # 숫자 뒤는 설명, 다른 각도는 숫자로 입력


def default_values(kind: str) -> dict:
    """종류의 입력칸 문자열 기본값"""
    return {f.key: f.default if f.type == TEXT else f"{f.default:g}" for f in KINDS[kind].fields}


@dataclass
class PropDraft:
    """비품 1개 (입력창 문자열). floor: 층 번호 (1 = 최하층), angle: '90' 또는 '90 (왼쪽 +t)'"""
    kind: str = "BENCH"
    floor: int = 1
    sta: str = "0"
    t: str = "0"
    angle: str = ANGLES[0]
    name: str = ""
    values: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.values and self.kind in KINDS:
            self.values = default_values(self.kind)

    def set_kind(self, kind: str):
        """종류를 바꾸면 치수·문구는 그 종류 기본값으로"""
        if kind != self.kind:
            self.kind, self.values = kind, default_values(kind)

    @property
    def is_wall(self) -> bool:
        return self.kind in KINDS and KINDS[self.kind].mount == WALL

    def to_spec(self, where: str, start_station: float) -> PropSpec:
        if self.kind not in KINDS:
            raise ValueError(f"{where}: 알 수 없는 비품 종류 '{self.kind}'")
        vals = {}
        for f in KINDS[self.kind].fields:
            text = str(self.values.get(f.key, f.default if f.type == TEXT else ""))
            if f.type == TEXT:
                vals[f.key] = text.strip()
            elif text.strip():
                v = _num(text, where, f.label)
                if f.type == INT:
                    if v != int(v):
                        raise ValueError(f"{where}: '{f.label}'은(는) 정수여야 합니다 ('{text}')")
                    v = int(v)
                vals[f.key] = v
        ang = 0.0 if self.is_wall else _num(str(self.angle).split("(")[0], where, "방향")
        return PropSpec(kind=self.kind, floor=self.floor, s=_num(self.sta, where, "STA") - start_station, t=_num(self.t, where, "t"),
                        angle=ang, values=vals, name=self.name.strip())


class PropDrafts:
    """비품 입력 초안 목록"""

    def __init__(self):
        self.items: list[PropDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 줄어 없어진 층의 비품은 최상층으로 옮김. 변경 여부 반환"""
        changed = False
        for it in self.items:
            if it.floor > floor_count:
                it.floor = max(1, floor_count)
                changed = True
        return changed

    @staticmethod
    def where(i: int, it: PropDraft) -> str:
        return f"비품 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")

    def to_specs(self, start_station: float) -> list:
        return [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]


def new_draft(kind: str, floor: int, sta: float, t: float = 0.0) -> PropDraft:
    return PropDraft(kind=kind, floor=floor, sta=num(sta), t=num(t))


def titles(d: PropDrafts) -> list:
    """목록 제목 (이름을 비우면 자동 이름)"""
    return resolve_prop_names([PropSpec(kind=it.kind, name=it.name) for it in d.items])


def preview(d: PropDrafts, start_station: float) -> str:
    """입력 중 미리보기: 종류별 개수 또는 입력 오류"""
    if not d.items:
        return "→ 비품 없음"
    try:
        d.to_specs(start_station)
    except ValueError as e:
        return f"→ {e}"
    cnt = {}
    for it in d.items:
        k = KINDS[it.kind].label.split(" (")[0]
        cnt[k] = cnt.get(k, 0) + 1
    return f"→ 비품 {len(d.items)}개: " + " · ".join(f"{k} {n}" for k, n in cnt.items())
