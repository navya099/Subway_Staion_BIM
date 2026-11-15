"""실(구획) 입력의 화면 비의존 모델 (문자열 초안 → RoomSpec / RoomSettings 변환 + 검증)"""
from dataclasses import dataclass, field

from gui.column_draft import _num, level_name
from rooms.room_spec import PARTITION, SEPARATION, RoomSettings, RoomSpec

_SET = RoomSettings()

B_PARTITION = "칸막이벽"
B_SEPARATION = "구획분리"
BOUNDARY_LABELS = [B_PARTITION, B_SEPARATION]
_BOUNDARY = {B_PARTITION: PARTITION, B_SEPARATION: SEPARATION}


@dataclass
class RoomDraft:
    """실 1개 (입력창 문자열 그대로 보관). STA 는 절대 측점 — 정거장 시작 측점을 빼서 s 로 변환.
    t 는 선형 중심 기준 (왼쪽 +), t0 < t1"""
    name: str = ""
    floor: int = 1
    use: str = "역무실"
    sta0: str = "0"
    sta1: str = "10"
    t0: str = "4"
    t1: str = "9"
    boundary: str = B_PARTITION          # 경계 종류: 칸막이벽 / 구획분리
    sep_t: str = "0"                     # 구획분리 두께 (0 = 가상 경계선)

    def to_spec(self, where: str, start_station: float) -> RoomSpec:
        if not str(self.use).strip():
            raise ValueError(f"{where}: 용도를 입력하세요")
        if self.boundary not in _BOUNDARY:
            raise ValueError(f"{where}: 경계 종류가 올바르지 않습니다 ('{self.boundary}')")
        kind = _BOUNDARY[self.boundary]
        sep_t = _num(self.sep_t, where, "구획분리 두께", nonneg=True) if kind == SEPARATION else 0.0
        return RoomSpec(floor=self.floor, use=str(self.use).strip(), boundary=kind, sep_t=sep_t,
                        s0=_num(self.sta0, where, "시작 STA") - start_station, s1=_num(self.sta1, where, "끝 STA") - start_station,
                        t0=_num(self.t0, where, "t 시작"), t1=_num(self.t1, where, "t 끝"), name=self.name.strip())


@dataclass
class RoomSettingsDraft:
    """실 공통 설정: 칸막이벽 두께, 층별 기본 실 용도 (층 번호 문자열 → 용도, 비우면 자동)"""
    partition_t: str = f"{_SET.partition_t:g}"
    default_uses: dict = field(default_factory=dict)

    def to_settings(self) -> RoomSettings:
        uses = {}
        for k, v in self.default_uses.items():
            if str(v).strip():
                uses[int(k)] = str(v).strip()
        return RoomSettings(default_uses=uses, partition_t=_num(self.partition_t, "실 설정", "칸막이벽 두께", positive=True))


class RoomDrafts:
    """실 입력 초안 목록 + 공통 설정"""

    def __init__(self):
        self.items: list[RoomDraft] = []
        self.settings = RoomSettingsDraft()

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 줄어 없어진 층의 실은 최상층으로 옮기고, 없어진 층의 기본 용도는 지움. 변경 여부 반환"""
        changed = False
        for it in self.items:
            if it.floor > floor_count:
                it.floor = max(1, floor_count)
                changed = True
        for k in [k for k in self.settings.default_uses if int(k) > floor_count]:
            del self.settings.default_uses[k]
            changed = True
        return changed

    def to_specs(self, start_station: float) -> list[RoomSpec]:
        return [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: RoomDraft) -> str:
        return f"실 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else f"({it.use})")


def preview(it: RoomDraft, start_station: float, floor_count: int) -> str:
    """입력 중 미리보기: 층·용도, 크기·면적 (칸막이벽 중심선 기준)"""
    try:
        sp = it.to_spec("", start_station)
    except ValueError:
        return "→ 입력값을 확인하세요"
    ds, dt = sp.s1 - sp.s0, sp.t1 - sp.t0
    if ds <= 0 or dt <= 0:
        return "→ 시작 < 끝 이어야 합니다"
    edge = "칸막이벽" if sp.boundary == PARTITION else ("구획분리 가상 경계선" if sp.sep_t == 0 else f"구획분리 벽 {sp.sep_t:g}m")
    return f"→ {level_name(floor_count, sp.floor)} {sp.use}: {ds:g} x {dt:g} m = {sp.area:.1f} m² (경계: {edge}, 중심선 기준)"
