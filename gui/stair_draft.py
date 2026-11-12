"""계단 입력의 화면 비의존 모델 (문자열 초안 → StairSpec 변환 + 검증)"""
from dataclasses import dataclass

from gui.column_draft import _num, level_name
from stairs.stair_layout import plan_risers
from stairs.stair_spec import StairSpec

_SPEC = StairSpec()                 # 초기값은 모델 기본값이 단일 출처

UP_PLUS = "종점 방향 (+s)"
UP_MINUS = "시점 방향 (−s)"
DIRECTIONS = [UP_PLUS, UP_MINUS]
_DIR = {UP_PLUS: 1, UP_MINUS: -1}


def floor_choice_label(floor_count: int, floor_n: int) -> str:
    """시작 층 선택 이름: 'B3F → B2F' (floor_n 층에서 위층으로)"""
    return f"{level_name(floor_count, floor_n)} → {level_name(floor_count, floor_n + 1)}"


@dataclass
class StairDraft:
    """계단 1개 (입력창 문자열 그대로 보관)
    sta_start: 첫 단이 시작되는 절대 STA (m) - 정거장 시작 측점을 빼서 내공 시점 기준 s 로 변환한다
    lower_floor: 시작 층 번호 (1 = 최하층)"""
    name: str = ""
    lower_floor: int = 1
    direction: str = UP_PLUS
    sta_start: str = "0"
    t_center: str = "6.5"
    width: str = "2.5"
    riser_max: str = f"{_SPEC.riser_max:g}"
    tread: str = f"{_SPEC.tread:g}"
    flight_rise_max: str = f"{_SPEC.flight_rise_max:g}"
    landing_len: str = f"{_SPEC.landing_len:g}"
    waist_t: str = f"{_SPEC.waist_t:g}"
    headroom: str = f"{_SPEC.headroom:g}"

    def to_spec(self, where: str, start_station: float) -> StairSpec:
        if self.direction not in _DIR:
            raise ValueError(f"{where}: 오르는 방향이 올바르지 않습니다 ('{self.direction}')")
        num = lambda attr, label: _num(getattr(self, attr), where, label, positive=True)
        return StairSpec(
            lower_floor=self.lower_floor,
            s_start=_num(self.sta_start, where, "시작 측점") - start_station,
            direction=_DIR[self.direction],
            t_center=_num(self.t_center, where, "t 위치"),
            width=num("width", "폭"),
            riser_max=num("riser_max", "단높이 상한"),
            tread=num("tread", "단너비"),
            flight_rise_max=num("flight_rise_max", "런 높이 상한"),
            landing_len=num("landing_len", "계단참 길이"),
            waist_t=num("waist_t", "계단 슬래브 두께"),
            headroom=num("headroom", "머리 높이"),
            name=self.name.strip())


class StairDrafts:
    """계단 입력 초안 목록"""

    def __init__(self):
        self.items: list[StairDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 줄어 시작 층이 없어진(최상층 이상) 계단은 가장 높은 가능한 층으로 옮김. 변경 여부 반환"""
        top = max(1, floor_count - 1)
        changed = False
        for it in self.items:
            if it.lower_floor > top:
                it.lower_floor = top
                changed = True
        return changed

    def to_specs(self, floor_count: int, start_station: float) -> list[StairSpec]:
        """초안 → StairSpec 목록. 잘못된 입력은 몇 번째 계단인지 밝혀서 ValueError"""
        return [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: StairDraft) -> str:
        return f"계단 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")


def preview(it: StairDraft, floor_height: float, start_station: float) -> str:
    """입력 중 미리보기: 층 바닥(FL) 기준·종단구배 무시 추정 (승강장 위 계단·구배는 출력 시 정확히 다시 계산)"""
    try:
        sp = it.to_spec("", start_station)
        n, r, counts, run = plan_risers(floor_height, sp)
    except ValueError:
        return "→ 입력값을 확인하세요"
    sta = sp.s_start + start_station
    end = sta + sp.direction * run
    lo, hi = sorted((sta, end))
    return (f"→ 약 {n}단 (단높이 {r * 1000:.0f}mm), 계단참 {len(counts) - 1}개, 길이 {run:.2f}m\n"
            f"   STA {lo:.2f} ~ {hi:.2f},  t {sp.t_lo:g} ~ {sp.t_hi:g}  (FL 기준 추정)")
