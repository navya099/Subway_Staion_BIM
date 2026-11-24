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
    skirts: list = field(default_factory=list)         # 걸레받이 (벽·기둥·승강로 둘레)
    skirt_rings: list = field(default_factory=list)    # 원기둥 둘레 걸레받이 BoxPiece
    wall_slopes: list = field(default_factory=list)    # 벽 마감 중 계단 옆 걸레받이에 잘린 조각 (s0, s1, t0, t1, 하단·상단 @ s0, 하단·상단 @ s1)
    skirt_slopes: list = field(default_factory=list)   # 계단 옆 걸레받이 (경사 띠, 같은 형식)
    columns: list = field(default_factory=list)        # 사각 기둥·승강로 둘레 마감
    rings: list = field(default_factory=list)          # 원기둥 둘레 마감 BoxPiece (세계 좌표)
    ceiling: list = field(default_factory=list)        # 천장판
    bars: list = field(default_factory=list)           # 천장틀 바 (M/T)
    carriers: list = field(default_factory=list)       # 캐링 채널
    lights: list = field(default_factory=list)         # 매입 조명 [(s0, s1, t0, t1, 긴 방향 's'|'t')] (천장판·천장틀은 그 자리를 비움)
    diffusers: list = field(default_factory=list)      # 디퓨저 [(s0, s1, t0, t1)]
    ffl_rel: float = 0.0                               # 바닥 마감면 (FL 기준, 기준 바닥이 여럿이면 대표값)
    ceiling_rel: float = 0.0                           # 천장판 하면 (FL 기준, 천장 없으면 0)


# ---------------------------------------------------------------- 사각형 도우미

def room_wall_hole(cfg, op):
    """본체 측벽 오프닝 → 실 벽 마감에서 비울 (s0, s1, z0, z1) (출구통로 마감이 있으면 통로 마감 개구부 — passage_finish)"""
    from passages.passage_finish import room_wall_hole as hole
    return hole(cfg, op)


def room_wall_holes(cfg, op, skirt: bool) -> list:
    """본체 측벽 오프닝 → 실 벽 마감(패널 또는 걸레받이)에서 비울 자리 목록"""
    from passages.passage_finish import room_wall_skirt_hole
    return [room_wall_hole(cfg, op)] + (room_wall_skirt_hole(cfg, op) if skirt else [])


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


def shaft_walls(cfg, n: int, openings: list, stairs: list, escalators: list) -> list:
    """층 n 에서 오르는 계단·ESC 의 위 슬래브 오프닝 중 벽 마감 패널까지 넓힌 쪽 (finish_clear.shaft_opening_t —
    본체 벽 마감 표면 또는 계단실 옆 칸막이벽) → [(s0, s1, 쪽, 윗면, 패널 t0, t1)].
    패널 = 계단·ESC 변 ~ 오프닝 가장자리, 아래층 바닥 마감면 ~ 위층 바닥 마감면 한 장 (이슈 #32 계단 구간 벽 마감)"""
    st = cfg.station
    if n >= st.floors:
        return []
    by_name = {x.opening.name: x for x in list(stairs) + list(escalators) if x.lower_floor == n}
    out = []
    for o in openings:
        lay = by_name.get(o.name)
        if lay is None or n not in o.slabs:
            continue
        sc = lay.spec.side_clear
        lo, hi = lay.t_range[0] - sc, lay.t_range[1] + sc
        mid = (o.s_start + o.s_end) / 2.0
        if o.t_hi > hi + 1e-5:
            up = st.floor_level(n + 1) + floor_ffl_at(cfg, n + 1, mid, o.t_hi + 0.01)
            out.append((o.s_start, o.s_end, 1, up, hi, o.t_hi))
        if o.t_lo < lo - 1e-5:
            up = st.floor_level(n + 1) + floor_ffl_at(cfg, n + 1, mid, o.t_lo - 0.01)
            out.append((o.s_start, o.s_end, -1, up, o.t_lo, lo))
    return out


