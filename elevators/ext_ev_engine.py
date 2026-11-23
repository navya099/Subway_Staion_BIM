import math
from dataclasses import dataclass, field
from typing import Optional

from bim_data.common_bim_data import CommonBIMData
from config.master_config import StationProjectConfig
from elevators import hall_fixture as HF
from elevators.elevator_engine import tri_faces
from helper.box_piece import cut_faces_by_plane
from helper.strip_member import StripShape, part_faces, strip_faces
from helper.view_item import ViewItem

# 부재 종류 → (재질, 3D 레이어, IFC (엔티티, 종류))
EXT_EV = {"RC_WALL": ("Concrete_C24", "STRUCT_ELEVATOR", ("IfcWall", "SOLIDWALL")),
          "PIT_SLAB": ("Concrete_C24", "STRUCT_ELEVATOR", ("IfcSlab", "BASESLAB")),
          "GLASS": ("EV_Glass", "STRUCT_ELEVATOR_GLASS", ("IfcPlate", "CURTAIN_PANEL")),
          "BAND": ("Stainless_Steel", "STRUCT_ELEVATOR_FRAME", ("IfcCovering", "CLADDING")),
          "POST": ("EV_Steel_Tube", "STRUCT_ELEVATOR_FRAME", ("IfcColumn", "COLUMN")),
          "BEAM": ("EV_Steel_Tube", "STRUCT_ELEVATOR_FRAME", ("IfcBeam", "BEAM")),
          "PORTAL": ("Portal_Panel", "STRUCT_ELEVATOR_FRAME", ("IfcCovering", "CLADDING")),
          "CANOPY": ("Canopy_Steel", "STRUCT_ELEVATOR_FRAME", ("IfcSlab", "ROOF")),
          "LOUVER": ("Stainless_Steel", "STRUCT_ELEVATOR_FRAME", ("IfcBuildingElementProxy", "USERDEFINED")),
          "ROOF": ("Stainless_Steel", "STRUCT_ELEVATOR_FRAME", ("IfcSlab", "ROOF")),
          "SIGN": ("Aluminium_Sign", "STRUCT_SIGN", ("IfcBuildingElementProxy", "USERDEFINED")),
          "SIGN_FACE": ("Aluminium_Sign", "STRUCT_SIGN_FACE", ("IfcBuildingElementProxy", "USERDEFINED")),
          "PODIUM": ("화강석", "FIN_FLOOR", ("IfcSlab", "FLOOR")),
          "RAMP": ("화강석", "FIN_FLOOR", ("IfcRampFlight", "STRAIGHT")),
          "CURB": ("화강석", "FIN_FLOOR", ("IfcBuildingElementPart", "USERDEFINED")),
          "RAIL": ("Stainless_Steel", "STRUCT_RAILING", ("IfcRailing", "HANDRAIL")),
          "LOW_FLOOR": ("화강석", "FIN_FLOOR", ("IfcCovering", "FLOORING")),
          "DOOR_FRAME": ("Stainless_Steel", "STRUCT_ELEVATOR_FRAME", ("IfcMember", "USERDEFINED")),
          "REVEAL": ("Stainless_Steel", "STRUCT_ELEVATOR_FRAME", ("IfcCovering", "CLADDING")),
          "SPIDER": ("Stainless_Steel", "STRUCT_ELEVATOR_FRAME", ("IfcDiscreteAccessory", "BRACKET")),
          "COLUMN": ("EV_Steel_Pipe", "STRUCT_ELEVATOR_FRAME", ("IfcColumn", "COLUMN")),
          "GIRT": ("EV_Steel_Pipe", "STRUCT_ELEVATOR_FRAME", ("IfcMember", "MEMBER")),
          "CALL_PANEL": ("Stainless_Steel", "STRUCT_ELEVATOR_FRAME", ("IfcUnitaryControlElement", "CONTROLPANEL")),
          "CALL_BUTTON": ("EV_Button", "STRUCT_ELEVATOR_FRAME", ("IfcSwitchingDevice", "MOMENTARYSWITCH")),
          "INDICATOR": ("EV_Indicator", "STRUCT_ELEVATOR_FRAME", ("IfcUnitaryControlElement", "INDICATORPANEL")),
          "LANDING_DOOR": ("Stainless_Steel", "STRUCT_ELEVATOR_FRAME", ("IfcDoor", "DOOR")),
          "CAR_FLOOR": ("Steel", "STRUCT_ELEVATOR_CAR", ("IfcBuildingElementPart", "USERDEFINED")),
          "CAR_WALL": ("Steel", "STRUCT_ELEVATOR_CAR", ("IfcBuildingElementPart", "USERDEFINED")),
          "CAR_GLASS": ("EV_Glass", "STRUCT_ELEVATOR_GLASS", ("IfcBuildingElementPart", "USERDEFINED")),
          "CAR_ROOF": ("Steel", "STRUCT_ELEVATOR_CAR", ("IfcBuildingElementPart", "USERDEFINED")),
          "CAR_DOOR": ("Steel", "STRUCT_ELEVATOR_CAR", ("IfcDoor", "DOOR"))}
