"""출구통로 건축 마감: 바닥(마감재 + 채움)·양 측벽(구조면에서 띄운 패널)·천장판·천장틀.

마감 종류 = 마감표의 '통로'(PassageSpec.finish 로 통로마다 바꿈), 마감을 켰을 때만. 조각은 모두 통로 구조와 같은 구간 틀
(PassageSegment: 축·구배·꺾임부 연귀)의 곧은 압출 BoxPiece 라 꺾임부에서 바닥·벽·천장 마감이 연귀로 맞닿는다.

단면 (v = 진행방향 왼쪽 +, dz = 그 자리 구조 바닥 상면 기준):
- 바닥: 구조 벽 면 사이 (하부 헌치가 있으면 헌치 빗면을 따라 좁아짐), 채움 [0, ffl − floor_t] + 마감재 [ffl − floor_t, ffl]
- 벽: 구조 벽 면에서 마감 표면 거리(face)만큼 안쪽이 표면, 마감재 두께 wall_t (0 이면 면처리 — 형상 없음), 높이 ffl ~ 천장판 하면
- 걸레받이(마감 종류의 skirt_*): ffl ~ ffl + skirt_h, 벽 마감 표면에서 들어간 면 (FinishType.skirt_span), 벽 마감은 그 윗면부터
- 천장판: 벽 마감 표면 사이, 하면 = ffl + ceiling_h, 위로 천장틀(바: 축에 직각, 캐링 채널: 축 방향)
천장(판 + 틀)이 내공(상부 헌치 아래)에 들어가지 않으면 천장 없이 만들고 경고 (통로 내공 높이를 늘려야 함 — 필요한 높이 안내).

접합부 (개구부 안까지 연장): 첫 구간은 본체(또는 부모 통로) 벽 두께를 지나 그쪽 실 벽 마감 표면까지 — 바닥은 구조 벽 안쪽 면까지,
벽 마감은 그쪽 마감 표면까지, 천장판은 그쪽 벽 마감재 뒷면까지(그쪽 벽 마감이 천장판 하면 위를 덮음). 그쪽 벽 마감에는 통로 마감
개구부(벽 마감재 뒷면 사이 × 바닥 ~ 천장판 하면)만 비움 — 본체 실은 finish_layout 이 `room_wall_hole`, 부모 통로는 여기서.
끝 폐합 통로는 끝 벽 안쪽 면에 벽 마감 (측벽 마감은 구조 끝 벽 면까지, 천장판은 끝 벽 마감 표면까지).
"""
import math
from dataclasses import dataclass, field

from finishes.finish_spec import FILL_MORTAR
from helper.box_piece import BoxPiece

FLOOR, FILL, WALL, SKIRT, CEILING, FRAME = "FLOOR", "FILL", "WALL", "SKIRT", "CEILING", "FRAME"
CODES = (FILL, FLOOR, WALL, SKIRT, CEILING, FRAME)
PASSAGE_USE = "통로"
_EPS = 1e-6


@dataclass
class PassageFinishLayout:
    """통로 1개의 마감: parts = 코드 → BoxPiece 목록, ft = 마감 종류, ceiling = 천장을 만들었는지"""
    name: str
    floor: int
    ft: object
    ceiling: bool
    parts: dict = field(default_factory=dict)
    fixtures: list = field(default_factory=list)      # 천장 기구 [(PassageSegment, 천장판 하면 높이(바닥 상면 기준), (종류, a0, a1, v0, v1, 깊이))]


def passage_finish_type(cfg, spec):
    """통로 마감 종류 FinishType (마감을 끄면 None). 통로마다 spec.finish, 비우면 '통로'"""
    fs = getattr(cfg, "finish_settings", None)
    if fs is None or not fs.enabled:
        return None
    return fs.for_room(PASSAGE_USE, getattr(spec, "finish", "") or "")


def _haunch_limit(spec, x: float) -> float:
    """구조 벽 면에서 x 안쪽 지점의 천장 하면 높이 (상부 헌치 빗면 고려, 바닥 상면 기준)"""
    hw, hh = spec.top_haunch_w, spec.top_haunch_h
    if hw > 0 and hh > 0 and x < hw:
        return spec.inner_height - hh * (1.0 - x / hw)
    return spec.inner_height


