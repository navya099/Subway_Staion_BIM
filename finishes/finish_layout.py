"""실별 건축 마감 배치 (바닥 마감·채움, 벽 마감, 기둥·승강로 둘레 마감, 천장판·천장틀).

좌표는 정거장 로컬 (s, t), 높이는 FL(z=0) 기준. 결과는 사각 조각 (s0, s1, t0, t1, z0, z1) — 엔진이 선형 각기둥으로 만든다
(원기둥 둘레만 세계 좌표 BoxPiece 다각형 고리).
- 기준 바닥 base: 그 층 FL. 최하층(승강장층)은 승강장 슬래브 위(t 범위)만 마감하고 base = 승강장 상면 (선로부 제외).
  천장 높이 기준도 승강장 상면
- 바닥: 실 영역 ∩ 기준 바닥 영역 − (칸막이벽·사각 기둥·승강로·그 층 계단·에스컬레이터 평면·아래 슬래브 오프닝).
  마감재 = 마감면(base + ffl) 아래 floor_t, 채움 = base ~ 마감재 하면 (FILL_MORTAR 일 때만)
- 벽: 실 경계 중 벽이 있는 부분(본체 벽 내공면, 칸막이벽·구획분리 벽 면)에 두께 wall_t. 가상 경계선·같은 실 안 경계는 없음.
  구조체 면에서 마감 표면까지 FinishType.face (= wall_face, 비우면 wall_t): 마감재는 [face − wall_t, face], 그 뒤 이격은 빈 공간.
  직각 벽 마감은 서로의 이격 공간에 들어가지 않아 모서리에서 마감 표면끼리 만남.
  높이 = 마감면 ~ 천장판 하면(천장 없으면 위 슬래브 하면). 문·본체 측벽 오프닝(통로·환기구) 자리는 비움.
  모서리: s 방향 조각을 그대로 두고 t 방향 조각에서 s 방향 조각을 뺌. 벽·기둥·승강로 평면과 겹치는 부분은 뺌
- 기둥 둘레(실 안 기둥), 승강로 바깥면(그 층을 지나는 엘리베이터, 출입구 자리 비움): 같은 두께·같은 이격의 고리
- 천장: 천장판 하면 = base + ffl + ceiling_h. 영역 = 실 영역 ∩ 기준 바닥(최하층은 승강장 위만, 선로 구간 천장 없음) − (칸막이벽·사각 기둥·승강로·위 슬래브 오프닝 — 위층 에스컬레이터 하부 피트는 제외)
  − 벽·사각 기둥·승강로 마감 표면 안쪽 (바닥은 구조체 면까지, 천장은 벽 마감 표면까지 — 실무 상세 WB-14).
  천장틀 바(M/T, t 방향)를 s 의 bar_spacing 격자에, 캐링 채널(s 방향)을 t 의 carrier_spacing 격자에 (원점 기준 격자)
"""
import math
from dataclasses import dataclass, field

from helper.box_piece import BoxPiece
from openings import decompose
from rooms.room_layout import ceiling_rel
from finishes.finish_gaps import contact_rects, opening_linings
from finishes.finish_spec import FILL_MORTAR

_EPS = 1e-6
RING_SIDES = 16                  # 원기둥 둘레 마감 다각형 변 수 (외접 다각형)


@dataclass
class RoomFinishLayout:
    room: str                    # 실 이름
    use: str
    floor: int
    finish: object               # FinishType
    floor_top: list = field(default_factory=list)      # 바닥 마감재 [(s0, s1, t0, t1, z0, z1)]
    floor_fill: list = field(default_factory=list)     # 바닥 채움(몰탈)
    tactile: list = field(default_factory=list)        # 바닥 마감재를 대체한 점자블록 [(s0, s1, t0, t1, z0, z1, 종류)]
    walls: list = field(default_factory=list)          # 벽 마감 (본체 벽·칸막이벽 면)
    columns: list = field(default_factory=list)        # 사각 기둥·승강로 둘레 마감
    rings: list = field(default_factory=list)          # 원기둥 둘레 마감 BoxPiece (세계 좌표)
    ceiling: list = field(default_factory=list)        # 천장판
    bars: list = field(default_factory=list)           # 천장틀 바 (M/T)
    carriers: list = field(default_factory=list)       # 캐링 채널
    ffl_rel: float = 0.0                               # 바닥 마감면 (FL 기준, 기준 바닥이 여럿이면 대표값)
    ceiling_rel: float = 0.0                           # 천장판 하면 (FL 기준, 천장 없으면 0)


