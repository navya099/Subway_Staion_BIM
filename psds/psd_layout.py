"""스크린도어(PSD) 배치: 선로마다 열차 문 위치에 유닛을 놓고 POST·구동부·채움 패널까지 정거장 로컬 상자 조각으로.

- 유닛 중심 = 열차 문 중심 (두 가동문 사이). 유닛 s 범위 = 중심 ± unit_w/2:
  고정부(−s) | 가동문(−s 짝) | 가동문(+s 짝) | 고정부(+s), emergency 쪽 고정부는 비상문 겸용
- POST: 유닛 양옆 (폭 post_w). 이웃 유닛의 POST 가 같은 자리(문 간격 = unit_w + post_w)면 하나로 같이 씀
- 유닛 사이가 벌어지면 채움 고정 패널 (한 장 ≤ fill_max, 여러 장이면 사이에 POST), 열차 밖(선두·후미 바깥)은 없음
- 내공 길이 [0, L] 밖으로 나간 조각(열차가 승강장 끝에 붙어 끝 유닛 POST·고정부가 단부 벽에 걸침)은 잘라냄
- t: 그 선로 쪽 승강장 끝단 |t| = D/2 + 끝단 거리에서 edge_offset 떨어진 PSD 중심선. 부재는 중심선 기준 깊이 대칭
- z(본체 FL 기준): 바닥 = 승강장 바닥 마감면 (그 자리 실의 마감 높이, 마감 끔·마감 없음이면 승강장 상면)
  문·패널 = 바닥 ~ 바닥 + door_h, 구동부 = 그 위 header_h, POST = 바닥 ~ 바닥 + door_h + header_h
- 패널(고정부·가동문·채움) = 프레임(양옆 기둥·위 레일 = frame_w, 아래 레일 = kick_h, 두께 frame_d) + 유리(glass_t, 가운데)
"""
from config.layout_cache import cached_layout
import math
from dataclasses import dataclass, field

from psds.psd_spec import EMERGENCY_SIDES
from rooms.room_layout import ceiling_rel, resolve_room_names
from trains.train_layout import layout_trains

_EPS = 1e-6
_TOL = 1e-3
POST, HEADER, DOOR, FIXED, EMERGENCY, FILL = "POST", "HEADER", "DOOR", "FIXED", "EMERGENCY", "FILL"


@dataclass
class PsdPart:
    name: str
    kind: str                    # POST | HEADER | DOOR | FIXED | EMERGENCY | FILL
    track: str
    unit: str                    # 유닛 번호(열차 문 '차량-문'), POST·채움은 ''
    pieces: list = field(default_factory=list)     # [(s0, s1, t0, t1, z0, z1)] 정거장 로컬, FL 기준
    glass: list = field(default_factory=list)      # 조각마다 유리 여부


@dataclass
class PsdRun:
    track: str
    side: int                    # 승강장 쪽 (+1 = +t)
    t: float                     # PSD 중심선 t
    parts: list                  # PsdPart


def psd_line_t(cfg, side: int) -> float:
    pl = cfg.platform
    return side * (pl.track_spacing / 2.0 + pl.plat_offset + cfg.psd_settings.edge_offset)


def platform_base(cfg, s: float, t: float) -> float:
    """(s, t) 의 승강장 바닥 마감면 (본체 FL 기준). 마감을 끄거나 그 실에 바닥 마감이 없으면 승강장 상면"""
    top = cfg.platform.top_level
    fs = getattr(cfg, "finish_settings", None)
    if fs is None or not fs.enabled:
        return top
    specs = dict(zip(resolve_room_names(cfg, cfg.rooms), cfg.rooms))
    for fl in cfg.room_layouts():
        if fl.floor != 1:
            continue
        for room in fl.rooms:
            if room.contains(s, t, _EPS):
                sp = specs.get(room.name)
                ft = fs.for_room(room.use, getattr(sp, "finish", "") if sp else "")
                return top + ft.ffl
    return top


def _box(s0, s1, tc, d, z0, z1):
    return (s0, s1, tc - d / 2.0, tc + d / 2.0, z0, z1)


def panel_pieces(ps, s0, s1, tc, z0) -> tuple:
    """패널 [s0, s1] × [z0, z0 + door_h] → (조각, 유리 여부)"""
    fw, fd, top = ps.frame_w, ps.frame_d, z0 + ps.door_h
    pcs = [_box(s0, s0 + fw, tc, fd, z0, top), _box(s1 - fw, s1, tc, fd, z0, top),            # 양옆
           _box(s0 + fw, s1 - fw, tc, fd, top - fw, top), _box(s0 + fw, s1 - fw, tc, fd, z0, z0 + ps.kick_h),
           _box(s0 + fw, s1 - fw, tc, ps.glass_t, z0 + ps.kick_h, top - fw)]
    return pcs, [False, False, False, False, True]


