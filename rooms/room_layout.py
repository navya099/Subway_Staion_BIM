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
from rooms.door_parts import AUTO, AUTO_HEAD_H, SLIDE_OVER
from rooms.room_spec import PARTITION, SEPARATION

_EPS = 1e-6
_SLIVER = 1e-4               # 이보다 얇은 칸막이벽 조각은 만들지 않음 (반올림 자투리)


@dataclass
class RoomLayout:
    name: str
    use: str
    floor: int
    rects: list                  # [(s0, s1, t0, t1)] 실 영역 조각 (입력 실은 1개, 기본 실은 여러 개일 수 있음)
    is_default: bool = False
    traps: list = None           # 구조물 내공 확폭 층: 실 영역 사다리꼴 조각 (helper.trap_region, rects 는 조각의 외접 사각형)

    @property
    def area(self) -> float:
        if self.traps is not None:
            from helper import trap_region as T
            return T.area(self.traps)
        return sum((b - a) * (d - c) for a, b, c, d in self.rects)

    def region(self) -> list:
        """실 영역 사다리꼴 조각 (직사각형 실은 사각형 조각)"""
        from helper import trap_region as T
        return list(self.traps) if self.traps is not None else T.from_rects(self.rects)

    def contains(self, s: float, t: float, tol: float = 1e-6) -> bool:
        from helper import trap_region as T
        return T.contains(self.region(), s, t, tol)


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
class DoorLayout:
    """문 1개: 벽 개구부 (정거장 로컬 상자, FL 기준 높이). 문틀·문짝 형상은 rooms.door_parts.door_shape"""
    name: str
    room: str                    # 문을 정의한 실 이름
    floor: int
    side: str                    # 실의 변 (문짝 열림 방향 = 실 안쪽)
    wall: str                    # 개구부가 난 벽 (PartitionLayout.name)
    kind: str
    opening: tuple               # (s0, s1, t0, t1, z0, z1) 벽 두께 전체
    width: float = 0.9
    height: float = 2.1
    swing: str = "in"            # 열림: 실 안쪽 / 바깥쪽
    hinge: str = None            # 경첩 쪽 (door_parts.hinge_low)
    ffl: float = 0.0             # 개구부 바닥(구조) → 바닥 마감면 (문짝·문틀 시작 높이, 그 아래는 문턱)


