"""미리보기 평면의 경로 객체(출구통로·환기구·점자 유도 경로) 표시·편집 모델 (화면 비의존).

- collect_paths(cfg, entries): 모델(배치 결과)의 꼭짓점 위치(정거장 로컬 (s, t))와 입력 초안 번호를 짝지은 EditPath 목록.
  출구통로·환기구의 첫 꼭짓점은 본체 외벽(분기면 부모 측벽)에 붙으므로 — 본체에 붙은 첫 꼭짓점은 벽을 따라(s 방향)만 움직이고
  (t 는 입력 그대로, 비웠으면 계속 자동), 분기 통로의 첫 꼭짓점은 움직일 수 없다 (부모 측벽에서 자동).
- move / insert / delete: 입력 초안(탭의 문자열)을 고침. 좌표 방식(선형 상대 STA·t / 절대 X·Y)을 그대로 지키고 높이는 유지·보간.
  환기구의 수직 구간(평면 위치가 같은 연속 꼭짓점)은 함께 움직인다.
고친 뒤에는 그 탭을 다시 그리고(render) 미리보기를 갱신하면 된다 (PreviewWindow 가 on_path_edit 로 부름).
"""
import math
from dataclasses import dataclass, field

from gui.passage_draft import MODE_WORLD
from gui.pick_fill import num

PASSAGE, VENT, TACTILE = "passage", "vent", "tactile"
KIND_LABEL = {PASSAGE: "출구통로", VENT: "환기구", TACTILE: "점자 유도 경로"}
_DRAFTS = {PASSAGE: "passage_drafts", VENT: "vent_drafts", TACTILE: "tactile_drafts"}
_SAME = 1e-3                     # 평면 위치가 같은 꼭짓점 (수직 구간)

FREE, ALONG_S, FIXED = "free", "along_s", "fixed"   # 꼭짓점 움직임: 자유 / 벽을 따라 s 방향만 / 고정


@dataclass
class EditPath:
    """kind: PASSAGE | VENT | TACTILE, index: 입력 초안 번호, points: 꼭짓점 (s, t) (초안 꼭짓점과 1:1),
    moves: 꼭짓점별 움직임 (FREE | ALONG_S | FIXED)"""
    kind: str
    index: int
    name: str
    floor: int
    points: list
    moves: list = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{KIND_LABEL[self.kind]} {self.name}"

    def group(self, k: int) -> list:
        """k 와 평면 위치가 같은 연속 꼭짓점들 (환기구 수직 구간) — 함께 움직임"""
        out = [k]
        for step in (-1, 1):
            j = k + step
            while 0 <= j < len(self.points) and _same(self.points[j], self.points[k]):
                out.append(j)
                j += step
        return sorted(out)

    def midpoints(self) -> list:
        """[(k, (s, t))] — 꼭짓점 k 와 k+1 사이 가운데 (평면 위치가 같은 수직 구간은 제외)"""
        out = []
        for k, (a, b) in enumerate(zip(self.points, self.points[1:])):
            if not _same(a, b):
                out.append((k, ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)))
        return out


def _same(a, b) -> bool:
    return abs(a[0] - b[0]) < _SAME and abs(a[1] - b[1]) < _SAME


def _drafts(entries, kind):
    d = entries.get(_DRAFTS[kind]) if entries is not None else None
    return d.items if d is not None else []


def collect_paths(cfg, entries) -> list:
    """모델 cfg(이 초안으로 만든 것)의 경로 객체 → EditPath 목록 (초안 수와 배치 결과 수가 다르면 그 종류는 건너뜀)"""
    out = []
    for kind, lays in ((PASSAGE, _safe(cfg.passage_layouts)), (VENT, _safe(cfg.vent_layouts))):
        drafts = _drafts(entries, kind)
        if len(drafts) != len(lays):
            continue
        for i, (lay, d) in enumerate(zip(lays, drafts)):
            pts = [(v.s, v.t) for v in lay.vertices]
            if len(pts) != len(d.vertices):
                continue
            moves = [FREE] * len(pts)
            moves[0] = FIXED if getattr(lay, "parent", "") else ALONG_S
            out.append(EditPath(kind, i, lay.name, lay.floor, pts, moves))
    ts = getattr(cfg, "tactile_settings", None)
    drafts = _drafts(entries, TACTILE)
    if ts is not None and ts.enabled and len(drafts) == len(ts.paths):
        for i, (p, d) in enumerate(zip(ts.paths, drafts)):
            if len(p.points) == len(d.vertices):
                out.append(EditPath(TACTILE, i, p.name or f"TP{i + 1}", p.floor, [tuple(x) for x in p.points],
                                    [FREE] * len(p.points)))
    return out


def _safe(fn):
    try:
        return fn()
    except (ValueError, AttributeError):
        return []