def _clip(part, L):
    """정거장 내공 길이 [0, L] 밖으로 나간 조각을 잘라냄 (열차 끝 유닛의 POST·고정부가 단부 벽에 걸칠 때)"""
    pcs, gl = [], []
    for pc, g in zip(part.pieces, part.glass):
        s0, s1 = max(pc[0], 0.0), min(pc[1], L)
        if s1 - s0 > _EPS:
            pcs.append((s0, s1, *pc[2:]))
            gl.append(g)
    part.pieces, part.glass = pcs, gl
    return part


@cached_layout("psds")
def layout_psds(cfg) -> list:
    """선로마다 PsdRun (PSD 를 쓰지 않으면 빈 목록). 겹침·좁은 간격은 ValueError"""
    ps = getattr(cfg, "psd_settings", None)
    if ps is None or not ps.enabled:
        return []
    U, pw, H = ps.unit_w, ps.post_w, ps.height
    out = []
    for tp in layout_trains(cfg):
        tc = psd_line_t(cfg, tp.side)
        doors = sorted(tp.doors, key=lambda d: d.s)
        parts, posts = [], []                      # posts: [(s0, s1, z0)]

        def add_post(s0, base):
            if posts and abs(posts[-1][0] - s0) < _TOL:
                return
            posts.append((s0, s0 + pw, base))

        def add_panel(name, kind, unit, a, b, base):
            pcs, gl = panel_pieces(ps, a, b, tc, base)
            parts.append(PsdPart(name, kind, tp.track, unit, pcs, gl))

        def add_header(name, unit, a, b, base):
            parts.append(PsdPart(name, HEADER, tp.track, unit,
                                 [_box(a, b, tc, ps.header_d, base + ps.door_h, base + H)], [False]))

        prev_end, fill_k = None, 0
        for d in doors:
            c = d.s
            lo, hi = c - U / 2.0, c + U / 2.0
            base = platform_base(cfg, c, tc)
            if prev_end is not None:
                gap = (lo - pw) - prev_end      # 앞 유닛 끝 POST 뒤 ~ 이 유닛 앞 POST 앞 (−pw = POST 공유, < −2pw = 유닛 겹침)
                if gap < -2 * pw - _TOL:
                    raise ValueError(f"스크린도어({tp.track} 선로) 유닛 {d.label}: 앞 유닛과 겹칩니다 "
                                     f"(문 간격이 유닛 폭 {U:g} + POST {pw:g} 보다 좁음 — 고정부·가동문 폭 확인)")
                if gap < -_TOL and abs(gap + pw) > _TOL:
                    raise ValueError(f"스크린도어({tp.track} 선로) 유닛 {d.label}: 앞 유닛과 POST 가 일부 겹칩니다 "
                                     f"(문 간격을 유닛 폭 + POST = {U + pw:g}m 로 맞추거나 더 벌리세요)")
                if gap > _TOL:                                             # 채움 패널
                    n = max(1, math.ceil(gap / ps.fill_max - 1e-9))
                    w = (gap - (n - 1) * pw) / n
                    if w < 2 * ps.frame_w + 0.05:
                        raise ValueError(f"스크린도어({tp.track} 선로) 유닛 {d.label} 앞: 유닛 사이 간격 {gap:.3f}m 가 "
                                         "채움 패널을 넣기에 너무 좁습니다")
                    a = prev_end
                    fbase = platform_base(cfg, a + gap / 2.0, tc)
                    for k in range(n):
                        if k:
                            add_post(a, fbase)
                            a += pw
                        fill_k += 1
                        add_panel(f"PSD_{tp.track}_F{fill_k}", FILL, "", a, a + w, fbase)
                        add_header(f"PSD_{tp.track}_FH{fill_k}", "", a, a + w, fbase)
                        a += w
            add_post(lo - pw, base)
            name = f"PSD_{tp.track}_{d.label}"
            fw, dw = ps.fixed_w, ps.door_w
            for code, kind, a, b in (("FIX_N", EMERGENCY if ps.emergency == "-s" else FIXED, lo, lo + fw),
                                     ("DOOR_N", DOOR, lo + fw, c), ("DOOR_P", DOOR, c, c + dw),
                                     ("FIX_P", EMERGENCY if ps.emergency == "+s" else FIXED, hi - fw, hi)):
                add_panel(f"{name}_{code}", kind, d.label, a, b, base)
            add_header(f"{name}_HEADER", d.label, lo, hi, base)
            add_post(hi, base)
            prev_end = hi + pw
        for k, (s0, s1, base) in enumerate(posts, start=1):
            parts.append(PsdPart(f"PSD_{tp.track}_P{k}", POST, tp.track, "", [_box(s0, s1, tc, ps.post_d, base, base + H)], [False]))
        out.append(PsdRun(tp.track, tp.side, tc, [p for p in (_clip(p, cfg.station.length) for p in parts) if p.pieces]))
    return out


