"""역명판·안내사인 배치 (정거장 로컬 상자 + 이미지 면).

- 역명판(NAMEPLATE): 최하층 승강장 양쪽 뒤 본체 측벽(내공면, 바닥 마감이 있는 실이면 벽 마감 표면) 승강장 쪽.
  s = 내공 가운데에서 plate_interval 간격으로 대칭, 폭 = plate_h × 이미지 비율, 하단 = 승강장 바닥 마감면 + plate_bottom.
  측벽 오프닝(출구통로·환기구) 높이 구간과 겹치는 자리는 건너뜀. 이미지의 왼쪽·오른쪽 이웃 역 = 보는 사람 기준 실제 방향
  (+t 측벽을 보면 오른쪽 = +s) 쪽 이웃 역 (StationInfo.plus / minus)
- 타는 곳(BOARDING): 승강장(1층)으로 내려가는 계단·에스컬레이터(lower_floor = 1)의 위층 도착 끝에서 hang_offset 더 간 곳 천장 매달림,
  면은 그 계단을 향해 걸어오는 사람 쪽(오르는 방향 = 법선). 방면 = 계단 t 부호 쪽 선로(+t = L)의 문구
- 출구(EXIT): 출구통로 측벽 접합부 앞 (측벽 면에서 hang_offset 안쪽) 천장 매달림, 면은 정거장 안쪽. 번호·목적지 = exit_info (없으면 순번)
높이 기준(그 층 바닥 마감면)·천장(마감 천장판 하면 또는 위 슬래브 하면)은 그 자리 실의 마감표로 정한다.
"""
import math
from dataclasses import dataclass, field

from rooms.room_layout import ceiling_rel, resolve_room_names
from trains.train_layout import layout_trains

_EPS = 1e-6
NAMEPLATE, BOARDING, EXIT = "NAMEPLATE", "BOARDING", "EXIT"
FACE_T = 0.002                   # 이미지 면 두께 (본체 앞면에 붙은 얇은 판)


@dataclass
class SignPlacement:
    name: str
    kind: str                    # NAMEPLATE | BOARDING | EXIT
    floor: int
    s: float                     # 중심 s
    t: float                     # 본체 뒷면(벽 부착) 또는 중심(매달림) t
    normal: tuple                # 앞면 법선 (ns, nt) — 축 방향 단위 벡터
    width: float
    height: float
    thick: float
    z0: float                    # 하단 (본체 FL 기준)
    mounted: bool                # True = 벽 부착 (t = 뒷면), False = 매달림 (t, s = 중심)
    content: dict = field(default_factory=dict)    # 이미지 입력 (종류별)

    def boxes(self) -> tuple:
        """(본체 상자, 이미지 면 상자) — 각 (s0, s1, t0, t1, z0, z1)"""
        ns, nt = self.normal
        hw, z1 = self.width / 2.0, self.z0 + self.height
        back = 0.0 if self.mounted else -self.thick / 2.0          # 법선 방향 거리: 뒷면
        front = back + self.thick

        def box(a, b):
            if ns:                                                  # 법선 = ±s → 면은 t 방향으로 펼쳐짐
                s0, s1 = sorted((self.s + ns * a, self.s + ns * b))
                return (s0, s1, self.t - hw, self.t + hw, self.z0, z1)
            t0, t1 = sorted((self.t + nt * a, self.t + nt * b))
            return (self.s - hw, self.s + hw, t0, t1, self.z0, z1)
        return box(back, front), box(front, front + FACE_T)

    def right(self) -> tuple:
        """앞에서 보는 사람의 오른쪽 방향 (ns, nt) — 이미지 가로(u) 방향"""
        ns, nt = self.normal
        return (-nt, ns)


def finish_at(cfg, n: int, s: float, t: float):
    """층 n 의 (s, t) 에 있는 실의 마감 종류 (마감 끔·실 없음이면 None)"""
    fs = getattr(cfg, "finish_settings", None)
    if fs is None or not fs.enabled:
        return None
    specs = dict(zip(resolve_room_names(cfg, cfg.rooms), cfg.rooms))
    for fl in cfg.room_layouts():
        if fl.floor != n:
            continue
        for room in fl.rooms:
            if any(a - _EPS <= s <= b + _EPS and c - _EPS <= t <= d + _EPS for a, b, c, d in room.rects):
                sp = specs.get(room.name)
                return fs.for_room(room.use, getattr(sp, "finish", "") if sp else "")
    return None


