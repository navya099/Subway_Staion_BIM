"""비품 외부 3D 모델 (GLB·glTF·OBJ): 파일 읽기, 단위·축·돌림, 놓는 기준점, 면 한도, 파일 없음 대체, DXF·IFC·DAE·웹 뷰어, 입력"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import base64
import gzip
import io
import json
import struct
import xml.etree.ElementTree as ET

import ifcopenshell
import ifcopenshell.util.element
import numpy as np
import pytest
from PIL import Image

from engine.cad_engine import StationCADEngine
from gui.project_file import ProjectState, open_project, save_project
from gui.prop_draft import CODE_SHAPE, ModelDraft, ModelDrafts, PropDraft, model_info, new_draft, new_model
from helper.prism_member import mesh_volume
from props.model_file import load_model
from props.model_spec import PropModel, bounds, mesh_size, model_mesh, placed_mesh, triangle_count
from props.prop_kinds import CEILING, FLOOR, HANG, WALL
from props.prop_spec import PropSpec, check_props, resolve_prop_names
from test_finishes import cfg_with, ifc_world_volume

# 상자 x 0~2, y 0~1(위), z 0~3(앞) — glTF 규약이면 왼쪽(+x) 2, 높이 1, 깊이 3
V = np.array([(x, y, z) for x in (0, 2) for y in (0, 1) for z in (0, 3)], dtype=np.float32)
F = np.array([(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)], dtype=np.uint16)
UV = np.array([(v[0] / 2, v[2] / 3) for v in V], dtype=np.float32)


def png(color=(200, 10, 10, 255)) -> bytes:
    b = io.BytesIO()
    Image.new("RGBA", (8, 4), color).save(b, "PNG")
    return b.getvalue()


def gltf(tmp, name="box.glb", node=None, uv=True, mode=None, idx=F, stride=False, mat=None, required=None, ext_bin=False, children=None):
    """시험용 glTF 파일. 텍스처 이미지는 안에 넣음"""
    blob, views = b"", []

    def add(data, **kw):
        nonlocal blob
        blob += b"\0" * (-len(blob) % 4)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **kw})
        blob += data
        return len(views) - 1
    acc = []
    if stride:                                                    # 좌표와 uv 를 번갈아 (20바이트 간격)
        v = add(np.concatenate([V, UV], axis=1).astype("<f4").tobytes(), byteStride=20)
        acc += [{"bufferView": v, "componentType": 5126, "count": 8, "type": "VEC3"}, {"bufferView": v, "byteOffset": 12, "componentType": 5126, "count": 8, "type": "VEC2"}]
    else:
        acc += [{"bufferView": add(V.astype("<f4").tobytes()), "componentType": 5126, "count": 8, "type": "VEC3"},
                {"bufferView": add(UV.astype("<f4").tobytes()), "componentType": 5126, "count": 8, "type": "VEC2"}]
    acc.append({"bufferView": add(np.asarray(idx, dtype="<u2").tobytes()), "componentType": 5123, "count": int(np.size(idx)), "type": "SCALAR"})
    pr = {"attributes": {"POSITION": 0, **({"TEXCOORD_0": 1} if uv else {})}, "indices": 2, "material": 0}
    if mode is not None:
        pr["mode"] = mode
    g = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, **(node or {})}] if children is None else children,
         "meshes": [{"primitives": [pr]}],
         "materials": [mat or {"name": "몸체", "pbrMetallicRoughness": {"baseColorFactor": [0.5, 0.0, 1.0, 1.0], "baseColorTexture": {"index": 0}}}],
         "textures": [{"source": 0}], "images": [{"bufferView": add(png()), "mimeType": "image/png"}], "bufferViews": views, "accessors": acc, "buffers": [{"byteLength": 0}]}
    if required:
        g["extensionsRequired"] = [required]
    blob += b"\0" * (-len(blob) % 4)
    g["buffers"][0]["byteLength"] = len(blob)
    p = tmp / name
    if name.endswith(".gltf"):
        if ext_bin:
            (tmp / "자료 1.bin").write_bytes(blob)
            g["buffers"][0]["uri"] = "%EC%9E%90%EB%A3%8C%201.bin"
        else:
            g["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(blob).decode()
        p.write_text(json.dumps(g), encoding="utf-8")
    else:
        js = json.dumps(g).encode()
        js += b" " * (-len(js) % 4)
        p.write_bytes(b"glTF" + struct.pack("<II", 2, 28 + len(js) + len(blob)) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob)
    return p


def tris(parts):
    return [tuple(map(tuple, p.pos[t])) for p in parts for t in p.idx]


# ===================================================== 파일 읽기
@pytest.mark.parametrize("kw", [dict(), dict(stride=True), dict(name="a.gltf"), dict(name="b.gltf", ext_bin=True)])
def test_gltf_geometry_material_texture(tmp_path, kw):
    (p,) = load_model(gltf(tmp_path, **kw))
    assert mesh_volume(tris([p])) == pytest.approx(6.0) and len(p.idx) == 12
    assert p.name == "몸체" and p.image.size == (8, 4) and not p.cut
    assert p.color == pytest.approx((0.7354, 0.0, 1.0), abs=1e-3)                        # 선형 0.5 → sRGB
    assert np.allclose(p.uv, np.stack([UV[:, 0], 1 - UV[:, 1]], axis=1))                 # 왼쪽 아래 원점
    assert load_model(tmp_path / kw.get("name", "box.glb"))[0] is p                      # 다시 읽지 않음


def test_gltf_nodes_transform_and_mirror(tmp_path):
    h = 2 ** 0.5 / 2
    kids = [{"translation": [10, 0, 0], "children": [1]}, {"mesh": 0, "rotation": [0, h, 0, h], "scale": [2, 1, 1]}]
    (p,) = load_model(gltf(tmp_path, children=kids))
    lo, hi = bounds([p])                                                                  # 배율(x 4) → y 둘레 90도 (x→−z, z→x) → 이동
    assert np.allclose(lo, (10, 0, -4), atol=1e-6) and np.allclose(hi, (13, 1, 0), atol=1e-6)
    (p,) = load_model(gltf(tmp_path, "m.glb", node={"scale": [-1, 1, 1]}))
    assert mesh_volume(tris([p])) == pytest.approx(6.0)                                   # 거울 변환도 바깥 면
    M = np.eye(4)
    M[:3, 3] = (1, 2, 3)
    (p,) = load_model(gltf(tmp_path, "n.glb", node={"matrix": M.T.ravel().tolist()}))
    assert np.allclose(bounds([p])[0], (1, 2, 3))


def test_gltf_strip_fan_alpha_and_missing_uv(tmp_path):
    (p,) = load_model(gltf(tmp_path, mode=5, idx=[0, 1, 2, 3]))
    assert p.idx.tolist() == [[0, 1, 2], [2, 1, 3]]
    (p,) = load_model(gltf(tmp_path, "f.glb", mode=6, idx=[0, 1, 2, 3]))
    assert p.idx.tolist() == [[0, 1, 2], [0, 2, 3]]
    (p,) = load_model(gltf(tmp_path, "u.glb", uv=False))
    assert p.uv is None and p.image is None
    (p,) = load_model(gltf(tmp_path, "g.glb", mat={"alphaMode": "BLEND", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 0.3]}}))
    assert p.alpha == pytest.approx(0.3) and p.name == "재질 1"
    (p,) = load_model(gltf(tmp_path, "c.glb", mat={"alphaMode": "MASK", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}))
    assert p.cut and p.alpha == 1.0


def test_model_errors(tmp_path):
    for kw, msg in ((dict(required="KHR_draco_mesh_compression"), "Draco"), (dict(mode=1), "면이 없습니다"), (dict(idx=[0, 1, 99]), "올바르지 않습니다")):
        with pytest.raises(ValueError, match=msg):
            load_model(gltf(tmp_path, f"e{len(msg)}.glb", **kw))
    with pytest.raises(ValueError, match="지원하지 않는"):
        load_model(tmp_path / "a.skp")
    with pytest.raises(ValueError, match="파일이 없습니다"):
        load_model(tmp_path / "none.glb")
    for name, data in (("x.glb", b"glTF"), ("y.glb", b"glTF" + struct.pack("<II", 2, 20) + b"abc"), ("z.gltf", b"{}"), ("w.gltf", b"\xff\xfe"), ("v.obj", b"v a b c\nf 1 2 3"),
                       ("t.obj", b"v 0 0 0\nf 1 2 3"), ("s.glb", b"glTF" + struct.pack("<II", 1, 20))):
        (tmp_path / name).write_bytes(data)
        with pytest.raises(ValueError):
            load_model(tmp_path / name)


def test_obj_with_mtl_polygons_negative_index_and_texture(tmp_path):
    (tmp_path / "tex 1.png").write_bytes(png())
    (tmp_path / "재질.mtl").write_bytes("newmtl 빨강\nKd 1 0 0\nd 0.5\nnewmtl 그림\nKd 0 1 0\nTr 1.0\nmap_Kd C:\\other\\tex 1.png\n".encode("cp949"))
    lines = ["mtllib 재질.mtl"] + [f"v {x} {y} {z}" for x, y, z in V.tolist()] + ["vt 0 0", "vt 1 0", "vt 1 1", "vt 0 1"]
    lines += ["usemtl 빨강", "f 1 2 4 3", "f 5 7 8 6", "f 1 5 6 2", "usemtl 그림", "f -6/1 -5/2 -1/3 -2/4", "f 1/1 3/2 7/3 5/4", "f 2/1 6/2 8/3 4/4"]
    (tmp_path / "m.obj").write_bytes("\n".join(lines).encode("cp949"))
    a, b = load_model(tmp_path / "m.obj")
    assert (a.name, a.color, a.alpha, a.image) == ("빨강", (1, 0, 0), 0.5, None) and len(a.idx) == 6
    assert b.name == "그림" and b.alpha == 1.0 and b.image.size == (8, 4) and b.uv.max() == 1.0      # 불투명도 0 은 잘못 저장된 값으로 봄
    assert mesh_volume(tris([a, b])) == pytest.approx(6.0)
    (tmp_path / "n.obj").write_text("\n".join(lines[1:]), encoding="utf-8")                          # MTL 이 없으면 회색
    assert all(p.color == (0.8, 0.8, 0.8) and p.image is None for p in load_model(tmp_path / "n.obj"))


# ===================================================== 방향·단위·기준점
def test_orientation_units_and_anchor(tmp_path):
    path = str(gltf(tmp_path))
    m = model_mesh(PropModel("A", path))
    assert mesh_size(m) == pytest.approx((3, 2, 1))                                                  # 깊이(앞 z) 3, 폭(x) 2, 높이(y) 1
    lo, hi = bounds(m)
    assert np.allclose(lo, (0, 0, 0), atol=1e-6) and np.allclose(hi, (3, 2, 1), atol=1e-6)            # 앞 +z → +x, 왼쪽 +x → +y, 위 +y → +z
    assert mesh_volume(tris(m)) == pytest.approx(6.0)
    lo, hi = bounds(model_mesh(PropModel("A", path, up="Z")))                                        # 위 Z 파일: 앞 = −y → +x
    assert np.allclose(hi - lo, (1, 2, 3)) and np.allclose(lo, (-1, 0, 0), atol=1e-6)
    lo, hi = bounds(model_mesh(PropModel("A", path, angle=90.0)))
    assert np.allclose(lo, (-2, 0, 0), atol=1e-6) and np.allclose(hi, (0, 3, 1), atol=1e-6)
    assert mesh_size(model_mesh(PropModel("A", path, unit="cm", scale=50.0))) == pytest.approx((1.5, 1.0, 0.5))
    for kw in (dict(scale=20.0), dict(unit="mm", scale=0.1)):
        with pytest.raises(ValueError, match="단위·배율"):
            model_mesh(PropModel("A", path, **kw))
    for mount, want in ((FLOOR, ((-1.5, -1, 0), (1.5, 1, 1))), (WALL, ((0, -1, 0.4), (3, 1, 1.4))), (CEILING, ((-1.5, -1, -1), (1.5, 1, 0))),
                        (HANG, ((-1.5, -1, 0.4), (1.5, 1, 1.4)))):
        lo, hi = bounds(placed_mesh(m, mount, 0.4 if mount in (WALL, HANG) else 0.0))
        assert np.allclose((lo, hi), want, atol=1e-6)


# ===================================================== 모델에서
def build(tmp_path, *props, limit=5000, models=None, **kw):
    path = str(gltf(tmp_path))
    cfg = cfg_with(no_cols=True, props=list(props), prop_models=models or [PropModel("상자", path, scale=0.4), PropModel("작은", path, scale=0.2)], **kw)
    cfg.prop_model_limit = limit
    check_props(cfg)
    return StationCADEngine(cfg)


SPECS = [PropSpec("BENCH", 2, 40, 0, 30.0, {}, "", "상자"), PropSpec("MODEL_F", 2, 45, 1, 0.0, {}, "", "상자"), PropSpec("MODEL_F", 2, 48, 1, 90.0, {}, "", "상자"),
         PropSpec("MODEL_W", 2, 55, 8.7, 0.0, {"z": 1.0}, "", "작은"), PropSpec("MODEL_C", 2, 60, 1, 0.0, {}, "", "작은"), PropSpec("MODEL_H", 2, 65, 1, 0.0, {"z": 2.2}, "", "작은"),
         PropSpec("HSIGN", 2, 70, 1, 0.0, {"z": 2.3}, "", "작은"), PropSpec("BIN", 2, 80, 0)]


def test_models_in_engine_names_boxes_and_heights(tmp_path):
    eng = build(tmp_path, *SPECS)
    by = {e.name: e for e in eng.props.elements}
    assert list(by) == ["의자 1", "상자 1", "상자 2", "작은 1", "작은 2", "작은 3", "매달림 안내사인 1", "쓰레기통 1"] and eng.props.warnings == []
    b = by["의자 1"]
    assert b.model == "상자" and b.detail and len(b.parts) == 1 and b.volume == pytest.approx(6 * 0.4 ** 3)      # 외곽 상자
    cfg = eng.cfg
    ft = cfg.finish_settings.for_room("대합실")
    w = by["작은 1"]
    assert w.t == pytest.approx(9.0 - ft.face) and w.angle == 270.0 and w.parts[0].z0 == 1.0
    assert by["작은 2"].parts[0].z1 == 0.0 and by["작은 2"].z == pytest.approx(cfg.station.floor_level(2) + ft.ffl + ft.ceiling_h)
    assert by["작은 3"].parts[0].z0 == 2.2 and "rods" not in by["매달림 안내사인 1"].values and by["매달림 안내사인 1"].mesh
    assert by["쓰레기통 1"].mesh == [] and len(by["쓰레기통 1"].parts) > 1
    for e in by.values():                                                                      # 세계 삼각형이 외곽 상자 안, 그 크기
        if e.mesh:
            pts = np.concatenate([t.reshape(-1, 3) for _, t in eng.props.model_faces(e)])
            box = np.array([v for q in eng.props.part_faces(e, e.parts[0]) for v in q])
            assert np.allclose(pts.min(axis=0), box.min(axis=0), atol=1e-6) and np.allclose(pts.max(axis=0), box.max(axis=0), atol=1e-6)
            assert mesh_volume([tuple(map(tuple, t - pts[0])) for _, ts in eng.props.model_faces(e) for t in ts]) == pytest.approx(e.volume)
    with pytest.raises(ValueError, match="겹칩니다"):
        build(tmp_path, PropSpec("MODEL_F", 2, 45, 1, 0.0, {}, "", "상자"), PropSpec("EXT", 2, 45.5, 1))


def test_model_spec_checks(tmp_path):
    for sp, msg in ((PropSpec("MODEL_F", 2, 40, 0), "모델을 골라야"), (PropSpec("BENCH", 2, 40, 0, model="없음"), "목록에 없습니다")):
        with pytest.raises(ValueError, match=msg):
            build(tmp_path, sp)
    for models, msg in (([PropModel("", "a.glb")], "이름"), ([PropModel("A", "a.glb"), PropModel("A", "b.glb")], "중복"), ([PropModel("A", "a.glb", unit="km")], "단위"),
                        ([PropModel("A", "a.glb", up="X")], "위쪽"), ([PropModel("A", "a.glb", scale=0.0)], "배율")):
        with pytest.raises(ValueError, match=msg):
            build(tmp_path, models=models)
    with pytest.raises(ValueError, match="면 한도"):
        build(tmp_path, limit=-1)
    assert resolve_prop_names([PropSpec("MODEL_F", model="화분"), PropSpec("MODEL_W", model="화분"), PropSpec("MODEL_F", model="탁자")]) == ["화분 1", "화분 2", "탁자 1"]


def test_missing_file_falls_back_with_warning(tmp_path):
    gone = [PropModel("상자", str(tmp_path / "gone.glb"), size=(0.6, 0.8, 1.0)), PropModel("작은", str(tmp_path / "gone2.glb"))]
    eng = build(tmp_path, *SPECS, models=gone)
    by = {e.name: e for e in eng.props.elements}
    assert len(eng.props.warnings) == 2 and "파일이 없습니다" in eng.props.warnings[0] and set(eng.props.warnings) <= set(eng.warnings)
    assert len(by["의자 1"].parts) > 5 and not by["의자 1"].mesh                                # 코드 형상
    assert by["상자 1"].volume == pytest.approx(0.48) and by["작은 1"].volume == pytest.approx(0.125)   # 마지막 크기 / 0.5 상자
    assert len(by["매달림 안내사인 1"].parts) == 5                                               # 행거까지


@pytest.mark.parametrize("limit", [5000, 5])
def test_outputs_detail_or_box(tmp_path, limit):
    eng = build(tmp_path, *SPECS, limit=limit)
    detail = limit == 5000
    els = [e for e in eng.props.elements if e.mesh]
    assert all(e.detail == detail for e in els)
    doc = eng.build_3d_doc()
    for e in els:
        assert len(e.source_element) == (12 if detail else 6)
    f = ifcopenshell.open(eng.generate_ifc(tmp_path / "m.ifc"))
    by = {x.Name: x for x in f.by_type("IfcProduct") if x.Name}
    for e in els:
        assert ifc_world_volume(by[e.name]) == pytest.approx(e.volume, rel=1e-5)
        assert by[e.name].Representation.Representations[0].Items[0].is_a() == ("IfcTriangulatedFaceSet" if detail else "IfcPolygonalFaceSet")
        assert ifcopenshell.util.element.get_psets(by[e.name])["SSBIM_Prop"]["Model"] == e.model
    assert doc is not None
    # DAE: 면 한도와 관계없이 실제 모양 — 형상은 (모델, 기준점)마다 하나, 배치는 행렬
    from exporter.dae_exporter import export_dae
    res = export_dae(eng, tmp_path / "out" / "m.dae")
    root = ET.parse(tmp_path / "out" / "m.dae").getroot()
    ns = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
    geoms = {g.get("id"): g for g in root.findall(".//c:geometry", ns) if g.get("id").startswith("prop")}
    assert len(geoms) == 5                                                                      # 상자-바닥, 작은-벽·천장·매달림·안내사인(높이 다름)
    nodes = {n.get("name"): n for n in root.findall(".//c:node", ns) if n.find("c:matrix", ns) is not None}
    assert set(nodes) == {e.name for e in els}
    for e in els:
        n = nodes[e.name]
        M = np.array(n.find("c:matrix", ns).text.split(), dtype=float).reshape(4, 4)
        gid = n.find("c:instance_geometry", ns).get("url")[1:]
        pos = np.array(geoms[gid].find(".//c:float_array", ns).text.split(), dtype=float).reshape(-1, 3)
        got = pos @ M[:3, :3].T + M[:3, 3] + res.origin
        want = np.concatenate([t.reshape(-1, 3) for _, t in eng.props.model_faces(e)])
        assert np.linalg.norm(want[:, None] - got[None], axis=2).min(axis=1).max() < 1e-4
        assert geoms[gid].find(".//c:triangles", ns).get("count") == "12"
    assert len(list((tmp_path / "out" / "textures").glob("prop_model_*.png"))) == 2              # 모델마다 이미지 하나
    # 웹 뷰어
    from exporter.web_viewer import build_web_data
    data, packed = build_web_data(eng)
    buf = gzip.decompress(packed)
    org = np.array(data["origin"])
    seen = {}
    for it in (x for x in data["instances"] if x["layer"] == "STRUCT_PROP" and x["material"] in ("몸체", "외곽 상자")):
        rows = np.frombuffer(buf, np.float32, it["count"] * 10, it["items"]).reshape(-1, 10).astype(float)
        pos = np.frombuffer(buf, np.float32, it["nv"] * 3, it["pos"]).reshape(-1, 3).astype(float)
        hid = bool(it.get("hidden"))
        assert it["solid"] == (hid or detail) and (hid or (it["tex"] in data["images"] and it["nt"] == 12))
        for x, y, z, co, si, *_, eid in rows:
            m = np.array([[co, -si, 0], [si, co, 0], [0, 0, 1]])
            seen[(data["elements"][int(eid)]["name"], hid)] = pos @ m.T + [x, y, z] + org
    assert set(seen) == {(e.name, h) for e in els for h in ((False,) if detail else (False, True))}
    for e in els:
        want = np.concatenate([t.reshape(-1, 3) for _, t in eng.props.model_faces(e)])
        for h in (False,) if detail else (False, True):
            assert np.linalg.norm(want[:, None] - seen[(e.name, h)][None], axis=2).min(axis=1).max() < 2e-3     # 상자 모델이라 외곽 상자와 같은 꼭짓점
    boxes = [x for x in data["instances"] if x.get("hidden")]
    assert bool(boxes) != detail
    assert eng.build_plan_doc(floors=[2]) is not None and eng.build_section_doc([45.0]) is not None


def test_same_model_shares_shape_between_kinds_only_when_anchored_alike(tmp_path):
    from exporter.web_viewer import build_web_data
    eng = build(tmp_path, *[PropSpec("MODEL_F", 2, 40 + 4 * k, 0, 0.0, {}, "", "상자") for k in range(5)] + [PropSpec("BENCH", 2, 70, 0, 90.0, {}, "", "상자")])
    data, _ = build_web_data(eng)
    it = [x for x in data["instances"] if x["layer"] == "STRUCT_PROP"]
    assert len(it) == 1 and it[0]["count"] == 6 and triangle_count(eng.props.elements[0].mesh) == 12


# ===================================================== 입력
def test_model_drafts(tmp_path):
    path = str(gltf(tmp_path))
    it = new_model(path, {"box"})
    assert it.name == "box 2" and it.size == "3.0000,2.0000,1.0000"
    assert "폭 2.00 × 깊이 3.00 × 높이 1.00 m · 면 12개 · 재질 1개 (이미지 1)" in model_info(it)
    it.scale = "0.5"
    assert "폭 1.00" in model_info(it) and it.to_model().size == (1.5, 1.0, 0.5)
    it.scale = "x"
    assert model_info(it).startswith("→ ") and it.size == "1.5000,1.0000,0.5000"
    with pytest.raises(ValueError, match="배율"):
        it.to_model()
    assert "파일이 없습니다" in model_info(ModelDraft("A", str(tmp_path / "no.glb")))
    d = ModelDrafts()
    assert d.to_models() == [] and d.to_limit() == 5000
    for v, ok in (("0", 0), ("", 5000), ("1.5", None), ("-1", None), ("a", None)):
        d.limit = v
        if ok is None:
            with pytest.raises(ValueError, match="한도"):
                d.to_limit()
        else:
            assert d.to_limit() == ok
    p = new_draft("MODEL_W", 1, 10)
    p.model = "box"
    assert p.to_spec("비품", 0.0).model == "box"


def test_project_file_keeps_paths_and_finds_moved_files(tmp_path):
    path = gltf(tmp_path)
    st = ProjectState()
    st.prop_models = [new_model(str(path), ())]
    st.prop_drafts = [PropDraft(kind="MODEL_F", model="box")]
    st.prop_model_limit = "800"
    save_project(tmp_path / "a.ssbim", st)
    back = open_project(tmp_path / "a.ssbim")
    assert back == st and back.warnings == [] and (tmp_path / "a.ssbim").stat().st_size < 60000      # 모델 내용은 넣지 않음
    other = tmp_path / "옮김"
    other.mkdir()
    (other / "a.ssbim").write_bytes((tmp_path / "a.ssbim").read_bytes())
    (other / "box.glb").write_bytes(path.read_bytes())
    path.unlink()
    assert open_project(other / "a.ssbim").prop_models[0].path == str(other / "box.glb")             # 프로젝트 옆의 같은 이름
    (other / "box.glb").unlink()
    w = open_project(other / "a.ssbim").warnings
    assert len(w) == 1 and "box" in w[0] and "파일이 없습니다" in w[0]
    raw = json.loads((tmp_path / "a.ssbim").read_text(encoding="utf-8"))
    for k in ("prop_models", "prop_model_limit"):
        raw.pop(k)
    old = ProjectState.from_dict(raw)
    assert old.prop_models == [] and old.prop_model_limit == "5000" and CODE_SHAPE
