from openings.decompose import overlap_area
from openings.opening_check import slab_label
from openings.opening_spec import resolve_names
from stairs.stair_layout import layout_stair
from stairs.stair_spec import StairSpec, resolve_stair_names

_EPS = 1e-6


def check_stair_spec(station, spec, name: str):
    """입력 제원 자체의 검사 (층 번호, 방향, 치수, 직교방향 범위)"""
    if not isinstance(spec, StairSpec):
        raise ValueError(f"계단 {name}: 제원 형식이 올바르지 않습니다 ({spec!r})")
    floors = station.floors
    if floors < 2:
        raise ValueError(f"계단 {name}: 계단은 층수가 2 이상일 때만 둘 수 있습니다")
    k = spec.lower_floor
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= floors - 1:
        raise ValueError(f"계단 {name}: 시작 층 번호 {k!r} 이(가) 범위(1 ~ {floors - 1})를 벗어납니다")
    if spec.direction not in (1, -1):
        raise ValueError(f"계단 {name}: 오르는 방향은 +1 (종점 방향) 또는 -1 (시점 방향) 이어야 합니다 ({spec.direction!r})")
    for label, v in (("폭", spec.width), ("단높이 상한", spec.riser_max), ("단너비", spec.tread),
                     ("런 높이 상한", spec.flight_rise_max), ("계단참 길이", spec.landing_len),
                     ("계단 슬래브 두께", spec.waist_t), ("머리 높이", spec.headroom)):
        if not v > 0:
            raise ValueError(f"계단 {name}: {label}은(는) 0보다 커야 합니다 ({v})")
    if spec.flight_rise_max < 2 * spec.riser_max - _EPS:
        raise ValueError(f"계단 {name}: 런 높이 상한({spec.flight_rise_max:g}m)은 단높이 상한의 2배"
                         f"({2 * spec.riser_max:g}m) 이상이어야 합니다")
    hw = station.width / 2.0
    if spec.t_lo < -hw - _EPS or spec.t_hi > hw + _EPS:
        raise ValueError(f"계단 {name}: t 범위 {spec.t_lo:.3f} ~ {spec.t_hi:.3f} 이(가) 내공 폭(±{hw:g}m)을 벗어납니다")
    if not -_EPS <= spec.s_start <= station.length + _EPS:
        raise ValueError(f"계단 {name}: 시작 위치 s={spec.s_start:.3f} 이(가) 내공 길이(0 ~ {station.length:g}m)를 벗어납니다")


def layout_stairs(cfg) -> list:
    """계단마다 StairLayout (이름 확정 + 입력 검사 + 배치 계산). 정거장 내공 길이를 벗어나면 오류"""
    st = cfg.station
    names = resolve_stair_names(cfg.stairs)
    out = []
    for name, spec in zip(names, cfg.stairs):
        check_stair_spec(st, spec, name)
        lay = layout_stair(cfg, spec, name)
        s0, s1 = lay.s_range
        if s0 < -_EPS or s1 > st.length + _EPS:
            raise ValueError(f"계단 {name}: 계단 범위 s {s0:.3f} ~ {s1:.3f} (길이 {lay.run:.2f}m) 이(가) "
                             f"내공 길이(0 ~ {st.length:g}m)를 벗어납니다. 시작 위치나 오르는 방향을 확인하세요")
        out.append(lay)
    return out


def _rect(lay):
    return (*lay.s_range, *lay.t_range)


def check_stair_layouts(cfg, layouts: list):
    """계단끼리, 계단과 수동 오프닝 사이의 간섭 검사
    - 같은 층에서 시작하는 계단끼리 평면이 겹치지 않을 것
    - 계단이 서 있는 슬래브(번호 = 시작 층 − 1)에 뚫린 오프닝 위에 놓이지 않을 것 (승강장 위 계단은 제외)"""
    for i, a in enumerate(layouts):
        for b in layouts[i + 1:]:
            if a.lower_floor == b.lower_floor and overlap_area(_rect(a), _rect(b)) > 1e-9:
                raise ValueError(f"계단 {a.name} 와 {b.name} 이(가) {cfg.station.level_name(a.lower_floor)} 에서 서로 겹칩니다")
    op_names = resolve_names(cfg.openings)
    for lay in layouts:
        if lay.on_platform:
            continue
        base_slab = lay.lower_floor - 1
        for n, sp in zip(op_names, cfg.openings):
            if base_slab in sp.slabs and overlap_area(_rect(lay), (sp.s_start, sp.s_end, sp.t_lo, sp.t_hi)) > 1e-9:
                raise ValueError(f"계단 {lay.name} 이(가) {slab_label(base_slab, cfg.station.floors)} 의 오프닝 {n} 위에 놓입니다")
