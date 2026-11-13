"""출구통로 입력의 화면 비의존 모델 (문자열 초안 → PassageSpec 변환 + 검증)

경로는 꼭짓점 표(행 = 꼭짓점)로 입력한다. 통로마다 좌표 방식을 하나 고른다 (모델은 꼭짓점마다 다른 방식도 지원).
- 선형 상대: (STA, t, 높이) — STA 는 절대 측점, t 는 선형 중심에서 왼쪽 +, 높이는 접합부 FL 기준
- 절대 좌표: (X, Y, EL) — 선형과 같은 평면 좌표계, EL 은 바닥 상면 절대 표고
첫 꼭짓점의 높이는 비워 두면 접합부 FL 이다.
"""
import math
from dataclasses import dataclass, field

from gui.column_draft import _num, level_name
from passages.passage_spec import STATION, WORLD, PassageSpec, PathVertex

_SPEC = PassageSpec()               # 초기값은 모델 기본값이 단일 출처

MODE_STATION = "선형 상대 (STA, t, 높이)"
MODE_WORLD = "절대 좌표 (X, Y, EL)"
MODES = [MODE_STATION, MODE_WORLD]
_MODE = {MODE_STATION: STATION, MODE_WORLD: WORLD}
COLUMN_LABELS = {MODE_STATION: ("STA", "t (왼쪽 +)", "높이(FL 기준)"), MODE_WORLD: ("X", "Y", "EL")}


def floor_label(floor_count: int, floor_n: int) -> str:
    return level_name(floor_count, floor_n)


@dataclass
class VertexDraft:
    x: str = "0"
    y: str = "0"
    z: str = ""


@dataclass
class PassageDraft:
    """출구통로 1개 (입력창 문자열 그대로 보관). floor: 통로가 붙는 층 번호 (1 = 최하층)"""
    name: str = ""
    floor: int = 1
    mode: str = MODE_STATION
    inner_width: str = f"{_SPEC.inner_width:g}"
    inner_height: str = f"{_SPEC.inner_height:g}"
    wall_t: str = f"{_SPEC.wall_t:g}"
    floor_t: str = f"{_SPEC.floor_t:g}"
    roof_t: str = f"{_SPEC.roof_t:g}"
    top_haunch_w: str = f"{_SPEC.top_haunch_w:g}"
    top_haunch_h: str = f"{_SPEC.top_haunch_h:g}"
    bottom_haunch_w: str = f"{_SPEC.bottom_haunch_w:g}"
    bottom_haunch_h: str = f"{_SPEC.bottom_haunch_h:g}"
    vertices: list = field(default_factory=list)

    def to_spec(self, where: str, start_station: float) -> PassageSpec:
        if self.mode not in _MODE:
            raise ValueError(f"{where}: 좌표 방식이 올바르지 않습니다 ('{self.mode}')")
        mode = _MODE[self.mode]
        cols = COLUMN_LABELS[self.mode]
        path = []
        for j, v in enumerate(self.vertices, start=1):
            w = f"{where} 꼭짓점 {j}"
            x = _num(v.x, w, cols[0])
            y = _num(v.y, w, cols[1])
            z = None if j == 1 and not str(v.z).strip() else _num(v.z, w, cols[2])
            path.append(PathVertex(mode, x - start_station if mode == STATION else x, y, z))
        pos = lambda attr, label: _num(getattr(self, attr), where, label, positive=True)
        nonneg = lambda attr, label: _num(getattr(self, attr), where, label, nonneg=True)
        return PassageSpec(
            floor=self.floor, path=path,
            inner_width=pos("inner_width", "내공 폭"), inner_height=pos("inner_height", "내공 높이"),
            wall_t=pos("wall_t", "벽 두께"), floor_t=pos("floor_t", "바닥 슬래브 두께"), roof_t=pos("roof_t", "천장 슬래브 두께"),
            top_haunch_w=nonneg("top_haunch_w", "상부 헌치 폭"), top_haunch_h=nonneg("top_haunch_h", "상부 헌치 높이"),
            bottom_haunch_w=nonneg("bottom_haunch_w", "하부 헌치 폭"), bottom_haunch_h=nonneg("bottom_haunch_h", "하부 헌치 높이"),
            name=self.name.strip())


def default_draft(floor: int, sta: float, t_face: float) -> PassageDraft:
    """새 통로 초안: 선형 상대 좌표로 측벽(왼쪽)에서 직각으로 15m 나가는 수평 직선"""
    return PassageDraft(floor=floor, vertices=[VertexDraft(f"{sta:g}", f"{t_face:g}", ""),
                                               VertexDraft(f"{sta:g}", f"{t_face + 15.0:g}", "0")])


class PassageDrafts:
    """출구통로 입력 초안 목록"""

    def __init__(self):
        self.items: list[PassageDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 줄어 없어진 층에 붙은 통로는 최상층으로 옮김. 변경 여부 반환"""
        changed = False
        for it in self.items:
            if it.floor > floor_count:
                it.floor = max(1, floor_count)
                changed = True
        return changed

    def to_specs(self, start_station: float) -> list[PassageSpec]:
        """초안 → PassageSpec 목록. 잘못된 입력은 몇 번째 통로·꼭짓점인지 밝혀서 ValueError"""
        return [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: PassageDraft) -> str:
        return f"출구통로 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")


def preview(it: PassageDraft, start_station: float) -> str:
    """입력 중 미리보기: 꼭짓점 수, 평면 길이(입력 좌표 기준), 측벽 오프닝 STA 범위(선형 상대일 때)"""
    try:
        sp = it.to_spec("", start_station)
    except ValueError:
        return "→ 입력값을 확인하세요"
    pts = [(v.x, v.y) for v in sp.path]
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    text = f"→ 꼭짓점 {len(pts)}개, 평면 길이 약 {length:.2f}m"
    if sp.path and sp.path[0].mode == STATION:
        sta = sp.path[0].x + start_station
        text += f"\n   측벽 오프닝 STA {sta - sp.half_in:.2f} ~ {sta + sp.half_in:.2f} (폭 {sp.inner_width:g} x 높이 {sp.inner_height:g})"
    return text
