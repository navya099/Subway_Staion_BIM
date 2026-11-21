from config.layout_cache import cached_layout
from config.widening import clear_contains_rect, has_pockets
from escalators.escalator_layout import layout_escalator
from escalators.escalator_spec import STEP_PLATE_T, EscalatorSpec, resolve_escalator_names
from openings.decompose import overlap_area
from openings.opening_check import slab_label
from openings.opening_spec import resolve_names

_EPS = 1e-6


def check_escalator_spec(station, spec, name: str, widened: bool = False):
    """입력 제원 자체의 검사 (층 번호, 방향, 치수, 직교방향 범위)"""
    if not isinstance(spec, EscalatorSpec):
        raise ValueError(f"에스컬레이터 {name}: 제원 형식이 올바르지 않습니다 ({spec!r})")
    floors = station.floors
    if floors < 2:
        raise ValueError(f"에스컬레이터 {name}: 층수가 2 이상일 때만 둘 수 있습니다")
    k = spec.lower_floor
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= floors - 1:
        raise ValueError(f"에스컬레이터 {name}: 시작 층 번호 {k!r} 이(가) 범위(1 ~ {floors - 1})를 벗어납니다")
    if spec.direction not in (1, -1):
        raise ValueError(f"에스컬레이터 {name}: 오르는 방향은 +1 (종점 방향) 또는 -1 (시점 방향) 이어야 합니다 ({spec.direction!r})")
    if not 0 < spec.angle_deg < 60:
        raise ValueError(f"에스컬레이터 {name}: 경사각은 0 ~ 60° 사이여야 합니다 ({spec.angle_deg})")
    for label, v in (("스텝 폭", spec.step_width), ("트러스 외폭", spec.truss_width), ("트러스 높이", spec.truss_depth),
                     ("하부 연장", spec.lower_ext), ("상부 연장", spec.upper_ext), ("스텝 깊이", spec.step_depth),
                     ("핸드레일 높이", spec.handrail_height), ("머리 높이", spec.headroom)):
        if not v > 0:
            raise ValueError(f"에스컬레이터 {name}: {label}은(는) 0보다 커야 합니다 ({v})")
    if not spec.side_clear >= 0:
        raise ValueError(f"에스컬레이터 {name}: 오프닝 옆 여유는 0 이상이어야 합니다 ({spec.side_clear})")
    for label, v in (("하부 평탄 스텝 수", spec.lower_flat_steps), ("상부 평탄 스텝 수", spec.upper_flat_steps)):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ValueError(f"에스컬레이터 {name}: {label}은(는) 0 이상의 정수여야 합니다 ({v!r})")
    if spec.lower_flat_steps * spec.step_depth > spec.lower_ext + _EPS:
        raise ValueError(f"에스컬레이터 {name}: 하부 평탄 스텝({spec.lower_flat_steps}단 x {spec.step_depth:g}m)이 "
                         f"하부 연장({spec.lower_ext:g}m)보다 깁니다")
    if spec.upper_flat_steps * spec.step_depth > spec.upper_ext + _EPS:
        raise ValueError(f"에스컬레이터 {name}: 상부 평탄 스텝({spec.upper_flat_steps}단 x {spec.step_depth:g}m)이 "
                         f"상부 연장({spec.upper_ext:g}m)보다 깁니다")
    from escalators.escalator_spec import DECK_T, HANDRAIL_H, SKIRT_T
    if not spec.newel_ext >= 0:
        raise ValueError(f"에스컬레이터 {name}: 뉴얼 연장은 0 이상이어야 합니다 ({spec.newel_ext:g})")
    if spec.newel_radius <= HANDRAIL_H + 0.01 or spec.handrail_height - 2 * spec.newel_radius < 0.02:
        raise ValueError(f"에스컬레이터 {name}: 뉴얼 반경({spec.newel_radius:g})은 핸드레일 단면보다 크고, 반원 아래 끝이 "
                         "승강구 바닥보다 높아야 합니다 (핸드레일 높이 − 2 × 반경 ≥ 0.02)")
    if not (isinstance(spec.bollard_count, int) and 0 <= spec.bollard_count <= 10):
        raise ValueError(f"에스컬레이터 {name}: 볼라드 수는 0 ~ 10 의 정수여야 합니다 ({spec.bollard_count})")
    if spec.bollard_count:
        for nm, v in (("볼라드 지름", spec.bollard_d), ("볼라드 높이", spec.bollard_h)):
            if not v > 0:
                raise ValueError(f"에스컬레이터 {name}: {nm}({v:g})는 0 보다 커야 합니다")
        if not spec.bollard_dist >= spec.bollard_d / 2.0:
            raise ValueError(f"에스컬레이터 {name}: 볼라드 거리({spec.bollard_dist:g})는 볼라드 반지름 이상이어야 합니다")
        ts = spec.bollard_ts()
        gap = (ts[1] - ts[0]) if len(ts) > 1 else float("inf")
        if gap - spec.bollard_d < 0.05:
            raise ValueError(f"에스컬레이터 {name}: 볼라드 {spec.bollard_count}개가 핸드레일 사이에 너무 촘촘합니다 "
                             f"(간격 {gap:.3f}m, 지름 {spec.bollard_d:g}m — 수 또는 지름을 줄이세요)")
    for nm, v in (("스커트 높이", spec.skirt_height), ("데크 폭", spec.deck_width), ("유리 두께", spec.glass_t)):
        if not v > 0:
            raise ValueError(f"에스컬레이터 {name}: {nm}({v:g})는 0 보다 커야 합니다")
    if spec.deck_width <= SKIRT_T + 1e-6:
        raise ValueError(f"에스컬레이터 {name}: 데크 폭({spec.deck_width:g})이 스커트 두께보다 커야 합니다")
    g1 = spec.detail_t(1)["GLASS"][1] - spec.t_center
    if g1 > spec.truss_width / 2.0 - 0.01:
        raise ValueError(f"에스컬레이터 {name}: 트러스 외폭({spec.truss_width:g}m)이 스텝·스커트·데크·유리에 비해 좁습니다 "
                         f"(반폭 {g1 + 0.01:.3f}m 이상)")
    if spec.skirt_height + DECK_T > spec.handrail_height - HANDRAIL_H - 0.1:
        raise ValueError(f"에스컬레이터 {name}: 스커트 높이가 핸드레일 높이에 비해 큽니다 (유리가 남지 않음)")
    outer = max(abs(t - spec.t_center) for side in (1, -1) for t in (*spec.balustrade_t(side), *spec.handrail_t(side)))
    if outer > spec.truss_width / 2.0 + _EPS:
        raise ValueError(f"에스컬레이터 {name}: 트러스 외폭({spec.truss_width:g}m)이 스텝 폭과 난간·핸드레일"
                         f"({2 * outer:.3f}m)보다 좁습니다")
    if spec.truss_depth <= spec.riser + STEP_PLATE_T + _EPS:
        raise ValueError(f"에스컬레이터 {name}: 트러스 높이({spec.truss_depth:g}m)가 스텝 층"
                         f"({spec.riser + STEP_PLATE_T:.3f}m)보다 낮습니다")
    hw = station.width / 2.0
    if not widened and (spec.t_lo < -hw - _EPS or spec.t_hi > hw + _EPS):
        raise ValueError(f"에스컬레이터 {name}: 트러스 t 범위 {spec.t_lo:.3f} ~ {spec.t_hi:.3f} 이(가) 내공 폭(±{hw:g}m)을 벗어납니다")
    if not -_EPS <= spec.s_wp <= station.length + _EPS:
        raise ValueError(f"에스컬레이터 {name}: 하부 WP s={spec.s_wp:.3f} 이(가) 내공 길이(0 ~ {station.length:g}m)를 벗어납니다")


