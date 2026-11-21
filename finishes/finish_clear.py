"""계단·에스컬레이터와 벽 마감 표면 (이슈 #32 근본 원인: 마감 간섭 검사 없음 + 중심 기준 입력).

- `wall_surface(cfg, floor, side, s0, s1)`: 본체 측벽 벽 마감 표면의 |t| = 내공면(s 구간에서 가장 안쪽, 구조물 확폭 포함)
  − 그 쪽 벽에 붙은 실의 벽 마감 표면 거리(FinishType.face, 마감을 끄거나 벽 마감이 없으면 0)
- `resolve_t_ref(cfg, spec, width)`: 계단·ESC t 기준점(중심 / 왼쪽·오른쪽 변 / 왼쪽·오른쪽 벽 마감면) → 중심 t
- `check_wall_clearance(cfg, what, name, floor, s_range, t_range)`: 평면이 벽 마감 표면 안쪽으로 들어가면 오류 (들어간 거리)
"""
_EPS = 1e-6

T_CENTER = "center"          # t = 중심
T_LEFT = "+t"                # t = 왼쪽(+t) 변, 폭은 −t 쪽으로
T_RIGHT = "-t"               # t = 오른쪽(−t) 변, 폭은 +t 쪽으로
T_WALL_LEFT = "wall+t"       # 왼쪽(+t) 벽 마감 표면에서 t(이격, ≥ 0) 만큼 안쪽에 왼쪽 변
T_WALL_RIGHT = "wall-t"      # 오른쪽(−t) 벽 마감 표면에서 t 만큼 안쪽에 오른쪽 변
T_REFS = (T_CENTER, T_LEFT, T_RIGHT, T_WALL_LEFT, T_WALL_RIGHT)
# 화면 라벨 → 기준점 (계단·ESC 탭 't 기준' 콤보)
T_REF_LABELS = {"중심": T_CENTER, "왼쪽 변(+t)": T_LEFT, "오른쪽 변(−t)": T_RIGHT,
                "왼쪽 벽 마감면": T_WALL_LEFT, "오른쪽 벽 마감면": T_WALL_RIGHT}


def room_finish_at(cfg, floor: int, s: float, t: float):
    """층 floor 의 점 (s, t) 가 든 실의 마감 종류 FinishType (마감을 끄거나 실을 못 찾으면 None)"""
    fs = getattr(cfg, "finish_settings", None)
    if fs is None or not fs.enabled:
        return None
    from rooms.room_check import layout_rooms
    from rooms.room_layout import resolve_room_names
    try:
        floors = layout_rooms(cfg)
        specs = dict(zip(resolve_room_names(cfg, cfg.rooms), cfg.rooms))
    except ValueError:
        return None
    if not 1 <= floor <= len(floors):
        return None
    for room in floors[floor - 1].rooms:
        if room.contains(s, t):
            sp = specs.get(room.name)
            try:
                return fs.for_room(room.use, getattr(sp, "finish", "") if sp else "")
            except ValueError:
                return None
    return None


def wall_surface(cfg, floor: int, side: int, s0: float, s1: float) -> float:
    """본체 측벽(side +1 = +t, −1 = −t) 벽 마감 표면의 |t| (s0 ~ s1 에서 가장 안쪽)"""
    from config.widening import inner_min
    L = cfg.station.length
    a, b = max(0.0, min(s0, s1)), min(L, max(s0, s1))
    inner = inner_min(cfg, floor, side, a, b)
    n = max(2, int((b - a) / 1.0) + 1)                   # 구간을 따라 여러 실이 벽에 붙을 수 있음 → 가장 두꺼운 벽 마감
    face = 0.0
    for k in range(n + 1):
        ft = room_finish_at(cfg, floor, a + (b - a) * k / n, side * (inner - 0.01))
        if ft is not None and ft.wall_t > _EPS:
            face = max(face, ft.face)
    return inner - face


def wall_panel(cfg, floor: int, side: int, s0: float, s1: float) -> tuple:
    """본체 측벽 (벽 마감 표면 |t|, 벽 마감재 두께) — 마감재는 표면에서 벽 쪽으로 [표면, 표면 + 두께]"""
    from config.widening import inner_min
    L = cfg.station.length
    a, b = max(0.0, min(s0, s1)), min(L, max(s0, s1))
    inner = inner_min(cfg, floor, side, a, b)
    n = max(2, int((b - a) / 1.0) + 1)
    face = thick = 0.0
    for k in range(n + 1):
        ft = room_finish_at(cfg, floor, a + (b - a) * k / n, side * (inner - 0.01))
        if ft is not None and ft.wall_t > _EPS and ft.face >= face:
            face, thick = ft.face, ft.wall_t
    return inner - face, thick