def floor_and_ceiling(cfg, n: int, s: float, t: float) -> tuple:
    """(바닥 마감면, 천장 하면) 본체 FL 기준. 최하층 승강장 위는 승강장 상면 기준"""
    st, pl = cfg.station, cfg.platform
    base = st.floor_level(n)
    if n == 1 and pl.exists and any(a <= t <= b for a, b in pl.slab_t_ranges(st.width)):
        base = pl.top_level
    ceil = ceiling_rel(st, n)
    ft = finish_at(cfg, n, s, t)
    if ft is not None:
        if ft.ceiling:
            ceil = min(ceil, base + ft.ffl + ft.ceiling_h)
        base += ft.ffl
    return base, ceil


def _wall_face(cfg, n, s, side) -> float:
    """측벽 면 |t| (내공면 − 벽 마감 표면 거리)"""
    hw = cfg.station.width / 2.0
    ft = finish_at(cfg, n, s, side * (hw - 0.5))
    return hw - (ft.face if ft is not None and ft.wall_t > _EPS else 0.0)


def _directions(cfg) -> dict:
    """선로 → 진행방향 (열차 정차가 있으면 그 값, 없으면 R = +1, L = −1)"""
    out = {"R": 1, "L": -1}
    for p in layout_trains(cfg):
        out[p.track] = p.direction
    return out


def nameplate_aspect(ss, right_plus: bool) -> float:
    from signs.nameplate import render_nameplate
    img = render_nameplate(ss.style, nameplate_input(ss, right_plus))
    return img.width / img.height


def nameplate_input(ss, right_plus: bool):
    """역명판 이미지 입력: 보는 사람 오른쪽이 +s 면 오른쪽(next 자리) = +s 이웃 역"""
    from signs.nameplate import NameplateInput
    si = ss.station
    left, right = (si.minus, si.plus) if right_plus else (si.plus, si.minus)
    return NameplateInput(kname=si.kname, ename=si.ename, cname=si.cname, jname=si.jname, no=si.no, rgb=si.rgb,
                          prev=left, next=right)


