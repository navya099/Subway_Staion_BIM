"""미리보기 평면에서 위치 선택 (CAD 명령 방식, 화면 비의존).

입력 탭의 [선택] 버튼이 PickRequest 를 만들어 미리보기 창에 넘기면, 창은 평면에서 클릭·명령줄 입력을 받아
PickSession 에 점을 더하고, 끝나면 request.on_done(점 목록) 을 부른다. 점은 정거장 로컬 (s, t) — t 는 왼쪽 +.

- 종류: POINT(점 1개) / RECT(대각 두 점) / PATH(여러 점, Enter·오른쪽 클릭으로 끝)
- 스냅 우선순위: 부재 점(기둥 중심·실/오프닝 모서리·내공 모서리) → 부재 선(내공면·외벽 바깥면·선형 중심·내공 시점/종점, 축별) → 격자
- 직교 모드(F8): 직전 점에서 s 방향 또는 t 방향으로만 (ortho_snap)
- 명령줄: 'STA, offset' (절대 측점, 예 '0+134.5, 3.2' 또는 '134.5,3.2') / '@ds, dt' (직전 점 기준 상대)
"""
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

POINT, RECT, PATH = "point", "rect", "path"
_PROMPTS = {POINT: ("위치를 클릭하세요",), RECT: ("첫 모서리를 클릭하세요", "반대쪽 모서리를 클릭하세요"),
            PATH: ("첫 꼭짓점을 클릭하세요", "다음 꼭짓점을 클릭하세요 (Enter·오른쪽 클릭 = 끝)")}
MIN_POINTS = {POINT: 1, RECT: 2, PATH: 2}


@dataclass
class PickRequest:
    """kind: POINT | RECT | PATH, floor: 평면을 볼 층 (1 = 최하층), title: 무엇을 고르는지 (상태줄 안내),
    on_done(points): 끝났을 때 [(s, t), ...] 로 부름. start: PATH 의 첫 점을 고정(없으면 클릭)"""
    kind: str
    floor: int
    title: str
    on_done: Callable
    start: Optional[tuple] = None
    to_world: Optional[Callable] = None     # 선택을 받는 창이 넣음: 정거장 로컬 (s, t) → 세계 (X, Y)


@dataclass
class SnapTargets:
    """부재 스냅 대상 (정거장 로컬): points = [(s, t, 이름)], s_lines = [(s, 이름)], t_lines = [(t, 이름)]"""
    points: list = field(default_factory=list)
    s_lines: list = field(default_factory=list)
    t_lines: list = field(default_factory=list)


def snap_targets(cfg, floor: int, columns=()) -> SnapTargets:
    """그 층 평면의 스냅 대상. columns = [(층, s, t)] (기둥 엔진에서)"""
    p = cfg.station
    hw = p.width / 2.0
    wt = p.wall_ts[floor - 1] if 0 < floor <= len(p.wall_ts) else p.max_wall_t
    tg = SnapTargets(s_lines=[(0.0, "내공 시점"), (p.length, "내공 종점")],
                     t_lines=[(hw, "내공면(왼쪽)"), (-hw, "내공면(오른쪽)"), (hw + wt, "외벽 바깥면(왼쪽)"),
                              (-hw - wt, "외벽 바깥면(오른쪽)"), (0.0, "선형 중심")])
    tg.points += [(s, t, "내공 모서리") for s in (0.0, p.length) for t in (hw, -hw)]
    tg.points += [(s, t, "기둥 중심") for n, s, t in columns if n == floor]
    for r in cfg.rooms:
        if r.floor == floor:
            tg.points += [(s, t, "실 모서리") for s in (r.s0, r.s1) for t in (r.t0, r.t1)]
    for o in cfg.openings:
        if (floor - 1) in o.slabs or floor in o.slabs:
            a, b = o.t_center - o.width / 2.0, o.t_center + o.width / 2.0
            tg.points += [(s, t, "오프닝 모서리") for s in (o.s_start, o.s_start + o.length) for t in (a, b)]
    return tg


@dataclass
class Snapper:
    """grid: 격자 간격 (m, None/0 = 끔), members: 부재 스냅 켬, base: 정거장 시작 측점 (격자는 절대 측점 기준)"""
    targets: SnapTargets = field(default_factory=SnapTargets)
    grid: Optional[float] = 0.1
    members: bool = True
    base: float = 0.0

    def snap(self, s: float, t: float, tol: float) -> tuple:
        """(s, t) → (s, t, 설명). tol = 부재 스냅 허용 거리 (m, 화면 몇 픽셀에 해당하는 값)"""
        if self.members:
            best = None
            for ps, pt, name in self.targets.points:
                d = ((ps - s) ** 2 + (pt - t) ** 2) ** 0.5
                if d <= tol and (best is None or d < best[0]):
                    best = (d, ps, pt, name)
            if best:
                return best[1], best[2], best[3]
        labels = []
        snapped_s = snapped_t = False
        if self.members:
            hit = min(((abs(v - s), v, n) for v, n in self.targets.s_lines if abs(v - s) <= tol), default=None)
            if hit:
                s, snapped_s = hit[1], True
                labels.append(hit[2])
            hit = min(((abs(v - t), v, n) for v, n in self.targets.t_lines if abs(v - t) <= tol), default=None)
            if hit:
                t, snapped_t = hit[1], True
                labels.append(hit[2])
        if self.grid:
            g = self.grid
            if not snapped_s:
                s = round((self.base + s) / g) * g - self.base
            if not snapped_t:
                t = round(t / g) * g
            if not (snapped_s and snapped_t):
                labels.append("격자")
        return s, t, " + ".join(labels)


