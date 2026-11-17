"""텍스처 3D 모델 내보내기 (COLLADA 1.4.1 .dae — 스케치업 기본 가져오기로 둘러보기용).

기하는 3D DXF 문서(StationCADEngine.build_3d_doc)의 3DFACE 그대로 (미리보기·3D DXF 와 같은 단일 원천).
재질: 마감 부재는 그 부재의 마감 재질(FinishElementData.material → source_element 3DFACE), 나머지는 레이어별 재질
(exporter.render_material). 텍스처 좌표는 면마다 평면 투영:
- 수평에 가까운 면(|n_z| ≥ 0.7, 바닥·천장): u = 선형 진행방향, v = 진행방향 왼쪽 (면 중심의 선형 접선 기준)
- 그 밖(벽·경사면): u = 면 안의 수평 방향, v = 면 안의 위쪽
좌표는 모두 세계 좌표 그대로가 아닌 정수 원점 기준 상대 좌표 (스케치업은 원점에서 먼 모델의 정밀도가 떨어짐).
원점은 <asset> 설명과 반환값에 남긴다. 레이어마다 노드 1개(스케치업 그룹), 그 안에 재질마다 삼각형 묶음.
"""
import datetime
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

from exporter.render_material import TEXTURE_DIR, find_image, finish_material, layer_material
from preview.preview_render import station_of

HORIZONTAL_NZ = 0.7          # 이 이상이면 바닥·천장처럼 수평 면으로 보고 선형 방향에 맞춰 텍스처를 깜
TEXTURE_FOLDER = "textures"  # .dae 옆에 텍스처 이미지를 복사하는 폴더


@dataclass
class DaeResult:
    path: str
    origin: tuple                                  # 상대 좌표의 세계 원점 (X, Y, Z)
    triangles: int = 0
    materials: dict = field(default_factory=dict)  # 재질 이름 → 삼각형 수
    textured: list = field(default_factory=list)   # 텍스처를 붙인 재질 이름
    missing: list = field(default_factory=list)    # 텍스처 이미지가 없어 색만 쓴 재질 (이름, 찾은 파일 이름)


def dae_notes(res: DaeResult) -> list:
    """출력 완료 알림에 덧붙일 문장: 원점, 텍스처 붙인 재질, 이미지가 없어 색만 쓴 재질"""
    ox, oy, oz = res.origin
    out = [f"텍스처 DAE: 원점 (X, Y, Z) = ({ox:.0f}, {oy:.0f}, {oz:.0f}) 기준 상대 좌표, 삼각형 {res.triangles:,}개"]
    if res.textured:
        out.append("  텍스처: " + ", ".join(res.textured))
    for name, tex in res.missing:
        out.append(f"  {name}: 텍스처 이미지 없음 → 색만 (assets/image/tile/{tex}.jpg|.png)")
    return out


def _triangles(doc, mat_of, skip_layers):
    """3DFACE → {(레이어, 재질): [삼각형 (3, 3)]}"""
    out = {}
    for ent in doc.modelspace().query("3DFACE"):
        d = ent.dxf
        if d.layer in skip_layers:
            continue
        v = [tuple(d.vtx0), tuple(d.vtx1), tuple(d.vtx2), tuple(d.vtx3)]
        mat = mat_of.get(d.handle) or layer_material(d.layer)
        tris = out.setdefault((d.layer, mat), [])
        tris.append(v[:3])
        if v[3] != v[2]:
            tris.append((v[0], v[2], v[3]))
    return out


def _heading(cfg, cxy: np.ndarray) -> np.ndarray:
    """면 중심 (세계 X, Y) → 그 위치의 선형 접선 방위각 (rad)"""
    if cfg.align.is_straight or len(cxy) == 0:
        return np.full(len(cxy), cfg.theta_at(0.0))
    a, base = cfg.align, cfg.station.start_station
    lo = max(a.start_station, base - 300.0) - base
    hi = min(a.end_station, base + cfg.station.length + 300.0) - base
    s = station_of(cfg, cxy, lo, hi)
    sq = np.arange(lo, hi + 1e-9, 1.0)
    th = np.unwrap([cfg.theta_at(x) for x in sq])
    return np.interp(s, sq, th)