def _haunch_floor(spec, x: float) -> float:
    """구조 벽 면에서 x 안쪽 지점의 하부 헌치 윗면 높이 (없으면 0)"""
    hw, hh = spec.bottom_haunch_w, spec.bottom_haunch_h
    if hw > 0 and hh > 0 and x < hw:
        return hh * (1.0 - x / hw)
    return 0.0


def ceiling_fit(spec, ft) -> tuple:
    """(천장이 들어가는가, 필요한 내공 높이). 천장판 + 천장틀 윗면 ≤ 벽 마감 표면 자리의 헌치 아래"""
    need = ft.ffl + ft.ceiling_h + ft.board_t + ft.frame_depth
    room = _haunch_limit(spec, ft.face)
    return need <= room + _EPS, need + (spec.inner_height - room)


def room_wall_hole(cfg, op) -> tuple:
    """본체 측벽 오프닝 op (이름, 층, side, s0, s1, z0, z1, 종류) → 실 벽 마감에서 비울 (s0, s1, z0, z1).
    출구통로이고 통로 마감이 있으면 통로 벽 마감재 뒷면 사이 × 바닥 ~ 통로 천장판 하면 (그 위·옆은 실 벽 마감이 덮음)"""
    s0, s1, z0, z1 = op[3], op[4], op[5], op[6]
    if len(op) < 8 or op[7] != "PASSAGE":
        return s0, s1, z0, z1
    lay = next((x for x in cfg.passage_layouts() if x.name == op[0]), None)
    ft = passage_finish_type(cfg, lay.spec) if lay is not None else None
    if ft is None:
        return s0, s1, z0, z1
    gap = ft.face - ft.wall_t if ft.wall_t > 0 else 0.0
    if ft.ceiling and ceiling_fit(lay.spec, ft)[0]:
        z1 = z0 + ft.ffl + ft.ceiling_h
    return s0 + gap, s1 - gap, z0, z1


def room_wall_skirt_hole(cfg, op) -> list:
    """본체 실 걸레받이에서 출구통로 걸레받이 자리로 더 비울 곳: 통로 걸레받이 앞면 사이 × 통로 걸레받이 윗면까지 (통로 걸레받이는
    실 걸레받이 뒷면까지 들어가고, 실 걸레받이 끝면이 통로 걸레받이 앞면과 같은 면이 됨). 통로에 걸레받이가 없으면 없음"""
    if len(op) < 8 or op[7] != "PASSAGE":
        return []
    lay = next((x for x in cfg.passage_layouts() if x.name == op[0]), None)
    ft = passage_finish_type(cfg, lay.spec) if lay is not None else None
    if ft is None or not ft.has_skirt:
        return []
    front = ft.skirt_span(ft.face)[1]
    return [(op[3] + front, op[4] - front, op[5], op[5] + ft.ffl + ft.skirt_h)]


def _back_of(ft) -> float:
    """구조 벽 면 → 벽 마감 맨 아래(걸레받이, 없으면 마감재) 뒷면 (마감 없으면 0)"""
    if ft is None or ft.wall_t <= 0:
        return 0.0
    return ft.skirt_span(ft.face)[0] if ft.has_skirt else ft.wall_gap


def _host_station(cfg, lay):
    """본체 접합부: (구조 벽 두께, 실 벽 마감 표면 거리, 실 벽 마감재 두께, 걸레받이(없으면 마감재) 뒷면 거리)"""
    from config.widening import inner_min
    from finishes.finish_clear import room_finish_at
    v0 = lay.vertices[0]
    a = lay.spec.half_in
    inner = inner_min(cfg, lay.floor, lay.side, v0.s - a, v0.s + a)
    wst = abs(v0.t) - inner
    rf = room_finish_at(cfg, lay.floor, v0.s, lay.side * (inner - 0.01))
    return wst, (rf.face if rf is not None else 0.0), (rf.wall_t if rf is not None else 0.0), _back_of(rf)


def _rect(v0, v1, d0, d1):
    return [(v0, d0), (v1, d0), (v1, d1), (v0, d1)]


def _piece(seg, a0, a1, sect, ks=None, ke=None, flat=False):
    """구간 틀의 조각 (a0 ~ a1). flat = 구배 없이 시작 꼭짓점 높이 (접합부 연장)"""
    slope = 0.0 if flat else seg.slope
    return BoxPiece(ox=seg.x, oy=seg.y, ux=seg.ux, uy=seg.uy, a0=a0, a1=a1, sect=sect,
                    z0=seg.z + slope * a0, slope=slope,
                    ks=seg.tp if ks is None else ks, ke=-seg.tn if ke is None else ke,
                    local={"seg": seg.index, "run": seg.run})