def ortho_snap(snapper: "Snapper", last, s: float, t: float, tol: float) -> tuple:
    """직교 모드: 직전 점에서 s 방향(t 고정) 또는 t 방향(s 고정)으로만 — 커서가 더 많이 움직인 축을 따름.
    고정 축은 직전 점 값 그대로, 움직이는 축만 스냅 (선형 직교 = 본체에 직각인 통로 첫 구간)"""
    along_s = abs(s - last[0]) >= abs(t - last[1])
    ss, tt, label = snapper.snap(s, last[1], tol) if along_s else snapper.snap(last[0], t, tol)
    if along_s:
        tt = last[1]
    else:
        ss = last[0]
    return ss, tt, ("직교 s" if along_s else "직교 t") + (f" + {label}" if label else "")


def fmt_sta(sta: float) -> str:
    km = int(sta // 1000)
    return f"{km}+{sta - km * 1000:06.2f}"


def parse_input(text: str, base: float, last: Optional[tuple]) -> tuple:
    """명령줄 입력 → (s, t). 'STA, offset' 절대 / '@ds, dt' 직전 점 기준 상대"""
    from gui.print_draft import parse_station
    raw = str(text).strip()
    rel = raw.startswith("@")
    parts = [x for x in re.split(r"[,\s]+", raw.lstrip("@").strip()) if x]
    if len(parts) != 2:
        raise ValueError("좌표는 'STA, offset' 또는 '@ds, dt' 로 입력하세요 (예: 0+134.5, 3.2 / @5, 0)")
    if rel:
        if last is None:
            raise ValueError("첫 점은 상대 좌표(@)로 줄 수 없습니다")
        try:
            ds, dt = float(parts[0]), float(parts[1])
        except ValueError:
            raise ValueError(f"상대 좌표가 숫자가 아닙니다 ('{raw}')") from None
        return last[0] + ds, last[1] + dt
    s = parse_station(parts[0], "좌표 입력") - base
    try:
        t = float(parts[1])
    except ValueError:
        raise ValueError(f"offset 이 숫자가 아닙니다 ('{parts[1]}')") from None
    return s, t


@dataclass
class PickSession:
    """선택 진행 상태. add() 가 True 를 돌려주면 끝 (finish 로 결과 확정)"""
    request: PickRequest
    points: list = field(default_factory=list)

    def __post_init__(self):
        if self.request.kind not in _PROMPTS:
            raise ValueError(f"선택 종류가 올바르지 않습니다 ({self.request.kind})")
        if self.request.kind == PATH and self.request.start is not None:
            self.points.append(tuple(self.request.start))

    @property
    def kind(self):
        return self.request.kind

    @property
    def last(self):
        return self.points[-1] if self.points else None

    def prompt(self) -> str:
        ps = _PROMPTS[self.kind]
        return f"[{self.request.title}] " + ps[min(len(self.points), len(ps) - 1)]

    def add(self, s: float, t: float) -> bool:
        """점 추가. 같은 자리(1mm) 연속 클릭은 무시. 점·사각형은 필요한 개수가 차면 True"""
        if self.points and abs(self.points[-1][0] - s) < 1e-3 and abs(self.points[-1][1] - t) < 1e-3:
            return False
        self.points.append((s, t))
        if self.kind == RECT and len(self.points) == 2:
            a, b = self.points
            if abs(a[0] - b[0]) < 1e-3 or abs(a[1] - b[1]) < 1e-3:
                self.points.pop()
                raise ValueError("사각형의 두 모서리는 s·t 가 모두 달라야 합니다")
        return self.kind != PATH and len(self.points) >= MIN_POINTS[self.kind]

    def undo(self):
        floor = 1 if (self.kind == PATH and self.request.start is not None) else 0
        if len(self.points) > floor:
            self.points.pop()

    def can_finish(self) -> bool:
        return len(self.points) >= MIN_POINTS[self.kind]

    def finish(self):
        if not self.can_finish():
            raise ValueError(f"점이 {MIN_POINTS[self.kind]}개 이상 필요합니다")
        self.request.on_done(list(self.points))

    def rubber(self, s: float, t: float) -> list:
        """커서까지의 고무줄 (정거장 로컬 꺾은선 목록): 사각형은 닫힌 사각형, 경로는 지금까지 + 커서"""
        if not self.points:
            return []
        if self.kind == RECT:
            (a, b) = self.points[0]
            return [[(a, b), (s, b), (s, t), (a, t), (a, b)]]
        return [list(self.points) + [(s, t)]]