@dataclass
class FloorRoomsLayout:
    floor: int
    rooms: list                  # RoomLayout (입력 실 + 기본 실)
    partitions: list             # PartitionLayout (칸막이벽 + 구획분리 벽)
    separations: list = field(default_factory=list)     # SeparationLineLayout (가상 경계선)
    doors: list = field(default_factory=list)           # DoorLayout


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
    from config.widening import has_pockets
    if has_pockets(cfg, floor):
        return _layout_pocket_floor(cfg, floor, specs, names)
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
    tops = {}                        # (축, 좌표) → 벽 윗면 상한 (RoomSpec.wall_tops: 계단 아래를 가로지르는 끝 벽)
    for sp in specs:
        kind = PARTITION if sp.boundary == PARTITION else SEPARATION
        thick = rs.partition_t if kind == PARTITION else sp.sep_t
        opened = set(getattr(sp, "open_sides", ()) or ())
        wtops = getattr(sp, "wall_tops", None) or {}
        for side, t in (("-t", sp.t0), ("+t", sp.t1)):
            if abs(abs(t) - hw) > _EPS and side not in opened:
                lines.setdefault(("s", round(t, 6)), []).append((sp.s0, sp.s1, kind, thick))
                if side in wtops:
                    tops[("s", round(t, 6))] = min(tops.get(("s", round(t, 6)), 1e9), wtops[side])
        for side, s in (("-s", sp.s0), ("+s", sp.s1)):
            if _EPS < s < L - _EPS and side not in opened:
                lines.setdefault(("t", round(s, 6)), []).append((sp.t0, sp.t1, kind, thick))
                if side in wtops:
                    tops[("t", round(s, 6))] = min(tops.get(("t", round(s, 6)), 1e9), wtops[side])
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
    s_walls, t_walls, vlines = [], [], []          # 벽: (사각형, 종류, 두께, 윗면 상한),  가상선: (s0, s1, t0, t1)
    for t, (a, b, (kind, th)) in segments["s"]:
        if th <= _EPS:
            vlines.append((max(a, 0.0), min(b, L), t, t))
            continue
        h = th / 2.0
        s_walls.append(((*clip(a - h, b + h, 0.0, L), *clip(t - h, t + h, -hw, hw)), kind, th, tops.get(("s", t))))
    s_rects = [r for r, *_ in s_walls]
    for s, (a, b, (kind, th)) in segments["t"]:
        a, b = clip(a, b, -hw, hw)
        if th <= _EPS:
            vlines.append((s, s, a, b))
            continue
        h = th / 2.0
        for r in decompose.subtract_rects((*clip(s - h, s + h, 0.0, L), a, b), s_rects):
            if r[1] - r[0] > _SLIVER and r[3] - r[2] > _SLIVER:    # 선 좌표는 1e-6 반올림이라 끝에 그만큼의 얇은 조각이 남음 → 버림
                t_walls.append((r, kind, th, tops.get(("t", s))))

    # ---- 높이 (최하층 승강장 위는 승강장 상면부터)
    z0, z1 = st.floor_level(floor), ceiling_rel(st, floor)
    plat = pl.slab_t_ranges(st.width) if (floor == 1 and pl.exists) else []

    def with_heights(rect, top=None):
        s0, s1, t0, t1 = rect
        cuts = sorted({t0, t1, *(min(max(v, t0), t1) for r in plat for v in r)})
        out = []
        zt = z1 if top is None else min(z1, top)
        for a, b in zip(cuts, cuts[1:]):
            if b - a <= _EPS:
                continue
            on = any(p0 - _EPS <= a and b <= p1 + _EPS for p0, p1 in plat)
            zb = pl.top_level if on else z0
            if zt - zb > _EPS:
                out.append((s0, s1, a, b, zb, zt))
        return out

    level = st.level_name(floor)
    partitions, counters = [], {}
    for axis, walls in (("s", s_walls), ("t", t_walls)):
        for r, kind, th, top in walls:
            pieces = with_heights(r, top)
            if not pieces:
                continue
            pre = "PW" if kind == PARTITION else "SW"
            counters[(pre, axis)] = counters.get((pre, axis), 0) + 1
            partitions.append(PartitionLayout(f"{pre}_{level}_{axis.upper()}{counters[(pre, axis)]}", floor, axis,
                                              pieces, kind, th))
    seps = [SeparationLineLayout(f"SL_{level}_{k}", floor, "s" if abs(r[2] - r[3]) < _EPS else "t", r, z0)
            for k, r in enumerate(vlines, start=1)]
    doors = _cut_doors(cfg, specs, names, partitions, seps)
    return FloorRoomsLayout(floor, rooms, partitions, seps, doors)


