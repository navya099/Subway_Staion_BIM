"""계단·에스컬레이터 옆 벽체 + 하부 창고 (실무 도면: 계단·ESC 의 승강장 쪽 긴 옆면을 칸막이벽으로 막고, 높은 쪽 아래는 창고·기계실).

기존 실(구획) 기능을 그대로 쓴다 — 계단·ESC 묶음마다 자동 실(RoomSpec.auto)을 만들어 cfg.rooms 에 넣으면 칸막이벽·문·마감·IFC
(IfcSpace·IfcWall·IfcDoor)가 따라 나온다. StationProjectConfig.validate 가 계단·ESC 배치 직후 자동 실을 다시 만든다.

- 묶음: 같은 층·같은 오르는 방향, s 구간이 겹치고 t 간격이 group_gap 이하인 계단·ESC (사이는 막지 않음)
- 계단실(그 층 기본 실 용도 — 마감·디딤판 기준 높이가 그대로): 앞(낮은 쪽, 첫 챌판)은 열린 변(open_sides), 노출된 긴 옆면은
  칸막이벽 (중심선 = 묶음 t 끝 − 그 실 벽 마감 표면 거리 − 반두께 → 벽 마감 표면이 계단 옆면에 닿음), 내공면에 가까우면 본체 벽에 붙임
- 창고: 계단·ESC 하면이 그 자리 바닥 마감면 + storage_h 이상이 되는 곳부터 높은 쪽 끝까지. 경계 끝 벽은 계단 아래를 가로지르므로
  윗면 = 그 벽 위 계단·ESC 하면 (RoomSpec.wall_tops), 문 = 뒷 벽(높은 쪽 끝) 가운데(door_at 'back', 기본) 또는 노출된 옆 벽 가운데
  ('side') — 뒷 벽이 본체 단부 벽이거나 폭이 모자라면 옆 벽
- 입력 실·엘리베이터 승강로와 겹치는 묶음, 구조물 내공 확폭 층은 만들지 않음
"""
import dataclasses

from rooms.room_spec import DoorSpec, RoomSpec

_EPS = 1e-6


@dataclasses.dataclass
class EnclosureSettings:
    """계단·ESC 옆 벽체 + 하부 창고. enabled: 생성 여부 (모델 기본 끔, GUI 켬). 벽 두께·재질 = 실 칸막이벽 설정"""
    enabled: bool = False
    escalators: bool = True
    storage: bool = True
    storage_use: str = "창고"
    storage_h: float = 2.1
    door_w: float = 0.9
    door_h: float = 2.1
    group_gap: float = 1.0
    min_storage: float = 1.0
    door_at: str = "back"            # 창고 문: 'back' 뒷 벽(높은 쪽 끝) | 'side' 노출된 옆 벽

    def check(self):
        for nm, v in (("창고 높이 기준", self.storage_h), ("창고 문 폭", self.door_w), ("창고 문 높이", self.door_h),
                      ("최소 창고 길이", self.min_storage)):
            if v <= 0:
                raise ValueError(f"계단 옆 벽체: {nm}({v:g})는 0 보다 커야 합니다")
        if self.group_gap < 0:
            raise ValueError("계단 옆 벽체: 묶음 간격은 0 이상이어야 합니다")
        if self.door_at not in ("back", "side"):
            raise ValueError(f"계단 옆 벽체: 창고 문 위치는 back / side 중 하나여야 합니다 ({self.door_at!r})")
        if not str(self.storage_use).strip():
            raise ValueError("계단 옆 벽체: 창고 용도를 입력하세요")


@dataclasses.dataclass
class _Member:
    name: str
    floor: int
    direction: int
    s_range: tuple
    t_range: tuple
    strips: list
    base: float


def _members(cfg, stairs, escs, es) -> list:
    out = []
    for lay in stairs:
        strips = [st for p in lay.parts for st in p.strips] + [st for f in lay.finish for st in f.strips]
        out.append(_Member(lay.name, lay.lower_floor, lay.spec.direction, lay.s_range, lay.t_range, strips, lay.base_level))
    if es.escalators:
        for lay in escs:
            strips = [st for p in lay.parts for st in p.strips]
            out.append(_Member(lay.name, lay.lower_floor, lay.spec.direction, lay.s_range, lay.t_range, strips, lay.base_level))
    return out


def _groups(members, gap) -> list:
    groups = []
    for m in sorted(members, key=lambda m: (m.floor, m.direction, m.t_range[0])):
        for g in groups:
            if g[0].floor != m.floor or g[0].direction != m.direction:
                continue
            s0, s1 = min(x.s_range[0] for x in g), max(x.s_range[1] for x in g)
            t0, t1 = min(x.t_range[0] for x in g), max(x.t_range[1] for x in g)
            if min(s1, m.s_range[1]) - max(s0, m.s_range[0]) > _EPS and \
                    max(m.t_range[0] - t1, t0 - m.t_range[1]) <= gap + _EPS:
                g.append(m)
                break
        else:
            groups.append([m])
    return groups


def _underside(cfg, group, s) -> float:
    """s 에서 묶음 부재 하면의 가장 낮은 높이 (본체 FL 기준, 부재가 없으면 None)"""
    vals = [st.zb_at(s) for m in group for st in m.strips if st.s0 - 1e-9 <= s <= st.s1 + 1e-9]
    return (min(vals) - (cfg.lv(s) - cfg.station.offset)) if vals else None


