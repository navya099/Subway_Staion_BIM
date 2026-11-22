"""출입구 입력의 화면 비의존 모델 (문자열 초안 → EntranceSpec 변환 + 검증)"""
from dataclasses import dataclass, field

from entrances.entrance_spec import EntranceSpec
from gui.column_draft import _num

_SPEC = EntranceSpec()              # 초기값은 모델 기본값이 단일 출처

SIDE_LEFT = "왼쪽 (+t)"
SIDE_RIGHT = "오른쪽 (−t)"
SIDES = [SIDE_LEFT, SIDE_RIGHT]
_SIDE = {SIDE_LEFT: 1, SIDE_RIGHT: -1}

# (속성, 라벨, 양수만 / 0 이상) — 숫자 입력칸
NUM_FIELDS = [("ground_el", "지표 EL", None), ("stair_width", "계단 폭", "pos"), ("partition_t", "칸막이벽", "pos"),
              ("escalator_zone", "ESC 구역 폭", "pos"), ("wall_t", "벽·슬래브 두께", "pos"), ("haunch_w", "헌치 폭", "nonneg"),
              ("haunch_h", "헌치 높이", "nonneg"), ("lower_margin", "하부 여유", "nonneg"), ("top_margin", "상부 여유", "nonneg"),
              ("parapet", "파라펫", "nonneg"), ("riser_max", "단높이 상한", "pos"), ("tread", "단너비", "pos"),
              ("flight_rise_max", "런 높이 상한", "pos"), ("landing_len", "계단참 길이", "pos"),
              ("stair_slab_t", "계단 슬래브", "pos"), ("stair_headroom", "계단 머리 높이", "pos"),
              ("roof_cover", "흙 덮개", "nonneg"), ("lean_t", "버림 콘크리트", "nonneg"), ("lean_ext", "버림 내민 폭", "nonneg"),
              ("top_rise", "상부 지표 위 높이", "nonneg"), ("ramp_width", "바깥 경사로 폭", "nonneg"),
              ("ramp_ratio", "경사로 기울기 1/n", "pos"), ("out_riser_max", "바깥 단높이 상한", "pos"),
              ("out_tread", "바깥 단너비", "pos"), ("open_narrow", "개구부 내공 축소", "nonneg"),
              ("open_wall_t", "개구부 벽 두께", "opt"), ("taper_ratio", "바깥면 전이 길이/차", "nonneg"),
              ("fc_length", "앞마당 길이", "pos"), ("fc_flat", "앞마당 평탄 길이", "opt0"),
              ("fc_pave_t", "앞마당 포장 두께", "nonneg"), ("parapet_t", "파라펫 두께", "opt"),
              ("top_ffl", "승강구 마감 두께", "nonneg"), ("landing_t", "승강구 슬래브", "pos"),
              ("cp_height", "캐노피 높이", "pos"), ("cp_slope", "캐노피 기울기", "nonneg"), ("cp_front", "캐노피 앞 내밈", "nonneg"),
              ("cp_spacing", "캐노피 기둥 간격", "pos"), ("cp_sign_w", "출구 사인 폭", "pos"), ("cp_sign_h", "출구 사인 높이", "pos"),
              ("arch_h", "건축 벽체 높이", "pos"), ("arch_t", "건축 벽체 두께", "opt")]

OUTDOOR_FORECOURT = "앞마당 슬래브"
OUTDOOR_STEPS = "경사로·계단"
OUTDOORS = [OUTDOOR_FORECOURT, OUTDOOR_STEPS]
_OUTDOOR = {OUTDOOR_FORECOURT: "forecourt", OUTDOOR_STEPS: "steps"}


