"""계단·ESC 입구 천장 제연경계벽 입력의 화면 비의존 모델 (문자열 초안 → SmokeBarrierSettings + 검증)"""
from dataclasses import dataclass

from gui.column_draft import _num
from smokewalls.smoke_spec import SmokeBarrierSettings

NUM_FIELDS = [("depth", "천장 아래 깊이"), ("frame_h", "프레임 높이"), ("frame_d", "프레임 두께"), ("glass_t", "유리 두께"),
              ("glass_alpha", "유리 불투명도")]


@dataclass
class SmokeDraft:
    """제연경계벽 (모든 계단·ESC 공통). glass_rgb = 'R, G, B' (0~255)"""
    enabled: bool = True                 # GUI 는 기본으로 생성
    escalators: bool = True
    depth: str = "0.6"
    frame_h: str = "0.05"
    frame_d: str = "0.05"
    frame_material: str = "알루미늄 프레임"
    glass_t: str = "0.012"
    glass_rgb: str = "150, 205, 190"
    glass_alpha: str = "0.35"

    def to_settings(self) -> SmokeBarrierSettings:
        if not self.enabled:
            return SmokeBarrierSettings(enabled=False)
        where = "제연경계벽"
        vals = {a: _num(getattr(self, a), where, lb) for a, lb in NUM_FIELDS}
        parts = [x.strip() for x in str(self.glass_rgb).replace(";", ",").split(",") if x.strip()]
        try:
            rgb = tuple(int(float(x)) for x in parts)
        except ValueError:
            raise ValueError(f"{where}: 유리 색은 'R, G, B' (0 ~ 255) 로 입력하세요 ('{self.glass_rgb}')") from None
        sb = SmokeBarrierSettings(enabled=True, escalators=bool(self.escalators), glass_rgb=rgb,
                                  frame_material=str(self.frame_material).strip() or "알루미늄 프레임", **vals)
        try:
            sb.check()
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None
        return sb


def preview(d: SmokeDraft) -> str:
    if not d.enabled:
        return "→ 제연경계벽 없음"
    try:
        sb = d.to_settings()
    except ValueError:
        return "→ 입력값을 확인하세요"
    who = "계단·에스컬레이터" if sb.escalators else "계단"
    return (f"→ {who} 입구 쪽 오프닝 가장자리 천장에서 {sb.depth:g}m 내려온 유리벽 (위·아래 프레임). "
            f"그만큼 오프닝을 늘려 아래 머리 높이 확보")
