import dataclasses
from dataclasses import dataclass
from typing import Optional


@dataclass
class ViewItem:
    """2D 도면(횡단/평면/종단)에 그릴 부재 1개의 윤곽 정보. BIM 객체(벽체·슬래브·승강장·기둥)가 스스로 만들어 낸다.

    좌표는 도면 좌표 (u, v): 횡단 = (t, z), 종단 = (s, z), 평면 = (s, t).
    연직(v) 방향 변이 평행한 사각형/평행사변형: u0~u1 구간, 하단 vb0→vb1, 상단 vt0→vt1 (직사각형이면 vb0 == vb1, vt0 == vt1)
    """
    name: str
    layer: str
    u0: float = 0.0
    u1: float = 0.0
    vb0: float = 0.0
    vb1: float = 0.0
    vt0: float = 0.0
    vt1: float = 0.0
    circle: Optional[tuple] = None      # (cu, cv, r): 원형 (평면도의 원기둥)
    hatch_layer: Optional[str] = None   # 지정하면 절단면 해치 작도
    merge: bool = False                 # 같은 u 구간에서 위아래로 맞닿은 부재를 하나로 합침 (층별로 나뉜 벽체)
    label: Optional[tuple] = None       # (text, u, v, height, layer)

    @property
    def poly(self) -> list[tuple[float, float]]:
        return [(self.u0, self.vb0), (self.u1, self.vb1), (self.u1, self.vt1), (self.u0, self.vt0)]

    @staticmethod
    def rect(name, layer, u0, u1, v0, v1, **kw) -> "ViewItem":
        return ViewItem(name, layer, u0, u1, v0, v0, v1, v1, **kw)

    @staticmethod
    def sloped(name, layer, u0, u1, vb0, vb1, height, **kw) -> "ViewItem":
        return ViewItem(name, layer, u0, u1, vb0, vb1, vb0 + height, vb1 + height, **kw)


def merge_items(items: list[ViewItem], tol: float = 1e-6) -> list[ViewItem]:
    """merge=True 부재 중 같은 (레이어, u 구간)에서 위아래로 맞닿은 것을 합침"""
    out, groups = [], {}
    for it in items:
        if it.merge and it.circle is None:
            groups.setdefault((it.layer, round(it.u0, 6), round(it.u1, 6)), []).append(it)
        else:
            out.append(it)
    for group in groups.values():
        group.sort(key=lambda x: (x.vb0, x.vb1))
        cur = dataclasses.replace(group[0])
        for nxt in group[1:]:
            if abs(nxt.vb0 - cur.vt0) < tol and abs(nxt.vb1 - cur.vt1) < tol:
                cur.vt0, cur.vt1 = nxt.vt0, nxt.vt1
            else:
                out.append(cur)
                cur = dataclasses.replace(nxt)
        out.append(cur)
    return out


def draw_view_items(msp, items: list[ViewItem], du: float = 0.0):
    """ViewItem 목록을 DXF 모델스페이스에 작도. du = u 방향 평행 이동량 (횡단면도 배치용)"""
    for it in merge_items(items):
        if it.circle is not None:
            cu, cv, r = it.circle
            msp.add_circle((du + cu, cv), r, dxfattribs={'layer': it.layer})
        else:
            pts = [(du + u, v) for u, v in it.poly]
            msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': it.layer})
            if it.hatch_layer:
                hatch = msp.add_hatch(color=8, dxfattribs={'layer': it.hatch_layer})
                hatch.set_pattern_fill('ANSI31', scale=0.5)
                hatch.paths.add_polyline_path(pts)
        if it.label:
            text, u, v, h, layer = it.label
            msp.add_text(text, dxfattribs={'height': h, 'layer': layer}).set_placement((du + u, v))