def layout_signs(cfg) -> list:
    """SignPlacement 목록 (사인을 쓰지 않으면 빈 목록)"""
    ss = getattr(cfg, "sign_settings", None)
    if ss is None or not ss.enabled:
        return []
    st, pl = cfg.station, cfg.platform
    L, hw = st.length, st.width / 2.0
    out = []
    # ---- 역명판: 승강장 양쪽 측벽
    if pl.exists:
        ops = [o for o in cfg.wall_openings() if o[1] == 1]
        for side in (1, -1):
            normal = (0.0, -float(side))                           # 측벽에서 승강장 쪽
            right_plus = (-normal[1], normal[0])[0] > 0
            w = ss.plate_h * nameplate_aspect(ss, right_plus)
            k_max = int(max(0.0, (L / 2.0 - w / 2.0 - 0.5)) // ss.plate_interval)
            for k in range(-k_max, k_max + 1):
                s = L / 2.0 + k * ss.plate_interval
                face = _wall_face(cfg, 1, s, side)
                base, _ = floor_and_ceiling(cfg, 1, s, side * (face - 0.5))
                z0 = base + ss.plate_bottom
                if any(o[2] == side and o[3] < s + w / 2 and s - w / 2 < o[4] and o[5] < z0 + ss.plate_h and z0 < o[6]
                       for o in ops):
                    continue                                        # 출구통로·환기구 측벽 오프닝 자리
                tag = "L" if side > 0 else "R"
                out.append(SignPlacement(f"NP_{tag}_{sum(1 for p in out if p.name.startswith(f'NP_{tag}_')) + 1}",
                                         NAMEPLATE, 1, s, side * face, normal, w, ss.plate_h, ss.plate_t, z0, True,
                                         {"right_plus": right_plus}))
    # ---- 타는 곳: 승강장으로 내려가는 계단·에스컬레이터 위층 도착 끝
    if ss.boarding:
        dirs = _directions(cfg)
        ends = [(lay.name, lay.s_at(lay.length + ss.hang_offset), lay.spec.direction, sum(lay.t_range) / 2.0)
                for lay in cfg.stair_layouts() if lay.lower_floor == 1]
        ends += [(lay.name, lay.s_at(lay.u_range[1] + ss.hang_offset), lay.spec.direction, sum(lay.t_range) / 2.0)
                 for lay in cfg.escalator_layouts() if lay.lower_floor == 1]
        for name, s, d, t in ends:
            track = "L" if t > 0 else "R"
            dest = ss.dest_l if track == "L" else ss.dest_r
            base, _ = floor_and_ceiling(cfg, 2, s, t)
            out.append(SignPlacement(f"BD_{name}", BOARDING, 2, s, t, (float(d), 0.0), ss.hang_w, ss.hang_h, ss.hang_t,
                                     base + ss.hang_bottom, False, {"dest": dest, "track": track,
                                                                    "direction": dirs.get(track, 1)}))
    # ---- 출구: 출구통로 측벽 접합부 앞
    if ss.exits:
        info = {e.passage.strip(): e for e in ss.exit_info if e.passage.strip()}
        for k, lay in enumerate(cfg.passage_layouts(), start=1):
            _, n, side, s0, s1, _, _ = lay.wall_opening
            s = (s0 + s1) / 2.0
            t = side * (hw - ss.hang_offset)
            e = info.get(lay.name)
            number = (e.number.strip() if e and e.number.strip() else str(k))
            base, _ = floor_and_ceiling(cfg, n, s, t)
            out.append(SignPlacement(f"EX_{lay.name}", EXIT, n, s, t, (0.0, -float(side)), ss.hang_w, ss.hang_h,
                                     ss.hang_t, base + ss.hang_bottom, False,
                                     {"number": number, "destinations": e.destinations if e else ""}))
    return out


def _pos(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def check_signs(cfg):
    """사인 입력 검사 (ValueError): 치수, 스타일, 매달림 사인이 천장 아래, 역명판이 승강장층 천장 아래"""
    ss = getattr(cfg, "sign_settings", None)
    if ss is None or not ss.enabled:
        return
    from signs.nameplate import STYLES
    if ss.style not in STYLES:
        raise ValueError(f"사인: 역명판 스타일 '{ss.style}' 이(가) 없습니다 (가능: {', '.join(STYLES)})")
    for label, v in (("역명판 간격", ss.plate_interval), ("역명판 높이", ss.plate_h), ("역명판 두께", ss.plate_t),
                     ("매달림 사인 폭", ss.hang_w), ("매달림 사인 높이", ss.hang_h), ("매달림 사인 두께", ss.hang_t)):
        if not _pos(v):
            raise ValueError(f"사인: {label}은(는) 0보다 커야 합니다 ({v})")
    for label, v in (("역명판 하단 높이", ss.plate_bottom), ("매달림 사인 하단 높이", ss.hang_bottom),
                     ("매달림 사인 거리", ss.hang_offset)):
        if not (isinstance(v, (int, float)) and math.isfinite(v) and v >= 0):
            raise ValueError(f"사인: {label}은(는) 0 이상이어야 합니다 ({v})")
    for p in layout_signs(cfg):
        probe_t = p.t - p.normal[1] * 0.5 if p.mounted else p.t
        _, ceil = floor_and_ceiling(cfg, p.floor, p.s, probe_t)
        if p.z0 + p.height > ceil + 1e-3:
            raise ValueError(f"사인 {p.name}: 윗면(FL+{p.z0 + p.height:.3f})이 천장(FL+{ceil:.3f})보다 높습니다 "
                             "(하단 높이·사인 높이를 줄이세요)")
        if not (-1e-3 <= p.s - p.width / 2.0 and p.s + p.width / 2.0 <= cfg.station.length + 1e-3):
            raise ValueError(f"사인 {p.name}: 정거장 내공 길이 밖입니다 (s = {p.s:.2f})")