# ---------------------------------------------------------------- 사각형 도우미
def _inter(a, b):
    r = (max(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), min(a[3], b[3]))
    return r if r[1] - r[0] > _EPS and r[3] - r[2] > _EPS else None


def ceiling_bottom_under(cfg, floor: int, rect) -> float:
    """층 floor 에서 rect(s0, s1, t0, t1) 와 겹치는 실 중 천장 마감이 있는 실의 가장 낮은 천장판 하면 (본체 FL 기준).
    마감을 끄거나 천장이 없으면 None. 계단·에스컬레이터 자동 오프닝의 머리 높이 기준 — 아래층 천장이 위 슬래브 하면보다
    낮으면 그 높이로 재서 오프닝을 키운다 (천장판·천장틀이 오르내리는 사람 머리에 걸리지 않게)"""
    fs = getattr(cfg, "finish_settings", None)
    if fs is None or not fs.enabled:
        return None
    from rooms.room_check import layout_rooms
    from rooms.room_layout import resolve_room_names
    try:
        floors = layout_rooms(cfg)
        specs = dict(zip(resolve_room_names(cfg, cfg.rooms), cfg.rooms))
    except ValueError:
        return None                                        # 실 입력 오류는 실 검사가 알림
    if not 1 <= floor <= len(floors):
        return None
    st, pl = cfg.station, cfg.platform
    ref = pl.top_level if (floor == 1 and pl.exists) else st.floor_level(floor)
    low = None
    for room in floors[floor - 1].rooms:
        if not any(_inter(tuple(r), tuple(rect)) for r in room.rects):
            continue
        sp = specs.get(room.name)
        try:
            ft = fs.for_room(room.use, getattr(sp, "finish", "") if sp else "")
        except ValueError:
            continue
        if ft.ceiling:
            c = ref + ft.ffl + ft.ceiling_h
            low = c if low is None else min(low, c)
    return low


def floor_ffl_at(cfg, floor: int, s: float, t: float) -> float:
    """층 floor 의 점 (s, t) 가 든 실의 바닥 마감 높이 ffl (기준 바닥 → 마감면). 마감을 끄거나 실을 못 찾으면 0.
    계단 마감이 디딤판 높이를 아래층·위층 바닥 마감면에 맞출 때 쓴다"""
    fs = getattr(cfg, "finish_settings", None)
    if fs is None or not fs.enabled:
        return 0.0
    from rooms.room_check import layout_rooms
    from rooms.room_layout import resolve_room_names
    try:
        floors = layout_rooms(cfg)
        specs = dict(zip(resolve_room_names(cfg, cfg.rooms), cfg.rooms))
    except ValueError:
        return 0.0
    if not 1 <= floor <= len(floors):
        return 0.0
    for room in floors[floor - 1].rooms:
        if not room.contains(s, t):
            continue
        sp = specs.get(room.name)
        try:
            return fs.for_room(room.use, getattr(sp, "finish", "") if sp else "").ffl
        except ValueError:
            return 0.0
    return 0.0


def _minus(rects, holes):
    out = []
    for r in rects:
        hs = [h for h in (_inter(r, h) for h in holes) if h]
        out += decompose.subtract_rects(r, hs) if hs else [tuple(r)]
    return [r for r in out if r[1] - r[0] > _EPS and r[3] - r[2] > _EPS]


def _merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + _EPS:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _sub_intervals(lo, hi, holes):
    out, cur = [], lo
    for a, b in _merge([(max(a, lo), min(b, hi)) for a, b in holes if min(b, hi) - max(a, lo) > _EPS]):
        if a > cur + _EPS:
            out.append((cur, a))
        cur = max(cur, b)
    if hi > cur + _EPS:
        out.append((cur, hi))
    return out


def _with_z(rects, z0, z1):
    return [(*r, z0, z1) for r in rects] if z1 - z0 > _EPS else []


def _cut_holes(strip, axis, holes):
    """벽 마감 조각 (s0, s1, t0, t1, z0, z1) 에서 벽 평면 구멍 [(접선0, 접선1, z0, z1)] 을 뺀 조각들.
    axis = 's' 이면 s 방향 조각(접선 = s), 't' 이면 t 방향 조각(접선 = t)"""
    s0, s1, t0, t1, z0, z1 = strip
    tan = (s0, s1) if axis == "s" else (t0, t1)
    hs = [(max(a, tan[0]), min(b, tan[1]), max(c, z0), min(d, z1)) for a, b, c, d in holes]
    hs = [h for h in hs if h[1] - h[0] > _EPS and h[3] - h[2] > _EPS]
    if not hs:
        return [strip]
    out = []
    for u0, u1, w0, w1 in decompose.subtract_rects((tan[0], tan[1], z0, z1), hs):
        out.append((u0, u1, t0, t1, w0, w1) if axis == "s" else (s0, s1, u0, u1, w0, w1))
    return out


