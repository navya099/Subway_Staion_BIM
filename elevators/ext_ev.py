"""외부 엘리베이터 (지하철 지상 노출 엘리베이터 — 서울시 2023 공공시설물 표준디자인 매뉴얼 + 외부 EV 표준도 070~073).

통로·출입구와 별개인 독립 객체 (cfg.ext_evs). 위치 기준 host 세 가지 — 모두 자기 좌표계 (u, t) (세계 평면에서 곧음) 위에 놓임:
- 'station' : 정거장 (s, t) 직접 — 그 측점의 선형 접선 = u, 왼쪽 = t. 지하 정지 바닥 EL 을 입력
- 'entrance': 출입구 좌표 (u = 이음면에서 진행 거리, t = 왼쪽 +). 지하 정지 바닥 = 통로 끝 바닥 (입력 가능)
- 'passage' : 출구통로 옆 박스형 — 통로 중심선 거리 along + 쪽 host_side. EV 통로 쪽 면 = 통로 측벽 바깥면, 통로 측벽에 문 개구부,
              벽 공유 (EV 의 통로 쪽 RC 벽은 통로 벽 높이 구간을 비움). 지하 정지 바닥 = 그 자리 통로 바닥
지표 = ground_el (비우면 출입구 지표 / 통로에 붙은 출입구 지표 / 정거장 공통 지표).

- 지하: RC 승강로 (외곽 = 지상 유리 박스 외곽, 벽 wall_t, 피트 pit_depth + 피트 슬래브) — 피트 바닥 ~ 지상 정지 바닥.
- 지하 정면 마감 low_finish (지하 정지층): 'closed' 폐쇄형 = 문 + 스테인리스 문틀(개구부 두께 전체) | 'glass' 투시형 = 개구부를 승강로
  내공 폭 × low_open_h 로 넓히고 유리 정면(내부 투시형 EV 와 같은 유리 줄·문틀·스파이더), RC 박스는 그대로, 그 안에 강관 기둥 4개 + 가로재.
  출구통로 옆이면 통로 측벽 두께 속 개구부 둘레를 금속으로 감싸고(유리 정면 = 통로 벽 바깥면) 바닥 마감을 이음
- 지상 정지 바닥 = 지표 + base_h (기단 윗면, 매뉴얼 GL+260).
- 지상 유리 박스 (매뉴얼 정·측면도, 높이 5,543): 정지 바닥부터 하부 금속 띠 sill → 하부 유리 low_glass → 캐노피 띠 band →
  상부 유리 up_glass → 줄눈 joint → 역명 띠 유리 sign_h → 환기 루버 louver → 지붕판 roof_t. 유리 바깥면 = 외곽, 두께 glass_t.
  모서리 각관 기둥 post (유리 안쪽, 정지 바닥 ~ 역명 띠 위) + 각관 테두리 보 (캐노피 띠 높이 · 역명 띠 위 끝).
- 입구 포털 (짙은 패널, 문 양옆 portal_l / portal_r · 문 위, 유리 바깥면 ~ RC 벽 안쪽 면 깊이) + 캐노피 판 (문 위, canopy_w × canopy_d).
- 역명 띠: 지상 문 면과 양옆 면 유리 안쪽에 사인 판 (앞면 이미지 = 노선 배지 + 역명, 출입구 사인 그림).
- 기단·경사로 (매뉴얼 기단부): 문 앞 평탄부 apron (지표 ~ 지상 정지 바닥) + 경사로 (기울기 1/ramp_ratio 로 지표까지),
  양옆 추락방지턱 curb_w × (면 + curb_h) + 난간 (기둥 + 위·아래 레일).
- 카·문: 내부 엘리베이터와 같은 함수 (elevator_layout.car_parts / landing_doors) — 애니메이션 대비 car_offset · door_open.
"""
import dataclasses
import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional

from config.layout_cache import cached_layout
from elevators.elevator_layout import car_parts, car_z, landing_doors
from elevators.elevator_spec import ElevatorSpec
from elevators.elevator_type import ElevatorPartKind as K
from helper.box_piece import BoxPiece, cut_faces_by_plane
from helper.strip_member import Strip
from helper.vertical_prism import VerticalPrism, circle_points
from openings import decompose

FACES = ("+u", "-u", "+t", "-t")
HOSTS = ("station", "entrance", "passage")
LOW_FINISHES = ("closed", "glass")
LINING_T = 0.03                      # 투시형 개구부 둘레 금속 감싸기 두께 (통로 측벽 두께 속)
PIPE_GAP = 0.02                      # 강관 기둥 ↔ RC 박스 안쪽 면
_EPS = 1e-6


