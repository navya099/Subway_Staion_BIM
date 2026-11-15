"""실(구획) 배치 계산: 층별 입력 실 + 나머지 기본 실, 실 경계 칸막이벽.

- 층마다 내공 영역(0 ~ L × ±W/2)에서 입력한 실을 뺀 나머지가 기본 실 (직사각형 조각들, decompose.subtract_rects)
- 칸막이벽: 입력한 실의 변 중 본체 벽(내공면) 위가 아닌 부분. 같은 선 위의 변은 합쳐 한 번만, 두께 = partition_t,
  변(중심선) 양쪽으로 반씩. 모서리 중복·빈틈이 없도록 s 방향 벽(t 일정)은 끝을 반 두께씩 늘리고,
  t 방향 벽(s 일정)은 s 방향 벽과 겹치는 부분을 뺀다. 모두 내공 영역 안으로 자름
- 높이: 그 층 바닥(FL) ~ 위 슬래브 하면. 최하층에서 승강장 슬래브 위(t 범위)는 승강장 상면부터
"""
from dataclasses import dataclass, field

from openings import decompose

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


@dataclass
class FloorRoomsLayout:
    floor: int
    rooms: list                  # RoomLayout (입력 실 + 기본 실)
    partitions: list             # PartitionLayout


def _merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + _EPS:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def ceiling_rel(st, floor: int) -> float:
    """그 층 위 슬래브 하면 (FL 기준)"""
    return st.height - st.roof_t if floor == st.floors else st.floor_level(floor + 1) - st.mid_t


def layout_floor_rooms(cfg, floor: int, specs: list, names: list) -> FloorRoomsLayout:
    st, pl = cfg.station, cfg.platform
    L, hw = st.length, st.width / 2.0
    clear = (0.0, L, -hw, hw)
    rooms = [RoomLayout(n, sp.use.strip(), floor, [sp.rect]) for n, sp in zip(names, specs)]
    rest = decompose.subtract_rects(clear, [sp.rect for sp in specs])
    if rest:
        use = cfg.room_settings.default_use(floor)
        rooms.append(RoomLayout(f"{st.level_name(floor)}_{use}", use, floor, rest, is_default=True))

    # ---- 칸막이벽 중심선: 입력 실의 변 (본체 벽 위는 제외)
    s_lines, t_lines = {}, {}        # t 값 → [(s0, s1)] (s 방향 벽),  s 값 → [(t0, t1)] (t 방향 벽)
    for sp in specs:
        for t in (sp.t0, sp.t1):
            if abs(abs(t) - hw) > _EPS:
                s_lines.setdefault(round(t, 6), []).append((sp.s0, sp.s1))
        for s in (sp.s0, sp.s1):
            if s > _EPS and s < L - _EPS:
                t_lines.setdefault(round(s, 6), []).append((sp.t0, sp.t1))
    h = cfg.room_settings.partition_t / 2.0
    clip = lambda a, b, lo, hi: (max(a, lo), min(b, hi))
    s_walls = []
    for t, segs in sorted(s_lines.items()):
        for a, b in _merge(segs):
            a, b = clip(a - h, b + h, 0.0, L)
            t0, t1 = clip(t - h, t + h, -hw, hw)
            s_walls.append((a, b, t0, t1))
    t_walls = []
    for s, segs in sorted(t_lines.items()):
        for a, b in _merge(segs):
            a, b = clip(a, b, -hw, hw)
            s0, s1 = clip(s - h, s + h, 0.0, L)
            t_walls += decompose.subtract_rects((s0, s1, a, b), s_walls)

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
    partitions = []
    for k, r in enumerate(s_walls, start=1):
        partitions.append(PartitionLayout(f"PW_{level}_S{k}", floor, "s", with_heights(r)))
    for k, r in enumerate(t_walls, start=1):
        partitions.append(PartitionLayout(f"PW_{level}_T{k}", floor, "t", with_heights(r)))
    return FloorRoomsLayout(floor, rooms, partitions)


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