def _ring_rects(rect, f):
    """사각형 둘레 두께 f 고리: s 방향 2개(모서리 포함) + t 방향 2개 → [(사각형, 축, 면 부호, 면 좌표)]"""
    s0, s1, t0, t1 = rect
    return [((s0 - f, s1 + f, t0 - f, t0), "s", -1, t0), ((s0 - f, s1 + f, t1, t1 + f), "s", 1, t1),
            ((s0 - f, s0, t0, t1), "t", -1, s0), ((s1, s1 + f, t0, t1), "t", 1, s1)]


def _grow(rect, d):
    """사각형을 사방으로 d 만큼 키움"""
    s0, s1, t0, t1 = rect
    return (s0 - d, s1 + d, t0 - d, t1 + d)


def _grid(lo, hi, step):
    """[lo, hi] 안의 step 격자점 (원점 0 기준, 끝에서 step/2 이상 떨어진 것만은 아님 — 구간 안 모두)"""
    k0, k1 = math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9)
    return [k * step for k in range(k0, k1 + 1) if lo + _EPS < k * step < hi - _EPS]


# ---------------------------------------------------------------- 실 경계
def _boundary(rects):
    """실 조각들의 바깥 경계 [(축, 선 좌표, 구간 lo, hi, 안쪽 부호)]. 축 's' = t 일정한 선(s 방향), 't' = s 일정한 선"""
    out = []
    for r in rects:
        s0, s1, t0, t1 = r
        for axis, c, lo, hi, sign in (("s", t0, s0, s1, 1), ("s", t1, s0, s1, -1), ("t", s0, t0, t1, 1), ("t", s1, t0, t1, -1)):
            shared = []
            for q in rects:                                   # 같은 선 반대편에 붙은 같은 실 조각
                if q is r:
                    continue
                if axis == "s" and abs((q[3] if sign > 0 else q[2]) - c) < _EPS:
                    shared.append((q[0], q[1]))
                if axis == "t" and abs((q[1] if sign > 0 else q[0]) - c) < _EPS:
                    shared.append((q[2], q[3]))
            for a, b in _sub_intervals(lo, hi, shared):
                out.append((axis, c, a, b, sign))
    return out