@cached_layout("escalators")
def layout_escalators(cfg) -> list:
    """에스컬레이터마다 EscalatorLayout (이름 확정 + 입력 검사 + 배치 계산). 트러스가 내공 길이를 벗어나면 오류"""
    st = cfg.station
    names = resolve_escalator_names(cfg.escalators)
    out = []
    for name, spec in zip(names, cfg.escalators):
        pocket = isinstance(spec.lower_floor, int) and 1 <= spec.lower_floor <= st.floors and has_pockets(cfg, spec.lower_floor)
        check_escalator_spec(st, spec, name, pocket)
        lay = layout_escalator(cfg, spec, name)
        s0, s1 = lay.s_range
        if s0 < -_EPS or s1 > st.length + _EPS:
            raise ValueError(f"에스컬레이터 {name}: 트러스 범위 s {s0:.3f} ~ {s1:.3f} 이(가) 내공 길이(0 ~ {st.length:g}m)를 "
                             "벗어납니다. 하부 WP 위치나 오르는 방향을 확인하세요")
        if pocket and not clear_contains_rect(cfg, spec.lower_floor, _rect(lay), _EPS):
            raise ValueError(f"에스컬레이터 {name}: 트러스 평면(s {s0:.3f} ~ {s1:.3f}, t {spec.t_lo:.3f} ~ {spec.t_hi:.3f}) 이(가) "
                             f"{st.level_name(spec.lower_floor)} 내공(구조물 확폭 포함)을 벗어납니다")
        check_bollards(cfg, name, lay)
        out.append(lay)
    return out