def _layout_pocket_floor(cfg, floor: int, specs: list, names: list) -> FloorRoomsLayout:
    """구조물 내공 확폭이 있는 층: 내공 = 넓어진 내공(사다리꼴 조각). 실의 ±t 변이 그 s 구간 어디서나 닿는 내공면
    (inner_min) 위면 그 쪽은 본체 벽 — 실이 확폭 공간(포켓)까지 넓어짐 ('맞닿은 실에 합침'). 다른 입력 실 자리는 뺌.
    나머지 = 기본 실(덩어리마다). 칸막이벽은 같은 규칙, 포켓까지 넓어진 실의 ±s 변 벽은 넓어진 내공면까지"""
    from config.widening import clear_traps, inner_at, inner_min, platform_ranges
    from helper import trap_region as T
    st, pl = cfg.station, cfg.platform
    L = st.length
    clear = clear_traps(cfg, floor)
    ext = [(sp.t0 <= -inner_min(cfg, floor, -1, sp.s0, sp.s1) + _EPS, sp.t1 >= inner_min(cfg, floor, 1, sp.s0, sp.s1) - _EPS)
           for sp in specs]
    rect_traps = [T.rect(*sp.rect) for sp in specs]
    rooms = []
    regions = []
    for i, (name, sp) in enumerate(zip(names, specs)):
        lo, hi = ext[i]
        reg = T.intersect(clear, [T.rect(sp.s0, sp.s1, -T.BIG if lo else sp.t0, T.BIG if hi else sp.t1)])
        others = [r for j, r in enumerate(rect_traps) if j != i]
        reg = T.subtract(reg, others) if others else reg
        regions += reg
        rooms.append(RoomLayout(name, sp.use.strip(), floor, [T.bbox(p) for p in reg], traps=reg))
    rest = T.subtract(clear, regions) if regions else clear
    groups = T.groups(rest)
    use = cfg.room_settings.default_use(floor)
    for k, g in enumerate(groups, start=1):
        suffix = "" if len(groups) == 1 else str(k)
        rooms.append(RoomLayout(f"{st.level_name(floor)}_{use}{suffix}", use, floor, [T.bbox(p) for p in g],
                                is_default=True, traps=g))

    rs = cfg.room_settings
    lines = {}
    for sp, (lo_x, hi_x) in zip(specs, ext):
        kind = PARTITION if sp.boundary == PARTITION else SEPARATION
        thick = rs.partition_t if kind == PARTITION else sp.sep_t
        for t, station in ((sp.t0, lo_x), (sp.t1, hi_x)):
            if not station:
                lines.setdefault(("s", round(t, 6)), []).append((sp.s0, sp.s1, kind, thick))
        for s in (sp.s0, sp.s1):
            if _EPS < s < L - _EPS:
                lines.setdefault(("t", round(s, 6)), []).append((-T.BIG if lo_x else sp.t0, T.BIG if hi_x else sp.t1,
                                                                 kind, thick))
    segments = {"s": [], "t": []}
    for (axis, c), ivs in sorted(lines.items()):
        cuts = sorted({v for a, b, *_ in ivs for v in (a, b)})
        cur = None
        for a, b in zip(cuts, cuts[1:]):
            cover = [(k, th) for lo, hi, k, th in ivs if lo - _EPS <= a and b <= hi + _EPS]
            if not cover:
                cur = None
                continue
            part = [th for k, th in cover if k == PARTITION]
            key = (PARTITION, part[0]) if part else (SEPARATION, max(th for _, th in cover))
            if cur is not None and cur[2] == key and abs(cur[1] - a) < _EPS:
                cur[1] = b
            else:
                cur = [a, b, key]
                segments[axis].append((c, cur))
    s_walls, t_walls, vlines = [], [], []          # 벽: (조각 목록, 종류, 두께)
    for t, (a, b, (kind, th)) in segments["s"]:
        if th <= _EPS:
            vlines.append((max(a, 0.0), min(b, L), t, t))
            continue
        h = th / 2.0
        s_walls.append((T.intersect(clear, [T.rect(max(a - h, 0.0), min(b + h, L), t - h, t + h)]), kind, th))
    s_regs = [p for ps, _, _ in s_walls for p in ps]
    for s, (a, b, (kind, th)) in segments["t"]:
        lo_f, hi_f = -inner_at(cfg, floor, -1, s), inner_at(cfg, floor, 1, s)
        if th <= _EPS:
            vlines.append((s, s, max(a, lo_f), min(b, hi_f)))
            continue
        h = th / 2.0
        reg = T.intersect(clear, [T.rect(max(s - h, 0.0), min(s + h, L), a, b)])
        ps = T.subtract(reg, s_regs) if s_regs else reg
        t_walls.append(([p for p in ps if T.bbox(p)[1] - T.bbox(p)[0] > _SLIVER and T.bbox(p)[3] - T.bbox(p)[2] > _SLIVER], kind, th))

    z0, z1 = st.floor_level(floor), ceiling_rel(st, floor)
    plat = [T.rect(0.0, L, a, b) for a, b in (platform_ranges(cfg) if (floor == 1 and pl.exists) else [])]

    def piece(p, za, zb):
        s0, s1, ta, tb = T.bbox(p)
        tr = T.trap_of(p)
        return (s0, s1, ta, tb, za, zb) if tr is None else (s0, s1, ta, tb, za, zb, tr)

    def with_heights(ps):
        out = []
        for p in ps:
            if plat:
                out += [piece(q, pl.top_level, z1) for q in T.intersect([p], plat)]
                out += [piece(q, z0, z1) for q in T.subtract([p], plat)]
            else:
                out.append(piece(p, z0, z1))
        return sorted(out, key=lambda x: x[:6])

    level = st.level_name(floor)
    partitions, counters = [], {}
    for axis, walls in (("s", s_walls), ("t", t_walls)):
        for ps, kind, th in walls:
            if not ps:
                continue
            pre = "PW" if kind == PARTITION else "SW"
            counters[(pre, axis)] = counters.get((pre, axis), 0) + 1
            partitions.append(PartitionLayout(f"{pre}_{level}_{axis.upper()}{counters[(pre, axis)]}", floor, axis,
                                              with_heights(ps), kind, th))
    seps = [SeparationLineLayout(f"SL_{level}_{k}", floor, "s" if abs(r[2] - r[3]) < _EPS else "t", r, z0)
            for k, r in enumerate(vlines, start=1) if (r[1] - r[0]) + (r[3] - r[2]) > _EPS]
    station_sides = {n: {side for side, x in (("-t", lo_x), ("+t", hi_x)) if x} for n, (lo_x, hi_x) in zip(names, ext)}
    doors = _cut_doors(cfg, specs, names, partitions, seps, station_sides)
    return FloorRoomsLayout(floor, rooms, partitions, seps, doors)