def _shaft_panels(cfg, fl, rfs, shafts):
    """계단 구간 벽 마감 패널: 그 띠(s 구간 × 패널 t) 자리의 다른 벽 마감(실 경계 마감·막이)을 빼고, 계단 시작 쪽 실의
    벽 마감재로 아래층 바닥 마감면 ~ 위층 바닥 마감면 한 장을 그 실 벽 마감에 더함 (문 자리는 비움)"""
    for s0, s1, side, top, b0, b1 in shafts:
        band = (s0, s1, b0, b1)
        for rf in rfs:                                       # 띠 자리의 기존 벽 마감 제거 (높이 무관)
            keep = []
            for p in rf.walls:
                fp = (p[0], p[1], p[2], p[3])
                if _inter(fp, band):
                    keep += [(*r, *p[4:]) for r in _minus([fp], [band])]
                else:
                    keep.append(p)
            rf.walls = keep
        tm = (b0 + b1) / 2.0
        owner = None
        for ds in (0.05, (s1 - s0) / 2.0, s1 - s0 - 0.05):   # −s 로 오르는 계단·ESC 는 창고가 s0 쪽 → 반대 끝(시작 쪽)까지 찾음
            for rf, rm in zip(rfs, fl.rooms):
                if rm.contains(s0 + ds, tm) and rf.finish.wall_t > _EPS:
                    owner = owner or rf
        if owner is None:
            continue
        holes = [(d.opening[0], d.opening[1], d.opening[4], d.opening[5]) for d in fl.doors
                 if min(d.opening[3], b1 + 0.5) - max(d.opening[2], b0 - 0.5) > _EPS
                 and min(d.opening[1], s1) - max(d.opening[0], s0) > _EPS]
        # 창고 끝 벽 등이 띠를 가로지르면 그 자리는 벽 윗면(계단 하면) 위로만 — 벽 위로 틈이 보이지 않게
        cross = [q for pw in fl.partitions for q in pw.pieces if _inter(tuple(q[:4]), band)]
        wide = (s0, s1, b0 - 0.06, b1 + 0.06)                # 그 자리 바닥을 따르는 걸레받이 윗면부터
        holes += [(q[0], q[1], q[4], q[5]) for rf in rfs for q in rf.skirts
                  if q[1] - q[0] > q[3] - q[2] and _inter(tuple(q[:4]), wide)]
        for r in _minus([band], [q[:4] for q in cross]):
            hs = [(r[0] if 0.0 < a - r[0] < 0.06 else a, r[1] if 0.0 < r[1] - b < 0.06 else b, c, d)      # 끝 벽 걸레받이 두께만큼의 틈까지
                  for a, b, c, d in holes]
            owner.walls += _cut_holes((*r, owner.ffl_rel, top), "s", hs)
        for q in cross:
            r = _inter(tuple(q[:4]), band)
            if top - q[5] > _EPS:
                owner.walls.append((*r, max(owner.ffl_rel, q[5]), top))


