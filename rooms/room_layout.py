"""실(구획) 배치 계산: 층별 입력 실 + 나머지 기본 실, 실 경계 칸막이벽 / 구획분리(벽 또는 가상 경계선).

- 층마다 내공 영역(0 ~ L × ±W/2)에서 입력한 실을 뺀 나머지가 기본 실 (직사각형 조각들, decompose.subtract_rects)
- 경계: 입력한 실의 변 중 본체 벽(내공면) 위가 아닌 부분. 실의 경계 종류가 칸막이벽이면 partition_t, 구획분리면 sep_t
  (0 이면 가상 경계선). 같은 선에서 겹치면 칸막이벽 우선, 구획분리끼리는 두꺼운 쪽. 같은 선 위의 같은 종류 변은 합쳐 한 번만,
  변(중심선) 양쪽으로 반씩. 모서리 중복·빈틈이 없도록 s 방향 벽(t 일정)은 끝을 반 두께씩 늘리고,
  t 방향 벽(s 일정)은 s 방향 벽과 겹치는 부분을 뺀다. 모두 내공 영역 안으로 자름
- 높이: 그 층 바닥(FL) ~ 위 슬래브 하면. 최하층에서 승강장 슬래브 위(t 범위)는 승강장 상면부터
"""
from dataclasses import dataclass, field

from openings import decompose
from rooms.room_spec import PARTITION, SEPARATION

_EPS = 1e-6


@dataclass
class RoomLayout:
    name: str
    use: str
    floor: int
    rects: list                  # [(s0, s1, t0, t1)] 실 영역 조각 (입력 실은 1개, 기본 실은 여러 개일 수 있음)
    is_default: bool = False

    @property
    def area(self) -> float:
        return sum((b - a) * (d - c) for a, b, c, d in self.rects)


@dataclass
class PartitionLayout:
    name: str
    floor: int
    axis: str                    # 's' = s 방향으로 뻗은 벽(t 일정), 't' = t 방향으로 뻗은 벽(s 일정)
    pieces: list = field(default_factory=list)      # [(s0, s1, t0, t1, z_rel0, z_rel1)]
    kind: str = PARTITION        # PARTITION(칸막이벽) | SEPARATION(구획분리 벽, 두께 > 0)
    thickness: float = 0.0


@dataclass
class SeparationLineLayout:
    """두께 없는 구획분리 경계선 (공간만 나눔). rect = (s0, s1, t0, t1) 중 한 방향 폭이 0"""
    name: str
    floor: int
    axis: str
    rect: tuple
    z_rel: float                 # 층 FL (FL 기준)


@dataclass
class FloorRoomsLayout:
    floor: int
    rooms: list                  # RoomLayout (입력 실 + 기본 실)
    partitions: list             # PartitionLayout (칸막이벽 + 구획분리 벽)
    separations: list = field(default_factory=list)     # SeparationLineLayout (가상 경계선)


def _merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + _EPS:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def connected_groups(rects: list) -> list:
    """직사각형 조각들을 서로 맞닿은(변을 길이 > 0 만큼 공유하는) 것끼리 묶음. 묶음은 가장 작은 s 순, 묶음 안 순서는 유지"""
    n = len(rects)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def touch(a, b):
        s_ov = min(a[1], b[1]) - max(a[0], b[0])
        t_ov = min(a[3], b[3]) - max(a[2], b[2])
        return (s_ov > _EPS and t_ov > -_EPS) or (t_ov > _EPS and s_ov > -_EPS)

    for i in range(n):
        for j in range(i + 1, n):
            if touch(rects[i], rects[j]):
                parent[find(i)] = find(j)
    groups = {}
    for i, r in enumerate(rects):
        groups.setdefault(find(i), []).append(r)
    return sorted(groups.values(), key=lambda g: (min(r[0] for r in g), min(r[2] for r in g)))


def ceiling_rel(st, floor: int) -> float:
    """그 층 위 슬래브 하면 (FL 기준)"""
    return st.height - st.roof_t if floor == st.floors else st.floor_level(floor + 1) - st.mid_t


