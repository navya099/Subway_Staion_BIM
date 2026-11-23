"""통로 경로 종단 (경로를 따라 펼친 종단면 — 실무 도면 A-A 처럼 본체 접합부 ~ 출구통로 ~ 출입구).

도면 좌표 (X, Z): X = 통로 중심선을 따라 첫 꼭짓점(본체 외벽 접합점)에서 잰 거리(꺾여도 펼침), Z = 절대 표고.
- 절단면: 구간마다 그 구간 축을 품은 연직면을 중심선에서 t_off(진행방향 왼쪽 +)만큼 옮긴 면. 통로 부재·통로 마감은 BoxPiece 를
  그 면으로 정확히 자르고(`BoxPiece.cut_by_plane`), 출입구(통로 끝에 붙은 박스·계단·에스컬레이터·마감)는 출입구 좌표의 띠를 t = t_off 에서
  자름 (출입구 u 축 = 통로 마지막 구간 방향이라 같은 면).
- 잘리지 않는 부재는 '너머'(PROF_BEYOND) 윤곽 — 절단면보다 왼쪽(+t)에 있는 것만 (오른쪽은 가려 보이지 않는다고 봄).
- 레이어: 콘크리트 절단 = PROF_CONCRETE + 해치, 마감 = PROF_FINISH, 에스컬레이터 = PROF_ESCALATOR, 너머 = PROF_BEYOND, 지표 = PROF_CENTER.
"""
from helper.box_piece import _convex_hull
from helper.view_item import ViewItem

TOL = 1e-9


def _plane(seg_x, seg_y, ux, uy, t_off):
    """구간 축을 품은 연직면을 t_off 만큼 옮긴 면: (점 x, y, 법선 nx, ny) — cut_by_plane 의 w 가 축 방향(u)이 되도록 법선 = −v"""
    vx, vy = -uy, ux
    return seg_x + vx * t_off, seg_y + vy * t_off, uy, -ux


def _project(faces, px, py, ux, uy):
    """면 집합을 축 방향(u)·표고 평면에 투영한 볼록 외곽 [(w, z)]"""
    pts = [((p[0] - px) * ux + (p[1] - py) * uy, p[2]) for f in faces for p in f]
    return _convex_hull(pts)


def _side(faces, px, py, ux, uy):
    """면 집합의 왼쪽 거리(v) 범위"""
    vs = [-(p[0] - px) * uy + (p[1] - py) * ux for f in faces for p in f]
    return min(vs), max(vs)


def passage_profile_items(engine, name: str, t_off: float = 0.0) -> list:
    """통로 name (와 그 끝 출입구) 의 경로 종단 ViewItem 목록 (X = 펼친 거리, v = 절대 표고)"""
    cfg = engine.cfg
    lay = next((x for x in cfg.passage_layouts() if x.name == name), None)
    if lay is None:
        raise ValueError(f"통로 종단: 출구통로 '{name}' 이(가) 없습니다")
    chain, acc = [], 0.0
    for sg in lay.segments:
        chain.append(acc)
        acc += sg.length
    segs = {sg.index: sg for sg in lay.segments}
    items = []

    def add_piece(label, layer, piece, hatch, beyond=True):
        sg = segs.get(piece.local.get("seg", 0))
        if sg is None:
            return
        px, py, nx, ny = _plane(sg.x, sg.y, sg.ux, sg.uy, t_off)
        x0 = chain[sg.index]
        poly = piece.cut_by_plane(px, py, nx, ny)
        if poly:
            pts = [(x0 + w, z) for w, z in poly]
            items.append(ViewItem(label, layer, u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts,
                                  hatch_layer="PROF_HATCH" if hatch else None))
            return
        if not beyond:
            return
        faces = piece.faces()
        lo, _ = _side(faces, px, py, sg.ux, sg.uy)
        if lo < -TOL:                                      # 절단면 오른쪽(가려짐)에 걸치면 안 그림
            return
        hull = _project(faces, px, py, sg.ux, sg.uy)
        if hull and len(hull) >= 3:
            pts = [(x0 + w, z) for w, z in hull]
            items.append(ViewItem(label, "PROF_BEYOND", u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts))

    ps = next((p for p in engine.passages.all_passages() if p.name == name), None)
    for e in (ps.elements if ps is not None else []):
        for pc in e.pieces:
            add_piece(e.name, "PROF_CONCRETE", pc, True)
    pf = getattr(engine, "passage_finishes", None)
    for e in (pf.elements if pf is not None else []):
        if e.passage == name and e.code != "FRAME":
            for pc in e.pieces:
                add_piece(e.name, "PROF_FINISH", pc, False, beyond=False)
    label_z = max((max(z for _, z in it.pts) for it in items if it.pts), default=lay.z_floor + 3.0) + 1.0
    items.append(ViewItem(name, "PROF_TEXT", pts=[], label=(f"{name} EXIT PASSAGE", 0.0, label_z, 0.6, "PROF_TEXT")))

    # ---- 출입구 (통로 끝, 같은 축)
    ents = getattr(engine, "entrances", None)
    ent = next((e for e in (ents.entrances if ents is not None else []) if e.passage == name), None)
    if ent is not None:
        items += _entrance_items(engine, ent, acc, t_off)
    return items