def _reflex(rects, axis, c, x) -> bool:
    """경계 선(axis, c) 위 점 x 가 실 영역의 반사각 꼭짓점(주변 네 칸 중 세 칸이 실 안)인가 — 실이 벽 모서리를 감쌈"""
    s, t = (x, c) if axis == "s" else (c, x)
    d = 1e-4
    inside = lambda u, v: any(r[0] - 1e-9 <= u <= r[1] + 1e-9 and r[2] - 1e-9 <= v <= r[3] + 1e-9 for r in rects)
    return sum(inside(s + ds, t + dt) for ds in (-d, d) for dt in (-d, d)) == 3


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
        shafts = shaft_walls(cfg, n, openings, stairs, escalators)   # 계단 구간 본체 벽 마감 (s0, s1, 쪽, 윗면) — 이슈 #32
        lines = {}                                           # (축, 좌표) → [(접선 lo, hi, 반두께)] 칸막이벽·구획분리 벽
        ptops = {}                                           # (축, 좌표) → [(접선 lo, hi, 벽 윗면)] 벽 마감이 벽 위로 나가지 않게
        for pw in fl.partitions:
            for s0, s1, t0, t1, *zz in pw.pieces:
                if pw.axis == "s":
                    key, iv = ("s", round((t0 + t1) / 2.0, 6)), (s0, s1)
                    lines.setdefault(key, []).append((s0, s1, (t1 - t0) / 2.0))
                else:
                    key, iv = ("t", round((s0 + s1) / 2.0, 6)), (t0, t1)
                    lines.setdefault(key, []).append((t0, t1, (s1 - s0) / 2.0))
                if len(zz) > 1:
                    ptops.setdefault(key, []).append((*iv, zz[1]))

        def part_top(axis, c, lo, hi, default):
            """그 선 칸막이벽 조각 중 [lo, hi] 와 겹치는 것의 가장 낮은 윗면 (계단 아래 끝 벽은 계단 하면까지라 마감도 거기까지)"""
            tops = [z for a, b, z in ptops.get((axis, round(c, 6)), []) if min(b, hi) - max(a, lo) > _EPS]
            return min([default] + tops)
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

            # ---- 벽 (실 경계 중 벽이 있는 곳). 패널·걸레받이 한 벌씩 (WallPass): 구조체 면에서 [gap, face] (뒷면 이격 = 빈 공간)
            def wall_pass(w):
                """벽 마감 한 벌 → (벽 조각, 기둥·승강로 둘레 조각, 원기둥 고리, 마감 표면까지 평면)"""
                gap, face = w.gap, w.face
                columns_out, rings_out = [], []
                gap_rects, face_rects = [], []      # 구조체 면 ~ 마감재 뒷면 (다른 벽 마감이 들어가지 않음) / ~ 마감 표면 (천장 제외)
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
                        kg, kf = (w.pgap, w.pface) if kind == "wall" else (gap, face)   # 칸막이벽은 칸막이벽 전용 거리
                        d0, d1 = sorted((c + sign * (off + kg), c + sign * (off + kf)))
                        # 실이 벽 모서리를 감싸는 곳(반사각 꼭짓점 — 다른 실의 바깥 모서리): 마감을 모서리 너머로 늘려 서로 만나게.
                        # s 방향 마감이 모서리를 차지(벽 반두께 + 마감 표면까지), t 방향 마감은 s 방향 마감 뒷면까지
                        g0, g1 = x0, x1                              # 이격 공간은 벽 끝(반두께)까지만 늘림
                        if kind == "wall":
                            ext = off + (kf if axis == "s" else kg)
                            other = "t" if axis == "s" else "s"

                            def turns(x):                            # 모서리를 돌아 이어지는 벽이 있음 (열린 끝은 끝막음이 맡음)
                                m = 2.0 * off + _EPS                # 직각 벽 조각은 이 선의 벽 두께만큼 잘려 있음
                                return any(lo - m <= c <= hi + m for lo, hi, _ in lines.get((other, round(x, 6)), []))
                            near = 2.0 * off + _EPS                  # t 방향 벽 조각은 s 방향 벽 두께만큼 짧음
                            if abs(x0 - a) <= near and _reflex(room.rects, axis, c, a) and turns(a):
                                x0, g0 = a - ext, a - off
                            if abs(x1 - b) <= near and _reflex(room.rects, axis, c, b) and turns(b):
                                x1, g1 = b + ext, b + off
                        r = (x0, x1, d0, d1) if axis == "s" else (d0, d1, x0, x1)
                        (s_strips if axis == "s" else t_strips).append((r, axis, c, kind))
                        for depth, bucket, (y0, y1) in ((kg, gap_rects, (g0, g1)), (kf, face_rects, (x0, x1))):
                            if depth > _EPS:
                                e0, e1 = sorted((c + sign * off, c + sign * (off + depth)))
                                bucket.append((y0, y1, e0, e1) if axis == "s" else (e0, e1, y0, y1))
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
                                z0 = zb + ft.ffl + w.z0
                                if wall_top <= z0 + _EPS:
                                    raise ValueError(f"실 {room.name}: 벽 마감 높이가 0 이하입니다 (바닥 마감 높이·걸레받이 높이·천장 높이 확인)")
                                holes = []
                                for d in fl.doors:                       # 이 벽 선의 문
                                    o = d.opening
                                    across = (o[2], o[3]) if axis == "s" else (o[0], o[1])
                                    if across[0] - _EPS <= c <= across[1] + _EPS:
                                        holes.append(((o[0], o[1]) if axis == "s" else (o[2], o[3])) + (o[4], o[5]))
                                if kind == "station" and axis == "s":    # 본체 측벽 오프닝 (출구통로·환기구)
                                    side = 1 if c > 0 else -1
                                    holes += [x for o in wall_ops if o[1] == n and o[2] == side for x in room_wall_holes(cfg, o, w.skirt)]
                                lo_, hi_ = (zz[0], zz[1]) if axis == "s" else (zz[2], zz[3])
                                top = part_top(axis, c, lo_, hi_, wall_top) if kind == "wall" else wall_top
                                if w.z1 is not None:
                                    top = min(top, zb + ft.ffl + w.z1)
                                if top - z0 > _EPS:
                                    pieces += _cut_holes((*zz, z0, top), axis, holes)

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
                        z1 = wall_top if w.z1 is None else min(wall_top, zb + ft.ffl + w.z1)
                        rings_out += _circle_ring(cfg, s, t, rad + gap, face - gap, zb + ft.ffl + w.z0, z1)   # 원기둥은 천장에서 빼지 않음 (기존 단순화)
                for ev in evs:
                    S0, S1, T0, T1 = ev.outer_rect()
                    if not inside((S0 + S1) / 2.0, (T0 + T1) / 2.0):
                        continue
                    zb = next((z for p0, p1, z in zones if p0 - _EPS <= (T0 + T1) / 2.0 <= p1 + _EPS), None)
                    if zb is None:
                        continue
                    base_abs = cfg.lv(ev.spec.s_center) - st.offset
                    if ev.spec.shaft == "glass":
                        continue                                  # 투시형: 유리·금속 패널이 마감
                    holes = [(rect, z0 - base_abs, z1 - base_abs) for _, _, fnum, rect, z0, z1 in ev.door_openings if fnum == n]
                    rings.append(((S0, S1, T0, T1), zb, holes))
                for rect, zb, door_holes in rings:
                    z0 = zb + ft.ffl + w.z0
                    z1 = wall_top if w.z1 is None else min(wall_top, zb + ft.ffl + w.z1)
                    face_rects.append(_grow(rect, face))
                    for r, axis, sign, c in _ring_rects(_grow(rect, gap), face - gap):
                        for rr in _minus([r], walls_fp + wall_fp + [x for x in col_rects if x != rect]):
                            rr = _inter(rr, clear)
                            if not rr:
                                continue
                            holes = []
                            for (a0, a1, b0, b1), h0, h1 in door_holes:
                                across = (b0, b1) if axis == "s" else (a0, a1)
                                if across[0] - gap - _EPS <= c <= across[1] + gap + _EPS:   # 마감은 벽면에서 이격(gap)만큼 떨어져 있음
                                    holes.append(((a0, a1) if axis == "s" else (b0, b1)) + (h0, h1))
                            columns_out += _cut_holes((*rr, z0, z1), axis, holes)
                return pieces, columns_out, rings_out, face_rects

            face_rects = []
            if f > _EPS:
                rf.walls, rf.columns, rf.rings, face_rects = wall_pass(ft.panel_pass())
                if ft.has_skirt:
                    sw, sc, rf.skirt_rings, _ = wall_pass(ft.skirt_pass())
                    rf.skirts = sw + sc

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
        _wall_end_caps(cfg, fl, [r for r in out if r.floor == n], zones, L)
        _shaft_panels(cfg, fl, [r for r in out if r.floor == n], shafts)
        _stair_skirts(cfg, fl, [r for r in out if r.floor == n], stairs, escalators)
        for rf in [r for r in out if r.floor == n]:
            _ceiling_fixtures(cfg, rf, columns)
    return out


