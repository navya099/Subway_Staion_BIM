"""스크린도어(PSD) 입력의 화면 비의존 모델 (문자열 초안 → PsdSettings 변환 + 검증)"""
from dataclasses import dataclass

from gui.column_draft import _num
from psds.psd_spec import PsdSettings

_SPEC = PsdSettings()
EMERGENCY = {"+s 쪽": "+s", "−s 쪽": "-s", "없음": ""}
EMERGENCY_LABELS = list(EMERGENCY)

# (속성, 라벨, 규칙) — 'pos' 양수, 'nonneg' 0 이상
NUM_FIELDS = [("edge_offset", "연단 이격", "nonneg"), ("fixed_w", "고정부 폭", "pos"), ("door_w", "가동문 폭", "pos"),
              ("door_h", "문 높이", "pos"), ("header_h", "구동부 높이", "pos"), ("header_d", "구동부 깊이", "pos"),
              ("post_w", "POST 폭", "pos"), ("post_d", "POST 깊이", "pos"), ("frame_w", "프레임 폭", "pos"),
              ("frame_d", "프레임 두께", "pos"), ("kick_h", "하부 레일", "pos"), ("glass_t", "유리 두께", "pos")]


@dataclass
class PsdDraft:
    enabled: bool = True
    edge_offset: str = f"{_SPEC.edge_offset:g}"
    fixed_w: str = f"{_SPEC.fixed_w:g}"
    door_w: str = f"{_SPEC.door_w:g}"
    door_h: str = f"{_SPEC.door_h:g}"
    header_h: str = f"{_SPEC.header_h:g}"
    header_d: str = f"{_SPEC.header_d:g}"
    post_w: str = f"{_SPEC.post_w:g}"
    post_d: str = f"{_SPEC.post_d:g}"
    frame_w: str = f"{_SPEC.frame_w:g}"
    frame_d: str = f"{_SPEC.frame_d:g}"
    kick_h: str = f"{_SPEC.kick_h:g}"
    glass_t: str = f"{_SPEC.glass_t:g}"
    emergency: str = EMERGENCY_LABELS[0]

    def to_settings(self) -> PsdSettings:
        if not self.enabled:
            return PsdSettings(enabled=False)
        if self.emergency not in EMERGENCY:
            raise ValueError(f"스크린도어: 비상문 쪽이 올바르지 않습니다 ('{self.emergency}')")
        vals = {attr: _num(getattr(self, attr), "스크린도어", label, positive=rule == "pos", nonneg=rule == "nonneg")
                for attr, label, rule in NUM_FIELDS}
        return PsdSettings(enabled=True, emergency=EMERGENCY[self.emergency], **vals)


def preview(d: PsdDraft) -> str:
    if not d.enabled:
        return "→ 스크린도어 없음"
    try:
        ps = d.to_settings()
    except ValueError:
        return "→ 입력값을 확인하세요"
    return (f"→ 유닛 {ps.unit_w:g}m (고정 {ps.fixed_w:g} + 가동문 {ps.door_w:g} × 2 + 고정 {ps.fixed_w:g}) + POST {ps.post_w:g}m, "
            f"높이 {ps.height:g}m\n   열차 문마다 유닛 (문 간격 {ps.unit_w + ps.post_w:g}m 면 POST 공유, 넓으면 채움 패널)")
