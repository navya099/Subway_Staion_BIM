"""외부 엘리베이터 입력의 화면 비의존 모델 (문자열 초안 → ExtEvSpec). 엘리베이터 탭에서 입력 — 출구통로·출입구와 별개 객체"""
from dataclasses import dataclass

from elevators.ext_ev import ExtEvSpec
from gui.column_draft import _num

_SPEC = ExtEvSpec()                # 초기값은 모델 기본값이 단일 출처

HOST_PASSAGE = "출구통로 옆"
HOST_WALL = "본체 측벽 옆"
HOST_ENTRANCE = "출입구 좌표"
HOST_STATION = "정거장 좌표"
HOSTS = {HOST_PASSAGE: "passage", HOST_WALL: "wall", HOST_ENTRANCE: "entrance", HOST_STATION: "station"}
HOST_LABELS = list(HOSTS)
SIDES = {"왼쪽 (+)": 1, "오른쪽 (−)": -1}
SIDE_LABELS = list(SIDES)
FACES = ["+u", "-u", "+t", "-t"]
SAME_FACE = "(지상과 같음)"
CAR_AT = {"지상": "ground", "지하": "low"}
CAR_LABELS = list(CAR_AT)
LOW_GLASS = "투시형 (유리+강관)"
LOW_CLOSED = "폐쇄형 (문+문틀)"
LOW_FINISHES = {LOW_GLASS: "glass", LOW_CLOSED: "closed"}
LOW_LABELS = list(LOW_FINISHES)

# 위치 기준 → 그 기준에서만 쓰는 (속성, 라벨) 입력칸
PLACE_FIELDS = {HOST_PASSAGE: [("along", "통로 거리(m)")],
                HOST_WALL: [("sta", "중심 STA")],
                HOST_ENTRANCE: [("u", "u"), ("t", "t"), ("low_z", "지하 EL(비우면 통로 끝 바닥)")],
                HOST_STATION: [("sta", "중심 STA"), ("t", "t"), ("low_z", "지하 EL")]}


@dataclass
class ExtEvDraft:
    """외부 엘리베이터 1대 (입력창 문자열 그대로 보관)
    host: 위치 기준 이름표, host_name: 출구통로·출입구 이름 (하나뿐이면 비워도 됨), sta: 절대 STA (정거장 좌표)"""
    name: str = ""
    host: str = HOST_PASSAGE
    host_name: str = ""
    along: str = "6"
    side: str = SIDE_LABELS[0]
    floor: int = 2                        # 본체 측벽 옆: 문이 나는 층 (1 = 최하층)
    u: str = "0"
    sta: str = "0"
    t: str = "0"
    face: str = FACES[0]
    low_face: str = SAME_FACE
    low_z: str = ""
    ground_el: str = ""                   # 비우면 출입구 지표 → 정거장 공통 지표
    car_at: str = CAR_LABELS[0]
    car_offset: str = "0"
    door_open: str = "0"
    line_name: str = ""
    sign_bg: str = _SPEC.sign_bg
    low_finish: str = LOW_GLASS           # 지하 정면 마감 (화면 기본 투시형, 모델 기본 폐쇄형)

    def to_spec(self, where: str, start_station: float) -> ExtEvSpec:
        if self.host not in HOSTS:
            raise ValueError(f"{where}: 위치 기준이 올바르지 않습니다 ('{self.host}')")
        if self.face not in FACES or (self.low_face != SAME_FACE and self.low_face not in FACES):
            raise ValueError(f"{where}: 문 방향이 올바르지 않습니다")
        if self.car_at not in CAR_AT or self.side not in SIDES:
            raise ValueError(f"{where}: 카 정지층·통로 쪽이 올바르지 않습니다")
        if self.low_finish not in LOW_FINISHES:
            raise ValueError(f"{where}: 지하 마감이 올바르지 않습니다 ('{self.low_finish}')")
        blank = lambda v, label: None if not str(v).strip() else _num(v, where, label)
        bg = str(self.sign_bg).strip() or _SPEC.sign_bg
        h = bg.lstrip("#")
        if len(h) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in h):
            raise ValueError(f"{where}: 사인 배경색은 #RRGGBB 형식이어야 합니다 ('{bg}')")
        v = dict(name=self.name.strip(), host=HOSTS[self.host], face=self.face, ground_el=blank(self.ground_el, "지표 EL"),
                 car_at=CAR_AT[self.car_at], car_offset=_num(self.car_offset, where, "카 위치 오프셋"),
                 door_open=_num(self.door_open, where, "문 열림", nonneg=True), line_name=str(self.line_name).strip(),
                 sign_bg="#" + h.upper(), low_finish=LOW_FINISHES[self.low_finish])
        if self.host == HOST_PASSAGE:                              # 지하 문·지하 바닥 = 통로 쪽 자동
            return ExtEvSpec(host_name=self.host_name.strip(), along=_num(self.along, where, "통로 거리", nonneg=True),
                             host_side=SIDES[self.side], **v)
        if self.host == HOST_WALL:                                 # 지하 문 = 본체 쪽, 지하 바닥 = 그 자리 바닥 마감면
            return ExtEvSpec(u=_num(self.sta, where, "중심 측점") - start_station, floor=int(self.floor), host_side=SIDES[self.side], **v)
        v.update(t=_num(self.t, where, "t 위치"), low_z=blank(self.low_z, "지하 EL"),
                 low_face=None if self.low_face == SAME_FACE else self.low_face)
        if self.host == HOST_ENTRANCE:
            return ExtEvSpec(host_name=self.host_name.strip(), u=_num(self.u, where, "u 위치"), **v)
        return ExtEvSpec(u=_num(self.sta, where, "중심 측점") - start_station, **v)