@dataclass
class EntranceDraft:
    """출입구 1개 (입력창 문자열 그대로 보관). stair_offset 이 비어 있으면 계단 시작 위치 자동"""
    name: str = ""
    passage: str = "EX1"
    escalator: bool = True
    stair: bool = True
    escalator_count: str = "1"            # 에스컬레이터 대수 (모두 같은 제원, 나란히)
    side: str = SIDE_LEFT
    ground_el: str = ""                  # 비우면 정거장 공통 지표 EL
    stair_width: str = f"{_SPEC.stair_width:g}"
    partition_t: str = f"{_SPEC.partition_t:g}"
    escalator_zone: str = f"{_SPEC.escalator_zone:g}"
    wall_t: str = f"{_SPEC.wall_t:g}"
    haunch_w: str = f"{_SPEC.haunch_w:g}"
    haunch_h: str = f"{_SPEC.haunch_h:g}"
    lower_margin: str = f"{_SPEC.lower_margin:g}"
    top_margin: str = f"{_SPEC.top_margin:g}"
    parapet: str = f"{_SPEC.parapet:g}"
    riser_max: str = f"{_SPEC.riser_max:g}"
    tread: str = f"{_SPEC.tread:g}"
    flight_rise_max: str = f"{_SPEC.flight_rise_max:g}"
    landing_len: str = f"{_SPEC.landing_len:g}"
    stair_slab_t: str = f"{_SPEC.stair_slab_t:g}"
    stair_headroom: str = f"{_SPEC.stair_headroom:g}"
    stair_offset: str = ""
    roof_cover: str = f"{_SPEC.roof_cover:g}"
    lean_t: str = f"{_SPEC.lean_t:g}"
    lean_ext: str = f"{_SPEC.lean_ext:g}"
    top_rise: str = f"{_SPEC.top_rise:g}"
    ramp_width: str = f"{_SPEC.ramp_width:g}"
    ramp_ratio: str = f"{_SPEC.ramp_ratio:g}"
    out_riser_max: str = f"{_SPEC.out_riser_max:g}"
    out_tread: str = f"{_SPEC.out_tread:g}"
    open_narrow: str = f"{_SPEC.open_narrow:g}"
    open_wall_t: str = ""                 # 비우면 두께 구간 그대로
    taper_ratio: str = "2"                # 화면 기본 = 실무 평면도 (모델 기본 0 = 직각 계단)
    outdoor: str = OUTDOOR_FORECOURT      # 바깥 접근 형식 (화면 기본 = 실무 상세 앞마당, 모델 기본 = 경사로·계단)
    fc_length: str = f"{_SPEC.fc_length:g}"
    fc_flat: str = ""                     # 비우면 자동 (포장 윗면이 앞마당 끝에서 지표)
    fc_pave_t: str = f"{_SPEC.fc_pave_t:g}"
    parapet_t: str = ""                   # 비우면 천장 끝·벽 두께 그대로
    top_ffl: str = "0.1"                  # 화면 기본 = 실무 상세 (모델 기본 0)
    landing_t: str = f"{_SPEC.landing_t:g}"
    canopy: bool = True                   # 화면 기본 = 캐노피 있음 (모델 기본 끔)
    cp_wall: bool = True                  # 캐노피 외부 차단 유리벽 (옆·뒤)
    cp_height: str = f"{_SPEC.cp_height:g}"
    cp_slope: str = f"{_SPEC.cp_slope:g}"
    cp_front: str = f"{_SPEC.cp_front:g}"
    cp_spacing: str = f"{_SPEC.cp_spacing:g}"
    cp_sign_w: str = f"{_SPEC.cp_sign_w:g}"
    cp_sign_h: str = f"{_SPEC.cp_sign_h:g}"
    exit_number: str = ""                 # 비우면 사인 설정 출구 안내 / 통로 순번
    line_name: str = ""                   # 출구 사인 노선명
    sign_bg: str = _SPEC.sign_bg          # 출구 사인 배경색 (#RRGGBB)
    arch_wall: bool = True                # 건축 마감 벽체 (화면 기본 켬, 모델 끔)
    arch_h: str = f"{_SPEC.arch_h:g}"
    arch_t: str = ""                      # 비우면 파라펫 두께 + 0.15
    finish: str = "(통로 기준)"                       # 내부 마감 종류 ('(통로 기준)' = 붙은 출구통로의 마감 종류)
    thick_zones: list = field(default_factory=list)   # 두께 구간 [[u 시작, 두께], ...] (문자열, 비우면 벽·슬래브 두께 일정)

    def zones(self, where: str) -> list:
        """두께 구간 → [(u 시작, 두께)] (u 순서, 둘 다 빈 줄은 건너뜀)"""
        out = []
        for k, row in enumerate(self.thick_zones, start=1):
            u, t = (str(x).strip() for x in (list(row) + ["", ""])[:2])
            if not u and not t:
                continue
            w = f"{where} 두께 구간 {k}"
            out.append((_num(u, w, "시작 위치", nonneg=True), _num(t, w, "두께", positive=True)))
        return sorted(out)

    def _color(self, where: str) -> str:
        """배경색 '#RRGGBB' (비우면 기본)"""
        v = str(self.sign_bg).strip() or _SPEC.sign_bg
        h = v.lstrip("#")
        if len(h) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in h):
            raise ValueError(f"{where}: 출구 사인 배경색은 #RRGGBB 형식이어야 합니다 ('{v}')")
        return "#" + h.upper()

    def to_spec(self, where: str) -> EntranceSpec:
        if self.side not in _SIDE:
            raise ValueError(f"{where}: 에스컬레이터 쪽이 올바르지 않습니다 ('{self.side}')")
        if not self.passage.strip():
            raise ValueError(f"{where}: 이어 붙일 출구통로 이름을 입력하세요")
        vals = {}
        for attr, label, rule in NUM_FIELDS:
            if attr == "ground_el" and not str(self.ground_el).strip():
                vals[attr] = None                        # 정거장 공통 지표 EL
                continue
            if rule in ("opt", "opt0"):                  # 비우면 None, 주면 양수 (opt0 = 0 이상)
                vals[attr] = None if not str(getattr(self, attr)).strip() else \
                    _num(getattr(self, attr), where, label, positive=rule == "opt", nonneg=rule == "opt0")
                continue
            vals[attr] = _num(getattr(self, attr), where, label, positive=rule == "pos", nonneg=rule == "nonneg")
        offset = None if not str(self.stair_offset).strip() else _num(self.stair_offset, where, "계단 시작 조정")
        if self.outdoor not in _OUTDOOR:
            raise ValueError(f"{where}: 바깥 접근 형식이 올바르지 않습니다 ('{self.outdoor}')")
        if not self.stair and not self.escalator:
            raise ValueError(f"{where}: 계단과 에스컬레이터 중 하나는 있어야 합니다")
        try:
            n_esc = int(str(self.escalator_count).strip() or "1")
        except ValueError:
            raise ValueError(f"{where}: 에스컬레이터 대수가 정수가 아닙니다 ('{self.escalator_count}')") from None
        return EntranceSpec(passage=self.passage.strip(), escalator=bool(self.escalator), escalator_side=_SIDE[self.side],
                            stair=bool(self.stair), escalator_count=n_esc, outdoor=_OUTDOOR[self.outdoor],
                            canopy=bool(self.canopy), cp_wall=bool(self.cp_wall), exit_number=str(self.exit_number).strip(),
                            line_name=str(self.line_name).strip(), sign_bg=self._color(where),
                            arch_wall=bool(self.arch_wall),
                            stair_offset=offset, name=self.name.strip(), thickness_zones=self.zones(where),
                            finish="" if str(self.finish).strip() in ("", "(통로 기준)") else str(self.finish).strip(), **vals)


