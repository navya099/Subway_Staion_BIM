import math

from helper.box_piece import footprints_overlap
from passages.passage_layout import layout_passage
from passages.passage_spec import MODES, PassageSpec, PathVertex, resolve_passage_names

_EPS = 1e-6


def check_passage_spec(station, spec, name: str):
    """입력 제원 자체의 검사 (층·경로 형식·치수·헌치, 내공 높이, 위·아래층 외벽과의 간섭)"""
    if not isinstance(spec, PassageSpec):
        raise ValueError(f"출구통로 {name}: 제원 형식이 올바르지 않습니다 ({spec!r})")
    floors = station.floors
    k = spec.floor
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= floors:
        raise ValueError(f"출구통로 {name}: 층 번호 {k!r} 이(가) 범위(1 ~ {floors})를 벗어납니다")
    if not isinstance(spec.path, (list, tuple)) or len(spec.path) < 2:
        raise ValueError(f"출구통로 {name}: 경로 꼭짓점은 2개 이상이어야 합니다")
    for i, v in enumerate(spec.path, start=1):
        if not isinstance(v, PathVertex) or v.mode not in MODES:
            raise ValueError(f"출구통로 {name}: 꼭짓점 {i} 의 형식이 올바르지 않습니다 ({v!r})")
        if not (math.isfinite(v.x) and math.isfinite(v.y)) or (v.z is not None and not math.isfinite(v.z)):
            raise ValueError(f"출구통로 {name}: 꼭짓점 {i} 의 좌표가 숫자가 아닙니다")
    for label, val in (("내공 폭", spec.inner_width), ("내공 높이", spec.inner_height), ("벽 두께", spec.wall_t),
                       ("바닥 슬래브 두께", spec.floor_t), ("천장 슬래브 두께", spec.roof_t)):
        if not val > 0:
            raise ValueError(f"출구통로 {name}: {label}은(는) 0보다 커야 합니다 ({val})")
    for label, val in (("상부 헌치 폭", spec.top_haunch_w), ("상부 헌치 높이", spec.top_haunch_h),
                       ("하부 헌치 폭", spec.bottom_haunch_w), ("하부 헌치 높이", spec.bottom_haunch_h)):
        if not val >= 0:
            raise ValueError(f"출구통로 {name}: {label}은(는) 0 이상이어야 합니다 ({val})")
    for label, w, h in (("상부", spec.top_haunch_w, spec.top_haunch_h), ("하부", spec.bottom_haunch_w, spec.bottom_haunch_h)):
        if (w > 0) != (h > 0):
            raise ValueError(f"출구통로 {name}: {label} 헌치는 폭과 높이를 모두 0 이거나 모두 0보다 크게 입력하세요")
        if w >= spec.half_in - _EPS:
            raise ValueError(f"출구통로 {name}: {label} 헌치 폭({w:g}m)이 내공 폭의 절반 이상입니다")
    if spec.top_haunch_h + spec.bottom_haunch_h >= spec.inner_height - _EPS:
        raise ValueError(f"출구통로 {name}: 상·하부 헌치 높이의 합이 내공 높이 이상입니다")
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


def _vertical_overlap(p, q) -> bool:
    (a0, a1), (b0, b1) = p.z_range, q.z_range
    return min(a1, b1) - max(a0, b0) > 1e-6


def _pieces_overlap(p, q) -> bool:
    return _vertical_overlap(p, q) and footprints_overlap(p.footprint(), q.footprint())


def layout_passages(cfg) -> list:
    """통로마다 PassageLayout (이름 확정 + 입력 검사 + 배치 계산 + 측벽 오프닝 범위 + 경로 자기 겹침)"""
    st = cfg.station
    names = resolve_passage_names(cfg.passages)
    out = []
    for name, spec in zip(names, cfg.passages):
        check_passage_spec(st, spec, name)
        lay = layout_passage(cfg, spec, name)
        _, _, _, s0, s1, _, _ = lay.wall_opening
        if s0 < -_EPS or s1 > st.length + _EPS:
            raise ValueError(f"출구통로 {name}: 측벽 오프닝 s {s0:.3f} ~ {s1:.3f} 이(가) 내공 길이(0 ~ {st.length:g}m)를 벗어납니다")
        pieces = lay.pieces()
        for i, p in enumerate(pieces):                     # 이웃하지 않은 구간끼리 겹치면 경로가 스스로 교차
            for q in pieces[i + 1:]:
                if abs(p.local["seg"] - q.local["seg"]) > 1 and _pieces_overlap(p, q):
                    raise ValueError(f"출구통로 {name}: 경로가 스스로 겹칩니다 (구간 {p.local['seg'] + 1} 와 {q.local['seg'] + 1})")
        out.append(lay)
    return out


def check_passage_layouts(cfg, layouts: list):
    """통로끼리 겹치지 않을 것 (평면이 겹치고 높이 범위도 겹치는 조각이 있으면 오류)"""
    for i, a in enumerate(layouts):
        for b in layouts[i + 1:]:
            for p in a.pieces():
                for q in b.pieces():
                    if _pieces_overlap(p, q):
                        raise ValueError(f"출구통로 {a.name} 와 {b.name} 이(가) 서로 겹칩니다")