def layout_passage_finishes(cfg) -> tuple:
    """([PassageFinishLayout], [경고 문구]) — 마감을 끄면 ([], [])"""
    from fixtures.corridor_layout import cut_boxes, passage_fixtures
    fs = getattr(cfg, "finish_settings", None)
    if fs is None or not fs.enabled:
        return [], []
    lays = cfg.passage_layouts()
    by_name = {x.name: x for x in lays}
    fts = {x.name: passage_finish_type(cfg, x.spec) for x in lays}
    fits = {n: (ft.ceiling and ceiling_fit(by_name[n].spec, ft)[0]) for n, ft in fts.items()}
    warns = []
    for n, ft in fts.items():
        if ft.ceiling and not fits[n]:
            sp = by_name[n].spec
            need = ceiling_fit(sp, ft)[1]
            warns.append(f"출구통로 {n}: 천장(마감면 + {ft.ceiling_h:g}m, 천장판·천장틀 포함)이 내공(높이 {sp.inner_height:g}m, "
                         f"상부 헌치 아래)에 들어가지 않습니다 — 통로 내공 높이를 {need:.2f}m 이상으로 늘리세요 (지금은 천장 없이 만듦)")
    out = []
    for lay in lays:
        ft = fts[lay.name]
        sp = lay.spec
        a, H = sp.half_in, sp.inner_height
        ceil = fits[lay.name]
        face = ft.face if ft.wall_t > 0 else 0.0
        cb = ft.ffl + ft.ceiling_h                                     # 천장판 하면 (바닥 상면 기준)
        w_top = cb if ceil else _haunch_limit(sp, face - ft.wall_t) if ft.wall_t > 0 else H
        w_bot = max(ft.ffl + (ft.skirt_h if ft.has_skirt else 0.0), _haunch_floor(sp, face - ft.wall_t)) if ft.wall_t > 0 else ft.ffl
        c_half = a - face                                              # 벽 마감 표면 (천장판 반폭)
        parts = {c: [] for c in CODES}
        # 접합부 (본체 또는 부모 통로): 구조 벽 두께, 그쪽 마감 표면 거리, 그쪽 마감재 두께
        if lay.parent:
            pft = fts.get(lay.parent)
            host = (by_name[lay.parent].spec.wall_t, (pft.face if pft is not None and pft.wall_t > 0 else 0.0),
                    (pft.wall_t if pft is not None else 0.0), _back_of(pft))
        else:
            host = _host_station(cfg, lay)
        wst, hface, hwall, hback = host
        sk = ft.has_skirt
        sb, sf = ft.skirt_span(face) if sk else (0.0, 0.0)             # 걸레받이 뒷면·앞면 (구조 벽 면에서)
        s_top = ft.ffl + (ft.skirt_h if sk else 0.0)                   # 벽 마감 시작 높이
        s_bot = max(ft.ffl, _haunch_floor(sp, sb)) if sk else 0.0      # 하부 헌치 위
        last = len(lay.segments) - 1
        fixtures = []
        for seg in lay.segments:
            L = seg.length
            end = L - sp.wall_t if (sp.close_end and seg.index == last) else L
            ke_end = 0.0 if (sp.close_end and seg.index == last) else None
            starts = [(0.0, None, False)]
            if seg.index == 0:
                starts = [(-wst, 0.0, True), (0.0, None, False)]       # 접합부 벽 두께 구간 (수평 연장) + 구간
            for k, (a0, ks, flat) in enumerate(starts):
                ext = flat
                a1 = 0.0 if ext else end
                kk = 0.0 if ext else None
                ke = 0.0 if ext else ke_end
                # 바닥 (구조 벽 안쪽 면까지, 하부 헌치 빗면을 따라)
                if ft.ffl > _EPS:
                    def floor_band(h0, h1):
                        w0 = a - (0.0 if ext else _haunch_x(sp, h0))
                        w1 = a - (0.0 if ext else _haunch_x(sp, h1))
                        return [(-w0, h0), (w0, h0), (w1, h1), (-w1, h1)]
                    mat0 = max(ft.ffl - ft.floor_t, 0.0)
                    parts[FLOOR].append(_piece(seg, a0, a1, floor_band(mat0, ft.ffl), kk, ke, flat))
                    if ft.floor_fill == FILL_MORTAR and mat0 > _EPS:
                        parts[FILL].append(_piece(seg, a0, a1, floor_band(0.0, mat0), kk, ke, flat))
                # 벽 (접합부는 그쪽 마감 표면까지 연장)
                if ft.wall_t > 0 and w_top - w_bot > _EPS:
                    wa0 = -(wst + hface) if ext else a0
                    wb = s_top if ext else w_bot
                    wt = cb if (ext and ceil) else (H if ext else w_top)
                    for sgn in (1, -1):
                        v0, v1 = sorted((sgn * c_half, sgn * (c_half + ft.wall_t)))
                        parts[WALL].append(_piece(seg, wa0, a1, _rect(v0, v1, wb, wt), kk, ke, flat))
                # 걸레받이 (접합부는 그쪽 걸레받이(없으면 마감재) 뒷면까지)
                if sk and s_top - (ft.ffl if ext else s_bot) > _EPS:
                    for sgn in (1, -1):
                        v0, v1 = sorted((sgn * (a - sf), sgn * (a - sb)))
                        parts[SKIRT].append(_piece(seg, -(wst + hback) if ext else a0, a1,
                                                   _rect(v0, v1, ft.ffl if ext else s_bot, s_top), kk, ke, flat))
                # 천장판 (접합부는 그쪽 벽 마감재 뒷면까지)
                if ceil:
                    ca0 = -(wst + hface) + hwall if ext else a0
                    ca1 = a1 if ext else (end - face if (sp.close_end and seg.index == last) else end)
                    if ca1 - ca0 > _EPS:
                        parts[CEILING].append(_piece(seg, ca0, ca1, _rect(-c_half, c_half, cb, cb + ft.board_t), kk, ke, flat))
            if ceil:
                parts[FRAME] += _frame(seg, ft, c_half, cb + ft.board_t,
                                       end - face if (sp.close_end and seg.index == last) else end, ke_end)
                if ft.has_light or ft.has_diffuser:                    # 천장 기구 (매입 — 천장판·천장틀에서 그 자리를 뺌)
                    fx = passage_fixtures(ft, seg, c_half, end - face if ke_end == 0.0 else end, -seg.tn if ke_end is None else 0.0,
                                          lambda v: _haunch_limit(sp, a - v) - cb)
                    holes = [f[1:5] for f in fx]
                    for code in (CEILING, FRAME):
                        parts[code] = cut_boxes(parts[code], seg.index, holes)
                    fixtures += [(seg, cb, f) for f in fx]
            if sp.close_end and seg.index == last and ft.wall_t > 0:   # 끝 벽 마감
                e0 = L - sp.wall_t - face
                parts[WALL].append(_piece(seg, e0, e0 + ft.wall_t, _rect(-c_half, c_half, s_top, cb if ceil else w_top),
                                          0.0, 0.0))
                if sk:
                    parts[SKIRT].append(_piece(seg, L - sp.wall_t - sf, L - sp.wall_t - sb, _rect(-(a - sf), a - sf, ft.ffl, s_top),
                                               0.0, 0.0))
        out.append(PassageFinishLayout(lay.name, lay.floor, ft, ceil, parts, fixtures))
    # 분기: 부모 벽 마감에 자식 통로 마감 개구부 (자식 벽 마감재 뒷면 사이 × 바닥 ~ 자식 천장판 하면)
    res = {x.name: x for x in out}
    for lay in lays:
        if not lay.parent or lay.parent not in res:
            continue
        ft = fts[lay.name]
        gap = ft.face - ft.wall_t if ft.wall_t > 0 else 0.0
        w = lay.spec.half_in - gap
        top = ft.ffl + ft.ceiling_h if fits[lay.name] else lay.spec.inner_height
        _cut_branch(res[lay.parent], by_name[lay.parent], lay.branch_seg, lay.side, lay.branch_a - w, lay.branch_a + w, top)
        cuts = [(w, top)]                                    # 부모 걸레받이: 자식 걸레받이 앞면 사이(자식 걸레받이 높이까지) + 위와 같은 개구부
        if ft.has_skirt:
            cuts.append((lay.spec.half_in - ft.skirt_span(ft.face)[1], ft.ffl + ft.skirt_h))
        for cw, ct in sorted(cuts, reverse=True):            # 넓은 것부터 (좁은 것은 남은 인방에서)
            _cut_branch(res[lay.parent], by_name[lay.parent], lay.branch_seg, lay.side, lay.branch_a - cw, lay.branch_a + cw, ct, SKIRT)
    from elevators.ext_ev import passage_front
    from passages.passage_layout import ext_ev_hosts, host_position
    for xn, xs, pn in ext_ev_hosts(cfg):                      # 외부 엘리베이터 문 자리 (벽 마감 비움, 위는 인방)
        if pn in res and pn in by_name:
            seg_i, a, _ = host_position(by_name[pn], xs.along, f"외부 엘리베이터 {xn}")
            fs, ffl, _ = passage_front(cfg, by_name[pn].spec, xs, f"외부 엘리베이터 {xn}")
            half, h = fs.low_front()
            for code in (WALL, SKIRT):
                _cut_branch(res[pn], by_name[pn], seg_i, xs.host_side, a - half, a + half, ffl + h, code)
    return out, warns