def _ceiling_fixtures(cfg, rf, columns):
    """천장 기구(조명·디퓨저) 배치 → 천장판·천장틀에서 그 자리를 뺌 (매입)"""
    ft = rf.finish
    if not rf.ceiling or not (ft.has_light or ft.has_diffuser):
        return
    from finishes.finish_pocket import _out, piece_region
    from fixtures.fixture_layout import layout_fixtures
    from helper import trap_region as T
    from smokewalls.smoke_layout import layout_smoke_barriers
    blocked = [_grow((s, s, t, t), rad + ft.face + 0.05) for fn, s, t, hs, ht, rad in columns if fn == rf.floor and rad is not None]
    blocked += [tuple(q[:4]) for sb in layout_smoke_barriers(cfg) if sb.floor == rf.floor for ps in sb.parts.values() for q in ps]
    rf.lights, rf.diffusers = layout_fixtures(ft, [piece_region(p) for p in rf.ceiling], blocked)
    holes = [tuple(x[:4]) for x in rf.lights + rf.diffusers]
    if not holes:
        return

    def cut(pieces):
        new = []
        for p in pieces:
            near = [h for h in holes if _inter(tuple(p[:4]), h)]
            if not near:
                new.append(p)
            elif len(p) == 6:
                new += [(*r, p[4], p[5]) for r in _minus([tuple(p[:4])], near)]
            else:                                                    # 사다리꼴 조각 (구조물 확폭)
                new += [_out(q, p[4], p[5]) for q in T.subtract([piece_region(p)], T.from_rects(near))]
        return new
    rf.ceiling, rf.bars, rf.carriers = cut(rf.ceiling), cut(rf.bars), cut(rf.carriers)


