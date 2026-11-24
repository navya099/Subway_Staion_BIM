"""출구통로·출입구 천장 기구 BIM 객체 (배치 corridor_layout): 기구 = 몸체 + 면, 세계 좌표 곧은 압출 BoxPiece (경사 천장은 기울어짐).

실 기구(FixtureEngine)와 같은 자료(FixtureData)·레이어·IFC·웹 뷰어 배치(instance)를 쓴다. rect = (a0, a1, v0, v1) 구간 틀의 수평 좌표.
"""
import math

from fixtures.fixture_engine import DIFFUSER, FACE_MATERIAL, LABELS, LAYERS, LIGHT, FixtureData
from fixtures.fixture_layout import CELL, FACE
from helper.box_piece import BoxPiece
from helper.view_item import ViewItem

_TAG = {LIGHT: "LT", DIFFUSER: "DF"}


class CorridorFixtureEngine:
    def __init__(self, config, passage_finishes, entrances):
        self.cfg = config
        self.elements: list[FixtureData] = []
        self.passage_finishes, self.entrances = passage_finishes, entrances
        st = config.station
        for lay in passage_finishes.layouts:
            base = st.level_name(lay.floor)
            for seg, cb, f in lay.fixtures:
                box = lambda d0, d1, f=f, seg=seg, cb=cb: BoxPiece(
                    seg.x, seg.y, seg.ux, seg.uy, f[1], f[2], _rect(f[3], f[4], cb + d0, cb + d1), seg.z + seg.slope * f[1], seg.slope)
                self._add(lay.name, lay.floor, base, f, box, seg.z + seg.slope * f[1] + cb, seg.slope)
        floors = {p.name: p.floor for p in config.passage_layouts()}
        for ent in entrances.entrances:
            lay = ent.layout
            fr = lay.frame
            floor = floors[lay.passage]
            for f in lay.fixtures:
                box = lambda d0, d1, f=f, fr=fr: BoxPiece(fr.px, fr.py, fr.ux, fr.uy, f[1], f[2], _rect(f[3], f[4], d0, d1), f[6], f[7])
                self._add(lay.name, floor, st.level_name(floor), f, box, f[6], f[7])

    def _add(self, host, floor, level, f, box, z, slope):
        kind, a0, a1, v0, v1, depth = f[:6]
        n = 1 + sum(e.host == host and e.kind == kind for e in self.elements)
        body, face = box(0.0, depth), box(-FACE[kind], 0.0)
        w, l = sorted((round((a1 - a0) * math.sqrt(1.0 + slope * slope), 3), round(v1 - v0, 3)))
        e = FixtureData(name=f"{_TAG[kind]}_{host}_{n:03d}", family_name="천장 기구", type_name=f"{LABELS[kind]} {w:g}x{l:g}", level=level,
                        material=FACE_MATERIAL[kind], pos_z=z, kind=kind, room=host, host=host, floor=floor, rect=(a0, a1, v0, v1), z=z,
                        along="s", depth=depth, body=body, face=face)
        e.pos_x, e.pos_y = body.point((a0 + a1) / 2.0, (v0 + v1) / 2.0, 0.0)[:2]
        self.elements.append(e)

    # ---------- 작도 ----------
    def add_fixture_mesh(self, msp):
        """3D 메쉬 (FIN_LIGHT / FIN_DIFFUSER). 한 번만 호출할 것"""
        for e in self.elements:
            add = lambda p: [msp.add_3dface(f, dxfattribs={"layer": LAYERS[e.kind]}) for f in p.faces()]
            e.body_entities, e.face_entities = add(e.body), add(e.face)
            e.source_element = e.body_entities + e.face_entities

    def frame(self, e) -> tuple:
        """면 아래쪽 이미지 한 장의 텍스처 틀 (원점, u = 짧은 방향 v, v = 축 방향, 폭, 수평 길이)"""
        a0, a1, v0, v1 = e.rect
        p = e.body
        o = p.point(a0, v0, 0.0)
        return (o[0], o[1], 0.0), (p.vx, p.vy, 0.0), (p.ux, p.uy, 0.0), v1 - v0, a1 - a0

    def instance(self, e) -> tuple:
        """웹 뷰어 배치: (x, y, z, cosθ, sinθ, 구배, 축척 1) — 기구 평면 중심·천장판 하면 기준, 축 방향 1m 당 구배만큼 오름"""
        a0, a1, v0, v1 = e.rect
        p = e.face
        x, y, z = p.point((a0 + a1) / 2.0, (v0 + v1) / 2.0, max(d for _, d in p.sect))
        return x, y, z, p.ux, p.uy, p.slope, 1.0

    def ceiling_frames(self, engine) -> dict:
        """기구가 있는 통로·출입구 천장판 면의 텍스처 틀: 이미지 격자를 배치 격자(구간 시작, 중심선 = 칸 가운데)에 맞춤"""
        from exporter.render_material import finish_material
        out = {}
        pf = self.passage_finishes
        for lay in pf.layouts:
            e = pf.element(lay.name, "CEILING")
            if not lay.fixtures or e is None or not e.source_element:
                continue
            m = finish_material(e.material)
            segs = {s.index: s for s, _, _ in lay.fixtures}
            i = 0
            for p in e.pieces:                                        # source_element 는 조각마다 faces() 순서
                n = len(p.faces())
                s = segs.get(p.local.get("seg"))
                if s is not None:
                    k = 1.0 / math.sqrt(1.0 + s.slope ** 2)
                    fr = _grid_frame(s.x, s.y, s.ux, s.uy, 0.0, m, k)
                    out.update({ent.dxf.handle: fr for ent in e.source_element[i:i + n]})
                i += n
        for ent in self.entrances.entrances:
            lay = ent.layout
            if not lay.fixtures:
                continue
            fr0 = lay.frame
            for fe in ent.finishes:
                if fe.kind != "CEILING" or not fe.source_element:
                    continue
                m = finish_material(fe.material)
                for x in fe.source_element:
                    d = x.dxf
                    us = [(d.get(f"vtx{j}")[0] - fr0.px) * fr0.ux + (d.get(f"vtx{j}")[1] - fr0.py) * fr0.uy for j in range(4)]
                    u0, sl = lay.ceiling_run(sum(us) / 4.0)
                    out[x.dxf.handle] = _grid_frame(fr0.px, fr0.py, fr0.ux, fr0.uy, u0, m, 1.0 / math.sqrt(1.0 + sl * sl))
        return out

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 의 연직면으로 자른 기구 윤곽"""
        x, y = self.cfg.to_world(sta, 0.0)
        th = self.cfg.theta_at(sta)
        nx, ny = math.cos(th), math.sin(th)
        items = []
        for e in self.elements:
            for p in (e.body, e.face):
                poly = p.cut_by_plane(x, y, nx, ny)
                if poly:
                    items.append(ViewItem(e.name, "SEC_FINISH", u0=min(w for w, _ in poly), u1=max(w for w, _ in poly), pts=poly))
        return items

    def plan_items(self, cut_h, floor=1):
        return []


def _rect(v0, v1, d0, d1):
    return [(v0, d0), (v1, d0), (v1, d1), (v0, d1)]


def _grid_frame(x, y, ux, uy, a0, m, k):
    """천장판 이미지 격자: 원점 = (a0, 칸 경계 v = −CELL/2), u = 축 방향(수평 투영 = 한 장 길이 × k), v = 왼쪽"""
    v0 = -CELL / 2.0
    return (x + a0 * ux - v0 * uy, y + a0 * uy + v0 * ux, 0.0), (ux, uy, 0.0), (-uy, ux, 0.0), m.size_u * k, m.size_v