def constrain(path: EditPath, k: int, s: float, t: float) -> tuple:
    """꼭짓점 k 를 (s, t) 로 옮길 때 실제 위치 (벽을 따라 움직이는 첫 꼭짓점은 t 고정). 고정이면 ValueError"""
    mv = path.moves[k] if k < len(path.moves) else FREE
    if mv == FIXED:
        raise ValueError(f"{path.label}: 분기 통로의 첫 꼭짓점은 부모 측벽에 자동으로 붙어 옮길 수 없습니다")
    if mv == ALONG_S:
        return s, path.points[k][1]
    return s, t


def _set_xy(path, d, j, s, t, base, to_world, keep_y=False):
    v = d.vertices[j]
    if path.kind != TACTILE and getattr(d, "mode", "") == MODE_WORLD:
        x, y = to_world(s, t)
        v.x, v.y = num(x), num(y)
        return
    v.x = num(base + s)
    if not keep_y:
        v.y = num(t)


def move(entries, path: EditPath, k: int, s: float, t: float, base: float, to_world) -> None:
    """꼭짓점 k (와 같은 평면 위치의 수직 구간 꼭짓점들) 를 (s, t) 로. 입력 초안을 고침"""
    s, t = constrain(path, k, s, t)
    d = _drafts(entries, path.kind)[path.index]
    for j in path.group(k):
        keep = path.moves[j] == ALONG_S and not getattr(d, "mode", "") == MODE_WORLD   # 첫 꼭짓점 t 는 입력 그대로 (비우면 자동)
        _set_xy(path, d, j, s, t, base, to_world, keep_y=keep)
        path.points[j] = (s, t)


def _zval(text):
    try:
        return float(str(text).strip())
    except ValueError:
        return None


def insert(entries, path: EditPath, k: int, s: float, t: float, base: float, to_world) -> int:
    """꼭짓점 k 와 k+1 사이에 (s, t) 꼭짓점 추가 → 새 꼭짓점 번호. 높이는 이웃 둘 사이를 평면 거리로 보간 (한쪽이 비면 다른 쪽)"""
    if not 0 <= k < len(path.points) - 1:
        raise ValueError(f"{path.label}: 꼭짓점을 추가할 구간이 없습니다")
    d = _drafts(entries, path.kind)[path.index]
    j = k + 1
    if path.kind == TACTILE:
        from gui.tactile_draft import TactilePointDraft
        new = TactilePointDraft()
    else:
        from gui.passage_draft import VertexDraft
        a, b = path.points[k], path.points[j]
        za, zb = _zval(d.vertices[k].z), _zval(d.vertices[j].z)
        if za is None and k == 0 and not getattr(d, "mode", "") == MODE_WORLD:
            za = 0.0                                                    # 첫 꼭짓점 높이를 비움 = 접합부 FL (0)
        if za is None and zb is None:
            z = "0"
        elif za is None or zb is None:
            z = num(zb if za is None else za)
        else:
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            f = math.hypot(s - a[0], t - a[1]) / L if L > 1e-9 else 0.5
            z = num(za + (zb - za) * min(max(f, 0.0), 1.0))
        new = VertexDraft(z=z)
    d.vertices.insert(j, new)
    path.points.insert(j, (s, t))
    path.moves.insert(j, FREE)
    _set_xy(path, d, j, s, t, base, to_world)
    return j


def delete(entries, path: EditPath, k: int) -> None:
    """꼭짓점 k 삭제 (꼭짓점은 2개 이상 남아야 하고, 벽에 붙은 첫 꼭짓점은 지울 수 없음)"""
    if path.moves[k] != FREE:
        raise ValueError(f"{path.label}: 벽에 붙은 첫 꼭짓점은 지울 수 없습니다")
    if len(path.points) <= 2:
        raise ValueError(f"{path.label}: 꼭짓점은 2개 이상이어야 합니다")
    d = _drafts(entries, path.kind)[path.index]
    del d.vertices[k]
    del path.points[k]
    del path.moves[k]


def nearest(paths, xy_of, x: float, y: float, tol: float):
    """평면 좌표 (x, y) 에 가장 가까운 손잡이: ('vertex', 경로, k) 또는 ('mid', 경로, k) (tol 안, 꼭짓점 우선). 없으면 None.
    xy_of(s, t) = 정거장 로컬 → 평면 그림 좌표"""
    best = None
    for kind_w, getter in (("vertex", lambda p: list(enumerate(p.points))), ("mid", lambda p: p.midpoints())):
        for p in paths:
            for k, (s, t) in getter(p):
                px, py = xy_of(s, t)
                dd = math.hypot(px - x, py - y)
                if dd <= tol and (best is None or dd < best[0]):
                    best = (dd, kind_w, p, k)
        if best is not None:
            return best[1], best[2], best[3]
    return None