def _wall_end_caps(cfg, fl, rfs, zones, L):
    """칸막이벽(s 방향)이 다른 벽에 닿지 않고 끝나는 곳(계단실 앞처럼 열린 끝): 벽 마감이 구조체에서 띄워 붙어 있어 끝에서 벽과
    양쪽 마감 사이 빈 공간이 보이므로 끝막음 — 양쪽 마감을 벽 끝 + 마감 두께까지 늘리고, 그 사이(벽 끝면 + 이격)를 끝 앞 실의
    마감재로 덮음. 높이 = 끝 앞 실 마감면 ~ 벽 마감 윗면(천장판 하면, 없으면 슬래브 하면 — 칸막이벽 윗면 이하)"""
    def room_at(s, t):
        return next((rf for rf, rm in zip(rfs, fl.rooms) if rm.contains(s, t)), None)
    walls = [(p, pw) for pw in fl.partitions for p in pw.pieces]
    s_walls = [(p, pw) for p, pw in walls if pw.axis == "s"]
    for p, pw in s_walls:
        s0, s1, t0, t1 = p[:4]
        c, h = (t0 + t1) / 2.0, (t1 - t0) / 2.0
        for end, out_dir in ((s0, -1), (s1, +1)):
            if end < _EPS or end > L - _EPS:
                continue
            touch = [q for q, _ in walls if q is not p and q[0] - _EPS <= end <= q[1] + _EPS
                     and min(q[3], t1) - max(q[2], t0) > -_EPS]          # 모서리로 맞닿아도 연결된 끝
            if touch:
                continue
            front = room_at(end + out_dir * 0.05, c)
            if front is None or front.finish.wall_t <= _EPS:
                continue
            ft = front.finish
            z_lo = front.ffl_rel
            z_hi = min(front.ceiling_rel if ft.ceiling else p[5], p[5])
            if z_hi - z_lo <= _EPS:
                continue
            sides = []                                    # 양쪽 실 (마감 없는 쪽은 None)
            for side in (-1, +1):
                rf = room_at(end - out_dir * (h + 0.05), c + side * (h + 0.05))   # 벽 끝은 실 경계(중심선 끝) + 반두께
                sides.append((side, rf if rf is not None and rf.finish.wall_t > _EPS else None))
            # 걸레받이는 앞·양쪽 실에 모두 있을 때만 (아니면 끝막음은 바닥 마감면부터 패널)
            sk = ft.has_skirt and all(rf is None or rf.finish.has_skirt for _, rf in sides)
            for skirt in ((False, True) if sk else (False,)):
                w0 = ft.skirt_pass() if skirt else ft.panel_pass()
                f = w0.pface - w0.pgap
                cz = (z_lo, min(z_lo + ft.skirt_h, z_hi)) if skirt else (z_lo + (ft.skirt_h if sk else 0.0), z_hi)
                if cz[1] - cz[0] <= _EPS:
                    continue
                cap_s = sorted((end, end + out_dir * f))
                backs = []
                for side, rf in sides:                    # 양쪽: 그 쪽 실 마감을 벽 끝 + f 까지 늘림
                    if rf is None:
                        backs.append(c + side * h)
                        continue
                    w = rf.finish.skirt_pass() if skirt else rf.finish.panel_pass()
                    g, fs = w.pgap, w.pface
                    face_lo, face_hi = sorted((c + side * (h + g), c + side * (h + fs)))
                    ext = sorted((end + out_dir * f, end - out_dir * h))    # 기존 마감은 실 경계(벽 끝 − 반두께)에서 끝남
                    zs = max(z_lo, rf.ffl_rel)
                    zz = (zs, min(zs + rf.finish.skirt_h, z_hi)) if skirt else (zs + (rf.finish.skirt_h if sk else 0.0), z_hi)
                    if zz[1] - zz[0] > _EPS:
                        (rf.skirts if skirt else rf.walls).append((ext[0], ext[1], face_lo, face_hi, *zz))
                    backs.append(c + side * (h + g))
                lo, hi = sorted(backs)
                (front.skirts if skirt else front.walls).append((cap_s[0], cap_s[1], lo, hi, *cz))