def check_bollards(cfg, name, lay):
    """승강구 앞 볼라드가 서는 층 내공(구조물 확폭 포함) 안인지 검사"""
    from config.widening import inner_min
    r, L = lay.spec.bollard_d / 2.0, cfg.station.length
    for b in lay.bollards:
        s, t = b.s, b.t
        if s - r < -_EPS or s + r > L + _EPS or t + r > inner_min(cfg, b.floor, 1, s - r, s + r) + _EPS or                 r - t > inner_min(cfg, b.floor, -1, s - r, s + r) + _EPS:
            where = "아래층" if b.end == "L" else "위층"
            raise ValueError(f"에스컬레이터 {name}: {where} 승강구 볼라드가 내공 밖입니다 (s {s:.3f}, t {t:.3f}) — "
                             "볼라드 거리를 줄이거나 볼라드 수를 0 으로 하세요")


def _rect(lay):
    return (*lay.s_range, *lay.t_range)


def check_escalator_layouts(cfg, esc_layouts: list, stair_layouts: list):
    """에스컬레이터끼리 / 계단과의 간섭, 다른 오프닝 위에 놓이는지 검사
    - 같은 층에서 시작하는 에스컬레이터·계단끼리 평면이 겹치지 않을 것
    - 에스컬레이터가 서 있는 슬래브(시작 층 − 1)에 뚫린 다른 오프닝(수동·계단) 위에 놓이지 않을 것
    - 계단이 서 있는 슬래브의 에스컬레이터 피트 오프닝 위에 놓이지 않을 것"""
    from finishes.finish_clear import check_wall_clearance
    for lay in esc_layouts:                               # 본체 측벽 벽 마감 표면 (이슈 #32)
        check_wall_clearance(cfg, "에스컬레이터", lay.name, lay.lower_floor, lay.s_range, lay.t_range)
    floors = cfg.station.floors
    level = cfg.station.level_name
    for i, a in enumerate(esc_layouts):
        for b in esc_layouts[i + 1:]:
            if a.lower_floor == b.lower_floor and overlap_area(_rect(a), _rect(b)) > 1e-9:
                raise ValueError(f"에스컬레이터 {a.name} 와 {b.name} 이(가) {level(a.lower_floor)} 에서 서로 겹칩니다")
        for s in stair_layouts:
            if a.lower_floor == s.lower_floor and overlap_area(_rect(a), (*s.s_range, *s.t_range)) > 1e-9:
                raise ValueError(f"에스컬레이터 {a.name} 와 계단 {s.name} 이(가) {level(a.lower_floor)} 에서 서로 겹칩니다")
    others = list(zip(resolve_names(cfg.openings), cfg.openings)) + [(s.opening.name, s.opening) for s in stair_layouts]
    for lay in esc_layouts:
        if lay.on_platform:
            continue
        base = lay.lower_floor - 1
        for n, sp in others:
            if base in sp.slabs and overlap_area(_rect(lay), (sp.s_start, sp.s_end, sp.t_lo, sp.t_hi)) > 1e-9:
                raise ValueError(f"에스컬레이터 {lay.name} 이(가) {slab_label(base, floors)} 의 오프닝 {n} 위에 놓입니다")
    for s in stair_layouts:
        if s.on_platform:
            continue
        base = s.lower_floor - 1
        for e in esc_layouts:
            pit = e.pit_opening
            if pit and base in pit.slabs and overlap_area((*s.s_range, *s.t_range), (pit.s_start, pit.s_end, pit.t_lo, pit.t_hi)) > 1e-9:
                raise ValueError(f"계단 {s.name} 이(가) 에스컬레이터 {e.name} 의 피트 오프닝 위에 놓입니다")