def _haunch_x(spec, h: float) -> float:
    """하부 헌치가 높이 h 에서 벽 면으로부터 나온 폭"""
    hw, hh = spec.bottom_haunch_w, spec.bottom_haunch_h
    if hw > 0 and hh > 0 and h < hh:
        return hw * (1.0 - h / hh)
    return 0.0


def _frame(seg, ft, c_half, z_board, end, ke_end) -> list:
    """천장틀: 바(축에 직각, 축 방향 bar_spacing 격자 — 구간 시작 기준) + 캐링 채널(축 방향, v 의 carrier_spacing 격자 — 중심 기준).
    바는 연귀·끝에 걸리지 않는 자리만"""
    out = []
    bw, bh, cw, chh = ft.bar_w, ft.bar_h, ft.carrier_w, ft.carrier_h
    lo = max(seg.tp * v for v in (-c_half, c_half))                 # 모든 v 에서 구간 안
    hi = min(end + (-seg.tn if ke_end is None else ke_end) * v for v in (-c_half, c_half))
    k = math.ceil((lo + bw / 2.0) / ft.bar_spacing - 1e-9)
    while k * ft.bar_spacing + bw / 2.0 <= hi + _EPS:
        u = k * ft.bar_spacing
        out.append(_piece(seg, u - bw / 2.0, u + bw / 2.0, _rect(-c_half, c_half, z_board, z_board + bh), 0.0, 0.0))
        k += 1
    n = int(math.floor((c_half - cw / 2.0) / ft.carrier_spacing + 1e-9))
    for j in range(-n, n + 1):
        v = j * ft.carrier_spacing
        out.append(_piece(seg, 0.0, end, _rect(v - cw / 2.0, v + cw / 2.0, z_board + bh, z_board + bh + chh), None, ke_end))
    return out