def layout_floor_rooms(cfg, floor: int, specs: list, names: list) -> FloorRoomsLayout:
    st, pl = cfg.station, cfg.platform
    L, hw = st.length, st.width / 2.0
    clear = (0.0, L, -hw, hw)
    rooms = [RoomLayout(n, sp.use.strip(), floor, [sp.rect]) for n, sp in zip(names, specs)]
    rest = decompose.subtract_rects(clear, [sp.rect for sp in specs])
    groups = connected_groups(rest)                # 입력 실로 끊긴 나머지 영역은 따로따로 기본 실
    use = cfg.room_settings.default_use(floor)
    for k, g in enumerate(groups, start=1):
        suffix = "" if len(groups) == 1 else str(k)
        rooms.append(RoomLayout(f"{st.level_name(floor)}_{use}{suffix}", use, floor, g, is_default=True))

    # ---- 경계 중심선: 입력 실의 변 (본체 벽 위는 제외). 선마다 (구간, 종류, 두께)
    rs = cfg.room_settings
    lines = {}                       # ('s', t) → [(s0, s1, 종류, 두께)] s 방향 선,  ('t', s) → [(t0, t1, …)] t 방향 선
    for sp in specs:
        kind = PARTITION if sp.boundary == PARTITION else SEPARATION
        thick = rs.partition_t if kind == PARTITION else sp.sep_t
        for t in (sp.t0, sp.t1):
            if abs(abs(t) - hw) > _EPS:
                lines.setdefault(("s", round(t, 6)), []).append((sp.s0, sp.s1, kind, thick))
        for s in (sp.s0, sp.s1):
            if _EPS < s < L - _EPS:
                lines.setdefault(("t", round(s, 6)), []).append((sp.t0, sp.t1, kind, thick))
    segments = {"s": [], "t": []}    # [(선 좌표, 구간 시작, 끝, 종류, 두께)]
    for (axis, c), ivs in sorted(lines.items()):
        cuts = sorted({v for a, b, *_ in ivs for v in (a, b)})
        cur = None
        for a, b in zip(cuts, cuts[1:]):
            cover = [(k, th) for lo, hi, k, th in ivs if lo - _EPS <= a and b <= hi + _EPS]
            if not cover:
                cur = None
                continue
            part = [th for k, th in cover if k == PARTITION]
            key = (PARTITION, part[0]) if part else (SEPARATION, max(th for _, th in cover))   # 칸막이벽 우선
            if cur is not None and cur[2] == key and abs(cur[1] - a) < _EPS:
                cur[1] = b
            else:
                cur = [a, b, key]
                segments[axis].append((c, cur))
    clip = lambda a, b, lo, hi: (max(a, lo), min(b, hi))
    s_walls, t_walls, vlines = [], [], []          # 벽: (사각형, 종류, 두께),  가상선: (s0, s1, t0, t1)
    for t, (a, b, (kind, th)) in segments["s"]:
        if th <= _EPS:
            vlines.append((max(a, 0.0), min(b, L), t, t))
            continue
        h = th / 2.0
        s_walls.append(((*clip(a - h, b + h, 0.0, L), *clip(t - h, t + h, -hw, hw)), kind, th))
    s_rects = [r for r, _, _ in s_walls]
    for s, (a, b, (kind, th)) in segments["t"]:
        a, b = clip(a, b, -hw, hw)
        if th <= _EPS:
            vlines.append((s, s, a, b))
            continue
        h = th / 2.0
        for r in decompose.subtract_rects((*clip(s - h, s + h, 0.0, L), a, b), s_rects):
            t_walls.append((r, kind, th))

    # ---- 높이 (최하층 승강장 위는 승강장 상면부터)
    z0, z1 = st.floor_level(floor), ceiling_rel(st, floor)
    plat = pl.slab_t_ranges(st.width) if (floor == 1 and pl.exists) else []

    def with_heights(rect):
        s0, s1, t0, t1 = rect
        cuts = sorted({t0, t1, *(min(max(v, t0), t1) for r in plat for v in r)})
        out = []
        for a, b in zip(cuts, cuts[1:]):
            if b - a <= _EPS:
                continue
            on = any(p0 - _EPS <= a and b <= p1 + _EPS for p0, p1 in plat)
            out.append((s0, s1, a, b, pl.top_level if on else z0, z1))
        return out

    level = st.level_name(floor)
    partitions, counters = [], {}
    for axis, walls in (("s", s_walls), ("t", t_walls)):
        for r, kind, th in walls:
            pre = "PW" if kind == PARTITION else "SW"
            counters[(pre, axis)] = counters.get((pre, axis), 0) + 1
            partitions.append(PartitionLayout(f"{pre}_{level}_{axis.upper()}{counters[(pre, axis)]}", floor, axis,
                                              with_heights(r), kind, th))
    seps = [SeparationLineLayout(f"SL_{level}_{k}", floor, "s" if abs(r[2] - r[3]) < _EPS else "t", r, z0)
            for k, r in enumerate(vlines, start=1)]
    return FloorRoomsLayout(floor, rooms, partitions, seps)


def resolve_room_names(cfg, specs: list) -> list[str]:
    """실 이름 (지정 이름 우선, 없으면 층이름_용도 + 층·용도별 일련번호). 중복은 오류"""
    st = cfg.station
    counters, names = {}, []
    for sp in specs:
        key = (sp.floor, sp.use.strip())
        counters[key] = counters.get(key, 0) + 1
        auto = f"{st.level_name(sp.floor) if 1 <= sp.floor <= st.floors else sp.floor}_{sp.use.strip()}{counters[key]}"
        names.append(sp.name.strip() or auto)
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"실 이름이 중복됩니다: {', '.join(dup)}")
    return names