@dataclass
class ExtEvSpec:
    """외부 엘리베이터 1대 (독립 객체). 치수 기본값 = 서울시 2023 표준디자인 매뉴얼 · 외부 EV 표준도"""
    name: str = ""
    u: float = 0.0
    t: float = 0.0
    face: str = "+u"                 # 지상 문 방향 (바깥 법선)
    low_face: Optional[str] = None   # 지하 문 방향 (None = face)
    low_z: Optional[float] = None    # 지하 정지 바닥 절대 표고 (None = 붙은 통로 끝 바닥)
    width: float = 3.17              # 유리 박스 외곽: 지상 문 면과 나란 (매뉴얼 3,170)
    depth: float = 3.13              # 문 면에 직각 (매뉴얼 3,130)
    wall_t: float = 0.25             # 지하 RC 벽
    pit_depth: float = 1.7
    pit_slab_t: float = 0.6
    base_h: float = 0.26             # 기단 (지상 정지 바닥 = 지표 + base_h)
    glass_t: float = 0.0175          # T17.52 접합유리
    post: float = 0.15               # 각관 기둥·보 단면
    sill: float = 0.11
    low_glass: float = 2.33
    band: float = 0.085
    up_glass: float = 1.88
    joint: float = 0.01
    sign_h: float = 0.795
    louver: float = 0.3
    roof_t: float = 0.033
    portal_l: float = 0.15           # 문 왼쪽(접선 −) 포털 폭
    portal_r: float = 0.45           # 문 오른쪽(접선 +) 포털 폭 (호출 버튼 판 자리)
    canopy_w: float = 3.0
    canopy_d: float = 0.775
    canopy_t: float = 0.055
    apron: float = 1.5               # 문 앞 평탄부 길이
    ramp_ratio: float = 18.0         # 경사로 1/n
    curb_w: float = 0.2              # 추락방지턱 폭 / 면 위 높이
    curb_h: float = 0.08
    rail_h: float = 0.85             # 난간 높이 (면 위)
    door_w: float = 0.9
    door_h: float = 2.1
    car_width: float = 1.6
    car_depth: float = 1.4
    car_height: float = 2.3
    car_at: str = "ground"           # 카 정지: ground (지상) | low (지하)
    car_offset: float = 0.0
    door_open: float = 0.0
    host: str = "station"            # 위치 기준: station (정거장 s·t) | entrance (출입구 u·t) | passage (출구통로 옆, 벽 공유)
    host_name: str = ""              # 출입구 / 출구통로 이름 (하나뿐이면 비워도 됨)
    along: float = 0.0               # passage: 통로 첫 꼭짓점에서 중심선을 따라 잰 EV 중심 위치 (m, 수평 구간)
    host_side: int = 1               # passage: 통로 진행방향 왼쪽 +1 / 오른쪽 −1
    ground_el: Optional[float] = None   # 지표 절대 표고 (None = 출입구·정거장 공통 지표)
    line_name: str = ""              # 역명 띠 사인 노선명 / 배경색
    sign_bg: str = "#3C3F45"
    low_finish: str = "closed"       # 지하 정면: closed 폐쇄형 (문 + 문틀) | glass 투시형 (유리 정면 + 강관)
    door_frame_w: float = 0.1        # 지하 승강장 문틀 폭
    low_open_h: float = 2.6          # 투시형 개구부 높이 (지하 정지 바닥 기준, 통로 천장·헌치에 걸리면 그 아래까지)
    low_row: float = 1.37            # 투시형 유리 가로 줄눈 높이 (아래 줄 = 바닥 띠 ~ 줄눈, 위 줄 = 줄눈 ~ 개구부 위)
    low_base: float = 0.07           # 유리 아래 금속 띠 높이
    low_glass_t: float = 0.012
    col_d: float = 0.1398            # 강관 기둥 / 가로재 지름 (실무 표준도)
    girt_d: float = 0.0891
    spider: float = 0.1
    spider_d: float = 0.03

    @property
    def axis(self) -> str:
        return self.face[1]

    @property
    def sign(self) -> int:
        return 1 if self.face[0] == "+" else -1

    def low_half(self) -> float:
        """지하 문 면의 외곽 접선 반폭 (출구통로 옆은 늘 ±t 면)"""
        hu, ht = self.halves()
        return hu if self.host == "passage" or (self.low_face or self.face)[1] == "t" else ht

    def low_front(self) -> tuple:
        """지하 정면 개구부 (반폭, 정지 바닥에서의 높이)"""
        if self.low_finish == "glass":
            return self.low_half() - self.wall_t, self.low_open_h
        return self.door_w / 2.0 + self.door_frame_w, self.door_h + self.door_frame_w

    def halves(self) -> tuple:
        """(u 반폭, t 반폭)"""
        return (self.depth / 2.0, self.width / 2.0) if self.axis == "u" else (self.width / 2.0, self.depth / 2.0)

    def outer(self) -> tuple:
        hu, ht = self.halves()
        return (self.u - hu, self.u + hu, self.t - ht, self.t + ht)

    def footprint(self) -> tuple:
        """평면 외접 (박스 + 기단·경사로) (u0, u1, t0, t1)"""
        U0, U1, T0, T1 = self.outer()
        run = self.apron + self.base_h * self.ramp_ratio
        if self.axis == "u":
            return (U0, U1 + run, T0, T1) if self.sign > 0 else (U0 - run, U1, T0, T1)
        return (U0, U1, T0, T1 + run) if self.sign > 0 else (U0, U1, T0 - run, T1)


@dataclass
class ExtEvPart:
    code: str
    kind: str                        # ElevatorPartKind 이름 또는 외부 EV 고유 (RC_WALL / POST / BEAM / BAND / PORTAL / CANOPY / SIGN /
    #                                  LOUVER / ROOF / PODIUM / RAMP / CURB / RAIL)
    t_range: tuple
    strips: list
    pieces: list = field(default_factory=list)
    slide: tuple = None
    stop: int = None


@dataclass
class ExtEvLayout:
    name: str
    spec: ExtEvSpec
    parts: list
    stops: dict                      # 1 = 지하, 2 = 지상 → 정지 바닥 절대 표고
    car_z: float
    outer: tuple
    frame: object = None             # EV 좌표계 EntranceFrame
    floor: int = 1                   # 소속 층 (지하 정지)
    host: str = "station"
    host_name: str = ""              # 붙은 출입구·출구통로 이름
    ground: float = 0.0              # 지표 절대 표고


