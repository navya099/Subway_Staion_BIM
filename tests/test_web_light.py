"""웹 뷰어 경량화 테스트: DXF 없는 3D 면 모으기, 맞닿아 가려진 면 빼기, 측점 표본 재사용, 빠른 광선 검사, 얇은 칸막이벽 조각"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gzip

import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from exporter.mesh_reduce import hidden_faces
from exporter.web_viewer import build_web_data
from preview.preview_render import centerline_samples
from test_patch import make_cfg


def quad(x0, x1, y0, y1, z=0.0, up=True):
    p = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
    return p if up else p[::-1]


def hid(faces, keys=None):
    return hidden_faces(faces, keys or [0] * len(faces)).tolist()


@pytest.mark.parametrize("faces, keys, want", [
    ([quad(0, 1, 0, 1), quad(0, 1, 0, 1, up=False)], None, [True, True]),                  # 똑같이 맞닿음 → 둘 다
    ([quad(0, 4, 0, 4), quad(1, 2, 1, 2, up=False)], None, [False, True]),                 # 안에 들어간 쪽만
    ([quad(0, 1, 0, 1), quad(0.5, 1.5, 0, 1, up=False)], None, [False, False]),            # 일부만 겹침 → 그대로
    ([quad(0, 1, 0, 1), quad(0, 1, 0, 1)], None, [False, False]),                          # 같은 쪽을 봄
    ([quad(0, 1, 0, 1), quad(0, 1, 0, 1, z=0.01, up=False)], None, [False, False]),        # 떨어진 평면
    ([quad(0, 1, 0, 1), quad(0, 1, 0, 1, up=False)], [0, 1], [False, False]),              # 다른 묶음
    ([quad(0, 1, 0, 1), quad(0, 1, 0, 1, up=False)], [0, -1], [False, False]),             # 판정하지 않는 면
    ([[(0, 0, 0), (4, 0, 0), (0, 4, 0)], quad(0.5, 1, 0.5, 1, up=False)], None, [False, True]),    # 삼각형 안
    ([[(0, 0, 0), (4, 0, 0), (0, 4, 0)], quad(1.5, 3, 1.5, 3, up=False)], None, [False, False]),   # 빗변에 걸침
    ([quad(0, 4, 0, 4), quad(1, 2, 1, 2, up=False), quad(1, 1, 1, 1)], None, [False, True, False]),  # 넓이 0 인 면은 무시
    ([], None, []),
])
def test_hidden_faces_cases(faces, keys, want):
    assert hid(faces, keys) == want


def test_hidden_faces_matches_brute_force_in_any_plane():
    rng = np.random.default_rng(7)
    for _ in range(6):
        ax = rng.normal(size=3)
        ax /= np.linalg.norm(ax)
        e1 = np.cross(ax, [0.3, 0.5, 0.8])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(ax, e1)
        o = rng.uniform(-50, 50, 3)
        rects, faces = [], []
        for _ in range(150):
            x, y = rng.integers(0, 12, 2)
            w, h = rng.integers(1, 5, 2)
            up = bool(rng.integers(2))
            rects.append((x, x + w, y, y + h, up))
            faces.append([tuple(o + u * e1 + v * e2) for u, v, _ in quad(x, x + w, y, y + h, up=up)])
        want = [any(b[4] != a[4] and b[0] <= a[0] and a[1] <= b[1] and b[2] <= a[2] and a[3] <= b[3] for b in rects) for a in rects]
        assert hid(faces) == want and 0 < sum(want) < len(want)


def _cfg():
    cfg = make_cfg()
    cfg.finish_settings.enabled = True
    cfg.sign_settings.enabled = True
    return cfg


def test_faces_without_dxf_equal_3d_doc():
    eng = StationCADEngine(_cfg())
    doc = [(e.dxf.layer, *(tuple(getattr(e.dxf, f"vtx{k}")) for k in range(4))) for e in eng.build_3d_doc().modelspace().query("3DFACE")]
    got = [(f.layer, f.vtx0, f.vtx1, f.vtx2, f.vtx3) for f in eng.build_3d_faces()]
    assert len(got) == len(doc) and [g[0] for g in got] == [d[0] for d in doc]
    assert np.array([g[1:] for g in got]) == pytest.approx(np.array([d[1:] for d in doc]), abs=1e-12)


def test_only_opaque_static_faces_are_hidden(monkeypatch):
    """투명(유리)·그린 이미지 면은 빼지 않음, 다른 묶음끼리는 가리지 않음 (키로 나눔)"""
    import exporter.web_viewer as W
    seen = {}

    def spy(faces, keys):
        seen["keys"] = list(keys)
        seen["out"] = hidden_faces(faces, keys)
        return seen["out"]
    monkeypatch.setattr(W, "hidden_faces", spy)
    data, packed = build_web_data(StationCADEngine(_cfg()))
    keys, out = np.array(seen["keys"]), seen["out"]
    assert (keys < 0).any() and not out[keys < 0].any() and out.any()
    assert len({e["group"] for e in data["elements"]}) >= len(set(keys[keys >= 0].tolist()))
    monkeypatch.setattr(W, "hidden_faces", lambda faces, keys: np.zeros(len(faces), dtype=bool))
    full, _ = build_web_data(StationCADEngine(_cfg()))
    assert full["hidden"] == 0 and full["triangles"] == data["triangles"] + data["hidden"]
    assert len(full["elements"]) == len(data["elements"])
    assert full["images"].keys() == data["images"].keys()
    assert len(gzip.decompress(packed)) > 0


def test_centerline_samples_are_reused_until_alignment_changes():
    cfg = make_cfg()
    a = centerline_samples(cfg, -10.0, 50.0)
    assert centerline_samples(cfg, -10.0, 50.0) is a
    assert len(centerline_samples(cfg, -10.0, 60.0)[0]) == len(a[0]) + 10
    import copy
    cfg.align = copy.deepcopy(cfg.align)
    b = centerline_samples(cfg, -10.0, 50.0)
    assert b is not a and np.allclose(b[1], a[1])


def test_template_uses_bvh_for_static_meshes():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exporter", "web_viewer_template.html")
    html = open(path, encoding="utf-8").read()
    assert "const BVH" in html and "mesh.raycast = BVH.raycast" in html


@pytest.mark.parametrize("s0", [20.0, 20.12345678, 20.7654321987])
def test_no_zero_thickness_partition(s0):
    """실 좌표가 1e-6 보다 잘게 나와도(계단 끝 등) 벽 모서리에 두께 0 인 벽 조각이 남지 않음"""
    from rooms.room_spec import RoomSpec
    from test_rooms import cfg_with, floor_layout
    cfg = cfg_with(RoomSpec(2, "창고", s0, s0 + 10.0000004, -3.0, 3.0))
    parts = floor_layout(cfg, 2).partitions
    rects = [p[:4] for w in parts for p in w.pieces]
    assert len(parts) == 4 and all(r[1] - r[0] > 1e-3 and r[3] - r[2] > 1e-3 for r in rects)
