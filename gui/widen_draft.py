"""구조물 확폭 입력의 화면 비의존 모델 (문자열 초안 → WidenSpec 변환 + 검증).

확폭 1개 = 쪽(+t / −t) · 적용 층(쉼표, 비우면 모든 층 — 'B2F' 같은 층 이름 또는 1 = 최하층 번호) ·
완전 확폭 구간 시작·끝 STA(비우면 시점·종점까지) · 확폭량 · 시작/끝 전이 길이(비우면 확폭량 = 45°, 0 = 직각).
"""
from dataclasses import dataclass

from gui.column_draft import _num, level_name
from config.widening import WidenSpec

SIDES = ["+t (왼쪽)", "−t (오른쪽)"]
_SIDE = {SIDES[0]: 1, SIDES[1]: -1}


@dataclass
class WidenDraft:
    side: str = SIDES[0]
    floors: str = ""
    s_start: str = ""
    s_end: str = ""
    amount: str = "2"
    taper_in: str = ""
    taper_out: str = ""

    def to_spec(self, where: str, start_station: float, floor_count: int) -> WidenSpec:
        if self.side not in _SIDE:
            raise ValueError(f"{where}: 쪽이 올바르지 않습니다 ('{self.side}')")
        names = {level_name(floor_count, n): n for n in range(1, floor_count + 1)}
        floors = []
        for tok in [x.strip() for x in str(self.floors).replace(" ", "").split(",") if x.strip()]:
            if tok.upper() in {k.upper(): k for k in names}:
                floors.append(names[next(k for k in names if k.upper() == tok.upper())])
            else:
                try:
                    floors.append(int(tok))
                except ValueError:
                    raise ValueError(f"{where}: 층 '{tok}' 을(를) 알 수 없습니다 (예: B2F 또는 1 = 최하층)") from None
        opt = lambda v, label: None if not str(v).strip() else _num(v, where, label)
        a, b = opt(self.s_start, "시작 STA"), opt(self.s_end, "끝 STA")
        return WidenSpec(side=_SIDE[self.side], floors=sorted(set(floors)),
                         s_start=None if a is None else a - start_station, s_end=None if b is None else b - start_station,
                         amount=_num(self.amount, where, "확폭량", positive=True),
                         taper_in=opt(self.taper_in, "시작 전이 길이"), taper_out=opt(self.taper_out, "끝 전이 길이"))


class WidenDrafts:
    def __init__(self):
        self.items: list[WidenDraft] = []

    def to_specs(self, start_station: float, floor_count: int) -> list:
        return [it.to_spec(f"확폭 {i + 1}", start_station, floor_count) for i, it in enumerate(self.items)]
