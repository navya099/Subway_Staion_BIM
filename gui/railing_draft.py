"""오프닝 유리난간 입력의 화면 비의존 모델 (문자열 초안 → RailingSettings + 검증)"""
from dataclasses import dataclass

from gui.column_draft import _num
from railings.railing_spec import RailingSettings

# (속성, 라벨) 숫자 칸
NUM_FIELDS = [("curb_w", "경계석 폭"), ("curb_h", "경계석 높이"), ("plate_t", "석판 두께"), ("skirt_t", "걸레받이 두께"),
              ("post_spacing", "POST 간격"),
              ("post_w", "POST 두께"), ("post_d", "POST 폭"), ("rail_d", "레일 지름"),
              ("rail_h1", "위 레일 높이"), ("rail_h2", "아래 레일 높이"), ("glass_t", "유리 두께"),
              ("glass_alpha", "유리 불투명도")]
TEXT_FIELDS = [("curb_material", "석판 재질"), ("skirt_material", "걸레받이 재질"), ("post_material", "POST·레일 재질")]


@dataclass
class RailingDraft:
    """유리난간 입력 (모든 계단·ESC 오프닝 공통). glass_rgb = 'R, G, B' (0~255)"""
    enabled: bool = True                 # GUI 는 기본으로 생성
    escalators: bool = True
    curb_w: str = "0.25"
    curb_h: str = "0.15"
    curb_material: str = "화강석"
    plate_t: str = "0.03"
    skirt_t: str = "0.02"
    skirt_material: str = "흑색 걸레받이"
    post_w: str = "0.015"
    post_d: str = "0.06"
    post_spacing: str = "1.2"
    post_material: str = "스테인리스"
    rail_d: str = "0.05"
    rail_h1: str = "1.2"
    rail_h2: str = "0.95"
    glass_t: str = "0.012"
    glass_rgb: str = "150, 205, 190"
    glass_alpha: str = "0.35"

    def to_settings(self) -> RailingSettings:
        where = "유리난간"
        if not self.enabled:
            return RailingSettings(enabled=False)
        vals = {a: _num(getattr(self, a), where, lb) for a, lb in NUM_FIELDS}
        texts = {a: str(getattr(self, a)).strip() or getattr(RailingSettings, a) for a, _ in TEXT_FIELDS}
        parts = [x.strip() for x in str(self.glass_rgb).replace(";", ",").split(",") if x.strip()]
        try:
            rgb = tuple(int(float(x)) for x in parts)
        except ValueError:
            raise ValueError(f"{where}: 유리 색은 'R, G, B' (0 ~ 255) 로 입력하세요 ('{self.glass_rgb}')") from None
        rs = RailingSettings(enabled=True, escalators=bool(self.escalators), glass_rgb=rgb, **vals, **texts)
        try:
            rs.check()
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None
        return rs


def preview(d: RailingDraft) -> str:
    if not d.enabled:
        return "→ 유리난간 없음"
    try:
        rs = d.to_settings()
    except ValueError:
        return "→ 입력값을 확인하세요"
    who = "계단·에스컬레이터" if rs.escalators else "계단"
    return (f"→ {who} 오프닝 둘레(도착 쪽 제외)에 경계석 {rs.curb_w:g}×{rs.curb_h:g}({rs.skirt_material} 위 {rs.curb_material} 석판) + POST {rs.post_spacing:g} 간격 + "
            f"유리 {rs.glass_t * 1000:g}mm, 레일 마감면 +{rs.rail_h1:g}/+{rs.rail_h2:g}")
