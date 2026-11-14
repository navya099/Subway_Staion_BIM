"""출력 탭 입력의 화면 비의존 모델 (문자열 초안 → OutputOptions 변환 + 검증)"""
import re
from dataclasses import dataclass, field

from config.output_config import PLAN_CUT_H, OutputOptions
from config.station_config import StationParameters
from gui.column_draft import _num


def parse_station(text: str, where: str) -> float:
    """측점 문자열 → m. '1234.5' 또는 '1+234.5' (km+m) 형식"""
    t = str(text).strip()
    m = re.fullmatch(r"(\d+)\s*\+\s*(\d+(?:\.\d*)?)", t)
    if m:
        return int(m.group(1)) * 1000.0 + float(m.group(2))
    try:
        return float(t)
    except ValueError:
        raise ValueError(f"{where}: 측점이 올바르지 않습니다 ('{t}'). 예: 134.45 또는 0+134.45") from None


def _split(text: str) -> list[str]:
    return [x for x in re.split(r"[,\s;]+", str(text).strip()) if x]


@dataclass
class PrintDraft:
    """출력 탭 입력 (입력창 문자열 그대로 보관)
    plan_floors: 체크한 평면도 층 번호 (1 = 최하층)
    profile_center / profile_track_l / profile_track_r: 선형 중심 / 왼쪽(+t)·오른쪽(−t) 선로 중심 축
    profile_offsets: 직접 입력하는 축 offset (쉼표 구분, 왼쪽 +)
    section_stations: 단면 측점 (쉼표 구분, 절대 STA)
    section_continuous: 연속 단면 사용. section_from / section_to 가 비면 정거장 내공 시점 / 종점
    """
    dxf3d: bool = True
    ifc: bool = True
    plan: bool = True
    plan_floors: set = field(default_factory=lambda: set(range(1, StationParameters().floors + 1)))   # 기본: 모든 층
    plan_cut_h: str = f"{PLAN_CUT_H:g}"
    profile: bool = True
    profile_center: bool = True
    profile_track_l: bool = False
    profile_track_r: bool = False
    profile_offsets: str = ""
    section: bool = True
    section_stations: str = ""
    section_continuous: bool = False
    section_interval: str = "20"
    section_from: str = ""
    section_to: str = ""

    def ensure_floors(self, floor_count: int, prev_count: int) -> bool:
        """층수가 바뀌면: 이전에 모든 층을 골랐으면 새 층수의 모든 층, 아니면 없어진 층만 뺌. 변경 여부 반환"""
        before = set(self.plan_floors)
        if prev_count and self.plan_floors == set(range(1, prev_count + 1)):
            self.plan_floors = set(range(1, floor_count + 1))
        else:
            self.plan_floors = {n for n in self.plan_floors if 1 <= n <= floor_count}
        return self.plan_floors != before

    def offsets(self, track_spacing: float) -> list[float]:
        """종단 축 offset 목록 (선택 순서: 중심 → 왼쪽 선로 → 오른쪽 선로 → 직접 입력, 1mm 안 중복 제거)"""
        raw = []
        if self.profile_center:
            raw.append(0.0)
        if self.profile_track_l:
            raw.append(track_spacing / 2.0)
        if self.profile_track_r:
            raw.append(-track_spacing / 2.0)
        raw += [_num(x, "종단면도", "축 offset") for x in _split(self.profile_offsets)]
        out = []
        for t in raw:
            if all(abs(t - u) > 1e-3 for u in out):
                out.append(t)
        return out

    def to_options(self, track_spacing: float) -> OutputOptions:
        """초안 → OutputOptions. 끈 성과물의 세부 입력은 검사하지 않음 (잘못 남아 있어도 출력 가능)"""
        opt = OutputOptions(dxf3d=bool(self.dxf3d), ifc=bool(self.ifc), plan=bool(self.plan),
                            profile=bool(self.profile), section=bool(self.section))
        if opt.plan:
            opt.plan_floors = sorted(self.plan_floors)
            opt.plan_cut_h = _num(self.plan_cut_h, "평면도", "절단 높이", positive=True)
        if opt.profile:
            opt.profile_offsets = self.offsets(track_spacing)
        if opt.section:
            opt.section_stations = [parse_station(x, "단면도") for x in _split(self.section_stations)]
            if self.section_continuous:
                opt.section_interval = _num(self.section_interval, "단면도", "연속 단면 간격", positive=True)
                opt.section_from = parse_station(self.section_from, "단면도 연속 시작") if self.section_from.strip() else None
                opt.section_to = parse_station(self.section_to, "단면도 연속 끝") if self.section_to.strip() else None
        return opt


def preview(d: PrintDraft, start_station, length, track_spacing, level_name=str) -> str:
    """입력 중 미리보기: 출력할 성과물과 단면 개수. start_station / length / track_spacing 이 None 이면 그 부분 생략"""
    names = [n for n, on in (("3D DXF", d.dxf3d), ("평면도", d.plan), ("종단면도", d.profile), ("단면도", d.section),
                             ("IFC", d.ifc)) if on]
    if not names:
        return "→ 출력할 성과물을 하나 이상 선택하세요"
    lines = ["→ 출력: " + ", ".join(names)]
    try:
        if d.plan:
            fl = sorted(d.plan_floors)
            lines.append(f"   평면: {', '.join(level_name(n) for n in fl) if fl else '(층 선택 없음)'} · FL+"
                         f"{_num(d.plan_cut_h, '', '', positive=True):g}m")
        if d.profile and track_spacing is not None:
            offs = d.offsets(track_spacing)
            lines.append("   종단 축: " + (", ".join("C.L." if t == 0 else f"C.L.{t:+g}" for t in offs) if offs else "(없음)"))
        if d.section and start_station is not None and length is not None:
            opt = d.to_options(track_spacing or 0.0)
            ss = opt.section_s_at(start_station, length)
            what = "기본 1/4·1/2·3/4" if not opt.section_stations and opt.section_interval is None else f"{len(ss)}개"
            first = ", ".join(f"{start_station + s:.2f}" for s in ss[:4]) + (" …" if len(ss) > 4 else "")
            lines.append(f"   단면: {what} (STA {first})")
    except ValueError:
        lines.append("   → 입력값을 확인하세요")
    return "\n".join(lines)

