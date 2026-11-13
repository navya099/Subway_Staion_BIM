"""출구통로 입력의 화면 비의존 모델 (문자열 초안 → PassageSpec 변환 + 검증)"""
from dataclasses import dataclass

from gui.column_draft import _num, level_name
from gui.stair_draft import DIRECTIONS, UP_MINUS, UP_PLUS
from passages.passage_spec import PassageSpec

_SPEC = PassageSpec()               # 초기값은 모델 기본값이 단일 출처

SIDE_PLUS = "왼쪽 (+t)"
SIDE_MINUS = "오른쪽 (−t)"
SIDES = [SIDE_PLUS, SIDE_MINUS]
_SIDE = {SIDE_PLUS: 1, SIDE_MINUS: -1}
TURNS = DIRECTIONS                 # 꺾임 방향: 종점 방향(+s) / 시점 방향(−s)
_TURN = {UP_PLUS: 1, UP_MINUS: -1}


def floor_label(floor_count: int, floor_n: int) -> str:
    return level_name(floor_count, floor_n)


@dataclass
class PassageDraft:
    """출구통로 1개 (입력창 문자열 그대로 보관)
    sta_center: 통로 중심의 절대 STA (m) - 정거장 시작 측점을 빼서 내공 시점 기준 s 로 변환한다
    floor: 통로가 붙는 층 번호 (1 = 최하층)"""
    name: str = ""
    floor: int = 1
    side: str = SIDE_PLUS
    turn: str = UP_PLUS
    sta_center: str = "0"
    inner_width: str = f"{_SPEC.inner_width:g}"
    inner_height: str = f"{_SPEC.inner_height:g}"
    wall_t: str = f"{_SPEC.wall_t:g}"
    floor_t: str = f"{_SPEC.floor_t:g}"
    roof_t: str = f"{_SPEC.roof_t:g}"
    top_haunch_w: str = f"{_SPEC.top_haunch_w:g}"
    top_haunch_h: str = f"{_SPEC.top_haunch_h:g}"
    bottom_haunch_w: str = f"{_SPEC.bottom_haunch_w:g}"
    bottom_haunch_h: str = f"{_SPEC.bottom_haunch_h:g}"
    length1: str = f"{_SPEC.length1:g}"
    length2: str = f"{_SPEC.length2:g}"
    grade_permil: str = f"{_SPEC.grade_permil:g}"

    def to_spec(self, where: str, start_station: float) -> PassageSpec:
        if self.side not in _SIDE:
            raise ValueError(f"{where}: 측벽 방향이 올바르지 않습니다 ('{self.side}')")
        if self.turn not in _TURN:
            raise ValueError(f"{where}: 꺾임 방향이 올바르지 않습니다 ('{self.turn}')")
        pos = lambda attr, label: _num(getattr(self, attr), where, label, positive=True)
        nonneg = lambda attr, label: _num(getattr(self, attr), where, label, nonneg=True)
        return PassageSpec(
            floor=self.floor, side=_SIDE[self.side], s_center=_num(self.sta_center, where, "중심 측점") - start_station,
            inner_width=pos("inner_width", "내공 폭"), inner_height=pos("inner_height", "내공 높이"),
            wall_t=pos("wall_t", "벽 두께"), floor_t=pos("floor_t", "바닥 슬래브 두께"), roof_t=pos("roof_t", "천장 슬래브 두께"),
            top_haunch_w=nonneg("top_haunch_w", "상부 헌치 폭"), top_haunch_h=nonneg("top_haunch_h", "상부 헌치 높이"),
            bottom_haunch_w=nonneg("bottom_haunch_w", "하부 헌치 폭"), bottom_haunch_h=nonneg("bottom_haunch_h", "하부 헌치 높이"),
            length1=pos("length1", "첫 구간 길이"), length2=nonneg("length2", "꺾임 후 길이"), turn=_TURN[self.turn],
            grade_permil=_num(self.grade_permil, where, "구배"), name=self.name.strip())


class PassageDrafts:
    """출구통로 입력 초안 목록"""

    def __init__(self):
        self.items: list[PassageDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 줄어 없어진 층에 붙은 통로는 최상층으로 옮김. 변경 여부 반환"""
        changed = False
        for it in self.items:
            if it.floor > floor_count:
                it.floor = max(1, floor_count)
                changed = True
        return changed

    def to_specs(self, start_station: float) -> list[PassageSpec]:
        """초안 → PassageSpec 목록. 잘못된 입력은 몇 번째 통로인지 밝혀서 ValueError"""
        return [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: PassageDraft) -> str:
        return f"출구통로 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")


def preview(it: PassageDraft, start_station: float) -> str:
    """입력 중 미리보기: 측벽 오프닝 STA 범위, 통로 길이·끝 위치 (직선 선형 기준)"""
    try:
        sp = it.to_spec("", start_station)
    except ValueError:
        return "→ 입력값을 확인하세요"
    sta = sp.s_center + start_station
    a = sp.half_in
    text = f"→ 측벽 오프닝 STA {sta - a:.2f} ~ {sta + a:.2f} (폭 {sp.inner_width:g} x 높이 {sp.inner_height:g})\n"
    if sp.bent:
        end = sta + sp.turn * sp.length2
        text += f"   L자: 직각 {sp.length1:g}m 후 꺾어 {sp.length2:g}m, 끝 STA ≈ {end:.2f}"
    else:
        text += f"   직선 {sp.length1:g}m (외벽 바깥면부터)"
    return text