def enclosure_rooms(cfg, stairs, escs, evs) -> list:
    es = getattr(cfg, "enclosure_settings", None)
    if es is None or not es.enabled:
        return []
    es.check()
    from config.widening import has_pockets, inner_min
    st, rs = cfg.station, cfg.room_settings
    L = st.length
    tw = rs.partition_t
    h = tw / 2.0
    fs = cfg.finish_settings

    def face_of(use):
        if not fs.enabled:
            return 0.0
        ft = fs.for_room(use)
        return ft.pface if ft.wall_t > _EPS else 0.0

    users = [r for r in cfg.rooms if not getattr(r, "auto", "")]
    out = []
    for g in _groups(_members(cfg, stairs, escs, es), es.group_gap):
        n, d = g[0].floor, g[0].direction
        if has_pockets(cfg, n):
            continue
        S0, S1 = min(m.s_range[0] for m in g), max(m.s_range[1] for m in g)
        T0, T1 = min(m.t_range[0] for m in g), max(m.t_range[1] for m in g)
        use = rs.default_use(n)
        face = face_of(use)
        lo_face, hi_face = -inner_min(cfg, n, -1, S0, S1), inner_min(cfg, n, +1, S0, S1)
        from finishes.finish_clear import wall_surface
        lo_surf, hi_surf = -wall_surface(cfg, n, -1, S0, S1), wall_surface(cfg, n, +1, S0, S1)
        c0, c1 = T0 - face - h, T1 + face + h
        # 칸막이벽이 본체 벽 마감 표면 안쪽에 설 자리가 없으면 그 쪽은 본체 벽 (벽 마감 표면 기준 — 이슈 #32)
        wall_lo, wall_hi = c0 - h > lo_surf + _EPS, c1 + h < hi_surf - _EPS
        t0 = c0 if wall_lo else lo_face
        t1 = c1 if wall_hi else hi_face
        front, back = (S0, S1) if d > 0 else (S1, S0)
        store_face = face_of(es.storage_use)
        back_c = back + d * (h + store_face)
        back_c = min(max(back_c, 0.0), L)
        # 창고 끝 벽: 하면이 바닥 마감면 + storage_h 이상이 되는 첫 위치 (앞 → 뒤)
        ffl = g[0].base + (fs.for_room(use).ffl if fs.enabled else 0.0)
        s_w = top = None
        if es.storage:
            steps = max(2, int(abs(back - front) / 0.05))
            for k in range(steps + 1):
                s = front + (back - front) * k / steps
                u = _underside(cfg, g, s)
                if u is not None and u >= ffl + es.storage_h - 1e-9:
                    s_w = s + d * (h + face)                     # 계단실 쪽 벽 마감 표면이 이 위치
                    lo = s_w - d * (h + face)                     # 끝 벽 + 계단실 쪽 마감이 차지하는 s 구간의 가장 낮은 하면
                    span = [lo + d * (tw + face) * i / 10.0 for i in range(11)]
                    tops = [x for x in (_underside(cfg, g, x) for x in span) if x is not None]
                    top = min(tops) - 1e-6 if tops else None
                    break
            if s_w is None or top is None or abs(back_c - s_w) < es.min_storage + tw:
                s_w = None
        names = "_".join(m.name for m in sorted(g, key=lambda m: m.t_range[0]))
        open_front = "-s" if d > 0 else "+s"
        to_store = "+s" if d > 0 else "-s"
        mid = s_w if s_w is not None else back_c
        a, b = sorted((front, mid))
        rooms = [RoomSpec(floor=n, use=use, s0=a, s1=b, t0=t0, t1=t1, name=f"ENC_{names}", open_sides=(open_front,),
                          wall_tops={to_store: top} if s_w is not None else {}, auto=f"ENC:{names}")]
        if s_w is not None:
            a, b = sorted((s_w, back_c))
            doors = []
            back_wall = "+s" if d > 0 else "-s"                     # 창고의 뒷 벽 (높은 쪽 끝)
            if es.door_at == "back" and _EPS < back_c < L - _EPS and t1 - t0 >= es.door_w + 2 * tw:
                doors.append(DoorSpec(side=back_wall, center=(t0 + t1) / 2.0, width=es.door_w, height=es.door_h,
                                      name=f"{names}_창고_D1"))
            side = "-t" if wall_lo else ("+t" if wall_hi else None)
            if not doors and side is not None and b - a >= es.door_w + 2 * tw:
                doors.append(DoorSpec(side=side, center=(a + b) / 2.0, width=es.door_w, height=es.door_h,
                                      name=f"{names}_창고_D1"))
            back_side = "-s" if d > 0 else "+s"
            rooms.append(RoomSpec(floor=n, use=str(es.storage_use).strip(), s0=a, s1=b, t0=t0, t1=t1, name=f"{names}_창고",
                                  doors=doors, wall_tops={back_side: top}, auto=f"ENC:{names}"))
        # 입력 실(벽 두께만큼 띄운 범위 — 벽끼리 부딪힘 포함)·승강로와 겹치면 이 묶음은 만들지 않음
        def hits(r):
            return any(u.floor == n and min(u.s1, r.s1) - max(u.s0, r.s0) > -tw + _EPS
                       and min(u.t1, r.t1) - max(u.t0, r.t0) > -tw + _EPS for u in users) or any(
                ev.lower_floor <= n <= ev.upper_floor and min(ev.outer_rect()[1], r.s1) - max(ev.outer_rect()[0], r.s0) > _EPS
                and min(ev.outer_rect()[3], r.t1) - max(ev.outer_rect()[2], r.t0) > _EPS for ev in evs)
        if any(hits(r) for r in rooms):
            continue
        out += rooms
    return out
