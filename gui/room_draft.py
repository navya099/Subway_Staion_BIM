"""실(구획) 입력의 화면 비의존 모델 (문자열 초안 → RoomSpec / RoomSettings 변환 + 검증)"""
from dataclasses import dataclass, field

from gui.column_draft import _num, level_name
from rooms.room_spec import DOOR_KINDS, PARTITION, SEPARATION, DoorSpec, RoomSettings, RoomSpec, snap_to_clear

_SET = RoomSettings()

B_PARTITION = "칸막이벽"
B_SEPARATION = "구획분리"
BOUNDARY_LABELS = [B_PARTITION, B_SEPARATION]
_BOUNDARY = {B_PARTITION: PARTITION, B_SEPARATION: SEPARATION}

# 문이 있는 변: 화면 표기 → 모델 값.  ±t 변(s 방향 벽)은 문 중심을 STA 로, ±s 변(t 방향 벽)은 t 로 입력
DOOR_SIDE_LABELS = {"−t 변 (오른쪽)": "-t", "+t 변 (왼쪽)": "+t", "−s 변 (시점 쪽)": "-s", "+s 변 (종점 쪽)": "+s"}
DOOR_KIND_LABELS = list(DOOR_KINDS)


def door_center_label(side_label: str) -> str:
    return "중심 STA" if DOOR_SIDE_LABELS.get(side_label, "+t") in ("+t", "-t") else "중심 t"


@dataclass
class DoorDraft:
    """문 1개 (입력창 문자열). center: ±t 변이면 절대 STA, ±s 변이면 t"""
    side: str = "−t 변 (오른쪽)"
    center: str = "0"
    width: str = "0.9"
    height: str = "2.1"
    kind: str = "여닫이"

    def to_spec(self, where: str, start_station: float) -> DoorSpec:
        if self.side not in DOOR_SIDE_LABELS:
            raise ValueError(f"{where}: 문 변이 올바르지 않습니다 ('{self.side}')")
        if self.kind not in DOOR_KINDS:
            raise ValueError(f"{where}: 문 종류가 올바르지 않습니다 ('{self.kind}')")
        side = DOOR_SIDE_LABELS[self.side]
        c = _num(self.center, where, door_center_label(self.side))
        return DoorSpec(side=side, center=c - start_station if side in ("+t", "-t") else c,
                        width=_num(self.width, where, "문 폭", positive=True),
                        height=_num(self.height, where, "문 높이", positive=True), kind=self.kind)


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
    doors: list = field(default_factory=list)     # DoorDraft
    finish: str = "(용도 기준)"                    # 마감 종류 덮어쓰기 ('(용도 기준)' = 용도 이름으로 마감표에서 찾음)

    def to_spec(self, where: str, start_station: float) -> RoomSpec:
        if not str(self.use).strip():
            raise ValueError(f"{where}: 용도를 입력하세요")
        if self.boundary not in _BOUNDARY:
            raise ValueError(f"{where}: 경계 종류가 올바르지 않습니다 ('{self.boundary}')")
        kind = _BOUNDARY[self.boundary]
        sep_t = _num(self.sep_t, where, "구획분리 두께", nonneg=True) if kind == SEPARATION else 0.0
        doors = [d.to_spec(f"{where} 문 {k}", start_station) for k, d in enumerate(self.doors, start=1)]
        finish = "" if str(self.finish).strip() in ("", "(용도 기준)") else str(self.finish).strip()
        return RoomSpec(floor=self.floor, use=str(self.use).strip(), boundary=kind, sep_t=sep_t, doors=doors, finish=finish,
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


def preview(it: RoomDraft, start_station: float, floor_count: int, clear=None, partition_t: float = 0.2) -> str:
    """입력 중 미리보기: 층·용도, 크기·면적 (칸막이벽 중심선 기준).
    clear = (내공 길이, 내공 폭): 주면 내공면에 붙는 경계를 붙인 값으로 보여 주고 알림"""
    try:
        sp = it.to_spec("", start_station)
    except ValueError:
        return "→ 입력값을 확인하세요"
    note = ""
    if clear is not None and sp.s0 < sp.s1 and sp.t0 < sp.t1:
        try:
            snapped = snap_to_clear(sp, clear[0], clear[1] / 2.0, RoomSettings(partition_t=float(partition_t)))
        except (TypeError, ValueError):
            snapped = sp
        if snapped is not sp:
            moved = [f"{lab} {a:g}→{b:g}" for lab, a, b in (("s0", sp.s0, snapped.s0), ("s1", sp.s1, snapped.s1),
                                                           ("t0", sp.t0, snapped.t0), ("t1", sp.t1, snapped.t1)) if a != b]
            note = "\n   (내공면에 붙임: " + ", ".join(moved) + ")"
            sp = snapped
    ds, dt = sp.s1 - sp.s0, sp.t1 - sp.t0
    if ds <= 0 or dt <= 0:
        return "→ 시작 < 끝 이어야 합니다"
    edge = "칸막이벽" if sp.boundary == PARTITION else ("구획분리 가상 경계선" if sp.sep_t == 0 else f"구획분리 벽 {sp.sep_t:g}m")
    doors = f", 문 {len(sp.doors)}개" if sp.doors else ""
    return f"→ {level_name(floor_count, sp.floor)} {sp.use}: {ds:g} x {dt:g} m = {sp.area:.1f} m² (경계: {edge}, 중심선 기준){doors}{note}"
