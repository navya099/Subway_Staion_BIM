"""3DFACE 만 가볍게 모으는 모델 공간 흉내 (웹 뷰어 자료용): ezdxf 문서를 만들지 않고 면 목록만 얻음.

엔진의 add_*_mesh(msp) 는 msp.add_3dface(점 목록, dxfattribs={"layer": …}) 만 쓰므로 그대로 넘길 수 있다. 돌려주는 FaceRef 는
3DFACE 처럼 `.dxf.handle / layer / vtx0~3` 를 가짐 (부재의 source_element 로 쓰임).
"""


class FaceRef:
    __slots__ = ("handle", "layer", "vtx0", "vtx1", "vtx2", "vtx3")

    def __init__(self, handle, layer, pts):
        self.handle, self.layer = handle, layer
        self.vtx0, self.vtx1, self.vtx2 = pts[0], pts[1], pts[2]
        self.vtx3 = pts[3] if len(pts) > 3 else pts[2]

    @property
    def dxf(self):
        return self

    def get(self, name, default=None):
        return getattr(self, name, default)

    @staticmethod
    def dxftype() -> str:
        return "3DFACE"


class FaceSink:
    """add_3dface 만 있는 모델 공간"""

    def __init__(self):
        self.faces: list[FaceRef] = []

    def add_3dface(self, points, dxfattribs=None):
        pts = [tuple(float(c) for c in p) for p in points]
        f = FaceRef(len(self.faces) + 1, (dxfattribs or {}).get("layer", "0"), pts)
        self.faces.append(f)
        return f