def _pos(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def check_psd(cfg):
    """스크린도어 입력 검사 (ValueError): 열차·승강장 필요, 치수, 프레임이 패널에 들어감, 승강장 폭·층 높이 안, 유닛 겹침"""
    ps = getattr(cfg, "psd_settings", None)
    if ps is None or not ps.enabled:
        return
    for label, v in (("고정부 폭", ps.fixed_w), ("가동문 폭", ps.door_w), ("문 높이", ps.door_h), ("구동부 높이", ps.header_h),
                     ("POST 폭", ps.post_w), ("POST 깊이", ps.post_d), ("구동부 깊이", ps.header_d),
                     ("프레임 폭", ps.frame_w), ("프레임 두께", ps.frame_d), ("하부 레일 높이", ps.kick_h),
                     ("유리 두께", ps.glass_t), ("채움 패널 최대 폭", ps.fill_max)):
        if not _pos(v):
            raise ValueError(f"스크린도어: {label}은(는) 0보다 커야 합니다 ({v})")
    if not (isinstance(ps.edge_offset, (int, float)) and math.isfinite(ps.edge_offset) and ps.edge_offset >= 0):
        raise ValueError(f"스크린도어: 연단 이격은 0 이상이어야 합니다 ({ps.edge_offset})")
    if ps.emergency not in EMERGENCY_SIDES:
        raise ValueError(f"스크린도어: 비상문 쪽은 +s, -s 또는 없음이어야 합니다 ({ps.emergency!r})")
    if 2 * ps.frame_w >= min(ps.fixed_w, ps.door_w) - _EPS:
        raise ValueError("스크린도어: 프레임 폭 × 2 가 고정부·가동문 폭보다 작아야 합니다")
    if ps.kick_h + ps.frame_w >= ps.door_h - _EPS:
        raise ValueError("스크린도어: 하부 레일 + 위 프레임이 문 높이보다 작아야 합니다")
    if ps.glass_t > ps.frame_d + _EPS:
        raise ValueError("스크린도어: 유리 두께가 프레임 두께보다 클 수 없습니다")
    if ps.fill_max <= 2 * ps.frame_w + 0.05:
        raise ValueError("스크린도어: 채움 패널 최대 폭이 너무 작습니다")
    if not cfg.platform.exists:
        raise ValueError("스크린도어: 승강장이 없습니다 (승강장 슬래브 두께 > 0 필요)")
    tr = getattr(cfg, "train_settings", None)
    if tr is None or not tr.enabled or not tr.stops:
        raise ValueError("스크린도어: 열차(승강장 탭 '열차')를 쓰고 정차 선로를 하나 이상 고르세요 — 유닛은 열차 문 위치에 놓입니다")
    st, pl = cfg.station, cfg.platform
    half = max(ps.post_d, ps.header_d, ps.frame_d) / 2.0
    edge = pl.track_spacing / 2.0 + pl.plat_offset
    if edge + ps.edge_offset - half < edge - _TOL or edge + ps.edge_offset + half > st.width / 2.0 + _TOL:
        raise ValueError(f"스크린도어: PSD 중심선(|t| = {edge + ps.edge_offset:g})이 승강장 폭 안에 들어가지 않습니다 "
                         f"(연단 이격 ≥ 부재 깊이/2 = {half:g}m)")
    runs = layout_psds(cfg)
    top = ceiling_rel(st, 1)
    for r in runs:
        for p in r.parts:
            for pc in p.pieces:
                if pc[5] > top + _TOL:
                    raise ValueError(f"스크린도어 {p.name}: 높이(FL+{pc[5]:.3f})가 승강장층 천장(위 슬래브 하면 FL+{top:.3f})"
                                     "보다 높습니다")
