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
    if not spec.stair and not spec.escalator:
        raise ValueError(f"출입구 {name}: 계단과 에스컬레이터 중 하나는 있어야 합니다")
    if spec.escalator and not (isinstance(spec.escalator_count, int) and not isinstance(spec.escalator_count, bool)
                               and 1 <= spec.escalator_count <= 6):
        raise ValueError(f"출입구 {name}: 에스컬레이터 대수는 1 ~ 6 의 정수여야 합니다 ({spec.escalator_count!r})")
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
    for label, v in (("상부 지표 위 높이", spec.top_rise), ("경사로 폭", spec.ramp_width), ("바깥 바닥 깊이", spec.out_base)):
        if not v >= 0:
            raise ValueError(f"출입구 {name}: {label}은(는) 0 이상이어야 합니다 ({v})")
    if spec.top_rise > 0:
        for label, v in (("경사로 기울기(1/n)", spec.ramp_ratio), ("바깥 계단 단높이 상한", spec.out_riser_max),
                         ("바깥 계단 단너비", spec.out_tread)):
            if not v > 0:
                raise ValueError(f"출입구 {name}: {label}은(는) 0보다 커야 합니다 ({v})")
        if spec.parapet < spec.top_rise - 1e-9:
            raise ValueError(f"출입구 {name}: 파라펫 높이({spec.parapet:g}m, 지표 위)가 상부 승강구 높이({spec.top_rise:g}m)보다 낮습니다")
        if spec.outdoor not in ("steps", "forecourt"):
            raise ValueError(f"출입구 {name}: 바깥 접근 형식이 올바르지 않습니다 ('{spec.outdoor}' — steps | forecourt)")
        if spec.outdoor == "forecourt":
            check_forecourt(spec, name)
        if spec.ramp_width > spec.inner_width + 1e-9:
            raise ValueError(f"출입구 {name}: 경사로 폭({spec.ramp_width:g}m)이 내공 폭({spec.inner_width:g}m)보다 넓습니다")
    check_landing(spec, name)
    check_canopy(spec, name)
    for label, v in (("개구부 내공 축소", spec.open_narrow), ("바깥면 전이 기울기", spec.taper_ratio)):
        if not v >= 0:
            raise ValueError(f"출입구 {name}: {label}은(는) 0 이상이어야 합니다 ({v})")
    if spec.open_wall_t is not None and not spec.open_wall_t > 0:
        raise ValueError(f"출입구 {name}: 개구부 벽 두께는 0보다 커야 합니다 ({spec.open_wall_t})")
    if spec.open_narrow > 0:
        a_o = spec.inner_width / 2.0 - spec.open_narrow
        zs = spec.zones()
        if "stair" in zs:
            s0, s1 = zs["stair"]
            if min(s1, a_o) - max(s0, -a_o) < 0.3:
                raise ValueError(f"출입구 {name}: 개구부 내공 축소({spec.open_narrow:g}m)로 계단 폭이 너무 좁아집니다")
        for k, (e0, e1) in enumerate(zs.get("escalators", []), start=1):
            if e0 < -a_o - 1e-9 or e1 > a_o + 1e-9:
                raise ValueError(f"출입구 {name}: 개구부 내공 축소({spec.open_narrow:g}m)가 에스컬레이터 {k} 트러스 옆 여유보다 큽니다 "
                                 "(ESC 구역 폭을 키우거나 축소를 줄이세요)")
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
    if spec.escalator:
        from escalators.escalator_check import check_escalator_shape
        check_escalator_shape(spec.escalator_spec(), f"{name} 에스컬레이터")
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