@dataclass
class HexaPiece:
    """세계 좌표 6면체 (아래 4점 + 위 4점, 같은 순서·반시계) — 기운 경사로·난간 레일. 면은 평면이 아닐 수 있어 삼각형으로"""
    bottom: list
    top: list

    def faces(self) -> list:
        b, t = self.bottom, self.top
        quads = [tuple(reversed(b)), tuple(t)] + [(b[i], b[(i + 1) % 4], t[(i + 1) % 4], t[i]) for i in range(4)]
        out = []
        for q in quads:
            out += [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
        return out

    @property
    def volume(self) -> float:
        v = 0.0
        for a, b, c in self.faces():
            v += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        return v

    @property
    def z_range(self) -> tuple:
        zs = [p[2] for p in self.bottom + self.top]
        return min(zs), max(zs)

    def cut_by_plane(self, px, py, nx, ny):
        return cut_faces_by_plane(self.faces(), px, py, nx, ny)


def _side(f: str) -> str:
    return ("+" if f[0] == "+" else "-") + ("s" if f[1] == "u" else "t")


def _pick(items, name: str, what: str, label: str):
    """이름으로 고름 (비우면 하나뿐일 때만)"""
    nm = name.strip()
    hit = [x for x in items if x.name == nm] if nm else (list(items) if len(items) == 1 else [])
    if not hit:
        raise ValueError(f"{what}: {label} '{nm}' 이(가) 없습니다" if nm else f"{what}: 기준이 될 {label} 이름을 입력하세요")
    return hit[0]


def passage_front(cfg, psp, spec: ExtEvSpec, what: str) -> tuple:
    """출구통로(psp) 옆 EV 의 지하 정면: (개구부를 통로에 맞춘 spec, 통로 바닥 마감 높이 ffl, 통로 벽 마감 표면 거리).
    통로 측벽·벽 마감 개구부 = low_front 반폭 × (통로 구조 바닥 ~ ffl + 높이)"""
    from passages.passage_finish import ceiling_fit, passage_finish_type
    ft = passage_finish_type(cfg, psp)
    ffl = ft.ffl if ft is not None else 0.0
    face = ft.face if ft is not None and ft.wall_t > 0 else 0.0
    spec = dataclasses.replace(spec, low_face="-t" if spec.host_side > 0 else "+t")
    if spec.low_finish == "glass":
        room = psp.inner_height - (psp.top_haunch_h if psp.top_haunch_w > 0 else 0.0) - ffl
        if ft is not None and ft.ceiling and ceiling_fit(psp, ft)[0]:
            room = min(room, ft.ceiling_h)
        spec = dataclasses.replace(spec, low_open_h=min(spec.low_open_h, room))
    if spec.low_front()[1] < spec.door_h + spec.door_frame_w - _EPS:
        raise ValueError(f"{what}: 출구통로 내공(천장·헌치 아래 {spec.low_front()[1]:.2f}m)이 문 높이 + 문틀"
                         f"({spec.door_h + spec.door_frame_w:.2f}m)보다 낮습니다")
    return spec, ffl, face


def place(cfg, spec: ExtEvSpec, name: str) -> SimpleNamespace:
    """위치 기준 풀기 → frame(EV 좌표계), spec(그 좌표계의 u·t·지하 문·지하 바닥), G(지표), zp(지하 바닥 기본), shared(벽 공유 높이),
    recess(통로 측벽 두께·벽 마감 표면 거리·바닥 마감 높이), floor(소속 층), host_name(붙은 출입구·통로 이름)"""
    from entrances.entrance_layout import EntranceFrame
    from passages.passage_layout import host_position
    what, st = f"외부 엘리베이터 {name}", cfg.station
    if spec.host == "passage":
        lay = _pick(cfg.passage_layouts(), spec.host_name, what, "출구통로")
        _, a, seg = host_position(lay, spec.along, what)
        G = spec.ground_el
        if G is None:                                              # 통로에 붙은 출입구의 지표 → 정거장 공통
            ent = next((e for e in cfg.entrances if (e.passage or "").strip() == lay.name), None)
            G = ent.ground_el if ent is not None and ent.ground_el is not None else st.ground_el
        spec, ffl, face = passage_front(cfg, lay.spec, spec, what)
        spec = dataclasses.replace(spec, u=a, t=spec.host_side * (lay.spec.half_out + spec.halves()[1]), low_z=seg.z + ffl)
        out = SimpleNamespace(frame=EntranceFrame(seg.x, seg.y, seg.ux, seg.uy), spec=spec, G=G, zp=seg.z + ffl, floor=lay.floor,
                              recess=(lay.spec.wall_t, face, ffl),
                              shared=(seg.z - lay.spec.floor_t, seg.z + lay.spec.inner_height + lay.spec.roof_t), host_name=lay.name)
    elif spec.host == "entrance":
        lay = _pick(cfg.entrance_layouts(), spec.host_name, what, "출입구")
        from passages.passage_finish import passage_finish_type
        pl = next(p for p in cfg.passage_layouts() if p.name == lay.passage)
        ft = passage_finish_type(cfg, pl.spec)                     # 지하 정지 바닥 = 통로 끝 바닥 마감면
        G = spec.ground_el if spec.ground_el is not None else lay.ground
        out = SimpleNamespace(frame=lay.frame, spec=spec, G=G, zp=lay.z_floor + (ft.ffl if ft is not None else 0.0),
                              floor=pl.floor, shared=None, recess=None, host_name=lay.name)
    else:
        if spec.low_z is None:
            raise ValueError(f"{what}: 정거장 좌표로 놓을 때는 지하 정지 바닥 EL 을 입력하세요")
        s0 = spec.u
        x, y = cfg.to_world(s0, 0.0)
        th = cfg.theta_at(s0)
        fl = cfg.lv(min(max(s0, 0.0), st.length)) - st.offset
        floor = max([n for n in range(1, st.floors + 1) if fl + st.floor_level(n) <= spec.low_z + 0.5] or [1])
        out = SimpleNamespace(frame=EntranceFrame(x, y, math.cos(th), math.sin(th)), spec=dataclasses.replace(spec, u=0.0),
                              G=spec.ground_el if spec.ground_el is not None else st.ground_el,
                              zp=spec.low_z, floor=floor, shared=None, recess=None, host_name="")
    if out.G is None:
        raise ValueError(f"{what}: 지표 EL 을 입력하세요 (외부 엘리베이터마다 또는 정거장 공통 지표 EL)")
    return out


def layout_ext_ev(spec: ExtEvSpec, name: str, frame, G: float, zp: float, shared=None, recess=None) -> ExtEvLayout:
    """외부 엘리베이터 배치 (frame 좌표). G = 지표, zp = 지하 정지 바닥 기본값 (spec.low_z 가 None 일 때).
    shared = (하면, 상면): 지하 문 면 RC 벽을 그 높이 구간에서 빼고 통로 측벽이 대신함 (벽 공유),
    recess = (통로 측벽 두께, 벽 마감 표면 거리, 바닥 마감 높이)"""
    U0, U1, T0, T1 = spec.outer()
    uc, tc = spec.u, spec.t
    w, gt, ps = spec.wall_t, spec.glass_t, spec.post
    zl = spec.low_z if spec.low_z is not None else zp
    Zs = G + spec.base_h
    if Zs - zl < spec.door_h + 0.5:
        raise ValueError(f"외부 엘리베이터 {name}: 지하 정지 바닥(EL {zl:.3f})이 지상 정지 바닥(EL {Zs:.3f})보다 충분히 낮지 않습니다")
    parts: list = []

    def box(code, kind, s0, s1, t0, t1, z0, z1, piece=0, slide=None, stop=None):
        if s1 - s0 > _EPS and t1 - t0 > _EPS and z1 - z0 > _EPS:
            kname = kind.name if isinstance(kind, K) else kind
            parts.append(ExtEvPart(code, kname, (t0, t1), [Strip(s0, s1, z0, z0, z1)], slide=slide, stop=stop))

    def put(code, kind, axis, nrm, tan, z0, z1, piece=0):
        if axis == "u":
            box(code, kind, nrm[0], nrm[1], tan[0], tan[1], z0, z1, piece)
        else:
            box(code, kind, tan[0], tan[1], nrm[0], nrm[1], z0, z1, piece)

    def face_box(axis, sign, d):
        """면 판 (바깥면 = 외곽, 두께 d): (법선 구간, 접선 구간). ±u 면이 t 외곽 전체, ±t 면은 그 사이"""
        if axis == "u":
            o = U1 if sign > 0 else U0
            return tuple(sorted((o, o - sign * d))), (T0, T1)
        o = T1 if sign > 0 else T0
        return tuple(sorted((o, o - sign * d))), (U0 + d, U1 - d)
    faces = [("PU", "u", 1), ("NU", "u", -1), ("PT", "t", 1), ("NT", "t", -1)]
    ax, sg = spec.axis, spec.sign
    mid = tc if ax == "u" else uc                                  # 문 중심 (접선 좌표)
    dw = spec.door_w / 2.0

    # ---- 지하 RC 승강로: 피트 슬래브 + 벽 (피트 바닥 ~ 지상 정지 바닥), 지하 문 면 출입구
    pit_top = zl - spec.pit_depth
    box("PIT", "PIT_SLAB", U0, U1, T0, T1, pit_top - spec.pit_slab_t, pit_top)
    lf = spec.low_face or spec.face
    lax, lsg = lf[1], 1 if lf[0] == "+" else -1
    lmid = tc if lax == "u" else uc
    lhalf, lh = spec.low_front()                                   # 지하 정면 개구부
    for tag, a, sgn in faces:
        nrm, tan = face_box(a, sgn, w)
        holes = [(lmid - lhalf, lmid + lhalf, zl, zl + lh)] if (a, sgn) == (lax, lsg) else []
        if shared is not None and (a, sgn) == (lax, lsg):            # 벽 공유: 통로 측벽 높이 구간은 비움
            holes = [(tan[0], tan[1], shared[0], shared[1])]
        for k, (v0, v1, z0, z1) in enumerate(decompose.subtract_rects((tan[0], tan[1], pit_top, Zs), holes), start=1):
            put(f"RC_WALL_{tag}", "RC_WALL", a, nrm, (v0, v1), z0, z1, k)

    _low_front(spec, frame, parts, put, face_box, (U0, U1, T0, T1), (lax, lsg, lmid), zl, (pit_top, Zs), recess)

    # ---- 지상 유리 박스 높이
    z_sill = Zs + spec.sill
    z_band = z_sill + spec.low_glass
    z_up = z_band + spec.band
    z_joint = z_up + spec.up_glass
    z_sign = z_joint + spec.joint
    z_lv = z_sign + spec.sign_h
    z_roof = z_lv + spec.louver
    pl, pr = spec.portal_l, spec.portal_r
    p0, p1 = mid - dw - pl, mid + dw + pr                           # 포털 + 문 (지상 문 면)
    for tag, a, sgn in faces:
        nrm, tan = face_box(a, sgn, gt)
        door_face = (a, sgn) == (ax, sg)
        low_tans = [(tan[0], p0), (p1, tan[1])] if door_face else [tan]
        for k, tr in enumerate(low_tans, start=1):
            put(f"GLASS_{tag}", "GLASS", a, nrm, tr, z_sill, z_band, k)          # 하부 유리
            bn, _ = face_box(a, sgn, gt)
            put(f"SILL_{tag}", "BAND", a, bn, tr, Zs, z_sill, k)                  # 하부 금속 띠
        put(f"GLASS_{tag}", "GLASS", a, nrm, tan, z_up, z_joint, 10)              # 상부 유리
        put(f"GLASS_{tag}", "GLASS", a, nrm, tan, z_sign, z_lv, 11)              # 역명 띠 유리
        put(f"BAND_{tag}", "BAND", a, nrm, tan, z_band, z_up, 0)                 # 캐노피 띠 (금속)
    # 모서리 각관 기둥 (유리 안쪽, 정지 바닥 ~ 역명 띠 위) + 테두리 보 (캐노피 띠 · 역명 띠 위)
    a0, a1 = U0 + gt, U1 - gt
    b0, b1 = T0 + gt, T1 - gt
    for su, (x0, x1) in (("N", (a0, a0 + ps)), ("P", (a1 - ps, a1))):
        for st_, (y0, y1) in (("N", (b0, b0 + ps)), ("P", (b1 - ps, b1))):
            box(f"POST_{su}{st_}", "POST", x0, x1, y0, y1, Zs, z_lv)
    for k, (zb0, zb1) in enumerate(((z_band, z_band + ps), (z_lv - ps, z_lv)), start=1):
        box("BEAM_PU", "BEAM", a1 - ps, a1, b0 + ps, b1 - ps, zb0, zb1, k)
        box("BEAM_NU", "BEAM", a0, a0 + ps, b0 + ps, b1 - ps, zb0, zb1, k)
        box("BEAM_PT", "BEAM", a0 + ps, a1 - ps, b1 - ps, b1, zb0, zb1, k)
        box("BEAM_NT", "BEAM", a0 + ps, a1 - ps, b0, b0 + ps, zb0, zb1, k)

    # ---- 입구 포털 (짙은 패널: 유리 바깥면 ~ RC 벽 안쪽 면 깊이) · 캐노피 판
    pn, _ = face_box(ax, sg, w)
    put("PORTAL", "PORTAL", ax, pn, (p0, mid - dw), Zs, z_band, 1)
    put("PORTAL", "PORTAL", ax, pn, (mid + dw, p1), Zs, z_band, 2)
    put("PORTAL", "PORTAL", ax, pn, (mid - dw, mid + dw), Zs + spec.door_h, z_band, 3)
    o = (U1 if sg > 0 else U0) if ax == "u" else (T1 if sg > 0 else T0)
    cn = tuple(sorted((o, o + sg * spec.canopy_d)))
    put("CANOPY", "CANOPY", ax, cn, (mid - spec.canopy_w / 2.0, mid + spec.canopy_w / 2.0), z_band, z_band + spec.canopy_t, 1)

    # ---- 역명 띠 사인 판 (지상 문 면 + 양옆 면, 유리 안쪽, 보 아래)
    signs = []
    for tag, a, sgn in faces:
        if a == ax and sgn != sg:
            continue                                               # 뒷면은 사인 없음
        nrm, tan = face_box(a, sgn, gt + 0.05)
        nrm = tuple(sorted((nrm[0], nrm[1])))
        sn = (nrm[0], nrm[0] + 0.05) if sgn > 0 else (nrm[1] - 0.05, nrm[1])
        lo_t, hi_t = tan[0] + gt + ps + 0.1, tan[1] - gt - ps - 0.1
        sz0, sz1 = z_sign + 0.08, z_lv - ps - 0.03
        if hi_t - lo_t > 0.5 and sz1 - sz0 > 0.2:
            face = 0.002
            fn = (sn[1] - face, sn[1]) if sgn > 0 else (sn[0], sn[0] + face)
            body = (sn[0], sn[1] - face) if sgn > 0 else (sn[0] + face, sn[1])
            code = f"SIGN_{tag}"
            if a == "u":
                strips = [Strip(body[0], body[1], sz0, sz0, sz1), Strip(fn[0], fn[1], sz0, sz0, sz1)]
                parts.append(ExtEvPart(code, "SIGN", (lo_t, hi_t), strips))
            else:                                                  # t 면: 본체·앞면이 t 로 나뉨 → 부재 두 개 (앞면 = _FACE)
                parts.append(ExtEvPart(code, "SIGN", body, [Strip(lo_t, hi_t, sz0, sz0, sz1)]))
                parts.append(ExtEvPart(code + "_FACE", "SIGN_FACE", fn, [Strip(lo_t, hi_t, sz0, sz0, sz1)]))
            signs.append(code)

    # ---- 환기 루버 (3단 날개, 바깥으로 0.03 내밈) · 지붕판
    for k in range(3):
        z0 = z_lv + 0.03 + k * (spec.louver - 0.1) / 2.0                   # 날개 0.04, 위·아래 0.03 여유
        z1 = z0 + 0.04
        for tag, a, sgn in faces:
            if a == "u":
                o_ = U1 if sgn > 0 else U0
                nrm, tan = tuple(sorted((o_ + sgn * 0.03, o_ - sgn * 0.1))), (T0 - 0.03, T1 + 0.03)
            else:
                o_ = T1 if sgn > 0 else T0
                nrm, tan = tuple(sorted((o_ + sgn * 0.03, o_ - sgn * 0.1))), (U0 + 0.1, U1 - 0.1)
            put(f"LOUVER_{tag}", "LOUVER", a, nrm, tan, z0, z1, k + 1)
    box("ROOF", "ROOF", U0 - 0.03, U1 + 0.03, T0 - 0.03, T1 + 0.03, z_roof, z_roof + spec.roof_t)

    # ---- 카·문 (내부 엘리베이터 함수: 출입구 좌표 s = u)
    inner = (U1 - U0 - 2 * w, T1 - T0 - 2 * w)
    esp = ElevatorSpec(lower_floor=1, upper_floor=2, car_floor=2 if spec.car_at == "ground" else 1, s_center=uc, t_center=tc,
                       inner_s=inner[0], inner_t=inner[1], wall_t=w, door_floors=[_side(lf), _side(spec.face)],
                       door_w=spec.door_w, door_h=spec.door_h, car_width=spec.car_width, car_depth=spec.car_depth,
                       car_height=spec.car_height, car_offset=spec.car_offset, door_open=spec.door_open)
    rel = {1: zl, 2: Zs}
    zc = car_z(esp, rel)
    if not zl - _EPS <= zc <= Zs + _EPS:
        raise ValueError(f"외부 엘리베이터 {name}: 카 위치가 운행 범위(지하 ~ 지상 정지 바닥) 밖입니다")
    car_parts(esp, zc, spec.door_open, box)
    def door_plane(d):
        return lambda a, sgn: ((U1 if sgn > 0 else U0) - sgn * d) if a == "s" else ((T1 if sgn > 0 else T0) - sgn * d)
    names = SimpleNamespace(level_name=lambda n: {1: "LOW", 2: "GND"}[n])
    # 지하 문: 투시형은 유리 안쪽 면, 폐쇄형은 RC 벽 안쪽 면 — 벽 공유면 EV 벽이 없으므로 통로 벽 바깥면(= EV 외곽)에 바로 붙임
    low_d = spec.low_glass_t if spec.low_finish == "glass" else 0.0 if shared is not None else w
    landing_doors(esp, rel, names, door_plane(low_d), box, floors=(1,))
    landing_doors(esp, rel, names, door_plane(w), box, floors=(2,))

    # ---- 기단·경사로·추락방지턱·난간 (문 앞, 박스 폭)
    _approach(spec, frame, parts, box, (U0, U1, T0, T1), mid, G, Zs)
    return ExtEvLayout(name=name, spec=spec, parts=parts, stops=rel, car_z=zc, outer=(U0, U1, T0, T1), frame=frame)


def _low_front(spec, frame, parts, put, face_box, outer, low, zl, zr, recess):
    """지하 정면 (지하 문 면 개구부): 폐쇄형 = 문틀, 투시형 = 유리 정면 + RC 박스 안 강관 기둥·가로재 (모듈 설명 참고)"""
    U0, U1, T0, T1 = outer
    ax, sg, mid = low
    half, h = spec.low_front()
    fw, dw, gt = spec.door_frame_w, spec.door_w / 2.0, spec.low_glass_t
    o = (U1 if sg > 0 else U0) if ax == "u" else (T1 if sg > 0 else T0)
    nrm = lambda d0, d1: tuple(sorted((o + sg * d0, o + sg * d1)))     # 외곽 면에서 바깥(+) 거리 구간
    glass = spec.low_finish == "glass"
    tw, face, ffl = recess if recess is not None else (0.0, 0.0, 0.0)
    if recess is not None and ffl > _EPS:                          # 통로 측벽 두께 속 바닥 (통로 바닥 마감에 이음)
        put("LOW_FLOOR", "LOW_FLOOR", ax, nrm(0.0, tw), (mid - half, mid + half), zl - ffl, zl)
    if not glass:                                                  # 폐쇄형 문틀: 개구부 두께 전체 (통로 옆 = 벽 마감 표면까지)
        n = nrm(0.0, tw + face) if recess is not None else nrm(-spec.wall_t, 0.0)
        put("LFRAME", "DOOR_FRAME", ax, n, (mid - half, mid - dw), zl, zl + h)
        put("LFRAME", "DOOR_FRAME", ax, n, (mid + dw, mid + half), zl, zl + h)
        put("LFRAME", "DOOR_FRAME", ax, n, (mid - dw, mid + dw), zl + spec.door_h, zl + h)
        return
    if recess is not None:                                         # 개구부 둘레 감싸기 (통로 벽 마감 표면까지)
        n, lt = nrm(0.0, tw + face), LINING_T
        put("LINING", "REVEAL", ax, n, (mid - half, mid - half + lt), zl, zl + h)
        put("LINING", "REVEAL", ax, n, (mid + half - lt, mid + half), zl, zl + h)
        put("LINING", "REVEAL", ax, n, (mid - half + lt, mid + half - lt), zl + h - lt, zl + h)
    gn = nrm(-gt, 0.0)                                             # 유리 정면 (바깥면 = 외곽 면)
    df = dw + fw
    for a0, a1 in ((mid - half, mid - df), (mid + df, mid + half)):
        put("LBASE", "BAND", ax, gn, (a0, a1), zl, zl + spec.low_base)
        put("LGLASS", "GLASS", ax, gn, (a0, a1), zl + spec.low_base, zl + spec.low_row)
        put("LGLASS", "GLASS", ax, gn, (a0, a1), zl + spec.low_row, zl + h)
    put("LFRAME", "DOOR_FRAME", ax, gn, (mid - df, mid - dw), zl, zl + h)          # 문틀 (양옆 + 문 위)
    put("LFRAME", "DOOR_FRAME", ax, gn, (mid + dw, mid + df), zl, zl + h)
    put("LFRAME", "DOOR_FRAME", ax, gn, (mid - dw, mid + dw), zl + spec.door_h, zl + h)
    sn, sp_ = nrm(-gt - spec.spider_d, -gt), spec.spider           # DPG 스파이더 (유리 안쪽 면, 바깥 모서리 줄)
    for ua in (mid - half, mid + half - sp_):
        for za in (zl + spec.low_base, zl + spec.low_row - sp_ / 2.0, zl + h - sp_):
            put("LSPIDER", "SPIDER", ax, sn, (ua, ua + sp_), za, za + sp_)
    # ---- RC 박스 안 강관 기둥 4개 (피트 바닥 ~ 지상 정지 바닥) + 가로재 (유리 줄눈·개구부 위 높이, 문 자리 끊김)
    r, rg = spec.col_d / 2.0, spec.girt_d / 2.0
    ci = spec.wall_t + PIPE_GAP + r / math.cos(math.pi / 16)
    cu, ct = (U0 + ci, U1 - ci), (T0 + ci, T1 - ci)
    ro = r / math.cos(math.pi / 16)
    for u, ua in zip(cu, "NP"):
        for t, ta in zip(ct, "NP"):
            x, y = frame.to_world(u, t)
            parts.append(ExtEvPart(f"LCOL_{ua}{ta}", "COLUMN", (t - ro, t + ro), [],
                                   pieces=[VerticalPrism(circle_points(x, y, r), zr[0], zr[1])]))
    sect0 = [(rg * math.cos(2 * math.pi * j / 12), rg * math.sin(2 * math.pi * j / 12)) for j in range(12)]
    for tag, a, sgn in (("PU", "u", 1), ("NU", "u", -1), ("PT", "t", 1), ("NT", "t", -1)):
        k = 1 if sgn > 0 else 0
        if a == "u":                                               # ±u 면: 축 = t 방향 (왼쪽 = −u)
            org, (dx, dy), rng = frame.to_world(cu[k], 0.0), (-frame.uy, frame.ux), (ct[0] + ro, ct[1] - ro)
            trng = rng
        else:
            org, (dx, dy), rng = frame.to_world(0.0, ct[k]), (frame.ux, frame.uy), (cu[0] + ro, cu[1] - ro)
            trng = (ct[k] - rg, ct[k] + rg)
        pcs = []
        for z in (zl + spec.low_row, zl + h):
            spans = [rng]
            if (a, sgn) == (ax, sg) and z < zl + h - _EPS:
                spans = [(rng[0], mid - df), (mid + df, rng[1])]
            pcs += [BoxPiece(ox=org[0], oy=org[1], ux=dx, uy=dy, a0=a0, a1=a1, sect=list(sect0), z0=z)
                    for a0, a1 in spans if a1 - a0 > _EPS]
        parts.append(ExtEvPart(f"LGIRT_{tag}", "GIRT", trng, [], pieces=pcs))


def _approach(spec, frame, parts, box, outer, mid, G, Zs):
    """문 앞 평탄부(기단) + 경사로 (기울기 1/ramp_ratio) + 양옆 추락방지턱 + 난간. 경사로는 방향이 ±t 일 수도 있어 세계 좌표 조각"""
    U0, U1, T0, T1 = outer
    ax, sg = spec.axis, spec.sign
    o = (U1 if sg > 0 else U0) if ax == "u" else (T1 if sg > 0 else T0)
    hw = spec.width / 2.0
    L = spec.base_h * spec.ramp_ratio
    cw, ch = spec.curb_w, spec.curb_h

    def pt(n, v, z):
        """(법선 거리 n (박스 바깥면에서 바깥 +), 접선 v, z) → 세계"""
        if ax == "u":
            x, y = frame.to_world(o + sg * n, v)
        else:
            x, y = frame.to_world(v, o + sg * n)
        return (x, y, z)

    def hexa(code, kind, n0, n1, v0, v1, zb0, zb1, zt0, zt1, piece=0):
        """법선 n0 < n1 · 접선 v0 < v1 사각 평면, 아래·위가 n 따라 선형 (n0 쪽 zb0/zt0, n1 쪽 zb1/zt1)"""
        corners = [(n0, v0), (n1, v0), (n1, v1), (n0, v1)]
        if (sg > 0) != (ax == "u"):                                # 세계에서 반시계가 되게
            corners = list(reversed(corners))
        bz = lambda n: zb0 + (zb1 - zb0) * (n - n0) / (n1 - n0)
        tz = lambda n: zt0 + (zt1 - zt0) * (n - n0) / (n1 - n0)
        hp = HexaPiece([pt(n, v, bz(n)) for n, v in corners], [pt(n, v, tz(n)) for n, v in corners])
        if hp.volume < 0:
            hp = HexaPiece(list(reversed(hp.bottom)), list(reversed(hp.top)))
        parts.append(ExtEvPart(code, kind, (v0, v1), [], pieces=[hp]))
    a0, a1 = mid - hw, mid + hw
    hexa("PODIUM", "PODIUM", 0.0, spec.apron, a0 + cw, a1 - cw, G, G, Zs, Zs)
    hexa("RAMP", "RAMP", spec.apron, spec.apron + L, a0 + cw, a1 - cw, G, G, Zs, G)
    n_end = spec.apron + L
    for k, (v0, v1) in enumerate(((a0, a0 + cw), (a1 - cw, a1)), start=1):          # 추락방지턱 (면 + curb_h)
        hexa("CURB", "CURB", 0.0, spec.apron, v0, v1, G, G, Zs + ch, Zs + ch, 2 * k - 1)
        hexa("CURB", "CURB", spec.apron, n_end, v0, v1, G, G, Zs + ch, G + ch, 2 * k)
        vc = (v0 + v1) / 2.0                                       # 난간: 턱 위 기둥 + 위·아래 레일
        top = lambda n: (Zs if n <= spec.apron else Zs - (n - spec.apron) / spec.ramp_ratio) + ch
        npost = max(2, math.ceil(n_end / 1.5) + 1)
        for j in range(npost):
            n = min(n_end - 0.025, max(0.025, n_end * j / (npost - 1)))
            hexa("RAIL", "RAIL", n - 0.025, n + 0.025, vc - 0.025, vc + 0.025, top(n), top(n), top(n) + spec.rail_h,
                 top(n) + spec.rail_h, 100 * k + j)
        rv = vc + (0.045 if k == 1 else -0.045)                    # 레일 = 기둥 안쪽(통로 쪽) 면에 붙음
        for h, tag in ((spec.rail_h, 1), (spec.rail_h - 0.2, 2)):
            for (na, nb) in ((0.0, spec.apron), (spec.apron, n_end)):
                zb0, zb1 = top(na) + h - 0.04, top(nb) + h - 0.04
                hexa("RAIL", "RAIL", na, nb, rv - 0.02, rv + 0.02, zb0, zb1, zb0 + 0.04, zb1 + 0.04, 1000 * k + tag)


def check_ext_ev(spec: ExtEvSpec, name: str):
    if spec.face not in FACES or (spec.low_face is not None and spec.low_face not in FACES):
        raise ValueError(f"외부 엘리베이터 {name}: 문 방향은 {', '.join(FACES)} 중 하나여야 합니다")
    for label, v in (("폭", spec.width), ("깊이", spec.depth), ("벽 두께", spec.wall_t), ("피트 깊이", spec.pit_depth),
                     ("기단 높이", spec.base_h), ("유리 두께", spec.glass_t), ("기둥", spec.post), ("문 폭", spec.door_w),
                     ("문 높이", spec.door_h), ("경사로 기울기", spec.ramp_ratio)):
        if not v > 0:
            raise ValueError(f"외부 엘리베이터 {name}: {label}은(는) 0 보다 커야 합니다 ({v})")
    face_len = spec.width
    if spec.door_w / 2.0 + max(spec.portal_l, spec.portal_r) + spec.post + spec.glass_t > face_len / 2.0 + _EPS:
        raise ValueError(f"외부 엘리베이터 {name}: 문 + 포털이 박스 폭({spec.width:g}m)에 비해 넓습니다")
    if spec.door_h > spec.sill + spec.low_glass - _EPS:
        raise ValueError(f"외부 엘리베이터 {name}: 문 높이가 하부 유리 높이보다 큽니다")
    inner_w = spec.width - 2 * spec.wall_t
    inner_d = spec.depth - 2 * spec.wall_t
    if spec.car_width + 0.1 > inner_w - 2 * 0.07 + _EPS or spec.car_depth + 0.2 > inner_d - 2 * 0.07 + _EPS:
        raise ValueError(f"외부 엘리베이터 {name}: 카({spec.car_width:g} × {spec.car_depth:g})가 승강로 내공"
                         f"({inner_w:.2f} × {inner_d:.2f})에 비해 큽니다")
    if spec.car_at not in ("ground", "low") or not 0.0 <= spec.door_open <= 1.0:
        raise ValueError(f"외부 엘리베이터 {name}: 카 정지(ground|low)·문 열림(0~1)이 올바르지 않습니다")
    if spec.low_finish not in LOW_FINISHES:
        raise ValueError(f"외부 엘리베이터 {name}: 지하 마감은 closed(폐쇄형) | glass(투시형) 이어야 합니다 ({spec.low_finish!r})")
    if not spec.door_frame_w > 0:
        raise ValueError(f"외부 엘리베이터 {name}: 문틀 폭은 0 보다 커야 합니다")
    half, h = spec.low_front()
    if half < spec.door_w / 2.0 + spec.door_frame_w - _EPS or half > spec.low_half() - spec.wall_t + _EPS:
        raise ValueError(f"외부 엘리베이터 {name}: 지하 문 + 문틀이 승강로 내공 폭에 비해 넓습니다")
    if spec.low_finish == "glass":
        for label, v in (("유리 두께", spec.low_glass_t), ("기둥 지름", spec.col_d), ("가로재 지름", spec.girt_d), ("스파이더", spec.spider),
                         ("스파이더 깊이", spec.spider_d)):
            if not v > 0:
                raise ValueError(f"외부 엘리베이터 {name}: 투시형 {label}은(는) 0 보다 커야 합니다 ({v})")
        if not spec.low_base + spec.spider < spec.low_row < h - spec.spider:
            raise ValueError(f"외부 엘리베이터 {name}: 유리 줄눈 높이({spec.low_row:g})가 개구부 높이({h:g}) 안에 있어야 합니다")
        if h < spec.door_h + spec.door_frame_w - _EPS:
            raise ValueError(f"외부 엘리베이터 {name}: 투시형 개구부 높이({h:g}m)가 문 높이 + 문틀보다 낮습니다")
        if spec.spider_d >= ElevatorSpec().door_gap - _EPS or spec.girt_d > spec.col_d + _EPS:
            raise ValueError(f"외부 엘리베이터 {name}: 스파이더 깊이는 승강장 문 띄움보다, 가로재는 기둥보다 작아야 합니다")
        room = spec.wall_t + PIPE_GAP + spec.col_d + 0.01
        if min(spec.width - 2 * room - spec.car_width, spec.depth - 2 * room - spec.car_depth) < 0.3:
            raise ValueError(f"외부 엘리베이터 {name}: 강관 기둥 안쪽이 카에 비해 좁습니다")
    if spec.host not in HOSTS:
        raise ValueError(f"외부 엘리베이터 {name}: 위치 기준은 {', '.join(HOSTS)} 중 하나여야 합니다 ({spec.host!r})")
    if spec.host == "passage" and (spec.host_side not in (1, -1) or spec.along < 0):
        raise ValueError(f"외부 엘리베이터 {name}: 통로 쪽(±1)·통로 거리(0 이상)가 올바르지 않습니다")
    if spec.canopy_w > spec.width + 1e-9:
        raise ValueError(f"외부 엘리베이터 {name}: 캐노피 폭({spec.canopy_w:g}m)이 박스 폭보다 넓습니다")


def ext_ev_names(cfg) -> list:
    """이름 확정 (비우면 OEV + 순번). 내부 엘리베이터와도 겹치면 오류"""
    from elevators.elevator_spec import resolve_elevator_names
    names = [(x.name or "").strip() or f"OEV{i}" for i, x in enumerate(cfg.ext_evs, start=1)]
    every = names + resolve_elevator_names(cfg.elevators)
    dup = sorted({n for n in names if every.count(n) > 1})
    if dup:
        raise ValueError(f"엘리베이터 이름이 중복됩니다: {', '.join(dup)}")
    return names


@cached_layout("ext_evs")
def layout_ext_evs(cfg) -> list:
    """외부 엘리베이터마다 ExtEvLayout (이름 확정 + 입력 검사 + 위치 기준 + 배치)"""
    out = []
    for i, spec in enumerate(cfg.ext_evs, start=1):
        if not isinstance(spec, ExtEvSpec):
            raise ValueError(f"외부 엘리베이터 {i}: 제원 형식이 올바르지 않습니다 ({spec!r})")
    for name, spec in zip(ext_ev_names(cfg), cfg.ext_evs):
        check_ext_ev(spec, name)
        pl = place(cfg, spec, name)
        lay = layout_ext_ev(pl.spec, name, pl.frame, pl.G, pl.zp, pl.shared, pl.recess)
        lay.floor, lay.host, lay.host_name, lay.ground = pl.floor, spec.host, pl.host_name, pl.G
        out.append(lay)
    return out