CONCRETE = ("RC_WALL", "PIT_SLAB")


@dataclass
class ExtEvElementData(CommonBIMData):
    """외부 엘리베이터 부재 1개 (EV 좌표계 띠 + 세계 좌표 기운 조각)
    Attributes:
        kind / code: 부재 종류(EXT_EV) / 코드, t_range · shape: EV 좌표계 띠, pieces: HexaPiece (경사로·난간)
        slide / stop: 문짝 애니메이션 ((du, dt) 단위 방향, 최대 이동) / 승강장 문 층 (1 = 지하, 2 = 지상)
    """
    kind: str = ""
    code: str = ""
    t_range: tuple = (0.0, 0.0)
    shape: Optional[StripShape] = None
    pieces: list = field(default_factory=list)
    slide: tuple = None
    stop: int = None
    frame: object = None

    @property
    def volume(self) -> float:
        return (self.shape.volume if self.shape else 0.0) + sum(p.volume for p in self.pieces)

    @property
    def is_car(self) -> bool:
        return self.kind.startswith("CAR_")

    def faces(self) -> list:
        return [f for q in part_faces(self.frame, self) for f in q] + [f for p in self.pieces for f in p.faces()]


@dataclass
class ExtEvData(CommonBIMData):
    """외부 엘리베이터 1대 (IFC: IfcElementAssembly ELEVATOR ⊃ 승강로·박스·기단 부재 + IfcTransportElement 카).
    stops = {1: 지하, 2: 지상} 정지 바닥, car_z = 카 바닥 (애니메이션), travel = (지하, 지상), door_open = 문 열림 비율"""
    elements: list = field(default_factory=list)
    stops: dict = field(default_factory=dict)
    car_z: float = 0.0
    travel: tuple = (0.0, 0.0)
    door_open: float = 0.0
    layout: object = None
    frame: object = None


