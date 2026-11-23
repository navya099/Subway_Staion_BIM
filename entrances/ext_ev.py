"""출입구 외부 엘리베이터 (지하철 지상 노출 엘리베이터 — 서울시 2023 공공시설물 표준디자인 매뉴얼 + 외부 EV 표준도 070~073).

출입구에 붙음: 위치 = 출입구 좌표 (u = 이음면에서 진행 거리, t = 왼쪽 +), 지상 문 방향 face ('+u'|'-u'|'+t'|'-t' = 문 바깥 법선).
- 지하: RC 승강로 (외곽 = 지상 유리 박스 외곽, 벽 wall_t, 피트 pit_depth + 피트 슬래브) — 피트 바닥 ~ 지상 정지 바닥.
  지하 정지 바닥 = low_z (None = 붙은 통로 끝 바닥), 지하 문 = low_face (None = face) 쪽 RC 벽 출입구.
- 지상 정지 바닥 = 지표 + base_h (기단 윗면, 매뉴얼 GL+260).
- 지상 유리 박스 (매뉴얼 정·측면도, 높이 5,543): 정지 바닥부터 하부 금속 띠 sill → 하부 유리 low_glass → 캐노피 띠 band →
  상부 유리 up_glass → 줄눈 joint → 역명 띠 유리 sign_h → 환기 루버 louver → 지붕판 roof_t. 유리 바깥면 = 외곽, 두께 glass_t.
  모서리 각관 기둥 post (유리 안쪽, 정지 바닥 ~ 역명 띠 위) + 각관 테두리 보 (캐노피 띠 높이 · 역명 띠 위 끝).
- 입구 포털 (짙은 패널, 문 양옆 portal_l / portal_r · 문 위, 유리 바깥면 ~ RC 벽 안쪽 면 깊이) + 캐노피 판 (문 위, canopy_w × canopy_d).
- 역명 띠: 지상 문 면과 양옆 면 유리 안쪽에 사인 판 (앞면 이미지 = 노선 배지 + 역명, 출입구 사인 그림).
- 기단·경사로 (매뉴얼 기단부): 문 앞 평탄부 apron (지표 ~ 지상 정지 바닥) + 경사로 (기울기 1/ramp_ratio 로 지표까지),
  양옆 추락방지턱 curb_w × (면 + curb_h) + 난간 (기둥 + 위·아래 레일).
- 카·문: 내부 엘리베이터와 같은 함수 (elevator_layout.car_parts / landing_doors) — 애니메이션 대비 car_offset · door_open.
좌표: 출입구 좌표 띠 (Strip, s = u) 와 세계 좌표 조각 (HexaPiece: 경사로·난간처럼 기운 것).
"""
import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional

from elevators.elevator_layout import car_parts, car_z, landing_doors
from elevators.elevator_spec import ElevatorSpec
from elevators.elevator_type import ElevatorPartKind as K
from helper.box_piece import cut_faces_by_plane
from helper.strip_member import Strip
from openings import decompose

FACES = ("+u", "-u", "+t", "-t")
_EPS = 1e-6


@dataclass
class ExtEvSpec:
    """외부 엘리베이터 1대 (출입구에 붙음). 치수 기본값 = 서울시 2023 표준디자인 매뉴얼 · 외부 EV 표준도"""
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

    @property
    def axis(self) -> str:
        return self.face[1]

    @property
    def sign(self) -> int:
        return 1 if self.face[0] == "+" else -1

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


def layout_ext_ev(spec: ExtEvSpec, name: str, frame, G: float, zp: float) -> ExtEvLayout:
    """외부 엘리베이터 배치 (출입구 좌표). G = 지표, zp = 붙은 통로 끝 바닥"""
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
    for tag, a, sgn in faces:
        nrm, tan = face_box(a, sgn, w)
        holes = [(lmid - dw, lmid + dw, zl, zl + spec.door_h)] if (a, sgn) == (lax, lsg) else []
        for k, (v0, v1, z0, z1) in enumerate(decompose.subtract_rects((tan[0], tan[1], pit_top, Zs), holes), start=1):
            put(f"RC_WALL_{tag}", "RC_WALL", a, nrm, (v0, v1), z0, z1, k)

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
    inner_face = lambda a, sgn: ((U1 if sgn > 0 else U0) - sgn * w) if a == "s" else ((T1 if sgn > 0 else T0) - sgn * w)
    landing_doors(esp, rel, SimpleNamespace(level_name=lambda n: {1: "LOW", 2: "GND"}[n]), inner_face, box)

    # ---- 기단·경사로·추락방지턱·난간 (문 앞, 박스 폭)
    _approach(spec, frame, parts, box, (U0, U1, T0, T1), mid, G, Zs)
    return ExtEvLayout(name=name, spec=spec, parts=parts, stops=rel, car_z=zc, outer=(U0, U1, T0, T1))


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
    if spec.canopy_w > spec.width + 1e-9:
        raise ValueError(f"외부 엘리베이터 {name}: 캐노피 폭({spec.canopy_w:g}m)이 박스 폭보다 넓습니다")
