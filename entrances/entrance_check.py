import math

from entrances.entrance_layout import layout_entrance
from entrances.entrance_spec import EntranceSpec, resolve_entrance_names

_EPS = 1e-6


def check_entrance_spec(spec, name: str):
    """입력 제원 자체의 검사 (형식·치수)"""
    if not isinstance(spec, EntranceSpec):
        raise ValueError(f"출입구 {name}: 제원 형식이 올바르지 않습니다 ({spec!r})")
    if not str(spec.passage).strip():
        raise ValueError(f"출입구 {name}: 이어 붙일 출구통로를 지정하세요")
    if spec.ground_el is not None and not math.isfinite(spec.ground_el):
        raise ValueError(f"출입구 {name}: 지표 EL 이 숫자가 아닙니다 ({spec.ground_el})")
    if spec.escalator_side not in (1, -1):
        raise ValueError(f"출입구 {name}: 에스컬레이터 쪽은 +1(왼쪽) 또는 -1(오른쪽) 이어야 합니다 ({spec.escalator_side!r})")
    positive = [("계단 폭", spec.stair_width), ("벽·슬래브 두께", spec.wall_t), ("단높이 상한", spec.riser_max),
                ("단너비", spec.tread), ("런 높이 상한", spec.flight_rise_max), ("계단참 길이", spec.landing_len),
                ("계단 슬래브 두께", spec.stair_slab_t), ("계단 머리 높이", spec.stair_headroom),
                ("에스컬레이터 경사각", spec.esc_angle_deg), ("에스컬레이터 트러스 높이", spec.esc_truss_depth),
                ("에스컬레이터 머리 높이", spec.esc_headroom)]
    if spec.escalator:
        positive += [("칸막이벽 두께", spec.partition_t), ("에스컬레이터 구역 폭", spec.escalator_zone)]
    for label, v in positive:
        if not v > 0:
            raise ValueError(f"출입구 {name}: {label}은(는) 0보다 커야 합니다 ({v})")
    for label, v in (("하부 여유", spec.lower_margin), ("상부 여유", spec.top_margin), ("파라펫 높이", spec.parapet),
                     ("헌치 폭", spec.haunch_w), ("헌치 높이", spec.haunch_h)):
        if not v >= 0:
            raise ValueError(f"출입구 {name}: {label}은(는) 0 이상이어야 합니다 ({v})")
    for label, v in (("흙 덮개", spec.roof_cover), ("버림 콘크리트 두께", spec.lean_t), ("버림 콘크리트 내민 폭", spec.lean_ext)):
        if not v >= 0:
            raise ValueError(f"출입구 {name}: {label}은(는) 0 이상이어야 합니다 ({v})")
    us = []
    for k, z in enumerate(spec.thickness_zones, start=1):
        try:
            u0, th = float(z[0]), float(z[1])
        except (TypeError, ValueError, IndexError):
            raise ValueError(f"출입구 {name}: 두께 구간 {k} 의 형식이 올바르지 않습니다 ({z!r})") from None
        if not (math.isfinite(u0) and u0 >= 0):
            raise ValueError(f"출입구 {name}: 두께 구간 {k} 의 시작 위치는 0 이상이어야 합니다 ({u0:g})")
        if not th > 0:
            raise ValueError(f"출입구 {name}: 두께 구간 {k} 의 두께는 0보다 커야 합니다 ({th:g})")
        us.append(u0)
    if len(set(round(u, 6) for u in us)) != len(us):
        raise ValueError(f"출입구 {name}: 두께 구간의 시작 위치가 겹칩니다")
    if (spec.haunch_w > 0) != (spec.haunch_h > 0):
        raise ValueError(f"출입구 {name}: 헌치는 폭과 높이를 모두 0 이거나 모두 0보다 크게 입력하세요")
    if not 0 < spec.esc_angle_deg < 60:
        raise ValueError(f"출입구 {name}: 에스컬레이터 경사각은 0 ~ 60° 사이여야 합니다 ({spec.esc_angle_deg})")
    if spec.landing_len < spec.tread - _EPS:
        raise ValueError(f"출입구 {name}: 계단참 길이({spec.landing_len:g}m)는 단너비({spec.tread:g}m) 이상이어야 합니다")
    if spec.flight_rise_max < 2 * spec.riser_max - _EPS:
        raise ValueError(f"출입구 {name}: 런 높이 상한은 단높이 상한의 2배 이상이어야 합니다")
    if spec.haunch_w >= spec.inner_width / 2.0 - _EPS:
        raise ValueError(f"출입구 {name}: 헌치 폭이 내공 폭의 절반 이상입니다")


def layout_entrances(cfg, passage_layouts: list) -> list:
    """출입구마다 EntranceLayout (이름 확정 + 입력 검사 + 배치 계산). 출구통로 하나에 출입구 하나"""
    names = resolve_entrance_names(cfg.entrances)
    used = {}
    out = []
    for name, spec in zip(names, cfg.entrances):
        check_entrance_spec(spec, name)
        if spec.passage in used:
            raise ValueError(f"출입구 {name}: 출구통로 {spec.passage} 에는 이미 출입구 {used[spec.passage]} 가 붙어 있습니다")
        used[spec.passage] = name
        out.append(layout_entrance(cfg, spec, name, passage_layouts))
    return out
