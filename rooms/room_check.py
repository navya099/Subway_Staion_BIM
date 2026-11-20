from config.widening import clear_contains_rect, has_pockets
from openings.decompose import overlap_area
from rooms.room_layout import layout_floor_rooms, resolve_room_names
from rooms.room_spec import BOUNDARIES, DOOR_KINDS, DOOR_SIDES, SEPARATION, DoorSpec, RoomSettings, RoomSpec

_EPS = 1e-6


def check_room_specs(cfg, specs: list, names: list):
    """입력 실 자체의 검사 (층·용도·범위·크기, 같은 층 실끼리 겹침)"""
    st = cfg.station
    rs = cfg.room_settings
    if not isinstance(rs, RoomSettings):
        raise ValueError(f"실 설정 형식이 올바르지 않습니다 ({rs!r})")
    if not rs.partition_t > 0:
        raise ValueError(f"칸막이벽 두께는 0보다 커야 합니다 ({rs.partition_t})")
    for n, use in rs.default_uses.items():
        if not isinstance(use, str) or not use.strip():
            raise ValueError(f"{n}층 기본 실 용도를 입력하세요")
    L, hw = st.length, st.width / 2.0
    for name, sp in zip(names, specs):
        if not isinstance(sp, RoomSpec):
            raise ValueError(f"실 {name}: 형식이 올바르지 않습니다 ({sp!r})")
        if not isinstance(sp.floor, int) or isinstance(sp.floor, bool) or not 1 <= sp.floor <= st.floors:
            raise ValueError(f"실 {name}: 층 번호 {sp.floor!r} 이(가) 범위(1 ~ {st.floors})를 벗어납니다")
        if not isinstance(sp.use, str) or not sp.use.strip():
            raise ValueError(f"실 {name}: 용도를 입력하세요")
        if sp.boundary not in BOUNDARIES:
            raise ValueError(f"실 {name}: 경계 종류는 {' / '.join(BOUNDARIES)} 중 하나여야 합니다 ({sp.boundary!r})")
        if sp.boundary == SEPARATION and not sp.sep_t >= 0:
            raise ValueError(f"실 {name}: 구획분리 두께는 0 이상이어야 합니다 ({sp.sep_t}, 0 = 가상 경계선)")
        for k, d in enumerate(sp.doors, start=1):
            w = f"실 {name} 문 {k}"
            if not isinstance(d, DoorSpec):
                raise ValueError(f"{w}: 형식이 올바르지 않습니다 ({d!r})")
            if d.side not in DOOR_SIDES:
                raise ValueError(f"{w}: 변은 {', '.join(DOOR_SIDES)} 중 하나여야 합니다 ({d.side!r})")
            if d.kind not in DOOR_KINDS:
                raise ValueError(f"{w}: 문 종류는 {', '.join(DOOR_KINDS)} 중 하나여야 합니다 ({d.kind!r})")
            if not (d.width > 0 and d.height > 0):
                raise ValueError(f"{w}: 문 폭·높이는 0보다 커야 합니다 ({d.width}, {d.height})")
        if not (sp.s1 - sp.s0 > rs.partition_t + _EPS and sp.t1 - sp.t0 > rs.partition_t + _EPS):
            raise ValueError(f"실 {name}: 크기({sp.s1 - sp.s0:g} x {sp.t1 - sp.t0:g}m)가 칸막이벽 두께보다 커야 합니다 "
                             "(시작 < 끝 인지 확인)")
        if has_pockets(cfg, sp.floor):                       # 구조물 내공 확폭: 넓어진 내공 안이면 됨
            if not clear_contains_rect(cfg, sp.floor, sp.rect, _EPS):
                raise ValueError(f"실 {name}: 범위 s {sp.s0:g} ~ {sp.s1:g}, t {sp.t0:g} ~ {sp.t1:g} 이(가) "
                                 f"{st.level_name(sp.floor)} 내공(확폭 포함)을 벗어납니다")
        elif sp.s0 < -_EPS or sp.s1 > L + _EPS or sp.t0 < -hw - _EPS or sp.t1 > hw + _EPS:
            raise ValueError(f"실 {name}: 범위 s {sp.s0:g} ~ {sp.s1:g}, t {sp.t0:g} ~ {sp.t1:g} 이(가) "
                             f"{st.level_name(sp.floor)} 내공(s 0 ~ {L:g}, t ±{hw:g})을 벗어납니다")
    for i, a in enumerate(specs):
        for j in range(i + 1, len(specs)):
            b = specs[j]
            if a.floor == b.floor and overlap_area(a.rect, b.rect) > 1e-9:
                raise ValueError(f"실 {names[i]} 와 {names[j]} 이(가) {st.level_name(a.floor)} 에서 서로 겹칩니다")


def layout_rooms(cfg) -> list:
    """층마다 FloorRoomsLayout (입력 실 검사 + 기본 실 + 칸막이벽). 모든 층을 돌려줌 (입력 실이 없으면 기본 실 하나)"""
    specs = list(cfg.rooms)
    names = resolve_room_names(cfg, specs)
    check_room_specs(cfg, specs, names)
    out = []
    for n in range(1, cfg.station.floors + 1):
        idx = [i for i, sp in enumerate(specs) if sp.floor == n]
        out.append(layout_floor_rooms(cfg, n, [specs[i] for i in idx], [names[i] for i in idx]))
    return out


def check_room_layouts(cfg, floors: list, openings: list, stairs: list, escalators: list, elevators: list):
    """칸막이벽·구획분리 벽(두께 > 0)이 서 있는 슬래브의 오프닝 위에 놓이지 않고, 계단·에스컬레이터·엘리베이터와 평면이
    겹치지 않을 것 (두께 없는 가상 경계선은 검사하지 않음)"""
    st = cfg.station
    for fl in floors:
        for pw in fl.partitions:
            for s0, s1, t0, t1, *_ in pw.pieces:
                r = (s0, s1, t0, t1)
                for op in openings:
                    if fl.floor - 1 in op.slabs and overlap_area(r, (op.s_start, op.s_end, op.t_lo, op.t_hi)) > 1e-9:
                        raise ValueError(f"칸막이벽 {pw.name}: {st.level_name(fl.floor)} 바닥 슬래브의 오프닝 {op.name or op.kind.label} "
                                         "위에 놓입니다 (실 경계를 옮기세요)")
                for kind, items in (("계단", stairs), ("에스컬레이터", escalators)):
                    for it in items:
                        if it.lower_floor == fl.floor and overlap_area(r, (*it.s_range, *it.t_range)) > 1e-9:
                            raise ValueError(f"칸막이벽 {pw.name}: {kind} {it.name} 과(와) 겹칩니다 (실 경계를 옮기세요)")
                for ev in elevators:
                    if ev.lower_floor <= fl.floor <= ev.upper_floor and overlap_area(r, ev.outer_rect()) > 1e-9:
                        raise ValueError(f"칸막이벽 {pw.name}: 엘리베이터 {ev.name} 승강로와 겹칩니다 (실 경계를 옮기세요)")
