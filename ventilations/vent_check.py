import math

from helper.box_piece import footprints_overlap
from passages.passage_spec import MODES, PathVertex
from ventilations.vent_layout import layout_vent
from ventilations.vent_spec import VentSpec, resolve_vent_names

_EPS = 1e-6


def check_vent_spec(station, spec, name: str):
    """입력 제원 자체의 검사 (층·경로 형식·치수·헌치·그릴, 내공 높이, 위·아래층 외벽과의 간섭)"""
    if not isinstance(spec, VentSpec):
        raise ValueError(f"환기구 {name}: 제원 형식이 올바르지 않습니다 ({spec!r})")
    floors = station.floors
    k = spec.floor
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= floors:
        raise ValueError(f"환기구 {name}: 층 번호 {k!r} 이(가) 범위(1 ~ {floors})를 벗어납니다")
    if not isinstance(spec.path, (list, tuple)) or len(spec.path) < 2:
        raise ValueError(f"환기구 {name}: 경로 꼭짓점은 2개 이상이어야 합니다")
    for i, v in enumerate(spec.path, start=1):
        if not isinstance(v, PathVertex) or v.mode not in MODES:
            raise ValueError(f"환기구 {name}: 꼭짓점 {i} 의 형식이 올바르지 않습니다 ({v!r})")
        if not (math.isfinite(v.x) and math.isfinite(v.y)) or (v.z is not None and not math.isfinite(v.z)):
            raise ValueError(f"환기구 {name}: 꼭짓점 {i} 의 좌표가 숫자가 아닙니다")
    if not isinstance(spec.cells, int) or isinstance(spec.cells, bool) or not 1 <= spec.cells <= 20:
        raise ValueError(f"환기구 {name}: 련 수는 1 ~ 20 의 정수여야 합니다 ({spec.cells!r})")
    for label, val in (("칸 내공 폭", spec.cell_width), ("칸 내공 높이", spec.cell_height), ("바깥 벽 두께", spec.wall_t),
                       ("바닥 슬래브 두께", spec.floor_t), ("천장 슬래브 두께", spec.roof_t), ("수직구 깊이", spec.depth),
                       ("그릴 두께", spec.grill_t), ("그릴 테두리 폭", spec.grill_frame), ("그릴 살 폭", spec.grill_bar),
                       ("그릴 살 간격", spec.grill_gap)):
        if not val > 0:
            raise ValueError(f"환기구 {name}: {label}은(는) 0보다 커야 합니다 ({val})")
    if spec.cells > 1 and not spec.mid_wall_t > 0:
        raise ValueError(f"환기구 {name}: 중벽 두께는 0보다 커야 합니다 ({spec.mid_wall_t})")
    for label, val in (("헌치 폭", spec.haunch_w), ("헌치 높이", spec.haunch_h)):
        if not val >= 0:
            raise ValueError(f"환기구 {name}: {label}은(는) 0 이상이어야 합니다 ({val})")
    if (spec.haunch_w > 0) != (spec.haunch_h > 0):
        raise ValueError(f"환기구 {name}: 헌치는 폭과 높이를 모두 0 이거나 모두 0보다 크게 입력하세요")
    if spec.haunch_w >= spec.cell_width / 2.0 - _EPS:
        raise ValueError(f"환기구 {name}: 헌치 폭({spec.haunch_w:g}m)이 칸 폭의 절반 이상입니다")
    if spec.haunch_h >= spec.cell_height - _EPS:
        raise ValueError(f"환기구 {name}: 헌치 높이({spec.haunch_h:g}m)가 칸 높이 이상입니다")
    if 2 * spec.grill_frame >= min(spec.cell_width, spec.cell_height, spec.depth) - _EPS:
        raise ValueError(f"환기구 {name}: 그릴 테두리 폭({spec.grill_frame:g}m)이 칸 크기에 비해 너무 큽니다")
    if spec.grill_t >= spec.depth / 2.0:
        raise ValueError(f"환기구 {name}: 그릴 두께({spec.grill_t:g}m)가 너무 큽니다")
    clear = station.clear_height(k)
    if spec.cell_height > clear + _EPS:
        raise ValueError(f"환기구 {name}: 칸 내공 높이({spec.cell_height:g}m)가 {station.level_name(k)} 내공 높이"
                         f"({clear:g}m)보다 큽니다 (측벽 오프닝이 위 슬래브에 닿음)")
    wt = station.wall_t_at(k)
    if k > 1 and station.wall_t_at(k - 1) > wt + _EPS:
        raise ValueError(f"환기구 {name}: 아래층({station.level_name(k - 1)}) 외벽이 더 두꺼워 덕트 바닥 슬래브와 겹칩니다")
    top = station.floor_level(k) + spec.cell_height + spec.roof_t
    if k < floors and top > station.floor_level(k + 1) + _EPS and station.wall_t_at(k + 1) > wt + _EPS:
        raise ValueError(f"환기구 {name}: 위층({station.level_name(k + 1)}) 외벽이 더 두꺼워 덕트 천장 슬래브와 겹칩니다")


def pieces_overlap(p, q) -> bool:
    (a0, a1), (b0, b1) = p.z_range, q.z_range
    return min(a1, b1) - max(a0, b0) > 1e-6 and footprints_overlap(p.footprint(), q.footprint())


def layout_vents(cfg) -> list:
    """환기구마다 VentLayout (이름 확정 + 입력 검사 + 배치 계산 + 측벽 오프닝 범위 + 경로 자기 겹침)"""
    st = cfg.station
    names = resolve_vent_names(cfg.vents)
    out = []
    for name, spec in zip(names, cfg.vents):
        check_vent_spec(st, spec, name)
        lay = layout_vent(cfg, spec, name)
        lo = min(o[3] for o in lay.wall_openings)
        hi = max(o[4] for o in lay.wall_openings)
        if lo < -_EPS or hi > st.length + _EPS:
            raise ValueError(f"환기구 {name}: 측벽 오프닝 s {lo:.3f} ~ {hi:.3f} 이(가) 내공 길이(0 ~ {st.length:g}m)를 벗어납니다")
        pieces = lay.concrete_pieces()
        for i, p in enumerate(pieces):                     # 이웃하지 않은 구간끼리 겹치면 경로가 스스로 교차
            for q in pieces[i + 1:]:
                if abs(p.local["seg"] - q.local["seg"]) > 1 and pieces_overlap(p, q):
                    raise ValueError(f"환기구 {name}: 경로가 스스로 겹칩니다 (구간 {p.local['seg'] + 1} 와 {q.local['seg'] + 1})")
        out.append(lay)
    return out


def check_vent_layouts(cfg, vents: list, passages: list):
    """환기구끼리, 환기구와 출구통로가 겹치지 않을 것"""
    for i, a in enumerate(vents):
        for b in vents[i + 1:]:
            if any(pieces_overlap(p, q) for p in a.concrete_pieces() for q in b.concrete_pieces()):
                raise ValueError(f"환기구 {a.name} 와 {b.name} 이(가) 서로 겹칩니다")
        for b in passages:
            if any(pieces_overlap(p, q) for p in a.concrete_pieces() for q in b.pieces()):
                raise ValueError(f"환기구 {a.name} 와 출구통로 {b.name} 이(가) 서로 겹칩니다")
