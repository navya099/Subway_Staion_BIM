from config.master_config import StationProjectConfig
from helper.view_item import ViewItem
from passages.passage_data import PassageData, PassageElementData
from passages.passage_package import PassagePackage
from passages.passage_type import PassagePartKind

_FAMILY = {PassagePartKind.FLOOR: "콘크리트-통로바닥슬래브", PassagePartKind.ROOF: "콘크리트-통로천장슬래브",
           PassagePartKind.WALL: "콘크리트-통로벽체"}


def _dz_span(sect, w):
    """단면 다각형(부재 좌표 w, dz)을 연직선 w 로 자른 dz 구간 (없으면 None)"""
    ds = []
    n = len(sect)
    for i in range(n):
        (w0, d0), (w1, d1) = sect[i], sect[(i + 1) % n]
        if abs(w1 - w0) < 1e-12:
            if abs(w - w0) < 1e-9:
                ds += [d0, d1]
            continue
        if min(w0, w1) - 1e-9 <= w <= max(w0, w1) + 1e-9:
            ds.append(d0 + (d1 - d0) * (w - w0) / (w1 - w0))
    if not ds or max(ds) - min(ds) < 1e-9:
        return None
    return min(ds), max(ds)


class PassageEngine:
    """출구통로 BIM 객체(구간별 바닥·천장 슬래브, 측벽)를 만들고, 3D DXF / 2D 도면 / IFC 의 단일 데이터 원천이 된다.

    - 배치(통로 좌표계·부재 조각·측벽 오프닝)는 cfg.passage_layouts() 결과를 그대로 쓴다 (벽체 엔진과 같은 계산)
    - 3D·IFC 는 세계 좌표의 곧은 압출이라 곡선 선형에서도 정확하고, 2D 도면은 통로를 정거장 로컬 좌표로 옮겨 그린다
      (곡선 선형에서는 중심 STA 접선 기준 근사)
    """

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.passage_packages: list[PassagePackage] = []
        self._build()

    def _build(self):
        by_level: dict[str, PassagePackage] = {}
        for lay in self.cfg.passage_layouts():
            spec = lay.spec
            level = self.sp.level_name(lay.floor)
            package = by_level.setdefault(level, PassagePackage(level=level, package_id=f"PKG_{level}_PASSAGES"))
            elements = []
            for e in lay.elements:
                thick = {PassagePartKind.FLOOR: spec.floor_t, PassagePartKind.ROOF: spec.roof_t,
                         PassagePartKind.WALL: spec.wall_t}[e.kind]
                elements.append(PassageElementData(
                    name=f"{lay.name}_{e.code}", family_name=_FAMILY[e.kind], type_name=f"{int(round(thick * 1000))}mm",
                    level=level, pos_z=min(p.z_range[0] for p in e.pieces), material="Concrete_C24",
                    kind=e.kind, seg=e.seg, pieces=e.pieces))
            package.add_passage(PassageData(
                name=lay.name, family_name="출구통로",
                type_name=f"{spec.inner_width:g}x{spec.inner_height:g}" + (" L" if spec.bent else ""),
                level=level, pos_x=spec.s_center, pos_y=spec.side * lay.frame.t_face, pos_z=lay.z_floor,
                floor=lay.floor, side=spec.side, turn=spec.turn, s_center=spec.s_center, frame=lay.frame,
                bent=spec.bent, opening_name=f"OPEN_{lay.name}", elements=elements))
        floor_no = {self.sp.level_name(n): n for n in range(1, self.sp.floors + 1)}
        self.passage_packages = sorted(by_level.values(), key=lambda pk: floor_no[pk.level])

    def all_passages(self) -> list[PassageData]:
        return [p for pk in self.passage_packages for p in pk.passages]

    # ---------- 작도 ----------
    def add_passage_mesh(self, msp):
        """3D 절대 좌표계 메쉬 (조각마다 곧은 각기둥). 한 번만 호출할 것"""
        for ps in self.all_passages():
            for e in ps.elements:
                faces = [f for piece in e.pieces for f in piece.faces()]
                e.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_PASSAGE"}) for f in faces]

    # ---------- 2D 도면 (정거장 로컬 좌표로 옮겨 그림) ----------
    @staticmethod
    def _station_pt(frame, axis, a, w):
        X, Y = (a, w) if axis == "X" else (w, a)
        return frame.station(X, Y)

    def section_items(self, sta):
        """횡단면도: 측점 sta 의 면이 자르는 통로 부재. 첫 구간은 길이 방향으로, 꺾임 후 구간은 단면으로 잘림"""
        items = []
        for ps in self.all_passages():
            fr = ps.frame
            y_cut = (sta - fr.s_center) * fr.turn             # 절단면의 통로 Y 좌표
            labeled = False
            for e in ps.elements:
                for p in e.pieces:
                    axis, sect = p.local["axis"], p.local["sect"]
                    if axis == "X":                            # 첫 구간: 절단면이 축을 따라 자름 → (t, z) 사변형
                        span = _dz_span(sect, y_cut)
                        if span is None:
                            continue
                        lo, hi = span
                        (_, ta), (_, tb) = fr.station(p.a0, y_cut), fr.station(p.a1, y_cut)
                        pts = [(ta, p.z_ref(p.a0) + lo), (tb, p.z_ref(p.a1) + lo),
                               (tb, p.z_ref(p.a1) + hi), (ta, p.z_ref(p.a0) + hi)]
                    else:                                      # 꺾임 후 구간: 절단면이 축을 가로지름 → 단면 그대로
                        if not p.a0 - 1e-9 <= y_cut < p.a1 - 1e-9:
                            continue
                        z = p.z_ref(y_cut)
                        pts = [(fr.station(w, y_cut)[1], z + dz) for w, dz in sect]
                    label = None
                    if not labeled:
                        t_lab = max(x for x, _ in pts) if fr.side > 0 else min(x for x, _ in pts)
                        label = (ps.name, t_lab, max(z for _, z in pts) + 0.4, 0.4, "SEC_TEXT")
                        labeled = True
                    items.append(ViewItem(e.name, "SEC_CONCRETE", u0=min(x for x, _ in pts), u1=max(x for x, _ in pts),
                                          pts=pts, hatch_layer="SEC_HATCH", label=label))
        return items

    def plan_items(self, cut_h):
        """평면도(최하층 절단): 최하층에 붙은 통로의 절단 높이에 걸리는 벽 (정거장 로컬 좌표)"""
        items = []
        for ps in self.all_passages():
            if ps.floor != 1:
                continue
            fr = ps.frame
            s_lab, t_lab = fr.station(ps.elements[0].pieces[0].a1 * 0.5, 0.0)      # 첫 구간 중간, 통로 중심선
            label = (f"{ps.name} EXIT", s_lab - 1.0, t_lab, 0.5, "PLAN_TEXT")
            for e in ps.elements:
                if e.kind != PassagePartKind.WALL:
                    continue
                for p in e.pieces:
                    ws = [w for w, _ in p.local["sect"]]
                    corners = [self._station_pt(fr, p.local["axis"], a, w) for a, w in
                               ((p.a0, min(ws)), (p.a1, min(ws)), (p.a1, max(ws)), (p.a0, max(ws)))]
                    s_vals = [c[0] for c in corners]
                    t_vals = [c[1] for c in corners]
                    items.append(ViewItem.rect(e.name, "PLAN_PASSAGE", min(s_vals), max(s_vals), min(t_vals), max(t_vals),
                                               label=label))
                    label = None
        return items