SIDE_TOL = 0.15                  # 계단·ESC 옆면에서 이 거리 안의 벽 마감을 그 옆 벽으로 봄


def stair_band(cfg, lay, h: float) -> list:
    """계단 옆 걸레받이 띠: 디딤판 코를 잇는 피치선(첫 코 한 단 앞 바닥 ~ 도착 디딤판 끝, 계단참·도착부는 수평) 아래 한 단 ~ 위 h.
    (s, FL 기준 높이) 평면의 사다리꼴 조각 (trap_region 형식). 아래 변은 디딤판 안쪽 모서리 선이라 계단 옆에 가려짐"""
    from entrances.entrance_layout import pitch_points
    off = cfg.station.offset
    surfaces = sorted(x for p in lay.parts for x in p.surfaces)
    if not surfaces:
        return []
    pts = pitch_points(surfaces, lay.spec.tread, lay.riser)
    ub, z_last = surfaces[-1][1], surfaces[-1][2]
    if ub <= lay.run + _EPS:                             # 도착 디딤판(위층 바닥 높이)이 걷는 면 목록에 없음 → 도착 코 ~ 끝
        pts += [(ub, z_last + lay.riser), (lay.length, z_last + lay.riser)]
    elif ub > pts[-1][0] + _EPS:
        pts.append((ub, z_last))
    out = []
    for (u0, z0), (u1, z1) in zip(pts, pts[1:]):
        (sa, za), (sb, zb) = sorted(((lay.s_at(u0), z0), (lay.s_at(u1), z1)))
        za, zb = za - (cfg.lv(sa) - off), zb - (cfg.lv(sb) - off)
        out.append((sa, sb, za - lay.riser, za + h, zb - lay.riser, zb + h))
    return out


