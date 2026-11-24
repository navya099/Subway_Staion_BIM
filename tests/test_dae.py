"""텍스처 3D 모델 (COLLADA .dae, 스케치업 둘러보기용) 테스트"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PIL import Image

from config.output_config import OutputOptions
from engine.bim_engine import BIMEngine
from engine.cad_engine import StationCADEngine
from exporter.dae_exporter import dae_notes, texture_uv
from exporter.render_material import CONCRETE, FINISH_MATERIALS, finish_material, layer_material
from finishes.finish_spec import FinishSettings, default_finishes
from gui.print_draft import PrintDraft, preview
from test_curved import curved_cfg
from test_finishes import cfg_with

NS = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
TEXTURES = {"metal_panel": "금속패널", "granite": "화강석", "ceiling_panel": "알루미늄 천장판",
            "Polished Concrete New": "콘크리트"}      # 구조 부재 기본 (파일 이름에 공백)


@pytest.fixture
def tex_dir(tmp_path):
    d = tmp_path / "tile"
    d.mkdir()
    for k, name in enumerate(TEXTURES):
        Image.new("RGB", (16, 16), (100 + 40 * k, 120, 140)).save(d / (name + (".png" if k in (1, 2) else ".jpg")))
    return d


def finish_cfg(curved=False):
    cfg = curved_cfg() if curved else cfg_with()
    cfg.finish_settings = FinishSettings(enabled=True)
    return cfg


def parse(path):
    """DAE → {재질 이름: (삼각형 (N,3,3) 상대 좌표, uv (N,3,2) | None, 레이어)} 목록, 이미지, 원점 설명"""
    root = ET.parse(path).getroot()
    names = {m.get("id"): m.get("name") for m in root.iterfind(".//c:material", NS)}
    images = {i.get("id"): i.find("c:init_from", NS).text for i in root.iterfind(".//c:image", NS)}
    layer_of = {}
    for node in root.iterfind(".//c:node", NS):
        for ig in node.findall("c:instance_geometry", NS):
            layer_of[ig.get("url")[1:]] = node.get("name")
    out = []
    for g in root.iterfind(".//c:geometry", NS):
        arrays = {a.get("id"): np.array(a.text.split(), dtype=float) for a in g.iterfind(".//c:float_array", NS)}
        tri = g.find(".//c:triangles", NS)
        pos = arrays[f"{g.get('id')}-pos-array"].reshape(-1, 3, 3)
        uv = arrays.get(f"{g.get('id')}-uv-array")
        assert int(tri.get("count")) == len(pos)
        out.append((names[tri.get("material")], pos, None if uv is None else uv.reshape(-1, 3, 2), layer_of[g.get("id")]))
    return out, images, root.find(".//c:comments", NS).text


def area(t):
    return 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum()


def dxf_area(doc, layers):
    tot = 0.0
    for e in doc.modelspace().query("3DFACE"):
        if e.dxf.layer not in layers:
            continue
        v = np.array([e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx2, e.dxf.vtx3], dtype=float)
        tot += area(v[None, :3]) + area(v[None, [0, 2, 3]])
    return tot


def test_default_floor_material_is_granite_with_textures():
    assert {default_finishes()[k].floor_material for k in ("대합실", "승강장층", "복도", "기본")} == {"화강석"}
    for tex, name in TEXTURES.items():
        assert (CONCRETE if name == "콘크리트" else FINISH_MATERIALS[name]).texture == tex
    assert layer_material("STRUCT_WALL") is CONCRETE and layer_material("STRUCT_SLAB") is CONCRETE
    assert FINISH_MATERIALS["콘크리트 면처리"].texture == CONCRETE.texture
    assert finish_material("없는 재질").texture == "" and finish_material("없는 재질").name == "없는 재질"


@pytest.mark.parametrize("curved", [False, True])
def test_dae_materials_textures_and_geometry(tmp_path, tex_dir, curved):
    cfg = finish_cfg(curved)
    eng = StationCADEngine(cfg)
    path = eng.generate_dae(tmp_path / "out" / "m.dae", texture_dir=tex_dir)
    res = eng.dae_result
    groups, images, comment = parse(path)
    # 텍스처: 네 재질 모두 이미지 붙음, textures/ 로 복사 (공백은 URI 에서 %20)
    assert sorted(res.textured) == sorted(TEXTURES.values()) and not res.missing
    assert sorted(images.values()) == ["textures/Polished%20Concrete%20New.jpg", "textures/ceiling_panel.png",
                                     "textures/granite.png", "textures/metal_panel.jpg"]
    assert sorted(os.listdir(tmp_path / "out" / "textures")) == ["Polished Concrete New.jpg", "ceiling_panel.png",
                                                                 "granite.png", "metal_panel.jpg"]
    with_uv = {n for n, _, uv, _ in groups if uv is not None}
    assert with_uv == set(TEXTURES.values())
    # 재질: 마감 부재는 마감 재질, 구조체는 콘크리트, 천장틀은 뺌
    by_layer = {}
    for n, t, _, ly in groups:
        by_layer.setdefault(ly, set()).add(n)
    assert "FIN_FRAME" not in by_layer
    assert by_layer["FIN_WALL"] == {"금속패널"} and by_layer["FIN_CEILING"] == {"알루미늄 천장판"}
    assert by_layer["FIN_FLOOR"] == {"화강석", "몰탈"} and by_layer["STRUCT_WALL"] == {"콘크리트"}
    # 기하 = 3D DXF 의 3DFACE (레이어별 면적 일치), 원점 = 설명·결과 일치
    doc = eng.build_3d_doc()
    for ly in by_layer:
        a = sum(area(t) for n, t, _, g in groups if g == ly)
        assert a == pytest.approx(dxf_area(doc, {ly}), rel=1e-5)        # 좌표 0.01mm 반올림
    assert res.triangles == sum(len(t) for _, t, _, _ in groups)
    ox, oy, oz = res.origin
    assert f"{ox:.3f}, {oy:.3f}, {oz:.3f}" in comment and ox == int(ox)


def _uv_scale_ok(t, uv, size_u, size_v, cfg, origin, flat, tol=1e-3):
    """삼각형마다 uv 차이 = 투영 길이 / 텍스처 크기 (수평 면: 선형 접선 기준, 벽: 수평·연직)"""
    for tri, q in zip(t, uv):
        d = tri[1] - tri[0]
        du = q[1] - q[0]
        if flat:
            s, _ = cfg.to_station(*(tri.mean(axis=0)[:2] + origin[:2]))
            th = cfg.theta_at(s)
            eu, ev = np.array([np.cos(th), np.sin(th), 0]), np.array([-np.sin(th), np.cos(th), 0])
            assert du[0] == pytest.approx(d @ eu / size_u, abs=tol)
            assert du[1] == pytest.approx(d @ ev / size_v, abs=tol)
        else:
            assert abs(du[1]) == pytest.approx(abs(d[2]) / size_v, abs=1e-3)
            assert abs(du[0]) == pytest.approx(np.hypot(d[0], d[1]) / size_u, abs=2e-3)


@pytest.mark.parametrize("curved", [False, True])
def test_uv_follows_alignment_and_real_size(tmp_path, tex_dir, curved):
    cfg = finish_cfg(curved)
    eng = StationCADEngine(cfg)
    groups, _, _ = parse(eng.generate_dae(tmp_path / "m.dae", texture_dir=tex_dir))
    origin = np.array(eng.dae_result.origin)
    for name, flat in (("화강석", True), ("알루미늄 천장판", True), ("금속패널", False), ("콘크리트", True),
                       ("콘크리트", False)):
        m = CONCRETE if name == "콘크리트" else FINISH_MATERIALS[name]
        t, uv = next((t, uv) for n, t, uv, _ in groups if n == name)
        k = np.linspace(0, len(t) - 1, 40).astype(int)              # 표본 40개
        n = np.cross(t[k, 1] - t[k, 0], t[k, 2] - t[k, 0])
        n /= np.linalg.norm(n, axis=1)[:, None]
        sel = k[np.abs(n[:, 2]) > 0.99] if flat else k[np.abs(n[:, 2]) < 0.01]     # 바닥·천장 면 / 연직 벽 면
        assert len(sel) > 0
        _uv_scale_ok(t[sel], uv[sel], m.size_u, m.size_v, cfg, origin, flat, 0.1 if "천장" in m.name else 1e-3)      # 천장판은 사각 면마다 한 방향 (정거장 격자)


def test_texture_uv_vertical_face_axes():
    cfg = finish_cfg()
    th = cfg.theta_at(0.0)
    h = np.array([np.cos(th), np.sin(th), 0.0])
    tri = np.array([[[0, 0, 0], h * 1.2, h * 1.2 + [0, 0, 0.6]]], dtype=float)
    uv = texture_uv(cfg, tri, tri, 1.2, 0.6)[0]
    assert abs(uv[1, 0] - uv[0, 0]) == pytest.approx(1.0) and uv[2, 1] - uv[1, 1] == pytest.approx(1.0)   # 위쪽 = +v


def test_missing_images_fall_back_to_color(tmp_path):
    cfg = finish_cfg()
    eng = StationCADEngine(cfg)
    path = eng.generate_dae(tmp_path / "m.dae", texture_dir=tmp_path / "없음")
    groups, images, _ = parse(path)
    res = eng.dae_result
    assert not images and not res.textured and all(uv is None for _, _, uv, _ in groups)
    assert sorted(n for n, _ in res.missing) == sorted(TEXTURES.values())
    assert not (tmp_path / "textures").exists()
    notes = dae_notes(res)
    assert "원점" in notes[0] and any("granite" in s and "색만" in s for s in notes)


def test_frames_option_includes_ceiling_frame(tmp_path):
    eng = StationCADEngine(finish_cfg())
    from exporter.dae_exporter import export_dae
    groups, _, _ = parse(export_dae(eng, tmp_path / "m.dae", texture_dir=tmp_path, frames=True).path)
    assert any(ly == "FIN_FRAME" and n == "M바 천장틀" for n, _, _, ly in groups)


def test_output_option_and_bim_engine(tmp_path):
    cfg = finish_cfg()
    assert OutputOptions().dae is False
    opt = OutputOptions(dxf3d=False, ifc=False, plan=False, profile=False, section=False, dae=True)
    notes = []
    paths = BIMEngine.build(cfg, tmp_path, opt, notes)
    assert [os.path.basename(p) for p in paths] == ["정거장3d모델.dae"] and notes and "텍스처 DAE" in notes[0]
    with pytest.raises(ValueError, match="하나 이상"):
        OutputOptions(dxf3d=False, ifc=False, plan=False, profile=False, section=False).validate(cfg)


def test_print_draft_dae():
    d = PrintDraft(dxf3d=False, ifc=False, plan=False, profile=False, section=False)
    assert d.dae is False
    d.dae = True
    assert d.to_options(4.0).dae is True
    assert "텍스처 DAE" in preview(d, None, None, None)
