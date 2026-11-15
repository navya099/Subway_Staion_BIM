"""미리보기 작도 (preview.preview_render) — 화면 없이 Agg 로 검사"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hashlib

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pytest
from matplotlib.figure import Figure

from engine.cad_engine import StationCADEngine
from preview import preview_render as R
from rooms.room_spec import RoomSpec
from test_curved import curved_cfg
from test_finishes import cfg_with
from test_patch import make_cfg, user_example


@pytest.fixture(scope="module")
def eng():
    return StationCADEngine(cfg_with(RoomSpec(floor=1, use="역무실", s0=10, s1=30, t0=-5, t1=5)))


@pytest.fixture(scope="module")
def mesh(eng):
    return R.mesh_from_doc(eng.build_3d_doc(), eng.cfg)


def _md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


# ===================================================== 도면 문서 = 출력 파일
def test_build_docs_match_generated_files(tmp_path):
    e = StationCADEngine(make_cfg(user_example()))
    pairs = [(e.generate_plan_dxf(tmp_path / "p.dxf", floors=[1, 2]), e.build_plan_doc(floors=[1, 2])),
             (e.generate_profile_dxf(tmp_path / "f.dxf", offsets=[0, 2.2]), e.build_profile_doc([0, 2.2])),
             (e.generate_section_dxf([50.0, 120.0], tmp_path / "s.dxf"), e.build_section_doc([50.0, 120.0]))]
    for path, doc in pairs:
        assert sorted(x.dxftype() for x in doc.modelspace()) == sorted(
            x.dxftype() for x in __import__("ezdxf").readfile(path).modelspace())
    doc = e.build_3d_doc()
    n = sum(1 for x in doc.modelspace() if x.dxftype() == "3DFACE")
    assert n == sum(1 for x in __import__("ezdxf").readfile(e.generate_3d_dxf(tmp_path / "3.dxf")).modelspace()
                    if x.dxftype() == "3DFACE")


def test_draw_2d_uses_korean_font_and_draws(eng):
    fig = Figure()
    ax = fig.add_axes([0, 0, 1, 1])
    doc = eng.build_plan_doc(floors=[1])
    R.draw_doc_2d(ax, doc)
    assert doc.styles.get("Standard").dxf.font == R.PREVIEW_FONT
    assert ax.collections or ax.lines or ax.patches
    x0, x1 = ax.get_xlim()
    assert x0 < 0 and x1 > eng.cfg.station.length          # 정거장 전체가 보이게 맞춰짐


# ===================================================== 3D 자료
def test_mesh_faces_and_station_coordinates(eng, mesh):
    doc = eng.build_3d_doc()
    by_layer = {}
    for x in doc.modelspace():
        if x.dxftype() == "3DFACE":
            by_layer[x.dxf.layer] = by_layer.get(x.dxf.layer, 0) + 1
    assert {ly: len(fs) for ly, fs in mesh.faces.items()} == by_layer
    p = eng.cfg.station
    ws = mesh.faces["STRUCT_WALL"]
    s = np.concatenate([f[:, 3] for f in ws])
    h = np.concatenate([f[:, 4] for f in ws])
    wall = max(p.wall_ts)
    assert s.min() == pytest.approx(-wall, abs=1e-3) and s.max() == pytest.approx(p.length + wall, abs=1e-3)
    # 높이 = 본체 FL 기준 (단부 벽의 구배 차이 정도만 오차)
    assert -p.floor_t - 0.05 < h.min() < 0.05 and h.max() == pytest.approx(p.height - p.roof_t, abs=0.05)   # 벽 = 층 FL ~ 위 슬래브 하면


def test_select_clips_faces_to_range_and_height(eng, mesh):
    p = eng.cfg.station
    layers = R.layers_of(R.default_groups())
    full = mesh.select(layers)
    cut = mesh.select(layers, s_range=(40.0, 80.0), h_max=p.floor_level(1) + p.clear_height(1))
    assert 0 < sum(map(len, cut.values())) < sum(map(len, full.values()))
    o = np.array(mesh.origin)
    for fs in cut.values():
        for f in fs:
            assert f.shape[1] == 3
            s, _ = eng.cfg.to_station(*(f.mean(axis=0) + o)[:2])
            assert 40.0 - 1.0 < s < 80.0 + 1.0
    # 긴 벽도 구간만큼만 남음: 벽 면의 길이 ≈ 40 m
    walls = cut["STRUCT_WALL"]
    span = max(np.linalg.norm(f.max(axis=0)[:2] - f.min(axis=0)[:2]) for f in walls)
    assert span == pytest.approx(40.0, abs=1.0)
    # 높이로 자르면 위층 슬래브(그 층 천장 하면 위)는 사라짐
    top = max(f[:, 2].max() for fs in cut.values() for f in fs)
    lv = eng.cfg.lv(80.0) - p.offset - o[2]
    assert top <= lv + p.floor_level(1) + p.clear_height(1) + 1e-3


def test_clip_polygon():
    sq = np.array([[0, 0, 0, 0, 0], [10, 0, 0, 10, 0], [10, 10, 0, 10, 0], [0, 10, 0, 0, 0]], dtype=float)
    a = R._clip(sq, 3, 4.0, 1.0)                    # s ≤ 4
    assert a[:, 0].max() == pytest.approx(4.0) and len(a) == 4
    assert R._clip(sq, 3, -1.0, 1.0) is None        # 모두 밖
    assert R._clip(sq, 3, 20.0, 1.0) is sq          # 모두 안
    assert R._clip(sq, 3, 0.0, 1.0) is None         # 경계에 닿기만 한 변 → 없음 (넓이 0)


def test_tiles_and_shade():
    q = np.array([[0, 0, 0], [20, 0, 0], [20, 3, 0], [0, 3, 0]], dtype=float)
    ts = R._tiles(q)
    assert len(ts) == 4 and sum(np.linalg.norm(t[1] - t[0]) * np.linalg.norm(t[3] - t[0]) for t in ts) == pytest.approx(60.0)
    tri = q[:3]
    assert R._tiles(tri)[0] is tri and len(R._tiles(tri)) == 1
    assert 0.55 <= R._shade(q) <= 1.0


def test_draw_3d_counts_and_keeps_view(mesh):
    fig = Figure()
    ax = fig.add_axes([0, 0, 1, 1], projection="3d")
    n = R.draw_mesh_3d(ax, mesh, R.layers_of(R.default_groups()), s_range=(0, 30))
    assert n > 0
    ax.view_init(elev=10, azim=33)
    R.zoom_3d(ax, 0.5)
    lim = ax.get_xlim3d()
    R.draw_mesh_3d(ax, mesh, R.layers_of({"구조체"}), s_range=(0, 30), transparent=True, keep_view=True)
    assert ax.azim == pytest.approx(33) and ax.get_xlim3d() == pytest.approx(lim)
    assert R.draw_mesh_3d(ax, mesh, set()) == 0


def test_curved_mesh_station_coordinates():
    cfg = curved_cfg()
    e = StationCADEngine(cfg)
    m = R.mesh_from_doc(e.build_3d_doc(), cfg)
    o = np.array(m.origin)
    for f in m.faces["STRUCT_WALL"][::7]:
        for v in f:
            s, _ = cfg.to_station(*(v[:2] + o[:2]))
            assert v[3] == pytest.approx(s, abs=0.05)


# ===================================================== 입력 해석
def test_choices_and_parsing():
    cfg = make_cfg(user_example())
    p = cfg.station
    assert [n for _, n in R.floor_choices(cfg)] == list(range(1, p.floors + 1))
    axes = R.axis_choices(cfg)
    assert axes[0][1] == 0 and len(axes) == 3
    assert R.parse_axis(axes[1][0], cfg) == pytest.approx(cfg.platform.track_spacing / 2)
    assert R.parse_axis("-1.5", cfg) == -1.5
    with pytest.raises(ValueError, match="외곽"):
        R.parse_axis("50", cfg)
    with pytest.raises(ValueError, match="숫자"):
        R.parse_axis("왼쪽", cfg)
    base = p.start_station
    assert R.parse_section_s(f"{base + 12.5}", cfg) == pytest.approx(12.5)
    with pytest.raises(ValueError, match="범위"):
        R.parse_section_s(f"{base - 5}", cfg)
    assert R.parse_cut_h("1.5", cfg, 1) == 1.5
    with pytest.raises(ValueError, match="내공 높이"):
        R.parse_cut_h("99", cfg, 1)
    assert "FIN_FRAME" not in R.layers_of(R.default_groups())
    assert R.layer_rgb("STRUCT_SLAB") != R.layer_rgb("STRUCT_WALL")