def _side_hits(fl, edge, sgn, q) -> bool:
    """s 방향 벽 마감 조각 q 가 옆면 t = edge 의 sgn 쪽(바깥) SIDE_TOL 안을 향해 붙은 벽인가 (사이에 칸막이벽이 없을 것)"""
    if q[1] - q[0] <= q[3] - q[2] or len(q) > 6:
        return False
    d = (q[2] - edge) if sgn > 0 else (edge - q[3])
    if not -0.02 < d < SIDE_TOL:
        return False
    lo, hi = sorted((edge, q[2] if sgn > 0 else q[3]))
    return not any(min(r[1], q[1]) - max(r[0], q[0]) > _EPS and min(r[3], hi) - max(r[2], lo) > 1e-4
                   for pw in fl.partitions for r in pw.pieces)


def _stair_skirts(cfg, fl, rfs, stairs, escalators):
    """계단 옆 걸레받이 (사용자 지정: 경사 띠, 에스컬레이터 옆은 없음) + 위층 오프닝 옆 벽의 평 걸레받이 빼기.
    1) 이 층 바닥(아래 슬래브)의 계단·ESC 오프닝 옆 벽: 바닥이 없으므로 걸레받이를 빼고 그 자리를 벽 마감으로 채움
    2) 계단 옆면에 붙은 벽 마감(이 층에서 오르는 계단, 이 층에 도착하는 계단)을 경사 띠 자리에서 걸레받이로 바꿈 — 띠는 벽 마감재와
       같은 자리(같은 면·두께): 계단 구간 패널 뒤는 슬래브 단면이라 들어갈 자리가 없음"""
    from helper import trap_region as T
    if not any(rf.finish.has_skirt for rf in rfs):
        return
    n = fl.floor
    for lay in list(stairs) + list(escalators):
        if lay.lower_floor != n - 1:
            continue
        o = lay.opening
        for edge, sgn in ((lay.t_range[0], -1), (lay.t_range[1], 1)):
            for rf in rfs:
                keep = []
                for q in rf.skirts:
                    a, b = max(q[0], o.s_start), min(q[1], o.s_end)
                    if b - a <= _EPS or not _side_hits(fl, edge, sgn, q):
                        keep.append(q)
                        continue
                    keep += [(x, y, *q[2:]) for x, y in ((q[0], a), (b, q[1])) if y - x > _EPS]
                    for p in list(rf.walls):                 # 그 위 벽 마감을 바닥 마감면까지 내림
                        x, y = max(a, p[0]), min(b, p[1])
                        near = min(abs(p[2] - q[2]), abs(p[3] - q[3]), abs(p[2] - q[3]), abs(p[3] - q[2])) < 0.06
                        if len(p) == 6 and y - x > _EPS and near and p[1] - p[0] > p[3] - p[2] and abs(p[4] - q[5]) < _EPS:
                            rf.walls.append((x, y, p[2], p[3], q[4], p[4]))
                rf.skirts = keep
    for lay in stairs:
        if lay.lower_floor not in (n, n - 1):
            continue
        for edge, sgn in ((lay.t_range[0], -1), (lay.t_range[1], 1)):
            for rf in rfs:
                band = stair_band(cfg, lay, rf.finish.skirt_h) if rf.finish.has_skirt else []
                if not band:
                    continue
                s_lo, s_hi = min(x[0] for x in band), max(x[1] for x in band)
                walls = []
                for p in rf.walls:
                    cut = []
                    if p[0] < s_hi and p[1] > s_lo and _side_hits(fl, edge, sgn, p):
                        reg = [T.rect(p[0], p[1], p[4], p[5])]
                        cut = [x for x in T.intersect(reg, band) if T.area([x]) > 1e-7]
                    if not cut:
                        walls.append(p)
                        continue
                    rf.skirt_slopes += [(x[0], x[1], p[2], p[3], *x[2:]) for x in cut]
                    for x in T.subtract(reg, band):
                        if T.area([x]) <= 1e-7:
                            continue
                        if T.is_rect(x):
                            walls.append((x[0], x[1], p[2], p[3], x[2], x[3]))
                        else:
                            rf.wall_slopes.append((x[0], x[1], p[2], p[3], *x[2:]))
                rf.walls = walls


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