def _cut_branch(res, parent, seg_i, side, o0, o1, top, code=WALL):
    """부모 통로 마감 res 의 side 쪽 벽 마감 조각(구간 seg_i)에서 축 o0 ~ o1 × 아래 ~ top 을 비움 (위는 인방으로 남김)"""
    new = []
    for pc in res.parts[code]:
        vs = [v for v, _ in pc.sect]
        on_side = min(vs) > 0 if side > 0 else max(vs) < 0
        if pc.local.get("seg") != seg_i or not on_side or not (pc.a0 - _EPS <= o0 and o1 <= pc.a1 + _EPS):
            new.append(pc)
            continue
        z = lambda a, pc=pc: pc.z0 + pc.slope * (a - pc.a0)
        new.append(BoxPiece(pc.ox, pc.oy, pc.ux, pc.uy, pc.a0, o0, pc.sect, pc.z0, pc.slope, pc.ks, 0.0, dict(pc.local)))
        new.append(BoxPiece(pc.ox, pc.oy, pc.ux, pc.uy, o1, pc.a1, pc.sect, z(o1), pc.slope, 0.0, pc.ke, dict(pc.local)))
        d0, d1 = min(dz for _, dz in pc.sect), max(dz for _, dz in pc.sect)
        if top < d1 - _EPS:
            v0, v1 = min(vs), max(vs)
            new.append(BoxPiece(pc.ox, pc.oy, pc.ux, pc.uy, o0, o1, _rect(v0, v1, max(top, d0), d1), z(o0), pc.slope, 0.0, 0.0,
                                dict(pc.local, lintel=True)))
    res.parts[code] = new