class ExtEvEngine:
    """외부 엘리베이터 BIM 객체 (통로·출입구와 별개) — 3D DXF / 횡단면도 / 통로 경로 종단 / IFC 의 단일 데이터 원천.
    배치는 cfg.ext_ev_layouts() 결과를 그대로 쓰고, 모든 부재는 EV 좌표계(세계 평면에서 곧음) 띠 또는 세계 좌표 조각"""

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.ext_evs: list[ExtEvData] = [self._data(x) for x in config.ext_ev_layouts()]

    def _data(self, xl) -> ExtEvData:
        level = self.sp.level_name(xl.floor)
        groups: dict = {}
        for p in xl.parts:
            groups.setdefault(p.code, []).append(p)
        els = []
        for code, ps in groups.items():
            # t 범위가 같은 조각은 한 부재, 다르면 조각마다 (이름 + 번호)
            sets = [ps] if len({p.t_range for p in ps}) == 1 else [[p] for p in ps]
            for j, grp in enumerate(sets, start=1):
                c = code if len(sets) == 1 else f"{code}_{j}"
                kind, tr = grp[0].kind, grp[0].t_range
                strips, pieces = [s for p in grp for s in p.strips], [h for p in grp for h in p.pieces]
                z0 = min([min(s.zb0, s.zb1) for s in strips] + [h.z_range[0] for h in pieces])
                els.append(ExtEvElementData(
                    name=f"{xl.name}_{c}", family_name=f"외부엘리베이터-{kind}", type_name=kind, level=level, pos_z=z0,
                    material=EXT_EV[kind][0], kind=kind, code=c, t_range=tr, shape=StripShape(strips=strips, width=tr[1] - tr[0]),
                    pieces=pieces, slide=grp[0].slide, stop=grp[0].stop, frame=xl.frame))
        return ExtEvData(name=xl.name, family_name="외부 엘리베이터", type_name="지상 노출 엘리베이터", level=level, pos_x=xl.spec.u,
                         pos_y=xl.spec.t, pos_z=xl.stops[1], elements=els, stops=xl.stops, car_z=xl.car_z,
                         travel=(xl.stops[1], xl.stops[2]), door_open=xl.spec.door_open, layout=xl, frame=xl.frame)

    # ---------- 작도 ----------
    def add_ext_ev_mesh(self, msp):
        """3D 메쉬. 한 번만 호출할 것"""
        for x in self.ext_evs:
            for e in x.elements:
                e.face_entities = []
                if e.kind == "SIGN" and len(e.shape.strips) == 2:      # ±u 면 사인: 본체 / 앞면 이미지 판 (띠 두 개)
                    body, face = part_faces(e.frame, e)
                    src = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SIGN"}) for f in body]
                    e.face_entities = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SIGN_FACE"}) for f in face]
                    e.source_element = src + e.face_entities
                    continue
                e.source_element = [msp.add_3dface(f, dxfattribs={"layer": EXT_EV[e.kind][1]}) for f in tri_faces(e.faces())]
                if e.kind == "SIGN_FACE":
                    e.face_entities = e.source_element

    def stop_labels(self, x: ExtEvData) -> dict:
        """정지 번호 → 층 이름 (지하 = 소속 층, 지상 = 1F)"""
        return {1: self.sp.level_name(x.layout.floor), 2: "1F"}

    def sign_images(self) -> list:
        """역명 띠 사인 [(재질 이름, PIL 이미지, uv 틀, 앞면 3DFACE 목록)] — add_ext_ev_mesh 뒤에 부를 것"""
        from signs.nameplate import render_entrance_sign
        from signs.sign_spec import StationInfo
        ss = getattr(self.cfg, "sign_settings", None)
        info = ss.station if ss is not None and getattr(ss, "station", None) is not None else StationInfo()
        out = []
        for x in self.ext_evs:
            fr, sp = x.frame, x.layout.spec
            label = self.stop_labels(x)[min(x.stops, key=lambda n: abs(x.stops[n] - x.car_z))]
            for e in x.elements:
                if e.kind in ("CALL_BUTTON", "INDICATOR"):         # 호출 버튼·층 표시기
                    _, axis, sign = HF.parse_code(e.code)
                    st = e.shape.strips[0]
                    nrm, tan = ((st.s0, st.s1), e.t_range) if axis == "s" else (e.t_range, (st.s0, st.s1))
                    frame = HF.front_frame(fr.to_world, axis, sign, nrm, tan, (st.zb0, st.zt))
                    out.append((f"사인 {e.name}", HF.fixture_image(e.code, label), frame, e.source_element))
                    continue
                if not getattr(e, "face_entities", None):
                    continue
                if e.kind == "SIGN":                               # ±u 면: 앞면 띠 = strips[1], 접선 = t
                    st, (a0, a1) = e.shape.strips[1], e.t_range
                    sgn = 1 if st.s1 > sp.u else -1
                    nx, ny = sgn * fr.ux, sgn * fr.uy
                    x0, y0 = fr.to_world(st.s1 if sgn > 0 else st.s0, a0 if sgn > 0 else a1)
                else:                                              # ±t 면: 앞면 부재 (t 범위 = 얇은 판), 접선 = u
                    st = e.shape.strips[0]
                    a0, a1 = st.s0, st.s1
                    sgn = 1 if e.t_range[0] > sp.t else -1
                    nx, ny = -sgn * fr.uy, sgn * fr.ux
                    x0, y0 = fr.to_world(a1 if sgn > 0 else a0, e.t_range[1] if sgn > 0 else e.t_range[0])
                w, h = a1 - a0, st.zt - st.zb0
                frame = ((x0, y0, st.zb0), (-ny, nx, 0.0), (0.0, 0.0, 1.0), w, h, 0.0)    # 앞에서 볼 때 오른쪽 = 법선 + 90°
                img = render_entrance_sign(w, h, sp.line_name, info.kname, info.ename, info.cname, info.jname, None, sp.sign_bg, info.rgb)
                out.append((f"사인 {e.name}", img, frame, e.face_entities))
        return out

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 의 연직면으로 정확히 자른 단면 (RC 는 해치, 나머지는 윤곽)"""
        cx, cy = self.cfg.to_world(sta, 0.0)
        th = self.cfg.theta_at(sta)
        nx, ny = math.cos(th), math.sin(th)
        items = []
        for x in self.ext_evs:
            labeled = False
            for e in x.elements:
                polys = [cut_faces_by_plane(strip_faces(e.frame, st, *e.t_range), cx, cy, nx, ny) for st in e.shape.strips]
                polys += [p.cut_by_plane(cx, cy, nx, ny) for p in e.pieces]
                for poly in polys:
                    if poly is None:
                        continue
                    label = None
                    if not labeled:
                        label = (x.name, min(w for w, _ in poly), max(z for _, z in poly) + 0.5, 0.4, "SEC_TEXT")
                        labeled = True
                    rc = e.kind in CONCRETE
                    items.append(ViewItem(e.name, "SEC_CONCRETE" if rc else "SEC_ELEVATOR", u0=min(w for w, _ in poly),
                                          u1=max(w for w, _ in poly), pts=poly, hatch_layer="SEC_HATCH" if rc else None, label=label))
        return items

    def path_items(self, x: ExtEvData, x0: float, t_off: float) -> list:
        """통로 경로 종단 (EV 좌표계 u 축 = 통로 구간·출입구 축, 종단 X = x0 + u): 절단면 t = t_off 를 지나면 절단(RC 해치),
        아니면 절단면 왼쪽(+t)에 있는 것만 너머 윤곽"""
        fr, items = x.frame, []
        px, py = fr.to_world(0.0, t_off)
        for e in x.elements:
            rc = e.kind in CONCRETE
            t0, t1 = e.t_range
            cut = t0 - 1e-9 <= t_off <= t1 + 1e-9
            layer = ("PROF_CONCRETE" if rc else "SEC_ELEVATOR") if cut else "PROF_BEYOND"
            if cut or t0 >= t_off:
                for st in e.shape.strips:
                    pts = [(x0 + st.s0, st.zb0), (x0 + st.s1, st.zb1), (x0 + st.s1, st.zt_end), (x0 + st.s0, st.zt)]
                    items.append(ViewItem(e.name, layer, u0=pts[0][0], u1=pts[1][0], pts=pts,
                                          hatch_layer="PROF_HATCH" if cut and rc else None))
            for p in e.pieces:
                poly = p.cut_by_plane(px, py, fr.uy, -fr.ux)
                if poly:
                    pts = [(x0 + w, z) for w, z in poly]
                    items.append(ViewItem(e.name, "SEC_ELEVATOR", u0=min(q[0] for q in pts), u1=max(q[0] for q in pts), pts=pts))
        return items
