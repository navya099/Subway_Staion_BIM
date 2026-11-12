"""에스컬레이터 입력의 화면 비의존 모델 (문자열 초안 → EscalatorSpec 변환 + 검증)"""
import math
from dataclasses import dataclass

from escalators.escalator_spec import EscalatorSpec
from gui.column_draft import _num
from gui.stair_draft import DIRECTIONS, UP_MINUS, UP_PLUS, floor_choice_label

_SPEC = EscalatorSpec()            # 초기값은 모델 기본값이 단일 출처
_DIR = {UP_PLUS: 1, UP_MINUS: -1}

__all__ = ["DIRECTIONS", "EscalatorDraft", "EscalatorDrafts", "floor_choice_label", "preview"]


def _int(text, where, label) -> int:
    try:
        v = int(str(text).strip())
    except ValueError:
        raise ValueError(f"{where}: {label}이(가) 정수가 아닙니다 ('{text}')") from None
    if v < 0:
        raise ValueError(f"{where}: {label}은(는) 0 이상이어야 합니다 ({v})")
    return v


@dataclass
class EscalatorDraft:
    """에스컬레이터 1대 (입력창 문자열 그대로 보관)
    sta_wp: 하부 WP 의 절대 STA (m) - 정거장 시작 측점을 빼서 내공 시점 기준 s 로 변환한다
    lower_floor: 시작 층 번호 (1 = 최하층)"""
    name: str = ""
    lower_floor: int = 1
    direction: str = UP_PLUS
    sta_wp: str = "0"
    t_center: str = "6.5"
    angle_deg: str = f"{_SPEC.angle_deg:g}"
    step_width: str = f"{_SPEC.step_width:g}"
    truss_width: str = f"{_SPEC.truss_width:g}"
    truss_depth: str = f"{_SPEC.truss_depth:g}"
    lower_ext: str = f"{_SPEC.lower_ext:g}"
    upper_ext: str = f"{_SPEC.upper_ext:g}"
    lower_flat_steps: str = f"{_SPEC.lower_flat_steps}"
    upper_flat_steps: str = f"{_SPEC.upper_flat_steps}"
    step_depth: str = f"{_SPEC.step_depth:g}"
    handrail_height: str = f"{_SPEC.handrail_height:g}"
    headroom: str = f"{_SPEC.headroom:g}"

    def to_spec(self, where: str, start_station: float) -> EscalatorSpec:
        if self.direction not in _DIR:
            raise ValueError(f"{where}: 오르는 방향이 올바르지 않습니다 ('{self.direction}')")
        num = lambda attr, label: _num(getattr(self, attr), where, label, positive=True)
        return EscalatorSpec(
            lower_floor=self.lower_floor,
            s_wp=_num(self.sta_wp, where, "하부 WP 측점") - start_station,
            direction=_DIR[self.direction],
            t_center=_num(self.t_center, where, "t 위치"),
            angle_deg=num("angle_deg", "경사각"),
            step_width=num("step_width", "스텝 폭"),
            truss_width=num("truss_width", "트러스 외폭"),
            truss_depth=num("truss_depth", "트러스 높이"),
            lower_ext=num("lower_ext", "하부 연장"),
            upper_ext=num("upper_ext", "상부 연장"),
            lower_flat_steps=_int(self.lower_flat_steps, where, "하부 평탄 스텝 수"),
            upper_flat_steps=_int(self.upper_flat_steps, where, "상부 평탄 스텝 수"),
            step_depth=num("step_depth", "스텝 깊이"),
            handrail_height=num("handrail_height", "핸드레일 높이"),
            headroom=num("headroom", "머리 높이"),
            name=self.name.strip())


class EscalatorDrafts:
    """에스컬레이터 입력 초안 목록"""

    def __init__(self):
        self.items: list[EscalatorDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 줄어 시작 층이 없어진 에스컬레이터는 가장 높은 가능한 층으로 옮김. 변경 여부 반환"""
        top = max(1, floor_count - 1)
        changed = False
        for it in self.items:
            if it.lower_floor > top:
                it.lower_floor = top
                changed = True
        return changed

    def to_specs(self, floor_count: int, start_station: float) -> list[EscalatorSpec]:
        """초안 → EscalatorSpec 목록. 잘못된 입력은 몇 번째 에스컬레이터인지 밝혀서 ValueError"""
        return [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: EscalatorDraft) -> str:
        return f"에스컬레이터 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")


def preview(it: EscalatorDraft, floor_height: float, start_station: float) -> str:
    """입력 중 미리보기: 층 바닥(FL) 기준·종단구배 무시 추정 (승강장 위·구배는 출력 시 정확히 다시 계산)"""
    try:
        sp = it.to_spec("", start_station)
        if not 0 < sp.angle_deg < 60:
            raise ValueError
    except ValueError:
        return "→ 입력값을 확인하세요"
    run = floor_height / math.tan(math.radians(sp.angle_deg))
    wp0 = sp.s_wp + start_station
    wp1 = wp0 + sp.direction * run
    lo, hi = sorted((wp0 - sp.direction * sp.lower_ext, wp1 + sp.direction * sp.upper_ext))
    return (f"→ WP 간 {run:.2f}m, 트러스 길이 {run + sp.lower_ext + sp.upper_ext:.2f}m, 상부 WP STA {wp1:.2f}\n"
            f"   STA {lo:.2f} ~ {hi:.2f},  t {sp.t_lo:g} ~ {sp.t_hi:g}  (FL 기준 추정)")