def check_forecourt(spec, name: str):
    """앞마당 접속 슬래브 치수·높이 검사 (포장 윗면이 끝단 보 바깥면에서 지표 ± 5cm 안이어야 함)"""
    for label, v in (("앞마당 길이", spec.fc_length), ("접속 슬래브 두께", spec.fc_slab_t), ("끝단 보 폭", spec.fc_beam_t)):
        if v <= 0:
            raise ValueError(f"출입구 {name}: {label}는 0 보다 커야 합니다 ({v:g})")
    for label, v in (("포장 두께", spec.fc_pave_t), ("앞마당 버림", spec.fc_lean_t), ("끝단 보 깊이", spec.fc_beam_h),
                     ("끝단 보 헌치 폭", spec.fc_haunch_w), ("끝단 보 헌치 높이", spec.fc_haunch_h), ("기초 버림 두께", spec.fc_foot_t)):
        if v < 0:
            raise ValueError(f"출입구 {name}: {label}는 0 이상이어야 합니다 ({v:g})")
    if spec.fc_foot_t > 0 and spec.fc_foot_w < spec.fc_beam_t - 1e-9:
        raise ValueError(f"출입구 {name}: 기초 버림 폭({spec.fc_foot_w:g}m)이 끝단 보 폭({spec.fc_beam_t:g}m)보다 좁습니다")
    if spec.fc_length < spec.fc_beam_t + spec.fc_haunch_w + 1e-6:
        raise ValueError(f"출입구 {name}: 앞마당 길이({spec.fc_length:g}m)가 끝단 보 + 헌치보다 짧습니다")
    flat = spec.fc_flat if spec.fc_flat is not None else max(0.0, spec.fc_length - spec.top_rise * spec.ramp_ratio)
    if flat < 0 or flat > spec.fc_length + 1e-9:
        raise ValueError(f"출입구 {name}: 앞마당 평탄 길이({flat:g}m)는 0 ~ 앞마당 길이({spec.fc_length:g}m) 여야 합니다")
    drop = (spec.fc_length - flat) / spec.ramp_ratio
    if spec.fc_beam_h <= drop + 1e-6:
        raise ValueError(f"출입구 {name}: 끝단 보 깊이({spec.fc_beam_h:g}m)가 앞마당 경사 낙차({drop:.3f}m)보다 커야 합니다 "
                         "(보 하면이 끝 슬래브 하면 아래)")
    end = spec.top_rise - drop                                              # 끝단 포장 윗면 − 지표
    if end < -1e-6:
        raise ValueError(f"출입구 {name}: 앞마당 끝 포장 윗면이 지표보다 {-end:.3f}m 낮습니다 (평탄 길이를 늘리거나 앞마당 길이를 줄이세요)")
    if end > 0.05 + 1e-9:
        need = spec.top_rise * spec.ramp_ratio + flat
        raise ValueError(f"출입구 {name}: 앞마당 끝 포장 윗면이 지표보다 {end:.3f}m 높습니다 (경사 1/{spec.ramp_ratio:g} 로 지표까지 "
                         f"앞마당 길이 {need:.3f}m 필요 — 평탄 길이를 줄이거나 앞마당 길이를 늘리세요)")


def check_landing(spec, name: str):
    """파라펫 두께·승강구 마감·승강구 슬래브 검사"""
    if spec.parapet_t is not None:
        if spec.parapet_t <= 0:
            raise ValueError(f"출입구 {name}: 파라펫 두께는 0 보다 커야 합니다 ({spec.parapet_t:g})")
        tw = spec.open_wall_t if spec.open_wall_t is not None else min(t for _, t in [(0.0, spec.wall_t)] + list(spec.thickness_zones))
        if spec.parapet_t > tw + 1e-9:
            raise ValueError(f"출입구 {name}: 파라펫 두께({spec.parapet_t:g}m)가 개구부 벽 두께({tw:g}m)보다 큽니다")
    if spec.top_ffl < 0:
        raise ValueError(f"출입구 {name}: 승강구 마감 두께는 0 이상이어야 합니다 ({spec.top_ffl:g})")
    if spec.escalator:
        if spec.landing_t <= 0:
            raise ValueError(f"출입구 {name}: 승강구 슬래브 두께는 0 보다 커야 합니다 ({spec.landing_t:g})")
        if spec.top_ffl + spec.landing_t >= spec.esc_truss_depth - 1e-6:
            raise ValueError(f"출입구 {name}: 승강구 마감 + 슬래브({spec.top_ffl + spec.landing_t:g}m)가 트러스 높이"
                             f"({spec.esc_truss_depth:g}m)보다 두껍습니다")


def check_canopy(spec, name: str):
    """캐노피·출구 사인 치수"""
    if not spec.canopy:
        return
    for label, v in (("캐노피 높이", spec.cp_height), ("캐노피 기둥", spec.cp_post), ("캐노피 기둥 간격", spec.cp_spacing),
                     ("캐노피 보 폭", spec.cp_beam_w), ("캐노피 보 높이", spec.cp_beam_h), ("캐노피 유리 두께", spec.cp_glass_t)):
        if not v > 0:
            raise ValueError(f"출입구 {name}: {label}는 0 보다 커야 합니다 ({v:g})")
    for label, v in (("캐노피 기울기", spec.cp_slope), ("캐노피 앞 내밈", spec.cp_front), ("캐노피 옆 내밈", spec.cp_side)):
        if not v >= 0:
            raise ValueError(f"출입구 {name}: {label}는 0 이상이어야 합니다 ({v:g})")
    if spec.cp_wall and not 0 < spec.cp_wall_t < spec.cp_beam_w:
        raise ValueError(f"출입구 {name}: 캐노피 유리벽 두께({spec.cp_wall_t:g}m)는 0 보다 크고 보 폭보다 작아야 합니다")
    if spec.cp_beam_w > spec.cp_post + 1e-9:
        raise ValueError(f"출입구 {name}: 캐노피 보 폭({spec.cp_beam_w:g}m)이 기둥({spec.cp_post:g}m)보다 큽니다")
    if spec.cp_sign:
        for label, v in (("출구 사인 폭", spec.cp_sign_w), ("출구 사인 높이", spec.cp_sign_h), ("출구 사인 두께", spec.cp_sign_t)):
            if not v > 0:
                raise ValueError(f"출입구 {name}: {label}는 0 보다 커야 합니다 ({v:g})")