def zones_summary(it: EntranceDraft) -> str:
    """두께 구간 요약 (탭의 버튼 옆 글자)"""
    try:
        zs = it.zones("")
    except ValueError:
        return "두께 구간: 입력값 확인"
    if not zs:
        return "두께 구간: 없음 (벽·슬래브 두께 일정)"
    return "두께 구간: " + ", ".join(f"u {u:g}~ {t:g}" for u, t in zs)


class EntranceDrafts:
    """출입구 입력 초안 목록"""

    def __init__(self):
        self.items: list[EntranceDraft] = []

    def to_specs(self) -> list[EntranceSpec]:
        return [it.to_spec(self.where(i, it)) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: EntranceDraft) -> str:
        return f"출입구 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")


def preview(it: EntranceDraft) -> str:
    """입력 중 미리보기: 내공 폭 구성 (높이·길이는 통로 끝 표고가 정해지는 출력 시 계산)"""
    try:
        sp = it.to_spec("")
    except ValueError:
        return "→ 입력값을 확인하세요"
    n = sp.n_escalators
    esc = f"에스컬레이터 {sp.escalator_zone:g}" + (f" + 트러스 {sp.esc_truss_width:g} × {n - 1} ({n}대 붙임)" if n > 1 else "")
    if sp.escalator and sp.stair:
        side = "왼쪽" if sp.escalator_side > 0 else "오른쪽"
        parts = f"계단 {sp.stair_width:g} + 칸막이 {sp.partition_t:g} + {esc} ({side})"
    elif sp.escalator:
        parts = esc + " (계단 없음)"
    else:
        parts = f"계단 {sp.stair_width:g}"
    return (f"→ 내공 폭 {sp.inner_width:g}m = {parts}\n"
            f"   통로 {sp.passage} 끝에서 " + ("정거장 공통 지표 EL" if sp.ground_el is None else f"지표 EL {sp.ground_el:g}")
            + " 까지 자동 계산"
            + ("" if sp.stair_offset is None else f", 계단 시작 조정 {sp.stair_offset:g}m")
            + (f"\n   두께 구간 {len(sp.thickness_zones)}개 (u = 통로 끝 이음면에서 거리)" if sp.thickness_zones else ""))
