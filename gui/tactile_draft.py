"""점자블록 입력의 화면 비의존 모델 (문자열 초안 → TactileSettings 변환 + 검증).

공통 설정(블록 크기·두께, 자동 경고블록: 승강장 연단·계단·에스컬레이터·엘리베이터 앞) + 유도블록 경로 목록.
경로 꼭짓점은 (STA, t) — STA 는 절대 측점, t 는 선형 중심에서 왼쪽 +. 선분은 선형 방향 또는 직각 방향만.
"""
from dataclasses import dataclass, field

from gui.column_draft import _num
from gui.pick_fill import num
from tactiles.tactile_spec import TactilePathSpec, TactileSettings

_SPEC = TactileSettings()           # 초기값은 모델 기본값이 단일 출처 (enabled 만 GUI 기본 켬)

# 숫자 입력칸 (속성, 라벨, 규칙) — 'pos' 양수, 'nonneg' 0 이상
SIZE_FIELDS = [("size", "블록 크기", "pos"), ("block_t", "블록 두께 (마감 없는 곳)", "pos")]
# 자동 경고블록: (켜기 속성, 라벨, [(속성, 라벨, 규칙)])
AUTO_GROUPS = [("edge", "승강장 연단", [("edge_offset", "연단 이격", "nonneg"), ("edge_width", "띠 폭", "pos")]),
               ("stair", "계단 앞", [("stair_clear", "이격", "nonneg"), ("stair_depth", "띠 깊이", "pos")]),
               ("escalator", "에스컬레이터 앞", [("esc_clear", "이격", "nonneg"), ("esc_depth", "띠 깊이", "pos")]),
               ("elevator", "엘리베이터 문 앞", [("ev_clear", "이격", "nonneg"), ("ev_depth", "띠 깊이", "pos")])]
NUM_FIELDS = SIZE_FIELDS + [f for _, _, fs in AUTO_GROUPS for f in fs]


@dataclass
class TactilePointDraft:
    x: str = "0"                    # STA (절대 측점)
    y: str = "0"                    # t (왼쪽 +)


@dataclass
class TactilePathDraft:
    """유도블록 경로 1개 (입력창 문자열). floor: 층 번호 (1 = 최하층), width 를 비우면 블록 크기"""
    name: str = ""
    floor: int = 1
    width: str = ""
    vertices: list = field(default_factory=list)

    def to_spec(self, where: str, start_station: float) -> TactilePathSpec:
        pts = []
        for j, v in enumerate(self.vertices, start=1):
            w = f"{where} 꼭짓점 {j}"
            pts.append((_num(v.x, w, "STA") - start_station, _num(v.y, w, "t")))
        width = None if not str(self.width).strip() else _num(self.width, where, "폭", positive=True)
        return TactilePathSpec(floor=self.floor, points=pts, width=width, name=self.name.strip())


@dataclass
class TactileSettingsDraft:
    enabled: bool = True
    size: str = f"{_SPEC.size:g}"
    block_t: str = f"{_SPEC.block_t:g}"
    edge: bool = _SPEC.edge
    edge_offset: str = f"{_SPEC.edge_offset:g}"
    edge_width: str = f"{_SPEC.edge_width:g}"
    stair: bool = _SPEC.stair
    stair_clear: str = f"{_SPEC.stair_clear:g}"
    stair_depth: str = f"{_SPEC.stair_depth:g}"
    escalator: bool = _SPEC.escalator
    esc_clear: str = f"{_SPEC.esc_clear:g}"
    esc_depth: str = f"{_SPEC.esc_depth:g}"
    elevator: bool = _SPEC.elevator
    ev_clear: str = f"{_SPEC.ev_clear:g}"
    ev_depth: str = f"{_SPEC.ev_depth:g}"


def default_path(floor: int, sta: float, t: float) -> TactilePathDraft:
    """새 경로 초안: 선형 방향 10m 직선"""
    return TactilePathDraft(floor=floor, vertices=[TactilePointDraft(num(sta), num(t)), TactilePointDraft(num(sta + 10.0), num(t))])


class TactileDrafts:
    """점자블록 입력 초안: 공통 설정 + 유도 경로 목록"""

    def __init__(self):
        self.settings = TactileSettingsDraft()
        self.items: list[TactilePathDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 줄어 없어진 층의 경로는 최상층으로 옮김. 변경 여부 반환"""
        changed = False
        for it in self.items:
            if it.floor > floor_count:
                it.floor = max(1, floor_count)
                changed = True
        return changed

    @staticmethod
    def where(i: int, it: TactilePathDraft) -> str:
        return f"유도블록 경로 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")

    def to_settings(self, start_station: float) -> TactileSettings:
        d = self.settings
        if not d.enabled:
            return TactileSettings(enabled=False)
        vals = {attr: _num(getattr(d, attr), "점자블록", label, positive=rule == "pos", nonneg=rule == "nonneg")
                for attr, label, rule in NUM_FIELDS}
        flags = {attr: bool(getattr(d, attr)) for attr, _, _ in AUTO_GROUPS}
        paths = [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]
        return TactileSettings(enabled=True, paths=paths, **vals, **flags)


def preview(d: TactileDrafts, start_station: float) -> str:
    """입력 중 미리보기: 자동 경고블록 종류, 경로 수·총 길이"""
    if not d.settings.enabled:
        return "→ 점자블록 만들지 않음"
    try:
        ts = d.to_settings(start_station)
    except ValueError:
        return "→ 입력값을 확인하세요"
    autos = [label for attr, label, _ in AUTO_GROUPS if getattr(ts, attr)]
    length = sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for p in ts.paths for a, b in zip(p.points, p.points[1:]))
    return (f"→ 자동 점형: {', '.join(autos) if autos else '없음'} · 블록 {ts.size:g}m\n"
            f"   유도 경로 {len(ts.paths)}개, 중심선 길이 {length:.1f}m (꼭짓점 = 점형, 사이 = 선형)")