def texture_uv(cfg, tris: np.ndarray, rel: np.ndarray, size_u: float, size_v: float) -> np.ndarray:
    """삼각형 (N, 3, 3) 세계 좌표 + 원점 기준 상대 좌표 rel → 꼭짓점 텍스처 좌표 (N, 3, 2)"""
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
    flat = np.abs(n[:, 2]) >= HORIZONTAL_NZ
    hu = np.zeros((len(tris), 3))
    hv = np.zeros((len(tris), 3))
    if flat.any():
        th = _heading(cfg, tris[flat].mean(axis=1)[:, :2])
        hu[flat, 0], hu[flat, 1] = np.cos(th), np.sin(th)
        hv[flat, 0], hv[flat, 1] = -np.sin(th), np.cos(th)
    st = ~flat
    if st.any():
        h = np.stack([-n[st, 1], n[st, 0], np.zeros(st.sum())], axis=1)      # z × n: 면 안의 수평 방향
        h /= np.maximum(np.linalg.norm(h, axis=1), 1e-12)[:, None]
        hu[st] = h
        hv[st] = np.cross(n[st], h)                                           # 면 안의 위쪽
    u = np.einsum("nkj,nj->nk", rel, hu) / size_u
    v = np.einsum("nkj,nj->nk", rel, hv) / size_v
    return np.stack([u, v], axis=2)


def _floats(a) -> str:
    return " ".join(f"{x:.5f}" for x in np.asarray(a).ravel())


def _floats_uv(a) -> str:
    return " ".join(f"{x:.5f}" for x in np.asarray(a).ravel())


def _library(kind: str, items: list) -> str:
    """COLLADA 라이브러리 요소 (항목이 없으면 생략 — 스키마상 빈 라이브러리는 허용되지 않음)"""
    return f"<library_{kind}>{''.join(items)}</library_{kind}>" if items else ""