def shaft_opening_t(cfg, floor: int, s0: float, s1: float, t_lo: float, t_hi: float) -> tuple:
    """계단·ESC 자동 오프닝 t 범위: 벽 마감 표면에 붙은 쪽은 벽 마감재 두께만큼 벽 쪽으로 넓힘 → 아래층 벽 마감 패널이
    오프닝을 지나 위층 바닥까지 한 장으로 이어짐 (이슈 #32 계단 구간 벽 마감). (t_lo, t_hi, 넓힌 쪽 집합)"""
    sides = set()
    lo0, hi0 = t_lo, t_hi
    for side in (1, -1):
        surf, thick = wall_panel(cfg, floor, side, s0, s1)
        edge = hi0 if side > 0 else -lo0
        if not (thick > _EPS and edge >= surf - 1e-3):
            thick = _partition_panel(cfg, floor, s0, s1, lo0, hi0, side)     # 계단실 옆 칸막이벽 쪽
            if thick <= _EPS:
                continue
            surf = edge
        sides.add(side)
        if side > 0:
            t_hi = max(t_hi, surf + thick)
        else:
            t_lo = min(t_lo, -(surf + thick))
    return t_lo, t_hi, sides


def _partition_panel(cfg, floor: int, s0: float, s1: float, t_lo: float, t_hi: float, side: int) -> float:
    """계단 옆 벽체(stair_enclosure)가 그 쪽에 칸막이벽을 세우면 그 실의 벽 마감재 두께 (아니면 0).
    같은 층·s 구간이 겹치고 그 쪽 t 간격이 묶음 간격 이하인 다른 계단·ESC 가 있으면 묶음 사이라 벽 없음"""
    es = getattr(cfg, "enclosure_settings", None)
    fs = getattr(cfg, "finish_settings", None)
    if es is None or not es.enabled or fs is None or not fs.enabled:
        return 0.0
    from config.widening import has_pockets
    if has_pockets(cfg, floor):
        return 0.0
    members = [(sp, sp.width) for sp in cfg.stairs]
    if es.escalators:
        members += [(sp, sp.truss_width) for sp in cfg.escalators]
    for sp, w in members:
        if sp.lower_floor != floor:
            continue
        lo, hi = sp.t_center - w / 2.0, sp.t_center + w / 2.0
        if abs(lo - t_lo) < 1e-3 and abs(hi - t_hi) < 1e-3:
            continue                                         # 자기 자신 (옆 여유 없이)
        a, b = _s_span(sp)
        if min(b, max(s0, s1)) - max(a, min(s0, s1)) <= _EPS:
            continue
        gap = (lo - t_hi) if side > 0 else (t_lo - hi)
        if -_EPS <= gap <= es.group_gap + _EPS:
            return 0.0
    ft = fs.for_room(cfg.room_settings.default_use(floor))
    return ft.wall_t if ft.wall_t > _EPS else 0.0


def _s_span(spec) -> tuple:
    """t 기준점을 풀 때 쓰는 대략의 s 구간 (계단은 첫 챌판 ~ 진행방향 20m, ESC 는 하부 WP 앞뒤 20m)"""
    s = getattr(spec, "s_start", None)
    if s is None:
        s = spec.s_wp
        return s - 20.0, s + 20.0
    return tuple(sorted((s, s + spec.direction * 20.0)))


def resolve_t_ref(cfg, spec, width: float) -> float:
    """spec.t_ref 와 spec.t_center(기준점 값) → 실제 중심 t"""
    ref = getattr(spec, "t_ref", T_CENTER) or T_CENTER
    v = spec.t_center
    if ref == T_CENTER:
        return v
    if ref == T_LEFT:
        return v - width / 2.0
    if ref == T_RIGHT:
        return v + width / 2.0
    if ref in (T_WALL_LEFT, T_WALL_RIGHT):
        if v < -_EPS:
            raise ValueError(f"벽 마감면 기준 이격({v:g})은 0 이상이어야 합니다")
        side = 1 if ref == T_WALL_LEFT else -1
        surf = wall_surface(cfg, spec.lower_floor, side, *_s_span(spec))
        return side * (surf - v - width / 2.0)
    raise ValueError(f"t 기준 '{ref}' 은(는) {', '.join(T_REFS)} 중 하나여야 합니다")


def normalize_t_refs(cfg, specs: list, width_of) -> list:
    """기준점 입력을 중심 t 로 푼 사본 목록 (StationProjectConfig.validate 가 배치 전에)"""
    import dataclasses
    out = []
    for sp in specs:
        ref = getattr(sp, "t_ref", T_CENTER) or T_CENTER
        if ref == T_CENTER:
            out.append(sp)
            continue
        out.append(dataclasses.replace(sp, t_center=resolve_t_ref(cfg, sp, width_of(sp)), t_ref=T_CENTER))
    return out


def check_wall_clearance(cfg, what: str, name: str, floor: int, s_range: tuple, t_range: tuple) -> None:
    """평면(s_range × t_range)이 그 층 본체 측벽 벽 마감 표면 안쪽으로 들어가면 오류 (마감을 켰을 때만 의미)"""
    fs = getattr(cfg, "finish_settings", None)
    if fs is None or not fs.enabled:
        return
    s0, s1 = s_range
    for side in (1, -1):
        surf = wall_surface(cfg, floor, side, s0, s1)
        edge = t_range[1] if side > 0 else -t_range[0]
        if edge > surf + 1e-4:
            label = "왼쪽(+t)" if side > 0 else "오른쪽(−t)"
            raise ValueError(f"{what} {name}: {cfg.station.level_name(floor)} {label} 본체 벽 마감 표면(|t| = {surf:.3f})에서 "
                             f"{edge - surf:.2f}m 들어갑니다 — t 를 옮기거나 t 기준을 '벽 마감면'으로 바꾸세요")
