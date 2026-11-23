import math

from config.master_config import StationProjectConfig
from entrances.entrance_data import FINISH_LAYER, EntranceData, EntranceElementData, EntranceFinishData
from escalators.escalator_data import EscalatorData, EscalatorPartData, EscalatorStepData
from escalators.escalator_type import EscalatorPartKind
from helper.strip_member import Strip
from escalators.escalator_engine import _FAMILY as ESC_FAMILY, _MATERIAL as ESC_MATERIAL, _SIDE as ESC_SIDE
from helper.box_piece import cut_faces_by_plane
from helper.strip_member import StripShape, part_faces, strip_faces
from helper.view_item import ViewItem
from stairs.stair_data import StairData, StairFinishData, StairPartData
from stairs.stair_finish import CODES as FINISH_CODES
from stairs.stair_type import StairPartKind

_FAMILY = {"FLOOR": "콘크리트-출입구바닥슬래브", "ROOF": "콘크리트-출입구천장슬래브", "WALL": "콘크리트-출입구벽체",
           "LEAN": "콘크리트-버림", "RAMP": "콘크리트-출입구경사로", "STEPS": "콘크리트-출입구바깥계단",
           "PAVE": "출입구 앞마당 포장", "LANDING": "콘크리트-출입구승강구슬래브", "LANDFIN": "출입구 승강구 바닥 마감",
           "ARCH": "출입구 건축 마감 벽체"}
_CANOPY = {"CP_POST": ("출입구 캐노피 기둥", "Canopy_Steel"), "CP_BEAM": ("출입구 캐노피 보", "Canopy_Steel"),
           "CP_GLASS": ("출입구 캐노피 유리", "Canopy_Glass"), "CP_SIGN": ("출입구 출구 사인", "Aluminium_Sign"),
           "CP_WALL": ("출입구 캐노피 유리벽", "Canopy_Glass")}
_CANOPY_LAYER = {"CP_POST": "STRUCT_CANOPY", "CP_BEAM": "STRUCT_CANOPY", "CP_GLASS": "STRUCT_CANOPY_GLASS",
                 "CP_WALL": "STRUCT_CANOPY_GLASS"}