def export_dae(engine, path, texture_dir=TEXTURE_DIR, frames: bool = False) -> DaeResult:
    """engine (StationCADEngine) 의 3D 모델을 텍스처 COLLADA 로 저장. frames=False 면 천장틀(FIN_FRAME)은 뺌
    (면이 매우 많고 천장판에 가려 보이지 않음). 텍스처 이미지는 path 옆 textures/ 폴더로 복사"""
    cfg = engine.cfg
    doc = engine.build_3d_doc()
    mat_of = {}
    for e in engine.finishes.all_elements():
        m = finish_material(e.material)
        for ent in e.source_element or []:
            mat_of[ent.dxf.handle] = m
    groups = _triangles(doc, mat_of, set() if frames else {"FIN_FRAME"})
    first = next((t[0][0] for t in groups.values() if t), (0.0, 0.0, 0.0))
    origin = np.floor(np.array(first, dtype=float))

    path = Path(path)
    os.makedirs(path.parent.resolve(), exist_ok=True)
    res = DaeResult(path=str(path.resolve()), origin=tuple(float(x) for x in origin))

    # 재질 (이름 순서 고정)
    mats = sorted({m for _, m in groups}, key=lambda m: m.name)
    mat_id, images = {}, {}
    for k, m in enumerate(mats):
        mat_id[m] = f"mat{k}"
        img = find_image(m.texture, texture_dir)
        if img is not None:
            images[m] = img
            res.textured.append(m.name)
        elif m.texture:
            res.missing.append((m.name, m.texture))
    if images:
        tex_dir = path.parent / TEXTURE_FOLDER
        tex_dir.mkdir(exist_ok=True)
        for img in set(images.values()):
            shutil.copyfile(img, tex_dir / img.name)

    lib_img, lib_fx, lib_mat = [], [], []
    for m in mats:
        i = mat_id[m]
        lib_mat.append(f'<material id="{i}" name="{escape(m.name, {chr(34): "&quot;"})}"><instance_effect url="#{i}-fx"/></material>')
        if m in images:
            lib_img.append(f'<image id="{i}-img" name="{i}-img"><init_from>{TEXTURE_FOLDER}/{escape(images[m].name)}</init_from></image>')
            diffuse = f'<texture texture="{i}-sampler" texcoord="UVSET0"/>'
            params = (f'<newparam sid="{i}-surface"><surface type="2D"><init_from>{i}-img</init_from></surface></newparam>'
                      f'<newparam sid="{i}-sampler"><sampler2D><source>{i}-surface</source></sampler2D></newparam>')
        else:
            r, g, b = m.color
            diffuse = f"<color>{r:.3f} {g:.3f} {b:.3f} 1</color>"
            params = ""
        lib_fx.append(f'<effect id="{i}-fx"><profile_COMMON>{params}<technique sid="common"><lambert><diffuse>{diffuse}'
                      f'</diffuse></lambert></technique></profile_COMMON><extra><technique profile="GOOGLEEARTH">'
                      f'<double_sided>1</double_sided></technique></extra></effect>')

    # 기하: 레이어마다 노드, (레이어, 재질)마다 기하 1개
    geoms, nodes = [], {}
    for g, ((layer, m), tris) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1].name))):
        t = np.array(tris, dtype=float)
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        t = t[np.linalg.norm(n, axis=1) > 1e-10]                       # 넓이 0 삼각형 제외
        if len(t) == 0:
            continue
        rel = t - origin
        gid = f"geo{g}"
        nv = len(t) * 3
        src = (f'<source id="{gid}-pos"><float_array id="{gid}-pos-array" count="{nv * 3}">{_floats(rel)}</float_array>'
               f'<technique_common><accessor source="#{gid}-pos-array" count="{nv}" stride="3"><param name="X" type="float"/>'
               f'<param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>')
        inputs = f'<input semantic="VERTEX" source="#{gid}-vtx" offset="0"/>'
        if m in images:
            uv = texture_uv(cfg, t, rel, m.size_u, m.size_v)
            src += (f'<source id="{gid}-uv"><float_array id="{gid}-uv-array" count="{nv * 2}">{_floats_uv(uv)}</float_array>'
                    f'<technique_common><accessor source="#{gid}-uv-array" count="{nv}" stride="2"><param name="S" type="float"/>'
                    f'<param name="T" type="float"/></accessor></technique_common></source>')
            inputs += f'<input semantic="TEXCOORD" source="#{gid}-uv" offset="0" set="0"/>'
        idx = " ".join(map(str, range(nv)))
        geoms.append(f'<geometry id="{gid}" name="{escape(layer)}_{mat_id[m]}"><mesh>{src}<vertices id="{gid}-vtx">'
                     f'<input semantic="POSITION" source="#{gid}-pos"/></vertices><triangles material="{mat_id[m]}" '
                     f'count="{len(t)}">{inputs}<p>{idx}</p></triangles></mesh></geometry>')
        bind = '<bind_vertex_input semantic="UVSET0" input_semantic="TEXCOORD" input_set="0"/>' if m in images else ""
        nodes.setdefault(layer, []).append(
            f'<instance_geometry url="#{gid}"><bind_material><technique_common><instance_material symbol="{mat_id[m]}" '
            f'target="#{mat_id[m]}">{bind}</instance_material></technique_common></bind_material></instance_geometry>')
        res.triangles += len(t)
        res.materials[m.name] = res.materials.get(m.name, 0) + len(t)

    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    ox, oy, oz = res.origin
    node_xml = "".join(f'<node id="node{k}" name="{escape(ly)}">{"".join(items)}</node>'
                       for k, (ly, items) in enumerate(nodes.items()))
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">'
           f'<asset><contributor><authoring_tool>subway_station_BIM</authoring_tool>'
           f'<comments>origin (world X, Y, Z) = {ox:.3f}, {oy:.3f}, {oz:.3f}</comments></contributor>'
           f'<created>{now}</created><modified>{now}</modified><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>'
           + _library("images", lib_img) + _library("effects", lib_fx) + _library("materials", lib_mat)
           + _library("geometries", geoms) +
           f'<library_visual_scenes><visual_scene id="scene" name="station"><node id="station" name="정거장">{node_xml}'
           '</node></visual_scene></library_visual_scenes>'
           '<scene><instance_visual_scene url="#scene"/></scene></COLLADA>\n')
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(xml)
    return res