def layout_room_finishes(cfg, settings, floors: list, room_specs: dict, columns: list, openings: list,
                         stairs: list, escalators: list, elevators: list, tactile: list = ()) -> list:
    """실마다 RoomFinishLayout.
    floors: FloorRoomsLayout 목록, room_specs: 실 이름 → RoomSpec (덮어쓸 마감 종류), columns: [(층, s, t, 반폭 s, 반폭 t, 반지름|None)],
    openings: 슬래브 오프닝 OpeningSpec 목록 (수동 + 자동), stairs / escalators / elevators: 배치 결과,
    tactile: 점자블록 TactileBlock 목록 — 바닥 마감재 자리에서 빼고 같은 높이·두께의 블록으로 (RoomFinishLayout.tactile)"""
    st, pl = cfg.station, cfg.platform
    L, hw = st.length, st.width / 2.0
    clear = (0.0, L, -hw, hw)
    wall_ops = cfg.wall_openings()
    pit_names = {lay.pit_opening.name for lay in escalators if getattr(lay, "pit_opening", None) is not None}
    out = []
    for fl in floors:
        n = fl.floor
        base0 = st.floor_level(n)
        zones = [(p0, p1, pl.top_level) for p0, p1 in pl.slab_t_ranges(st.width)] if (n == 1 and pl.exists) else [(-hw, hw, base0)]
        ref = pl.top_level if (n == 1 and pl.exists) else base0
        top_slab = ceiling_rel(st, n)
        walls_fp = [p[:4] for pw in fl.partitions for p in pw.pieces]
        col_rects = [(s - hs, s + hs, t - ht, t + ht) for fn, s, t, hs, ht, r in columns if fn == n and r is None]
        evs = [ev for ev in elevators if ev.lower_floor <= n <= ev.upper_floor]
        ev_rects = [ev.outer_rect() for ev in evs]
        risers = [x for x in list(stairs) + list(escalators) if x.lower_floor == n]      # 이 층에서 오르는 계단·ESC
        skip_ops = pit_names | {o.name for o in openings if o.name.endswith("_SHAFT")}      # 둘레 마감 없는 오프닝
        from railings.railing_layout import railing_footprints
        curbs = railing_footprints(cfg, n)                   # 유리난간 경계석 (구조 바닥 위) — 바닥 마감에서 뺌
        below = [(o.s_start, o.s_end, o.t_lo, o.t_hi) for o in openings if n - 1 in o.slabs]
        # 위 슬래브 오프닝만큼 천장을 뺌. 단 위층 에스컬레이터 하부 피트(슬래브 두께 안에서 트러스가 막음)는 아래층 천장을 뚫지 않음
        above = [(o.s_start, o.s_end, o.t_lo, o.t_hi) for o in openings if n in o.slabs and o.name not in pit_names]
        lines = {}                                           # (축, 좌표) → [(접선 lo, hi, 반두께)] 칸막이벽·구획분리 벽
        for pw in fl.partitions:
            for s0, s1, t0, t1, *_ in pw.pieces:
                if pw.axis == "s":
                    lines.setdefault(("s", round((t0 + t1) / 2.0, 6)), []).append((s0, s1, (t1 - t0) / 2.0))
                else:
                    lines.setdefault(("t", round((s0 + s1) / 2.0, 6)), []).append((t0, t1, (s1 - s0) / 2.0))
        for room in fl.rooms:
            sp = room_specs.get(room.name)
            ft = settings.for_room(room.use, getattr(sp, "finish", "") if sp else "")
            rf = RoomFinishLayout(room.name, room.use, n, ft)
            f = ft.wall_t
            ffl_ref = ref + ft.ffl
            rf.ffl_rel = ffl_ref
            wall_top = top_slab
            if ft.ceiling:
                c = ffl_ref + ft.ceiling_h
                if c + ft.board_t + ft.frame_depth > top_slab + _EPS:
                    raise ValueError(f"실 {room.name}: 천장({ft.name}) 천장판 하면 FL+{c:.3f} + 판·천장틀 "
                                     f"{ft.board_t + ft.frame_depth:.3f}m 가 위 슬래브 하면(FL+{top_slab:.3f})보다 높습니다 "
                                     "(천장 높이를 줄이세요)")
                rf.ceiling_rel = c
                wall_top = c
            obstacles = walls_fp + col_rects + ev_rects
            # 계단·ESC 는 바닥 마감면 아래로 내려오는 곳(접지 구간)만 바닥 마감에서 뺌 — 경사부·트러스 아래 바닥은 마감
            stair_fp = (contact_rects(cfg, risers, n, ft.ffl) if ft.ffl > _EPS else []) + curbs
            # 위 슬래브 오프닝 둘레 마감 (천장 속 막이 + 슬래브 옆면): 벽 마감과 같은 재질, 막이 자리는 천장판에서 뺌
            linings, lining_fp = opening_linings(cfg, n, room, ft, rf.ceiling_rel, openings, stairs, escalators,
                                                 skip_ops, obstacles) if ft.ceiling else ([], [])
            if room.traps is not None:                       # 구조물 내공 확폭 층: 사다리꼴 영역 마감
                from config.widening import clear_traps
                from finishes.finish_pocket import finish_trap_room, piece_region
                from helper import trap_region as T
                walls_t = [piece_region(p) for pw in fl.partitions for p in pw.pieces]
                ctx = dict(clear=clear_traps(cfg, n), zones=zones, obstacles_t=walls_t + T.from_rects(col_rects + ev_rects),
                           walls_t=walls_t, stair_fp=stair_fp, below=below, above=above, tactile=tactile, lines=lines,
                           wall_ops=wall_ops, doors=fl.doors, columns=columns, evs=evs, col_rects=col_rects, top_slab=top_slab,
                           lining_fp=lining_fp)
                finish_trap_room(cfg, room, rf, ft, ctx)
                rf.walls += linings
                out.append(rf)
                continue

            # ---- 바닥
            if ft.ffl > _EPS:
                for p0, p1, zb in zones:
                    area = [r for r in (_inter(rr, (0.0, L, p0, p1)) for rr in room.rects) if r]
                    area = _minus(area, obstacles + stair_fp + below)
                    z_top = zb + ft.ffl
                    blocks = [b for b in tactile if b.floor == n]
                    if blocks and ft.floor_t > _EPS:
                        for b in blocks:
                            for r in area:
                                c = _inter(r, b.rect)
                                if c:
                                    rf.tactile.append((*c, z_top - ft.floor_t, z_top, b.kind))
                        area_top = _minus(area, [b.rect for b in blocks])
                    else:
                        area_top = area
                    rf.floor_top += _with_z(area_top, z_top - ft.floor_t, z_top)
                    if ft.floor_fill == FILL_MORTAR:
                        rf.floor_fill += _with_z(area, zb, z_top - ft.floor_t)

            # ---- 벽 (실 경계 중 벽이 있는 곳). 마감재는 구조체 면에서 gap 띄워 [gap, gap + f] (뒷면 이격 = 빈 공간)
            gap = ft.wall_gap if f > _EPS else 0.0
            face = gap + f
            gap_rects, face_rects = [], []      # 구조체 면 ~ 마감재 뒷면 (다른 벽 마감이 들어가지 않음) / ~ 마감 표면 (천장 제외)
            if f > _EPS:
                s_strips, t_strips = [], []
                for axis, c, a, b, sign in _boundary(room.rects):
                    station = (axis == "s" and abs(abs(c) - hw) < _EPS) or (axis == "t" and (abs(c) < _EPS or abs(c - L) < _EPS))
                    if station:
                        backs = [(a, b, 0.0, "station")]
                    else:
                        backs = []
                        for lo, hi, half in lines.get((axis, round(c, 6)), []):
                            x0, x1 = max(lo, a), min(hi, b)
                            if x1 - x0 > _EPS:
                                backs.append((x0, x1, half, "wall"))
                    for x0, x1, off, kind in backs:
                        d0, d1 = sorted((c + sign * (off + gap), c + sign * (off + face)))
                        r = (x0, x1, d0, d1) if axis == "s" else (d0, d1, x0, x1)
                        (s_strips if axis == "s" else t_strips).append((r, axis, c, kind))
                        for depth, bucket in ((gap, gap_rects), (face, face_rects)):
                            if depth > _EPS:
                                e0, e1 = sorted((c + sign * off, c + sign * (off + depth)))
                                bucket.append((x0, x1, e0, e1) if axis == "s" else (e0, e1, x0, x1))
                s_rects = [r for r, *_ in s_strips]
                pieces = []
                for group, cut_by in ((s_strips, []), (t_strips, s_rects)):
                    for r, axis, c, kind in group:
                        # 직각 벽의 이격 공간에는 들어가지 않음 → 모서리에서 마감 표면끼리 만남
                        for rr in _minus(_minus(_minus([r], obstacles), gap_rects), cut_by):
                            for p0, p1, zb in zones:
                                zz = _inter(rr, (0.0, L, p0, p1))
                                if not zz:
                                    continue
                                z0 = zb + ft.ffl
                                if wall_top <= z0 + _EPS:
                                    raise ValueError(f"실 {room.name}: 벽 마감 높이가 0 이하입니다 (바닥 마감 높이·천장 높이 확인)")
                                holes = []
                                for d in fl.doors:                       # 이 벽 선의 문
                                    o = d.opening
                                    across = (o[2], o[3]) if axis == "s" else (o[0], o[1])
                                    if across[0] - _EPS <= c <= across[1] + _EPS:
                                        holes.append(((o[0], o[1]) if axis == "s" else (o[2], o[3])) + (o[4], o[5]))
                                if kind == "station" and axis == "s":    # 본체 측벽 오프닝 (출구통로·환기구)
                                    side = 1 if c > 0 else -1
                                    holes += [(o[3], o[4], o[5], o[6]) for o in wall_ops if o[1] == n and o[2] == side]
                                pieces += _cut_holes((*zz, z0, wall_top), axis, holes)
                rf.walls = pieces

                # ---- 기둥 둘레 · 승강로 바깥면
                wall_fp = [p[:4] for p in pieces]
                inside = lambda s, t: any(r[0] - _EPS <= s <= r[1] + _EPS and r[2] - _EPS <= t <= r[3] + _EPS for r in room.rects)
                rings = []
                for fn, s, t, hs, ht, rad in columns:
                    if fn != n or not inside(s, t):
                        continue
                    zb = next((z for p0, p1, z in zones if p0 - _EPS <= t <= p1 + _EPS), None)
                    if zb is None:
                        continue                                      # 선로부 기둥
                    if rad is None:
                        rings.append(((s - hs, s + hs, t - ht, t + ht), zb, []))
                    else:
                        rf.rings += _circle_ring(cfg, s, t, rad + gap, f, zb + ft.ffl, wall_top)   # 원기둥은 천장에서 빼지 않음 (기존 단순화)
                for ev in evs:
                    S0, S1, T0, T1 = ev.outer_rect()
                    if not inside((S0 + S1) / 2.0, (T0 + T1) / 2.0):
                        continue
                    zb = next((z for p0, p1, z in zones if p0 - _EPS <= (T0 + T1) / 2.0 <= p1 + _EPS), None)
                    if zb is None:
                        continue
                    base_abs = cfg.lv(ev.spec.s_center) - st.offset
                    holes = [(rect, z0 - base_abs, z1 - base_abs) for _, _, fnum, rect, z0, z1 in ev.door_openings if fnum == n]
                    rings.append(((S0, S1, T0, T1), zb, holes))
                for rect, zb, door_holes in rings:
                    z0 = zb + ft.ffl
                    face_rects.append(_grow(rect, face))
                    for r, axis, sign, c in _ring_rects(_grow(rect, gap), f):
                        for rr in _minus([r], walls_fp + wall_fp + [x for x in col_rects if x != rect]):
                            rr = _inter(rr, clear)
                            if not rr:
                                continue
                            holes = []
                            for (a0, a1, b0, b1), h0, h1 in door_holes:
                                across = (b0, b1) if axis == "s" else (a0, a1)
                                if across[0] - _EPS <= c <= across[1] + _EPS:
                                    holes.append(((a0, a1) if axis == "s" else (b0, b1)) + (h0, h1))
                            rf.columns += _cut_holes((*rr, z0, wall_top), axis, holes)

            # ---- 천장 · 천장틀
            if ft.ceiling:
                c = rf.ceiling_rel
                # 최하층은 승강장 위(t 범위)만 — 선로 구간에는 천장 마감 없음 (바닥·벽과 같은 기준 영역)
                area = [r for rr in room.rects for p0, p1, _ in zones for r in [_inter(tuple(rr), (0.0, L, p0, p1))] if r]
                area = _minus(area, obstacles + above + face_rects + lining_fp)     # 천장판은 벽 마감 표면에서 끝남
                rf.ceiling = _with_z(area, c, c + ft.board_t)
                zb0, zb1 = c + ft.board_t, c + ft.board_t + ft.bar_h
                zc1 = zb1 + ft.carrier_h
                for s0, s1, t0, t1 in area:
                    for s in _grid(s0, s1, ft.bar_spacing):
                        r = _inter((s - ft.bar_w / 2.0, s + ft.bar_w / 2.0, t0, t1), (s0, s1, t0, t1))
                        if r:
                            rf.bars.append((*r, zb0, zb1))
                    for t in _grid(t0, t1, ft.carrier_spacing):
                        r = _inter((s0, s1, t - ft.carrier_w / 2.0, t + ft.carrier_w / 2.0), (s0, s1, t0, t1))
                        if r:
                            rf.carriers.append((*r, zb1, zc1))
            rf.walls += linings
            out.append(rf)
    return out