def _entrance_items(engine, ent, x0: float, t_off: float) -> list:
    from entrances.entrance_data import EntranceElementData, EntranceFinishData
    from escalators.escalator_data import EscalatorPartData, EscalatorStepData
    from stairs.stair_data import StairFinishData
    items = []
    fr = ent.frame
    for name, m in engine.entrances.strip_members(ent):
        if isinstance(m, EntranceFinishData) and m.kind == "FRAME":
            continue
        t0, t1 = m.t_range
        cut = t0 - TOL <= t_off <= t1 + TOL
        fin = isinstance(m, (EntranceFinishData, StairFinishData)) or (isinstance(m, EntranceElementData) and m.kind in ("PAVE", "LANDFIN", "ARCH"))
        esc = isinstance(m, (EscalatorPartData, EscalatorStepData))
        if not cut and (fin or t0 < t_off):                # 너머: 절단면 왼쪽(+t) 부재만, 마감은 너머로 안 그림
            continue
        cp = isinstance(m, EntranceElementData) and (m.kind.startswith("CP_") or
                                                     (m.kind.startswith("EV_") and m.kind not in ("EV_RC_WALL", "EV_PIT_SLAB")))
        layer = ("PROF_FINISH" if fin else "PROF_ESCALATOR" if esc else "PROF_CONCRETE") if cut else "PROF_BEYOND"
        if cp and cut:
            layer = "SEC_SIGN" if m.kind == "CP_SIGN" else "SEC_RAILING"           # 캐노피·출구 사인 (윤곽)
        hatch = cut and not fin and not esc and not cp
        for st in m.shape.strips:
            pts = [(x0 + st.s0, st.zb0), (x0 + st.s1, st.zb1), (x0 + st.s1, st.zt_end), (x0 + st.s0, st.zt)]
            if max(abs(pts[3][1] - pts[0][1]), abs(pts[2][1] - pts[1][1])) < 1e-9:
                continue
            items.append(ViewItem(name, layer, u0=pts[0][0], u1=pts[1][0], pts=pts, hatch_layer="PROF_HATCH" if hatch else None))
        if isinstance(m, EntranceElementData):             # 천장 헌치 (세계 좌표 곧은 조각)
            px, py, nx, ny = _plane(fr.px, fr.py, fr.ux, fr.uy, t_off)
            for pc in m.pieces:
                poly = pc.cut_by_plane(px, py, nx, ny)
                if poly:
                    pts = [(x0 + w, z) for w, z in poly]
                    items.append(ViewItem(name, "PROF_CONCRETE", u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts,
                                          hatch_layer="PROF_HATCH"))
    lay = ent.layout
    u_end = lay.u["end"]
    items.append(ViewItem(f"{ent.name}_GL", "PROF_CENTER", pts=[(x0 + u_end - 15.0 if u_end > 15 else x0, lay.ground),
                                                                 (x0 + u_end + 5.0, lay.ground)]))
    items.append(ViewItem(ent.name, "PROF_TEXT", pts=[], label=(f"{ent.name} ENTRANCE  G.L {lay.ground:.3f}",
                                                                x0 + u_end - 10.0, lay.ground + 1.5, 0.6, "PROF_TEXT")))
    return items


def profile_bounds(items) -> tuple:
    """(X 최소, X 최대, Z 최소, Z 최대)"""
    pts = [p for it in items if it.pts for p in it.pts]
    if not pts:
        return 0.0, 1.0, 0.0, 1.0
    return min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts)


def path_axis_choices(cfg) -> list:
    """미리보기 종단 축 선택지 [(표시 이름, 통로 이름)] — 통로 경로 종단"""
    try:
        return [(f"통로 {x.name} 경로", x.name) for x in cfg.passage_layouts()]
    except (ValueError, AttributeError):
        return []


def parse_path_axis(text: str, cfg):
    """'통로 EX1 경로' 또는 '통로 EX1 경로 +0.98' → (통로 이름, t_off) / 통로 축이 아니면 None"""
    t = str(text).strip()
    for label, name in path_axis_choices(cfg):
        if t == label:
            return name, 0.0
        if t.startswith(label):
            rest = t[len(label):].strip()
            try:
                return name, float(rest)
            except ValueError:
                raise ValueError(f"통로 종단 축: '{label}' 뒤에는 중심선에서의 거리(m, 왼쪽 +)만 쓸 수 있습니다 ('{rest}')") from None
    return None


