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
from urllib.parse import quote
from xml.sax.saxutils import escape

import numpy as np

from exporter.render_material import (ESC_MATERIALS, TEXTURE_DIR, RenderMaterial, find_image, finish_material,
                                      layer_material, railing_glass_material)
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


def _triangles(doc, mat_of, skip_layers, handles=None):
    """3DFACE → {(레이어, 재질): [삼각형 (3, 3)]}. handles 를 주면 {(레이어, 재질): [3DFACE 핸들]} 을 같은 순서로 채움"""
    out = {}
    for ent in doc.modelspace().query("3DFACE"):
        d = ent.dxf
        if d.layer in skip_layers:
            continue
        v = [tuple(d.vtx0), tuple(d.vtx1), tuple(d.vtx2), tuple(d.vtx3)]
        mat = mat_of.get(d.handle) or layer_material(d.layer)
        tris = out.setdefault((d.layer, mat), [])
        hs = handles.setdefault((d.layer, mat), []) if handles is not None else None
        tris.append(v[:3])
        if hs is not None:
            hs.append(d.handle)
        if v[3] != v[2]:
            tris.append((v[0], v[2], v[3]))
            if hs is not None:
                hs.append(d.handle)
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


def frame_uv(frame, rel: np.ndarray, origin) -> np.ndarray:
    """이미지 한 장을 면에 맞춘 텍스처 좌표 (사인): frame = (왼쪽 아래 세계 좌표, 오른쪽, 위쪽, 폭, 높이, 구배)
    구배 = 오른쪽 1m 당 판 하단 상승 (판이 종단구배를 따름)"""
    o, u, v, w, h, k = frame
    d = rel - (np.asarray(o, dtype=float) - origin)
    du = d @ np.asarray(u)
    return np.stack([du / w, (d @ np.asarray(v) - k * du) / h], axis=2)


def element_materials(engine) -> dict:
    """3DFACE 핸들 → 보기 재질 (부재 자신의 재질을 쓰는 것: 마감·점자블록·계단 마감·유리난간·제연경계벽·에스컬레이터 부재).
    build_3d_doc 뒤에 부를 것. 나머지 면은 레이어 재질 (DAE·웹 뷰어 공통)"""
    cfg = engine.cfg
    mat_of = {}

    def put(e, m):
        for ent in e.source_element or []:
            mat_of[ent.dxf.handle] = m
    tactile = getattr(engine, "tactiles", None)
    stair_fin = engine.stairs.finish_elements() if getattr(engine, "stairs", None) is not None else []
    pfin = getattr(engine, "passage_finishes", None)
    ents_ = getattr(engine, "entrances", None)
    ent_fin = [f for en in (ents_.entrances if ents_ is not None else [])
               for f in (en.stair.finishes if en.stair is not None else []) + en.finishes
               + [e for e in en.elements if e.kind in ("PAVE", "LANDFIN", "ARCH")]]   # 출입구 계단·내부 마감·앞마당 포장·승강구 마감
    for e in (engine.finishes.all_elements() + (tactile.elements if tactile is not None else []) + stair_fin
              + (pfin.elements if pfin is not None else []) + ent_fin):
        put(e, finish_material(e.material))
    xe = getattr(engine, "ext_evs", None)
    for x in (xe.ext_evs if xe is not None else []):                 # 외부 엘리베이터 기단·경사로·턱 (화강석)
        for e in x.elements:
            if e.kind in ("PODIUM", "RAMP", "CURB", "LOW_FLOOR"):
                put(e, finish_material(e.material))
            elif e.kind in ("DOOR_FRAME", "REVEAL", "LANDING_DOOR"):     # 문틀·문·개구부 둘레 (벽 패널과 구분)
                put(e, finish_material("스테인리스"))
    evs_ = getattr(engine, "elevators", None)
    for ev in (evs_.elevators if evs_ is not None else []):         # 투시형 승강로 금속 패널 띠
        for e in ev.elements:
            if e.kind.name == "PANEL":
                put(e, finish_material("금속패널"))
    rails = getattr(engine, "railings", None)
    for e in (rails.elements if rails is not None else []):          # 유리난간: 경계석·POST·레일 = 부재 재질, 유리 = 설정 색
        put(e, railing_glass_material(cfg.railing_settings) if e.code == "GLASS" else finish_material(e.material))
    smokes = getattr(engine, "smokes", None)
    for e in (smokes.elements if smokes is not None else []):          # 제연경계벽: 유리 = 설정 색
        put(e, railing_glass_material(cfg.smoke_settings, "제연 유리") if e.code == "GLASS" else finish_material(e.material))
    escs = getattr(engine, "escalators", None)
    ents = getattr(engine, "entrances", None)
    ent_escs = [x for e in (ents.entrances if ents is not None else []) for x in e.escalators]
    for esc in (escs.all_escalators() if escs is not None else []) + ent_escs:   # 핸드레일 검정·스텝·승강판 텍스처·볼라드
        for e in list(esc.parts) + list(esc.bollards):
            m = ESC_MATERIALS.get(e.material)
            if m is not None:
                put(e, m)
        top, side = ESC_MATERIALS.get("Aluminium_Step"), ESC_MATERIALS.get("Aluminium_Step_Side")
        for stp in esc.steps:              # 스텝: 디딤판 윗면(수평, 텍스처 틀)만 노란 경계띠 이미지, 나머지 면은 홈만
            for ent in stp.source_element or []:
                h = ent.dxf.handle
                mat_of[h] = top if h in stp.face_frames and _horizontal(ent) else side
    return mat_of