class ExtEvDrafts:
    """외부 엘리베이터 입력 초안 목록"""

    def __init__(self):
        self.items: list[ExtEvDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 바뀌면 문이 나는 층을 새 층수 안으로. 변경 여부 반환"""
        changed = False
        for it in self.items:
            n = min(max(it.floor, 1), max(1, floor_count))
            changed |= n != it.floor
            it.floor = n
        return changed

    def to_specs(self, start_station: float) -> list[ExtEvSpec]:
        return [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: ExtEvDraft) -> str:
        return f"외부 엘리베이터 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")


def preview(it: ExtEvDraft, start_station: float) -> str:
    """입력 중 미리보기: 위치 기준 요약 (실제 겹침·범위는 미리보기 갱신 때 검사)"""
    try:
        sp = it.to_spec("", start_station)
    except ValueError as e:
        return f"→ 입력값을 확인하세요{str(e) if str(e).startswith(':') else ''}"
    size = f"외곽 {sp.width:g} × {sp.depth:g} · 지하 {'투시형' if sp.low_finish == 'glass' else '폐쇄형'}"
    if sp.host == "passage":
        return f"→ {sp.host_name or '출구통로'} 시작에서 {sp.along:g}m, {'왼쪽' if sp.host_side > 0 else '오른쪽'} 벽 공유 · 지하 문 = 통로 쪽 · {size}"
    if sp.host == "wall":
        return f"→ STA {sp.u + start_station:.2f} {'왼쪽(+t)' if sp.host_side > 0 else '오른쪽(−t)'} 본체 측벽 공유 · 지하 문 = 본체 쪽 · {size}"
    if sp.host == "entrance":
        return f"→ {sp.host_name or '출입구'} 좌표 u {sp.u:g}, t {sp.t:g} · 지하 문 {sp.low_face or sp.face} · {size}"
    return f"→ STA {sp.u + start_station:.2f}, t {sp.t:g} (u = 선형 진행방향) · 지하 문 {sp.low_face or sp.face} · {size}"


def migrate_entrance_evs(entrance_items: list) -> list:
    """옛 프로젝트: 출입구 입력에 들어 있던 외부 EV(ev_*) → 독립 외부 엘리베이터 초안. 출입구 이름·통로·지표·사인을 이어받음"""
    out = []
    for i, e in enumerate(entrance_items, start=1):
        if not isinstance(e, dict) or not e.get("ev_on"):
            continue
        get = lambda k, d="": str(e.get(k) if e.get(k) is not None else d)
        nm = get("name").strip() or f"EN{i}"
        beside = get("ev_host") == HOST_PASSAGE
        out.append(ExtEvDraft(name=f"{nm}_EV1", host=HOST_PASSAGE if beside else HOST_ENTRANCE,
                              host_name=(get("ev_host_name").strip() or get("passage")) if beside else nm,
                              along=get("ev_along"), side=get("ev_side", SIDE_LABELS[0]), u=get("ev_u"), t=get("ev_t"),
                              face=get("ev_face", FACES[0]), low_face=get("ev_low_face", SAME_FACE), low_z=get("ev_low_z"),
                              ground_el=get("ground_el"), car_at=get("ev_car_at", CAR_LABELS[0]),
                              door_open=get("ev_door_open", "0"), line_name=get("line_name"), sign_bg=get("sign_bg", _SPEC.sign_bg)))
    return out
