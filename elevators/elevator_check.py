from elevators.elevator_layout import layout_elevator
from elevators.elevator_spec import DOOR_SIDES, ElevatorSpec, resolve_elevator_names
from openings.decompose import overlap_area

_EPS = 1e-6


def check_elevator_spec(station, spec, name: str):
    """입력 제원 자체의 검사 (층·치수·문·카 크기)"""
    if not isinstance(spec, ElevatorSpec):
        raise ValueError(f"엘리베이터 {name}: 제원 형식이 올바르지 않습니다 ({spec!r})")
    floors = station.floors
    k0, k1 = spec.lower_floor, spec.upper_floor
    for label, k in (("최하 정지층", k0), ("최상 정지층", k1)):
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= floors:
            raise ValueError(f"엘리베이터 {name}: {label} {k!r} 이(가) 범위(1 ~ {floors})를 벗어납니다")
    if k1 <= k0:
        raise ValueError(f"엘리베이터 {name}: 최상 정지층({station.level_name(k1)})이 최하 정지층({station.level_name(k0)})보다 "
                         "위여야 합니다")
    c = spec.stop_car
    if not isinstance(c, int) or isinstance(c, bool) or not k0 <= c <= k1:
        raise ValueError(f"엘리베이터 {name}: 카 정지층 {c!r} 이(가) 정지층 범위({station.level_name(k0)} ~ "
                         f"{station.level_name(k1)})를 벗어납니다")
    if spec.door_side not in DOOR_SIDES:
        raise ValueError(f"엘리베이터 {name}: 문 방향은 {', '.join(DOOR_SIDES)} 중 하나여야 합니다 ({spec.door_side!r})")
    for label, val in (("승강로 내공(s)", spec.inner_s), ("승강로 내공(t)", spec.inner_t), ("승강로 벽 두께", spec.wall_t),
                       ("문 폭", spec.door_w), ("문 높이", spec.door_h), ("피트 깊이", spec.pit_depth),
                       ("피트 슬래브 두께", spec.pit_slab_t), ("오버헤드", spec.overhead), ("천장 슬래브 두께", spec.top_slab_t),
                       ("카 폭", spec.car_width), ("카 깊이", spec.car_depth), ("카 높이", spec.car_height),
                       ("카 바닥 두께", spec.car_floor_t), ("카 벽 두께", spec.car_wall_t), ("카 천장 두께", spec.car_roof_t)):
        if not val > 0:
            raise ValueError(f"엘리베이터 {name}: {label}은(는) 0보다 커야 합니다 ({val})")
    along, across = (spec.inner_t, spec.inner_s) if spec.door_axis == "s" else (spec.inner_s, spec.inner_t)
    if spec.car_width + 2 * spec.car_wall_t > along + _EPS or spec.car_depth + 2 * spec.car_wall_t > across + _EPS:
        raise ValueError(f"엘리베이터 {name}: 카 외곽({spec.car_width + 2 * spec.car_wall_t:g} x "
                         f"{spec.car_depth + 2 * spec.car_wall_t:g})이 승강로 내공({along:g} x {across:g}, 문 면 기준)보다 큽니다")
    if spec.door_w > spec.car_width - _EPS:
        raise ValueError(f"엘리베이터 {name}: 문 폭({spec.door_w:g}m)이 카 폭({spec.car_width:g}m) 이상입니다")
    if spec.door_h > spec.car_height - _EPS:
        raise ValueError(f"엘리베이터 {name}: 문 높이({spec.door_h:g}m)가 카 높이({spec.car_height:g}m) 이상입니다")
    if spec.pit_depth < spec.car_floor_t - _EPS:
        raise ValueError(f"엘리베이터 {name}: 피트 깊이({spec.pit_depth:g}m)가 카 바닥 두께보다 작습니다")
    if spec.overhead < spec.car_height + spec.car_roof_t - _EPS:
        raise ValueError(f"엘리베이터 {name}: 오버헤드({spec.overhead:g}m)가 카 높이 + 카 천장({spec.car_height + spec.car_roof_t:g}m)"
                         "보다 작습니다")


def layout_elevators(cfg) -> list:
    """엘리베이터마다 ElevatorLayout (이름 확정 + 입력 검사 + 배치 계산)"""
    names = resolve_elevator_names(cfg.elevators)
    out = []
    for name, spec in zip(names, cfg.elevators):
        check_elevator_spec(cfg.station, spec, name)
        out.append(layout_elevator(cfg, spec, name))
    return out


def _floors(lay) -> set:
    return set(range(lay.lower_floor, lay.upper_floor + 1))


def check_elevator_layouts(cfg, elevators: list, stairs: list, escalators: list):
    """엘리베이터끼리, 계단·에스컬레이터와 평면이 겹치지 않을 것 (같은 층을 지날 때). 슬래브 오프닝·기둥 관통은
    자동 오프닝(cfg.all_openings) 검사가 맡는다"""
    for i, a in enumerate(elevators):
        ra = a.outer_rect()
        for b in elevators[i + 1:]:
            if _floors(a) & _floors(b) and overlap_area(ra, b.outer_rect()) > 1e-9:
                raise ValueError(f"엘리베이터 {a.name} 와 {b.name} 이(가) 서로 겹칩니다")
        for kind, items in (("계단", stairs), ("에스컬레이터", escalators)):
            for b in items:
                used = {b.lower_floor, b.lower_floor + 1}
                if used & _floors(a) and overlap_area(ra, (*b.s_range, *b.t_range)) > 1e-9:
                    raise ValueError(f"엘리베이터 {a.name} 와 {kind} {b.name} 이(가) 평면에서 겹칩니다")