def _horizontal(ent) -> bool:
    """3DFACE 가 수평 면인지 (법선 |n_z| ≥ HORIZONTAL_NZ)"""
    p = [np.asarray(ent.dxf.get(f"vtx{i}"), dtype=float) for i in range(3)]
    n = np.cross(p[1] - p[0], p[2] - p[0])
    return abs(n[2]) >= HORIZONTAL_NZ * max(float(np.linalg.norm(n)), 1e-12)


def stair_face_frames(engine) -> dict:
    """3DFACE 핸들 → 디딤판 텍스처 틀 (원점, u, v, 한 장 폭, 깊이) — 디딤판 윗면에 이미지 한 장씩
    (계단석: StairEngine.add_stair_mesh, 에스컬레이터 스텝: EscalatorEngine._step_frames)"""
    out = {}
    stairs = getattr(engine, "stairs", None)
    ents = getattr(engine, "entrances", None)
    ent_fin = [f for en in (ents.entrances if ents is not None else []) for f in (en.stair.finishes if en.stair is not None else [])]   # 출입구 계단 마감
    for fe in (stairs.finish_elements() if stairs is not None else []) + ent_fin:
        out.update(getattr(fe, "face_frames", None) or {})
    escs = getattr(engine, "escalators", None)
    ent_escs = [x for e in (ents.entrances if ents is not None else []) for x in e.escalators]
    for esc in (escs.all_escalators() if escs is not None else []) + ent_escs:
        for stp in esc.steps:
            out.update(stp.face_frames or {})
    return out


def tread_uv(frame, pts: np.ndarray) -> np.ndarray:
    """계단석 틀 + 세계 좌표 점 (K, 3) → (K, 2) 텍스처 좌표 (u = 폭 방향 / 한 장 폭, v = 앞 코에서 / 깊이)"""
    o, u, v, w, depth = frame
    d = pts - np.asarray(o, dtype=float)
    d[:, 2] = 0.0
    return np.stack([d @ np.asarray(u) / w, d @ np.asarray(v) / depth], axis=1)


def apply_tread_uv(uv: np.ndarray, tris: np.ndarray, handles: list, frames: dict) -> np.ndarray:
    """삼각형 (N, 3, 3) 세계 좌표의 텍스처 좌표 uv (N, 3, 2) 중 계단석 틀이 있는 수평 면만 바꿈"""
    if not frames:
        return uv
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    flat = np.abs(n[:, 2]) >= HORIZONTAL_NZ * np.maximum(np.linalg.norm(n, axis=1), 1e-12)
    for i, h in enumerate(handles):
        fr = frames.get(h)
        if fr is not None and flat[i]:
            uv[i] = tread_uv(fr, tris[i])
    return uv


def texture_uv(cfg, tris: np.ndarray, rel: np.ndarray, size_u: float, size_v: float) -> np.ndarray:
    """삼각형 (N, 3, 3) 세계 좌표 + 원점 기준 상대 좌표 rel → 꼭짓점 텍스처 좌표 (N, 3, 2)"""
    hu, hv = texture_axes(cfg, tris)
    u = np.einsum("nkj,nj->nk", rel, hu) / size_u
    v = np.einsum("nkj,nj->nk", rel, hv) / size_v
    return np.stack([u, v], axis=2)