class EntranceEngine:
    """출입구 BIM 객체(박스 부재 + 계단 + 에스컬레이터)를 만들고, 3D DXF / 2D 도면 / IFC 의 단일 데이터 원천이 된다.

    - 배치는 cfg.entrance_layouts() 결과를 그대로 쓴다 (모든 부재는 출입구 좌표의 띠, 헌치는 세계 좌표 곧은 조각)
    - 출입구 좌표는 세계 평면에서 곧으므로 3D·IFC 는 곡선 선형에서도 정확하다
    - 횡단면도: 측점 sta 의 연직면으로 각 띠를 정확히 자른 다각형, 평면도: 최하층 통로에 붙은 출입구의 외곽
    """

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.entrances: list[EntranceData] = []
        self._build()

    def _build(self):
        floors = {p.name: p.floor for p in self.cfg.passage_layouts()}
        for lay in self.cfg.entrance_layouts():
            spec = lay.spec
            floor = floors[lay.passage]
            level = self.sp.level_name(floor)
            elements = []
            for p in lay.box_parts:
                t0, t1 = p.t_range
                elements.append(EntranceElementData(
                    name=f"{lay.name}_{p.code}", family_name=_FAMILY[p.kind],
                    type_name=f"{int(round((p.thick if p.thick is not None else spec.wall_t) * 1000))}mm",
                    level=level, pos_z=min(min(s.zb0, s.zb1) for s in p.strips),
                    material={"LEAN": "Lean_Concrete", "PAVE": spec.fc_material, "LANDFIN": spec.top_material,
                              "ARCH": spec.arch_material}.get(p.kind, "Concrete_C24"),
                    kind=p.kind, code=p.code, t_range=p.t_range, shape=StripShape(strips=p.strips, width=t1 - t0),
                    pieces=(list(lay.haunches) if p.code in ("ROOF", "ROOF_Z1") else []) + list(p.pieces)))
            stair = self._stair(lay, level) if lay.stair is not None else None
            fin_labels = {"FLOOR": "바닥 마감", "FILL": "바닥 채움", "WALL": "벽 마감", "CEILING": "천장판", "FRAME": "천장틀"}
            finishes = []
            for code, kind, mat, t_rng, strips in lay.finish:
                ft0, ft1 = t_rng
                finishes.append(EntranceFinishData(
                    name=f"{lay.name}_{code}", family_name="출입구 마감",
                    type_name=f"{lay.finish_type.name} {fin_labels[kind]}", level=level,
                    pos_z=min(min(s.zb0, s.zb1) for s in strips), material=mat, kind=kind, code=code, t_range=t_rng,
                    shape=StripShape(strips=strips, width=ft1 - ft0)))
            canopy = []
            for p in lay.canopy:
                fam, mat = _CANOPY[p.kind]
                ct0, ct1 = p.t_range
                canopy.append(EntranceElementData(
                    name=f"{lay.name}_{p.code}", family_name=fam, type_name=fam.split()[-1] if p.kind != "CP_SIGN" else "출구",
                    level=level, pos_z=min(min(s.zb0, s.zb1) for s in p.strips), material=mat, kind=p.kind, code=p.code,
                    t_range=p.t_range, shape=StripShape(strips=p.strips, width=ct1 - ct0)))
            number = self._exit_info(lay)
            n_esc = len(lay.escalators)
            escalators = [self._escalator(lay, level, e, k, n_esc) for k, e in enumerate(lay.escalators)]
            kinds = (["계단"] if lay.stair is not None else []) + ([f"ESC×{n_esc}" if n_esc > 1 else "ESC"] if n_esc else [])
            self.entrances.append(EntranceData(
                name=lay.name, family_name="출입구", type_name=f"W{spec.inner_width:g} " + "+".join(kinds),
                level=level, pos_x=lay.frame.px, pos_y=lay.frame.py, pos_z=lay.z_floor, passage=lay.passage, floor=floor,
                frame=lay.frame, layout=lay, elements=elements, stair=stair, escalator=escalators[0] if escalators else None,
                escalators=escalators, finishes=finishes, canopy=canopy, exit_number=number))

    def _exit_info(self, lay) -> str:
        """캐노피 출구 사인 번호: 출입구 입력 → 사인 설정 출구 안내(통로 이름) → 통로 순번"""
        spec = lay.spec
        ss = getattr(self.cfg, "sign_settings", None)
        info = {e.passage.strip(): e for e in (ss.exit_info if ss is not None else []) if e.passage.strip()}.get(lay.passage)
        names = [p.name for p in self.cfg.passage_layouts()]
        number = spec.exit_number.strip() or (info.number.strip() if info and info.number.strip() else "") or \
            str(names.index(lay.passage) + 1 if lay.passage in names else 1)
        return number

    def station_info(self):
        """출구 사인 역 정보 (사인 설정의 역 정보, 없으면 기본값)"""
        from signs.sign_spec import StationInfo
        ss = getattr(self.cfg, "sign_settings", None)
        return ss.station if ss is not None and getattr(ss, "station", None) is not None else StationInfo()

    def sign_images(self) -> list:
        """캐노피 출구 사인 [(재질 이름, PIL 이미지, uv 틀, 앞면 3DFACE 목록)] — DAE·웹 뷰어가 면에 한 장 맞춤. add_entrance_mesh 뒤에 부를 것"""
        from signs.nameplate import render_entrance_sign
        info = self.station_info()
        out = []
        for ent in self.entrances:
            for e in ent.canopy:
                if e.kind != "CP_SIGN" or not getattr(e, "face_entities", None):
                    continue
                st = e.shape.strips[1]
                t0, t1 = e.t_range
                w, h = t1 - t0, st.zt - st.zb0
                fr = ent.frame
                x0, y0 = fr.to_world(st.s1, t0)                       # 앞(+u)에서 볼 때 오른쪽 = +t, 왼쪽 아래 = (앞면, t0, 하단)
                frame = ((x0, y0, st.zb0), (-fr.uy, fr.ux, 0.0), (0.0, 0.0, 1.0), w, h, 0.0)
                sp = ent.layout.spec
                img = render_entrance_sign(w, h, sp.line_name, info.kname, info.ename, info.cname, info.jname, ent.exit_number,
                                           sp.sign_bg, info.rgb)
                out.append((f"사인 {e.name}", img, frame, e.face_entities))
        return out

    @staticmethod
    def _stair(lay, level) -> StairData:
        sp = lay.spec.stair_spec()
        t_rng = (sp.t_lo, sp.t_hi)
        parts, count = [], {StairPartKind.FLIGHT: 0, StairPartKind.LANDING: 0}
        for p in lay.stair.parts:
            p_rng = p.t_range if p.t_range is not None else t_rng      # 개구부 쪽 조각은 축소된 내공면까지
            count[p.kind] += 1
            flight = p.kind == StairPartKind.FLIGHT
            surfaces = [(lay.stair.start + ua, lay.stair.start + ub, zt) for ua, ub, zt in p.surfaces]
            parts.append(StairPartData(
                name=f"{lay.name}_STAIR_{p.kind.value}{count[p.kind]}",
                family_name="콘크리트-계단" if flight else "콘크리트-계단참",
                type_name=f"{p.n_risers}단" if flight else f"{int(round(sp.waist_t * 1000))}mm", level=level,
                pos_z=min(z for _, _, z in surfaces) if surfaces else lay.z_floor, material="Concrete_C24", kind=p.kind,
                n_risers=p.n_risers, n_treads=len(surfaces) if flight else 0, t_range=p_rng, surfaces=surfaces,
                shape=StripShape(strips=p.strips, width=p_rng[1] - p_rng[0])))
        finishes = []                                   # 계단 마감 (정거장 계단과 같은 계단석 분리 구조, 출입구 좌표의 띠)
        fin_t = {"TREAD": "tread_t", "RISER": "riser_t"}
        for k, f in enumerate(getattr(lay.stair, "finish", []) or [], start=1):
            fa, fb = f.t_range
            thick = getattr(lay.spec_stair_finish, fin_t[f.code]) if f.code in fin_t else (fb - fa if f.code == "SIDE" else None)
            finishes.append(StairFinishData(
                name=f"{lay.name}_STAIR_FIN_{f.code}_{k}", family_name=f"계단 {FINISH_CODES[f.code][0]}",
                type_name=f"{f.material} {int(round(thick * 1000))}mm" if thick else f.material, level=level,
                pos_z=min(min(st.zb0, st.zb1) for st in f.strips), material=f.material, code=f.code, t_range=f.t_range,
                shape=StripShape(strips=f.strips, width=fb - fa), columns=list(f.columns)))
        s0 = parts[0].shape.strips[0].s0
        s1 = parts[-1].shape.strips[-1].s1
        return StairData(name=f"{lay.name}_STAIR", family_name="콘크리트-직선계단",
                         type_name=f"{lay.stair.n_risers}단 R{lay.stair.riser * 1000:.0f} T{sp.tread * 1000:.0f}",
                         level=level, pos_z=lay.z_floor, material="Concrete_C24", lower_floor=0, direction=1,
                         n_risers=lay.stair.n_risers, riser=lay.stair.riser, tread=sp.tread, s_range=(s0, s1),
                         t_range=t_rng, parts=parts, finishes=finishes)

    @staticmethod
    def _escalator(lay, level, le, k=0, n=1) -> EscalatorData:
        """에스컬레이터 1대 (le = 배치 결과). 이름 {출입구}_ESC (1대) / {출입구}_ESC{k} (여러 대, 칸막이벽 쪽부터 1)"""
        esp = le.spec
        tag = "ESC" if n <= 1 else f"ESC{k + 1}"
        parts = []
        for p in le.parts:
            t0, t1 = p.t_range
            parts.append(EscalatorPartData(
                name=f"{lay.name}_{tag}_{p.kind.value}{ESC_SIDE[p.side]}", family_name=ESC_FAMILY[p.kind],
                type_name=f"S{int(round(esp.step_width * 1000))} {esp.angle_deg:g}°", level=level,
                pos_z=min(min(s.zb0, s.zb1) for s in p.strips), material=ESC_MATERIAL[p.kind], kind=p.kind,
                side=p.side, t_range=p.t_range, shape=StripShape(strips=p.strips, width=t1 - t0)))
        st0, st1 = esp.t_center - esp.step_width / 2.0, esp.t_center + esp.step_width / 2.0
        steps = []
        for stp in getattr(le, "steps", []):                        # 개별 스텝 (위 운행로) — 출입구 좌표 s = u_wp + u
            strips = sorted((Strip(le.u_wp + ua, le.u_wp + ub, zb, zb, zt) for ua, ub, zb, zt in stp.pieces),
                            key=lambda x: x.s0)
            steps.append(EscalatorStepData(
                name=f"{lay.name}_{tag}_STEP{stp.index + 1:03d}", family_name="에스컬레이터-스텝",
                type_name=f"S{int(round(esp.step_width * 1000))} 스텝", level=level, pos_z=stp.z,
                material=ESC_MATERIAL[EscalatorPartKind.STEPS], index=stp.index, chain_u=stp.u, t_range=(st0, st1),
                shape=StripShape(strips=strips, width=st1 - st0)))
        u = lay.u
        return EscalatorData(name=f"{lay.name}_{tag}", family_name="에스컬레이터",
                             type_name=f"S{int(round(esp.step_width * 1000))} {esp.angle_deg:g}°", level=level,
                             pos_z=lay.z_floor, lower_floor=0, direction=1, angle_deg=esp.angle_deg,
                             rise=le.rise, run=le.run, s_wp=(u["wp_lo"], u["wp_hi"]),
                             s_range=(u["truss_lo"], u["truss_hi"]), t_range=(esp.t_lo, esp.t_hi), parts=parts, steps=steps)

    # ---------- 부재 모음 ----------
    def strip_members(self, ent: EntranceData) -> list:
        """(부재 이름, 띠 부재) — 박스 부재·계단 런/계단참·에스컬레이터 부재 (모두 출입구 좌표의 띠)"""
        out = [(e.name, e) for e in ent.elements]
        if ent.stair is not None:
            out += [(p.name, p) for p in ent.stair.parts] + [(f.name, f) for f in ent.stair.finishes]
        out += [(f.name, f) for f in ent.finishes]
        out += [(c.name, c) for c in ent.canopy]
        for esc in ent.escalators:
            out += [(p.name, p) for p in esc.parts] + [(s.name, s) for s in esc.steps]
        return out

    # ---------- 작도 ----------
    def add_entrance_mesh(self, msp):
        """3D 절대 좌표계 메쉬 (출입구 좌표의 곧은 띠 + 헌치 조각). 한 번만 호출할 것"""
        for ent in self.entrances:
            for _, m in self.strip_members(ent):
                faces = [f for quads in part_faces(ent.frame, m) for f in quads]
                faces += [f for p in getattr(m, "pieces", []) for f in p.faces()]
                layer = "STRUCT_ENTRANCE"                              # 박스·계단 = 콘크리트, 에스컬레이터 = 정거장 에스컬레이터와 같은 레이어
                if isinstance(m, StairFinishData):
                    layer = "FIN_STAIR"
                if isinstance(m, EntranceElementData) and m.kind in FINISH_LAYER:
                    layer = FINISH_LAYER[m.kind]                        # 앞마당 포장·승강구 바닥 마감 / 건축 마감 벽체
                if isinstance(m, EntranceElementData) and m.kind in _CANOPY_LAYER:
                    layer = _CANOPY_LAYER[m.kind]                      # 캐노피 철골 / 유리
                if isinstance(m, EntranceElementData) and m.kind == "CP_SIGN":   # 출구 사인: 본체 / 앞면 이미지 판
                    quads = part_faces(ent.frame, m)
                    body = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SIGN"}) for f in quads[0]]
                    m.face_entities = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SIGN_FACE"}) for f in quads[1]]
                    m.source_element = body + m.face_entities
                    continue                                 # 계단 마감 = 정거장 계단 마감과 같은 레이어
                if isinstance(m, EntranceFinishData):                    # 내부 마감 = 실 마감과 같은 레이어
                    layer = {"FLOOR": "FIN_FLOOR", "FILL": "FIN_FLOOR", "WALL": "FIN_WALL", "CEILING": "FIN_CEILING",
                             "FRAME": "FIN_FRAME"}[m.kind]
                if isinstance(m, (EscalatorPartData, EscalatorStepData)):
                    glass = getattr(m, "kind", None) == EscalatorPartKind.BALUSTRADE and m.material == "Glass_Balustrade"
                    layer = "STRUCT_ESC_GLASS" if glass else "STRUCT_ESCALATOR"
                m.source_element = [msp.add_3dface(f, dxfattribs={"layer": layer}) for f in faces]
            if ent.escalator:
                self._step_frames(ent)
            self._tread_frames(ent)

    @staticmethod
    def _tread_frames(ent):
        """계단 디딤판(계단석·디딤판 판석) 윗면에 계단석 이미지 한 장씩 (정거장 StairEngine._tread_frames 와 같은 규약, 출입구 좌표:
        u = +t, v = 앞 코 → 안쪽, 한 장 폭 = 계단 폭을 stone_len 에 가깝게 고르게 나눔, 계단참은 일반 타일)"""
        from stairs.stair_engine import TREAD_TEXTURE_CODES
        fr_ = ent.frame
        tv, uv = (-fr_.uy, fr_.ux, 0.0), (fr_.ux, fr_.uy, 0.0)
        stone = ent.layout.spec_stair_finish.stone_len if ent.layout.spec_stair_finish is not None else 1.2
        for fe in (ent.stair.finishes if ent.stair is not None else []):
            fe.face_frames = {}
            if fe.code not in TREAD_TEXTURE_CODES:
                continue
            n_faces = [len(q) for q in part_faces(fr_, fe)]
            a = 0
            for strip, nf in zip(fe.shape.strips, n_faces):
                mid = (strip.s0 + strip.s1) / 2.0
                col = next((c for c in fe.columns if c[0] - 1e-9 <= mid <= c[1] + 1e-9), None)
                if col is not None and not col[5]:
                    s0, s1, nose, t0, t1, _ = col
                    o = fr_.to_world(nose, t0)
                    pieces = max(1, round((t1 - t0) / stone))
                    frame = ((o[0], o[1], 0.0), tv, uv, (t1 - t0) / pieces, s1 - s0)
                    fe.face_frames.update({e.dxf.handle: frame for e in fe.source_element[a:a + nf]})
                a += nf

    @staticmethod
    def _step_frames(ent):
        """스텝마다 디딤판 윗면 텍스처 틀 (정거장 EscalatorEngine._step_frames 와 같은 규약, 출입구 좌표)"""
        fr_ = ent.frame
        u_wp = ent.layout.escalator.u_wp
        dep = ent.layout.escalator.spec.step_depth
        uv = (fr_.ux, fr_.uy, 0.0)
        tv = (-fr_.uy, fr_.ux, 0.0)                                   # +t (왼쪽)
        for stp in (s for esc in ent.escalators for s in esc.steps):
            t0, t1 = stp.t_range
            o = fr_.to_world(u_wp + stp.chain_u, t0)
            frame = ((o[0], o[1], 0.0), tv, uv, t1 - t0, dep)
            n_faces = [len(q) for q in part_faces(fr_, stp)]
            tread = max(range(len(stp.shape.strips)), key=lambda i: stp.shape.strips[i].s1 - stp.shape.strips[i].s0)
            a = sum(n_faces[:tread])
            stp.face_frames = {e.dxf.handle: frame for e in stp.source_element[a:a + n_faces[tread]]}

    def section_items(self, sta):
        """횡단면도: 측점 sta 의 연직면으로 자른 출입구 부재 단면 (콘크리트는 해치, 설비는 윤곽만)"""
        cx, cy = self.cfg.to_world(sta, 0.0)
        th = self.cfg.theta_at(sta)
        nx, ny = math.cos(th), math.sin(th)
        items = []
        for ent in self.entrances:
            labeled = False
            for name, m in self.strip_members(ent):
                if isinstance(m, EntranceFinishData) and m.kind == "FRAME":
                    continue                                    # 천장틀은 단면에 안 그림
                pave = isinstance(m, EntranceElementData) and m.kind in FINISH_LAYER
                cp = isinstance(m, EntranceElementData) and m.kind.startswith("CP_")
                concrete = not pave and not cp and not isinstance(m, (EscalatorPartData, EscalatorStepData, StairFinishData,
                                                                      EntranceFinishData))
                fin_layer = pave or isinstance(m, (StairFinishData, EntranceFinishData))
                t0, t1 = m.t_range
                polys = [cut_faces_by_plane(strip_faces(ent.frame, st, t0, t1), cx, cy, nx, ny) for st in m.shape.strips]
                polys += [p.cut_by_plane(cx, cy, nx, ny) for p in getattr(m, "pieces", [])]
                for poly in polys:
                    if poly is None:
                        continue
                    label = None
                    if not labeled:
                        label = (ent.name, min(w for w, _ in poly), max(z for _, z in poly) + 0.5, 0.4, "SEC_TEXT")
                        labeled = True
                    layer = "SEC_CONCRETE" if concrete else ("SEC_FINISH" if fin_layer else "SEC_ESCALATOR")
                    if cp:
                        layer = "SEC_SIGN" if m.kind == "CP_SIGN" else "SEC_RAILING"
                    items.append(ViewItem(name, layer,
                                          u0=min(w for w, _ in poly), u1=max(w for w, _ in poly), pts=poly,
                                          hatch_layer="SEC_HATCH" if concrete else None, label=label))
        return items
