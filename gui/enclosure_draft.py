"""계단·ESC 옆 벽체 + 하부 창고 입력의 화면 비의존 모델 (문자열 초안 → EnclosureSettings + 검증)"""
from dataclasses import dataclass

from gui.column_draft import _num
from stairs.stair_enclosure import EnclosureSettings

NUM_FIELDS = [("storage_h", "창고 높이 기준"), ("door_w", "창고 문 폭"), ("door_h", "창고 문 높이"), ("group_gap", "묶음 간격")]


@dataclass
class EnclosureDraft:
    """계단 옆 벽체 (모든 계단·ESC 공통). 벽 두께·재질은 실 탭 칸막이벽 설정"""
    enabled: bool = True                 # GUI 는 기본으로 생성
    escalators: bool = True
    storage: bool = True
    storage_use: str = "창고"
    storage_h: str = "2.1"
    door_w: str = "0.9"
    door_h: str = "2.1"
    group_gap: str = "1.0"
    door_back: bool = True               # 창고 문을 뒷 벽에 (끄면 옆 벽)

    def to_settings(self) -> EnclosureSettings:
        if not self.enabled:
            return EnclosureSettings(enabled=False)
        where = "계단 옆 벽체"
        vals = {a: _num(getattr(self, a), where, lb) for a, lb in NUM_FIELDS}
        es = EnclosureSettings(enabled=True, escalators=bool(self.escalators), storage=bool(self.storage),
                               storage_use=str(self.storage_use).strip(), door_at="back" if self.door_back else "side", **vals)
        es.check()
        return es


def preview(d: EnclosureDraft) -> str:
    if not d.enabled:
        return "→ 계단 옆 벽체 없음"
    try:
        es = d.to_settings()
    except ValueError:
        return "→ 입력값을 확인하세요"
    who = "계단·에스컬레이터" if es.escalators else "계단"
    where = "뒷 벽" if es.door_at == "back" else "옆 벽"
    store = (f", 하면이 바닥 마감면 + {es.storage_h:g} 넘는 곳부터 '{es.storage_use}'({where} 문 {es.door_w:g}×{es.door_h:g})"
             if es.storage else "")
    return f"→ {who} 노출된 긴 옆면을 칸막이벽으로 (앞면은 열림){store}. 벽 두께·재질 = 실 탭 칸막이벽"