def texture_axes(cfg, tris: np.ndarray) -> tuple:
    """삼각형 (N, 3, 3) 세계 좌표 → 면마다 텍스처 u·v 방향 단위 벡터 (hu, hv) — (N, 3) 둘.
    수평에 가까운 면: u = 선형 진행방향, v = 왼쪽. 그 밖: u = 면 안 수평, v = 면 안 위쪽"""
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
    return hu, hv


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
    mat_of = element_materials(engine)
    path = Path(path)
    os.makedirs(path.parent.resolve(), exist_ok=True)
    signs = getattr(engine, "signs", None)
    if signs is not None and signs.elements:                         # 사인 이미지: 그려서 textures/ 에 저장, 면에 한 장 맞춤
        tex_dir = path.parent / TEXTURE_FOLDER
        tex_dir.mkdir(exist_ok=True)
        for k, e in enumerate(signs.elements, start=1):
            img_path = tex_dir / f"sign_{k:03d}.png"
            signs.image(e).save(img_path)
            m = RenderMaterial(f"사인 {e.name}", (1.0, 1.0, 1.0), image=str(img_path), frame=signs.uv_frame(e))
            for ent in e.face_entities:
                mat_of[ent.dxf.handle] = m
    extra = [s for k in ("entrances", "ext_evs") if getattr(engine, k, None) is not None for s in getattr(engine, k).sign_images()]
    if extra:                                                        # 출입구 캐노피 출구 사인 · 외부 엘리베이터 역명 띠
        tex_dir = path.parent / TEXTURE_FOLDER
        tex_dir.mkdir(exist_ok=True)
        for k, (name, img, frame, faces) in enumerate(extra, start=1):
            img_path = tex_dir / f"entrance_sign_{k:03d}.png"
            img.save(img_path)
            m = RenderMaterial(name, (1.0, 1.0, 1.0), image=str(img_path), frame=frame)
            for ent in faces:
                mat_of[ent.dxf.handle] = m
    handles = {}
    groups = _triangles(doc, mat_of, set() if frames else {"FIN_FRAME"}, handles)
    tread_frames = stair_face_frames(engine)
    first = next((t[0][0] for t in groups.values() if t), (0.0, 0.0, 0.0))
    origin = np.floor(np.array(first, dtype=float))

    res = DaeResult(path=str(path.resolve()), origin=tuple(float(x) for x in origin))

    # 재질 (이름 순서 고정)
    mats = sorted({m for _, m in groups}, key=lambda m: m.name)
    mat_id, images = {}, {}
    for k, m in enumerate(mats):
        mat_id[m] = f"mat{k}"
        img = Path(m.image) if m.image else find_image(m.texture, texture_dir)
        if img is not None:
            images[m] = img
            res.textured.append(m.name)
        elif m.texture:
            res.missing.append((m.name, m.texture))
    if images:
        tex_dir = path.parent / TEXTURE_FOLDER
        tex_dir.mkdir(exist_ok=True)
        for img in set(images.values()):
            if img.resolve() != (tex_dir / img.name).resolve():
                shutil.copyfile(img, tex_dir / img.name)

    lib_img, lib_fx, lib_mat = [], [], []
    for m in mats:
        i = mat_id[m]
        lib_mat.append(f'<material id="{i}" name="{escape(m.name, {chr(34): "&quot;"})}"><instance_effect url="#{i}-fx"/></material>')
        if m in images:
            lib_img.append(f'<image id="{i}-img" name="{i}-img"><init_from>{TEXTURE_FOLDER}/{escape(quote(images[m].name))}</init_from></image>')
            diffuse = f'<texture texture="{i}-sampler" texcoord="UVSET0"/>'
            params = (f'<newparam sid="{i}-surface"><surface type="2D"><init_from>{i}-img</init_from></surface></newparam>'
                      f'<newparam sid="{i}-sampler"><sampler2D><source>{i}-surface</source></sampler2D></newparam>')
        else:
            r, g, b = m.color
            diffuse = f"<color>{r:.3f} {g:.3f} {b:.3f} 1</color>"
            params = ""
        trans = (f'<transparent opaque="A_ONE"><color>1 1 1 1</color></transparent>'      # 불투명도 = alpha (유리)
                 f'<transparency><float>{m.alpha:.3f}</float></transparency>') if m.alpha < 1.0 else ""
        lib_fx.append(f'<effect id="{i}-fx"><profile_COMMON>{params}<technique sid="common"><lambert><diffuse>{diffuse}'
                      f'</diffuse>{trans}</lambert></technique></profile_COMMON><extra><technique profile="GOOGLEEARTH">'
                      f'<double_sided>1</double_sided></technique></extra></effect>')

    # 기하: 레이어마다 노드, (레이어, 재질)마다 기하 1개
    geoms, nodes = [], {}
    for g, ((layer, m), tris) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1].name))):
        t = np.array(tris, dtype=float)
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        keep = np.linalg.norm(n, axis=1) > 1e-10
        t = t[keep]                                                    # 넓이 0 삼각형 제외
        hs = [h for h, k in zip(handles.get((layer, m), []), keep) if k]
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
            uv = frame_uv(m.frame, rel, origin) if m.frame else                 apply_tread_uv(texture_uv(cfg, t, rel, m.size_u, m.size_v), t, hs, tread_frames)
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
