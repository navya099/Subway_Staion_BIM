"""환기구 입력의 화면 비의존 모델 (문자열 초안 → VentSpec 변환 + 검증).

경로는 출구통로와 같은 꼭짓점 표(선형 상대 STA·t·높이 또는 절대 X·Y·EL)로 입력한다.
평면 위치가 같고 높이만 다른 연속 두 꼭짓점 = 수직 구간(수직구, 위로만).
"""
from dataclasses import dataclass, field

from gui.column_draft import _num
from gui.passage_draft import _MODE, COLUMN_LABELS, MODE_STATION, VertexDraft
from passages.passage_spec import STATION, PathVertex
from ventilations.vent_spec import VentSpec

_SPEC = VentSpec()                  # 초기값은 모델 기본값이 단일 출처

# (속성, 라벨, 규칙) — 'pos' 양수, 'nonneg' 0 이상
NUM_FIELDS = [("cell_width", "칸 내공 폭", "pos"), ("cell_height", "칸 내공 높이", "pos"),
              ("wall_t", "바깥 벽 두께", "pos"), ("mid_wall_t", "중벽 두께", "pos"),
              ("floor_t", "바닥 두께", "pos"), ("roof_t", "천장 두께", "pos"),
              ("haunch_w", "헌치 폭", "nonneg"), ("haunch_h", "헌치 높이", "nonneg"),
              ("grill_t", "그릴 두께", "pos"), ("grill_frame", "그릴 테두리", "pos"),
              ("grill_bar", "그릴 살 폭", "pos"), ("grill_gap", "그릴 살 간격", "pos")]


@dataclass
class VentDraft:
    """환기구 1개 (입력창 문자열 그대로 보관). floor: 붙는 층 (1 = 최하층). shaft_depth 가 비면 칸 높이"""
    name: str = ""
    floor: int = 1
    mode: str = MODE_STATION
    cells: str = f"{_SPEC.cells}"
    cell_width: str = f"{_SPEC.cell_width:g}"
    cell_height: str = f"{_SPEC.cell_height:g}"
    wall_t: str = f"{_SPEC.wall_t:g}"
    mid_wall_t: str = f"{_SPEC.mid_wall_t:g}"
    floor_t: str = f"{_SPEC.floor_t:g}"
    roof_t: str = f"{_SPEC.roof_t:g}"
    haunch_w: str = f"{_SPEC.haunch_w:g}"
    haunch_h: str = f"{_SPEC.haunch_h:g}"
    shaft_depth: str = ""
    grill_t: str = f"{_SPEC.grill_t:g}"
    grill_frame: str = f"{_SPEC.grill_frame:g}"
    grill_bar: str = f"{_SPEC.grill_bar:g}"
    grill_gap: str = f"{_SPEC.grill_gap:g}"
    vertices: list = field(default_factory=list)

    def to_spec(self, where: str, start_station: float) -> VentSpec:
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
        try:
            cells = int(str(self.cells).strip())
        except ValueError:
            raise ValueError(f"{where}: 련 수가 정수가 아닙니다 ('{self.cells}')") from None
        if cells < 1:
            raise ValueError(f"{where}: 련 수는 1 이상이어야 합니다 ({cells})")
        vals = {attr: _num(getattr(self, attr), where, label, positive=rule == "pos", nonneg=rule == "nonneg")
                for attr, label, rule in NUM_FIELDS}
        depth = None if not str(self.shaft_depth).strip() else _num(self.shaft_depth, where, "수직구 깊이", positive=True)
        return VentSpec(floor=self.floor, path=path, cells=cells, shaft_depth=depth, name=self.name.strip(), **vals)


def default_draft(floor: int, sta: float, t_face: float) -> VentDraft:
    """새 환기구 초안: 측벽(왼쪽)에서 직각으로 15m 나간 뒤 수직으로 10m 올라가는 경로"""
    return VentDraft(floor=floor, vertices=[VertexDraft(f"{sta:g}", f"{t_face:g}", ""),
                                            VertexDraft(f"{sta:g}", f"{t_face + 15.0:g}", "0"),
                                            VertexDraft(f"{sta:g}", f"{t_face + 15.0:g}", "10")])


class VentDrafts:
    """환기구 입력 초안 목록"""

    def __init__(self):
        self.items: list[VentDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 줄어 없어진 층에 붙은 환기구는 최상층으로 옮김. 변경 여부 반환"""
        changed = False
        for it in self.items:
            if it.floor > floor_count:
                it.floor = max(1, floor_count)
                changed = True
        return changed

    def to_specs(self, start_station: float) -> list[VentSpec]:
        return [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: VentDraft) -> str:
        return f"환기구 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")


def preview(it: VentDraft, start_station: float) -> str:
    """입력 중 미리보기: 단면 구성(내공 전체 폭), 꼭짓점 수, 수직 구간 수, 그릴 위치"""
    try:
        sp = it.to_spec("", start_station)
    except ValueError:
        return "→ 입력값을 확인하세요"
    pts = sp.path
    vertical = [i for i, (a, b) in enumerate(zip(pts, pts[1:])) if abs(a.x - b.x) < 1e-3 and abs(a.y - b.y) < 1e-3]
    end = "수직구 상단" if vertical and vertical[-1] == len(pts) - 2 else "덕트 끝 단면"
    text = (f"→ {sp.cells}련 × {sp.cell_width:g}×{sp.cell_height:g}, 내공 폭 {sp.inner_width:g}m "
            f"(외곽 {2 * sp.half_out:g}m)\n   꼭짓점 {len(pts)}개, 수직 구간 {len(vertical)}곳, 그릴: {end} {sp.cells}개")
    return text
