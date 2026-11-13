import math

from helper.box_piece import footprints_overlap
from passages.passage_layout import layout_passage
from passages.passage_spec import PassageSpec, resolve_passage_names

_EPS = 1e-6


def check_passage_spec(station, spec, name: str):
    """입력 제원 자체의 검사 (층·방향·치수·헌치, 측벽 오프닝이 그 층 측벽 안에 들어가는지, 위·아래층 외벽과의 간섭)"""
    if not isinstance(spec, PassageSpec):
        raise ValueError(f"출구통로 {name}: 제원 형식이 올바르지 않습니다 ({spec!r})")
    floors = station.floors
    k = spec.floor
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= floors:
        raise ValueError(f"출구통로 {name}: 층 번호 {k!r} 이(가) 범위(1 ~ {floors})를 벗어납니다")
    if spec.side not in (1, -1):
        raise ValueError(f"출구통로 {name}: 측벽 방향은 +1 (t 큰 쪽) 또는 -1 (t 작은 쪽) 이어야 합니다 ({spec.side!r})")
    if spec.turn not in (1, -1):
        raise ValueError(f"출구통로 {name}: 꺾임 방향은 +1 (종점 방향) 또는 -1 (시점 방향) 이어야 합니다 ({spec.turn!r})")
    for label, v in (("내공 폭", spec.inner_width), ("내공 높이", spec.inner_height), ("벽 두께", spec.wall_t),
                     ("바닥 슬래브 두께", spec.floor_t), ("천장 슬래브 두께", spec.roof_t), ("첫 구간 길이", spec.length1)):
        if not v > 0:
            raise ValueError(f"출구통로 {name}: {label}은(는) 0보다 커야 합니다 ({v})")
    for label, v in (("꺾임 후 길이", spec.length2), ("상부 헌치 폭", spec.top_haunch_w), ("상부 헌치 높이", spec.top_haunch_h),
                     ("하부 헌치 폭", spec.bottom_haunch_w), ("하부 헌치 높이", spec.bottom_haunch_h)):
        if not v >= 0:
            raise ValueError(f"출구통로 {name}: {label}은(는) 0 이상이어야 합니다 ({v})")
    if not math.isfinite(spec.grade_permil):
        raise ValueError(f"출구통로 {name}: 구배가 숫자가 아닙니다 ({spec.grade_permil})")
    for label, w, h in (("상부", spec.top_haunch_w, spec.top_haunch_h), ("하부", spec.bottom_haunch_w, spec.bottom_haunch_h)):
        if (w > 0) != (h > 0):
            raise ValueError(f"출구통로 {name}: {label} 헌치는 폭과 높이를 모두 0 이거나 모두 0보다 크게 입력하세요")
        if w >= spec.half_in - _EPS:
            raise ValueError(f"출구통로 {name}: {label} 헌치 폭({w:g}m)이 내공 폭의 절반 이상입니다")
    if spec.top_haunch_h + spec.bottom_haunch_h >= spec.inner_height - _EPS:
        raise ValueError(f"출구통로 {name}: 상·하부 헌치 높이의 합이 내공 높이 이상입니다")
    if spec.bent:
        if spec.length1 < spec.half_out - _EPS:
            raise ValueError(f"출구통로 {name}: 꺾임이 있으면 첫 구간 길이({spec.length1:g}m)가 통로 외폭의 절반"
                             f"({spec.half_out:g}m) 이상이어야 합니다 (꺾인 통로가 본체 외벽에 닿음)")
        if spec.length2 <= spec.half_out + _EPS:
            raise ValueError(f"출구통로 {name}: 꺾임 후 길이({spec.length2:g}m)가 통로 외폭의 절반({spec.half_out:g}m)보다 "
                             "커야 합니다")
    a, L = spec.half_in, station.length
    if spec.s_center - a < -_EPS or spec.s_center + a > L + _EPS:
        raise ValueError(f"출구통로 {name}: 측벽 오프닝 s {spec.s_center - a:.3f} ~ {spec.s_center + a:.3f} 이(가) "
                         f"내공 길이(0 ~ {L:g}m)를 벗어납니다")
    clear = station.clear_height(k)
    if spec.inner_height > clear + _EPS:
        raise ValueError(f"출구통로 {name}: 내공 높이({spec.inner_height:g}m)가 {station.level_name(k)} 내공 높이"
                         f"({clear:g}m)보다 큽니다 (측벽 오프닝이 위 슬래브에 닿음)")
    wt = station.wall_t_at(k)
    if k > 1 and station.wall_t_at(k - 1) > wt + _EPS:
        raise ValueError(f"출구통로 {name}: 아래층({station.level_name(k - 1)}) 외벽이 더 두꺼워 통로 바닥 슬래브와 겹칩니다")
    top = station.floor_level(k) + spec.inner_height + spec.roof_t
    if k < floors and top > station.floor_level(k + 1) + _EPS and station.wall_t_at(k + 1) > wt + _EPS:
        raise ValueError(f"출구통로 {name}: 위층({station.level_name(k + 1)}) 외벽이 더 두꺼워 통로 천장 슬래브와 겹칩니다")


def layout_passages(cfg) -> list:
    """통로마다 PassageLayout (이름 확정 + 입력 검사 + 배치 계산)"""
    names = resolve_passage_names(cfg.passages)
    out = []
    for name, spec in zip(names, cfg.passages):
        check_passage_spec(cfg.station, spec, name)
        out.append(layout_passage(cfg, spec, name))
    return out


def _vertical_overlap(p, q) -> bool:
    (a0, a1), (b0, b1) = p.z_range, q.z_range
    return min(a1, b1) - max(a0, b0) > 1e-6


def check_passage_layouts(cfg, layouts: list):
    """통로끼리 겹치지 않을 것 (평면이 겹치고 높이 범위도 겹치는 조각이 있으면 오류)"""
    for i, a in enumerate(layouts):
        for b in layouts[i + 1:]:
            for p in a.pieces():
                fp = p.footprint()
                for q in b.pieces():
                    if _vertical_overlap(p, q) and footprints_overlap(fp, q.footprint()):
                        raise ValueError(f"출구통로 {a.name} 와 {b.name} 이(가) 서로 겹칩니다")
