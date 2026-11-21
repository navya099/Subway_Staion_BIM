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


def _t_ref(label: str, where: str) -> str:
    from finishes.finish_clear import T_REF_LABELS
    if label not in T_REF_LABELS:
        raise ValueError(f"{where}: t 기준이 올바르지 않습니다 ('{label}')")
    return T_REF_LABELS[label]


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
    t_ref: str = "중심"             # t 기준 (finishes.finish_clear.T_REF_LABELS) — 벽 마감면이면 t = 마감면에서의 이격 (≥ 0)
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
    side_clear: str = f"{_SPEC.side_clear:g}"      # 자동 오프닝 옆 여유 (양쪽)
    lower_radius: str = f"{_SPEC.lower_radius:g}"  # 하부 곡선 전이 반경 (0 = 꺾임)
    upper_radius: str = f"{_SPEC.upper_radius:g}"  # 상부 곡선 전이 반경
    skirt_height: str = f"{_SPEC.skirt_height:g}"  # 코 선 위 스커트 높이 (= 데크 하면)
    deck_width: str = f"{_SPEC.deck_width:g}"      # 안쪽 데크 폭
    glass_t: str = f"{_SPEC.glass_t:g}"            # 난간 유리 두께
    newel_ext: str = f"{_SPEC.newel_ext:g}"        # 스텝 끝 너머 난간 연장
    newel_radius: str = f"{_SPEC.newel_radius:g}"  # 끝 뉴얼 반경

    def to_spec(self, where: str, start_station: float) -> EscalatorSpec:
        if self.direction not in _DIR:
            raise ValueError(f"{where}: 오르는 방향이 올바르지 않습니다 ('{self.direction}')")
        num = lambda attr, label: _num(getattr(self, attr), where, label, positive=True)
        return EscalatorSpec(
            lower_floor=self.lower_floor,
            s_wp=_num(self.sta_wp, where, "하부 WP 측점") - start_station,
            direction=_DIR[self.direction],
            t_center=_num(self.t_center, where, "벽 마감면 이격" if "벽" in self.t_ref else "t 위치",
                          nonneg="벽" in self.t_ref),
            t_ref=_t_ref(self.t_ref, where),
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
            side_clear=_num(self.side_clear, where, "오프닝 옆 여유", nonneg=True),
            lower_radius=_num(self.lower_radius, where, "하부 전이 반경", nonneg=True),
            upper_radius=_num(self.upper_radius, where, "상부 전이 반경", nonneg=True),
            skirt_height=num("skirt_height", "스커트 높이"),
            deck_width=num("deck_width", "데크 폭"),
            glass_t=num("glass_t", "유리 두께"),
            newel_ext=_num(self.newel_ext, where, "뉴얼 연장", nonneg=True),
            newel_radius=num("newel_radius", "뉴얼 반경"),
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
            f"   STA {lo:.2f} ~ {hi:.2f},  {t_text(sp, sp.truss_width)}  (FL 기준 추정)")


def t_text(sp, width: float) -> str:
    """미리보기용 t 범위 문구 (벽 마감면 기준은 검증 때 실제 t 를 계산)"""
    ref = getattr(sp, "t_ref", "center")
    if ref.startswith("wall"):
        side = "왼쪽" if ref == "wall+t" else "오른쪽"
        return f"{side} 벽 마감면에서 {sp.t_center:g} 띄움 (폭 {width:g})"
    c = sp.t_center - width / 2.0 if ref == "+t" else (sp.t_center + width / 2.0 if ref == "-t" else sp.t_center)
    return f"t {c - width / 2.0:g} ~ {c + width / 2.0:g}"