def _circle_ring(cfg, s, t, r, f, z0_rel, z1_rel) -> list:
    """원기둥 둘레 마감: 기둥에 외접하는 정 RING_SIDES 각형 고리 (두께 f, 모서리 연귀), 세계 좌표 BoxPiece"""
    n = RING_SIDES
    cx, cy = cfg.to_world(s, t)
    th = cfg.theta_at(s)
    half = math.pi / n
    R = r / math.cos(half)                              # 외접 다각형 꼭짓점 반지름
    side = 2.0 * r * math.tan(half)
    base = cfg.lv(s) - cfg.station.offset
    out = []
    for k in range(n):
        a = th + 2.0 * half * k - half                  # 변 시작 꼭짓점 각도 (반시계)
        px, py = cx + R * math.cos(a), cy + R * math.sin(a)
        ux, uy = -math.sin(a + half), math.cos(a + half)   # 변 방향 (반시계 접선)
        tn = math.tan(half)                             # 꼭짓점 회전각 2π/n 의 절반
        out.append(BoxPiece(ox=px, oy=py, ux=ux, uy=uy, a0=0.0, a1=side,
                            sect=[(-f, 0.0), (0.0, 0.0), (0.0, z1_rel - z0_rel), (-f, z1_rel - z0_rel)],
                            z0=base + z0_rel, ks=tn, ke=-tn, local={"center": (s, t, cx, cy, th)}))
    return out