def _door_ffl(cfg, specs, floor: int, line: float, d, half: float, z0: float) -> float:
    """문 양쪽 실의 바닥 마감 높이 중 큰 값 (마감을 끄거나 선로부 바닥이면 0). 실 배치 도중이라 입력 실·층 기본 실 용도에서 바로 찾음"""
    fs = getattr(cfg, "finish_settings", None)
    if fs is None or not fs.enabled:
        return 0.0
    pl = cfg.platform
    if floor == 1 and pl.exists and z0 < pl.top_level - _EPS:
        return 0.0
    best = 0.0
    for sgn in (-1, 1):
        x = line + sgn * (half + 0.05)
        s, t = (x, d.center) if d.side in ("+s", "-s") else (d.center, x)
        sp = next((r for r in specs if r.floor == floor and r.s0 <= s <= r.s1 and r.t0 <= t <= r.t1), None)
        try:
            ft = fs.for_room(sp.use if sp else cfg.room_settings.default_use(floor), sp.finish if sp else "")
        except ValueError:
            continue                                                 # 없는 마감 종류는 마감 검사가 알림
        best = max(best, ft.ffl)
    return best


def _cut_doors(cfg, specs: list, names: list, partitions: list, seps: list, station_sides: dict = None) -> list:
    """실마다 문: 그 변의 벽 조각에서 개구부를 빼고(벽 평면 (접선, z) 에서 decompose), 문짝을 만든다.
    문은 벽 조각 하나의 접선 범위 안에 있어야 하고(승강장 끝 등에서 바닥 높이가 바뀌는 곳에 걸치면 오류),
    문 위로 벽이 남아야 한다 (문 높이 < 벽 높이)"""
    st = cfg.station
    L, hw = st.length, st.width / 2.0
    margin = cfg.room_settings.partition_t / 2.0
    out = []
    for rname, sp in zip(names, specs):
        for k, d in enumerate(sp.doors, start=1):
            dname = d.name.strip() or f"{rname}_D{k}"
            where = f"문 {dname}"
            if d.side in ("+s", "-s"):
                line, wall_axis, lo, hi = (sp.s1 if d.side == "+s" else sp.s0), "t", sp.t0, sp.t1
                on_station = line < _EPS or line > L - _EPS
            else:
                line, wall_axis, lo, hi = (sp.t1 if d.side == "+t" else sp.t0), "s", sp.s0, sp.s1
                on_station = abs(abs(line) - hw) < _EPS if station_sides is None else d.side in station_sides.get(rname, ())
            a, b = d.center - d.width / 2.0, d.center + d.width / 2.0
            if on_station:
                raise ValueError(f"{where}: 실 {rname} 의 {d.side} 변은 본체 벽입니다 (본체 벽 출입은 출구통로·환기구로)")
            if a < lo + margin - _EPS or b > hi - margin + _EPS:
                raise ValueError(f"{where}: 문 범위 {a:.3f} ~ {b:.3f} 이(가) 실 {rname} 의 {d.side} 변"
                                 f"({lo + margin:.3f} ~ {hi - margin:.3f}, 끝 벽 반 두께 제외)을 벗어납니다")

            def on_line(lo_, hi_):
                return lo_ - _EPS <= line <= hi_ + _EPS
            hit = None
            for pw in partitions:
                if pw.axis != wall_axis:
                    continue
                for i, pc in enumerate(pw.pieces):
                    if len(pc) > 6:
                        continue                                  # 사선(확폭 전이부) 조각에는 문을 두지 않음
                    s0, s1, t0, t1, z0, z1 = pc
                    across, tan = ((s0, s1), (t0, t1)) if wall_axis == "t" else ((t0, t1), (s0, s1))
                    if on_line(*across) and tan[0] - _EPS <= a and b <= tan[1] + _EPS and z0 < z1:
                        hit = (pw, i, pc, across, tan)
                        break
                if hit:
                    break
            if hit is None:
                for sl in seps:
                    s0, s1, t0, t1 = sl.rect
                    across, tan = ((s0, s1), (t0, t1)) if wall_axis == "t" else ((t0, t1), (s0, s1))
                    if sl.axis == wall_axis and on_line(*across) and min(tan[1], b) - max(tan[0], a) > _EPS:
                        raise ValueError(f"{where}: 실 {rname} 의 {d.side} 변은 두께 없는 구획분리 경계선입니다 (문을 둘 벽이 없음)")
                raise ValueError(f"{where}: 실 {rname} 의 {d.side} 변 문 자리({a:.3f} ~ {b:.3f})에 벽이 없거나, "
                                 "다른 문·바닥 높이가 바뀌는 곳(승강장 끝)에 걸칩니다")
            pw, i, (s0, s1, t0, t1, z0, z1), across, tan = hit
            ffl = _door_ffl(cfg, specs, sp.floor, line, d, (across[1] - across[0]) / 2.0, z0)
            top = z0 + ffl + d.height
            if top > z1 - _EPS:
                raise ValueError(f"{where}: 문 높이({d.height:g}m)가 벽 높이({z1 - z0 - ffl:.3f}m) 이상입니다")
            if d.kind == AUTO:
                head = top + SLIDE_OVER + AUTO_HEAD_H
                if a - d.width / 2.0 < tan[0] - _EPS or b + d.width / 2.0 > tan[1] + _EPS or head > z1 + _EPS:
                    raise ValueError(f"{where}: 자동문은 양옆에 문 폭의 절반({d.width / 2.0:g}m)과 위에 구동부 높이"
                                     f"({SLIDE_OVER + AUTO_HEAD_H:g}m)만큼 벽이 있어야 합니다")
            hole = (a, b, z0, top)
            new = []
            for u0, u1, w0, w1 in decompose.subtract_rects((tan[0], tan[1], z0, z1), [hole]):
                new.append((across[0], across[1], u0, u1, w0, w1) if wall_axis == "t" else (u0, u1, across[0], across[1], w0, w1))
            pw.pieces[i:i + 1] = new
            if wall_axis == "t":
                opening = (across[0], across[1], a, b, z0, top)
            else:
                opening = (a, b, across[0], across[1], z0, top)
            out.append(DoorLayout(dname, rname, sp.floor, d.side, pw.name, d.kind, opening, d.width, d.height, d.swing, d.hinge, ffl))
    names_ = [d.name for d in out]
    dup = sorted({n for n in names_ if names_.count(n) > 1})
    if dup:
        raise ValueError(f"문 이름이 중복됩니다: {', '.join(dup)}")
    return out


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

