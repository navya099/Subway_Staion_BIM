"""사인(역명판·안내사인) 입력의 화면 비의존 모델 (문자열 초안 → SignSettings 변환 + 검증)"""
from dataclasses import dataclass, field

from gui.column_draft import _num
from signs.nameplate import STYLES
from signs.sign_spec import ExitInfo, SignSettings, StationInfo, StationRef

_SPEC = SignSettings()
_SI = StationInfo()
STYLE_LABELS = {s.label: s.id for s in STYLES.values()}
STYLE_NAMES = list(STYLE_LABELS)

# 숫자 칸 (속성, 라벨, 규칙)
PLATE_FIELDS = [("plate_interval", "간격", "pos"), ("plate_bottom", "하단 높이", "nonneg"), ("plate_h", "판 높이", "pos"),
                ("plate_t", "두께", "pos")]
HANG_FIELDS = [("hang_bottom", "하단 높이", "nonneg"), ("hang_w", "폭", "pos"), ("hang_h", "높이", "pos"),
               ("hang_t", "두께", "pos"), ("hang_offset", "거리", "nonneg")]
STATION_FIELDS = [("kname", "한글"), ("ename", "영문"), ("cname", "한자"), ("jname", "일문"), ("no", "역번호"), ("rgb", "노선색")]
NEIGHBOR_FIELDS = [("kname", "한글"), ("ename", "영문"), ("cname", "한자"), ("no", "역번호")]


@dataclass
class ExitDraft:
    passage: str = ""
    number: str = ""
    destinations: str = ""          # ' / ' 로 줄 구분


def _label_of(style_id: str) -> str:
    return next((k for k, v in STYLE_LABELS.items() if v == style_id), STYLE_NAMES[0])


@dataclass
class SignDraft:
    enabled: bool = True
    kname: str = _SI.kname
    ename: str = _SI.ename
    cname: str = _SI.cname
    jname: str = _SI.jname
    no: str = _SI.no
    rgb: str = _SI.rgb
    plus_kname: str = ""
    plus_ename: str = ""
    plus_cname: str = ""
    plus_no: str = ""
    minus_kname: str = ""
    minus_ename: str = ""
    minus_cname: str = ""
    minus_no: str = ""
    style: str = _label_of(_SPEC.style)
    plate_interval: str = f"{_SPEC.plate_interval:g}"
    plate_bottom: str = f"{_SPEC.plate_bottom:g}"
    plate_h: str = f"{_SPEC.plate_h:g}"
    plate_t: str = f"{_SPEC.plate_t:g}"
    boarding: bool = _SPEC.boarding
    dest_l: str = ""
    dest_r: str = ""
    exits_on: bool = _SPEC.exits
    exits: list = field(default_factory=list)
    hang_bottom: str = f"{_SPEC.hang_bottom:g}"
    hang_w: str = f"{_SPEC.hang_w:g}"
    hang_h: str = f"{_SPEC.hang_h:g}"
    hang_t: str = f"{_SPEC.hang_t:g}"
    hang_offset: str = f"{_SPEC.hang_offset:g}"

    def exit_for(self, passage: str) -> ExitDraft:
        """그 통로의 출구 입력 (없으면 만들어 붙임)"""
        for e in self.exits:
            if e.passage == passage:
                return e
        e = ExitDraft(passage)
        self.exits.append(e)
        return e

    def to_settings(self) -> SignSettings:
        if not self.enabled:
            return SignSettings(enabled=False)
        if self.style not in STYLE_LABELS:
            raise ValueError(f"사인: 역명판 스타일이 올바르지 않습니다 ('{self.style}')")
        vals = {a: _num(getattr(self, a), "사인", lb, positive=r == "pos", nonneg=r == "nonneg")
                for a, lb, r in PLATE_FIELDS + HANG_FIELDS}
        ref = lambda p: StationRef(*(getattr(self, f"{p}_{a}").strip() for a, _ in NEIGHBOR_FIELDS))
        si = StationInfo(**{a: getattr(self, a).strip() for a, _ in STATION_FIELDS}, plus=ref("plus"), minus=ref("minus"))
        exits = [ExitInfo(e.passage, e.number.strip(), "\n".join(x.strip() for x in e.destinations.split("/") if x.strip()))
                 for e in self.exits if e.passage.strip()]
        return SignSettings(enabled=True, station=si, style=STYLE_LABELS[self.style], boarding=bool(self.boarding),
                            dest_l=self.dest_l.strip(), dest_r=self.dest_r.strip(), exits=bool(self.exits_on),
                            exit_info=exits, **vals)


def preview(d: SignDraft) -> str:
    if not d.enabled:
        return "→ 사인 없음"
    try:
        ss = d.to_settings()
    except ValueError:
        return "→ 입력값을 확인하세요"
    parts = [f"역명판 {d.style} {ss.plate_interval:g}m 간격"]
    if ss.boarding:
        parts.append("타는 곳")
    if ss.exits:
        parts.append(f"출구 {len([e for e in ss.exit_info if e.number or e.destinations])}곳 입력")
    return "→ " + " · ".join(parts)
